"""Bounded client tool-calling transport; one send is one HTTP attempt.

Saved assistant messages retain reasoning and tool call IDs for continuation.
A timeout or malformed reply consumes its attempt and is never retried.
"""
import fcntl
import hashlib
import json
import os
import time
from pathlib import Path
import urllib.request
from uuid import uuid4

from ...providers import load_key, request_once
from ...state import write_json
from ..single_call.transport import _open_http, live_page
from .context_budget import plan_context

MARKER = '.review-task.json'


def _provider_prefixes(root, model):
    prefixes=[]
    for response in (root/'model-turns').glob('*/response.json'):
        request=response.parent/'request.json'
        if not request.exists():continue
        raw=json.loads(response.read_text())
        body=json.loads(request.read_text())['body']
        if body.get('model')!=model:continue
        # Only accepted complete turns may supply a calibration baseline.
        try:_message(raw)
        except (ValueError,KeyError,TypeError):continue
        prefixes.append({'messages':body['messages'],'tools':body.get('tools',[]),
                         'prompt_tokens':raw.get('usage',{}).get('prompt_tokens')})
    return prefixes


def _read_stream(response, folder):
    reasoning=[]; content=[]; calls={}; metadata={}; usage={}; finish=None; done=False; last_update=0
    with (folder/'events.jsonl').open('w') as events:
        for line in response:
            line=line.decode('utf-8') if isinstance(line,bytes) else line
            if not line.startswith('data:'):continue
            data=line[5:].strip()
            if data=='[DONE]':done=True;break
            chunk=json.loads(data)
            events.write(json.dumps(chunk,ensure_ascii=False)+'\n');events.flush()
            if chunk.get('error'):raise ValueError('provider returned stream error')
            metadata.update({k:chunk[k] for k in ('id','model','created') if k in chunk})
            if chunk.get('usage'):usage=chunk['usage']
            for choice in chunk.get('choices',[]):
                if choice.get('index',0)!=0:continue
                delta=choice.get('delta',{})
                if delta.get('reasoning_content'):reasoning.append(delta['reasoning_content'])
                if delta.get('content'):content.append(delta['content'])
                for part in delta.get('tool_calls',[]):
                    index=part['index']
                    call=calls.setdefault(index,{'id':'','type':'function','function':{'name':'','arguments':''}})
                    if part.get('id'):call['id']+=part['id']
                    if part.get('type'):call['type']=part['type']
                    for key in ('name','arguments'):
                        call['function'][key]+=part.get('function',{}).get(key) or ''
                if choice.get('finish_reason'):finish=choice['finish_reason']
            if time.monotonic()-last_update >= 2:
                (folder/'reasoning.txt').write_text(''.join(reasoning),encoding='utf-8')
                (folder/'content.partial.txt').write_text(''.join(content),encoding='utf-8')
                live_page(folder,''.join(reasoning),''.join(content),'接收中')
                last_update=time.monotonic()
        if not done:raise ValueError('stream ended without DONE; no retry')
    message={'role':'assistant','content':''.join(content),'reasoning_content':''.join(reasoning)}
    if calls:message['tool_calls']=[calls[i] for i in sorted(calls)]
    return {**metadata,'choices':[{'message':message,'finish_reason':finish}],'usage':usage}


def _message(raw):
    if raw.get('error'):raise ValueError('provider returned error')
    choice=raw['choices'][0]
    if choice.get('finish_reason') not in ('stop','tool_calls'):
        raise ValueError('incomplete model turn; no retry')
    msg=choice['message']
    if msg.get('role')!='assistant':raise ValueError('expected assistant turn')
    ids=set()
    for call in msg.get('tool_calls',[]):
        if not call.get('id') or call['id'] in ids or call.get('type')!='function':
            raise ValueError('invalid tool call identity')
        ids.add(call['id'])
        if not call.get('function',{}).get('name') or not isinstance(call['function'].get('arguments'),str):
            raise ValueError('invalid tool function')
    if choice.get('finish_reason')=='tool_calls' and not ids:raise ValueError('missing tool calls')
    return msg


def send(messages, tools, task_dir, *, send_http=None, request_limit=2):
    """Return the full assistant message; injected HTTP takes (Request, timeout).

    The resolved task root owns a fixed ceiling of one or two requests. Reusing
    identical messages/tools returns its saved response without another request.
    """
    if type(request_limit) is not int or request_limit not in (1,2):
        raise ValueError('request limit must be 1 or 2')
    root=Path(task_dir).resolve()
    for parent in (root,*root.parents):
        if (parent/'local-replay.json').exists():raise ValueError('local replay cannot call a model')
        if parent!=root and ((parent/MARKER).exists() or (parent/'api-ledger.jsonl').exists()):
            raise ValueError('must use the existing task root request ledger')
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.review-transport.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        marker=root/MARKER
        if marker.exists():
            record=json.loads(marker.read_text())
            if record.get('root')!=str(root):raise ValueError('task root marker mismatch')
            if record.get('request_limit')!=request_limit:raise ValueError('task request limit cannot change')
        else:write_json(marker,{'root':str(root),'request_limit':request_limit})
        model=os.environ.get('FLOW_DS_MODEL','deepseek-flash')
        budget=plan_context(messages,tools,provider_prefixes=_provider_prefixes(root,model))
        body={'model':model,
              'messages':messages,'max_tokens':budget['max_output_tokens'],'thinking':{'type':'enabled'},
              'reasoning_effort':'high','stream':True,'stream_options':{'include_usage':True}}
        if tools:body.update(tools=tools,tool_choice='auto')
        encoded=json.dumps(body,ensure_ascii=False,sort_keys=True).encode('utf-8')
        token=hashlib.sha256(encoded).hexdigest()
        folder=root/'model-turns'/token;folder.mkdir(parents=True,exist_ok=True)
        if (folder/'response.json').exists():return _message(json.loads((folder/'response.json').read_text()))
        if (folder/'attempt.json').exists():raise ValueError('this turn was already attempted; no retry')
        write_json(folder/'context-budget.json',budget)
        if budget['status']=='blocked_before_http':
            raise ValueError('input_capacity_exceeded: local estimate leaves insufficient output capacity; '
                             'no HTTP attempt made, all evidence and saved initial SVG retained; see '+str(folder/'context-budget.json'))
        endpoint='https://api.deepseek.com/chat/completions'
        write_json(folder/'request.json',{'endpoint':endpoint,'body':body})
        def once():
            write_json(folder/'attempt.json',{'request_id':token})
            # Fake HTTP tests need no credential; real transport always requires it.
            headers={'Content-Type':'application/json'}
            if send_http is None:headers['Authorization']='Bearer '+load_key('DEEPSEEK_API_KEY')
            request=urllib.request.Request(endpoint,encoded,headers)
            live_page(folder)
            try:
                with (send_http or _open_http)(request,timeout=300) as response:
                    if 'text/event-stream' in response.headers.get('Content-Type',''):
                        raw=_read_stream(response,folder)
                    else:raw=json.loads(response.read())
                write_json(folder/'response.json',raw)
                msg=_message(raw)
                write_json(folder/'usage.json',raw.get('usage',{}))
                (folder/'reasoning.txt').write_text(msg.get('reasoning_content') or '',encoding='utf-8')
                live_page(folder,msg.get('reasoning_content') or '',msg.get('content') or '','API 返回完成；工具等待本地执行')
                return msg
            except Exception as error:
                details={'type':type(error).__name__,'retry_allowed':False}
                if isinstance(error,urllib.error.HTTPError):
                    details.update(status=error.code,response_body=error.read(65536).decode('utf-8',errors='replace'))
                write_json(folder/'error.json',details)
                raise
        return request_once('deepseek',uuid4().hex,root/'api-ledger.jsonl',once,{'deepseek':request_limit})
