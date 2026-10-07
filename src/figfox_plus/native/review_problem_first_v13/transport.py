"""Bounded client tool-calling transport; one send is one HTTP attempt.

Saved assistant messages retain reasoning and tool call IDs for continuation.
A timeout or malformed reply consumes its attempt and is never retried.
"""
from figfox_plus import file_lock as fcntl
import hashlib
import json
import os
import time
from pathlib import Path
import urllib.request
from uuid import uuid4

from ...providers import load_key, request_once
from ...state import write_json
from ...cost_budget import cost_guard
from ...progress import RequestProgress
from ..single_call.transport import _NoRedirect, _open_http, live_page
from .context_budget import budget_request, ContextCapacityError

MARKER = '.review-task.json'


def _network_transport(send_http=None):
    """Select one route per request, without automatic fallback or global changes."""
    route=(os.environ.get('FIGFOX_DS_HTTP_ROUTE','') or 'direct').strip().lower()
    if route not in ('direct','system'):
        raise ValueError('FIGFOX_DS_HTTP_ROUTE must be direct or system')
    if send_http is not None:return 'injected',send_http
    if route=='system':return route,_open_http
    def direct(request,timeout):
        return urllib.request.build_opener(_NoRedirect(),urllib.request.ProxyHandler({})).open(request,timeout=timeout)
    return route,direct


def _read_stream(response, folder, progress=None):
    reasoning=[]; content=[]; calls={}; metadata={}; usage={}; finish=None; done=False; last_update=0
    started=time.monotonic(); first_event=None; last_event=None; event_count=0; wire_bytes=0

    def snapshot(status, error=None):
        message={'role':'assistant','content':''.join(content),'reasoning_content':''.join(reasoning)}
        if calls:message['tool_calls']=[calls[i] for i in sorted(calls)]
        raw={**metadata,'choices':[{'message':message,'finish_reason':finish}],'usage':usage}
        (folder/'reasoning.txt').write_text(message['reasoning_content'],encoding='utf-8')
        (folder/'content.partial.txt').write_text(message['content'],encoding='utf-8')
        write_json(folder/'stream-state.json',{'status':status,'done_received':done,
            'finish_reason':finish,'usage_received':bool(usage),'provider_request_id':metadata.get('id'),
            'reasoning_characters':len(message['reasoning_content']),'content_characters':len(message['content']),
            'tool_call_count':len(calls),'error':error,'automatic_retry':False,
            'elapsed_seconds':round(time.monotonic()-started,3), 'event_count':event_count,
            'wire_bytes_received':wire_bytes,
            'first_event_seconds':first_event, 'last_event_seconds':last_event})
        if status=='interrupted':
            # A partial transcript is evidence only; never cache it as response.json.
            write_json(folder/'response.partial.json',{**raw,'complete':False})
        live_page(folder,message['reasoning_content'],message['content'],
            '接收中断；片段已保存，请求未完成，不自动重试' if status=='interrupted'
            else 'API 返回完成；工具等待本地执行')
        return raw

    try:
        with (folder/'events.jsonl').open('w', encoding='utf-8') as events:
            for line in response:
                if progress:progress.wire(line)
                wire_bytes+=len(line) if isinstance(line,bytes) else len(line.encode('utf-8'))
                line=line.decode('utf-8') if isinstance(line,bytes) else line
                if not line.startswith('data:'):continue
                data=line[5:].strip()
                if data=='[DONE]':done=True;break
                chunk=json.loads(data)
                elapsed=round(time.monotonic()-started,3)
                first_event=elapsed if first_event is None else first_event
                last_event=elapsed; event_count+=1
                events.write(json.dumps(chunk,ensure_ascii=False)+'\n');events.flush()
                if chunk.get('error'):raise ValueError('provider returned stream error')
                metadata.update({k:chunk[k] for k in ('id','model','created') if k in chunk})
                if chunk.get('usage'):
                    usage=chunk['usage']
                    if progress:progress.delta(usage=usage)
                for choice in chunk.get('choices',[]):
                    if choice.get('index',0)!=0:continue
                    delta=choice.get('delta',{})
                    if progress:progress.delta(reasoning=delta.get('reasoning_content') or '',
                        content=delta.get('content') or '',
                        arguments=''.join(p.get('function',{}).get('arguments') or '' for p in delta.get('tool_calls',[])),usage=usage)
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
                if time.monotonic()-last_update >= 10:
                    (folder/'reasoning.txt').write_text(''.join(reasoning),encoding='utf-8')
                    (folder/'content.partial.txt').write_text(''.join(content),encoding='utf-8')
                    live_page(folder,''.join(reasoning),''.join(content),'接收中')
                    last_update=time.monotonic()
            if progress:progress.check()
            if not done:raise ValueError('stream ended without DONE; no retry')
    except Exception as error:
        cause=progress.interrupt_when_stalled(error) if progress else error
        snapshot('interrupted',{'type':type(cause).__name__,'message':str(cause)})
        if cause is not error:raise cause from error
        raise
    return snapshot('stream_complete')


def _message(raw):
    if raw.get('error'):raise ValueError('provider returned error')
    choice=raw['choices'][0]
    if choice.get('finish_reason') not in ('stop','tool_calls'):
        raise ValueError('incomplete model turn; finish_reason=' + str(choice.get('finish_reason')) + '; no retry')
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
    route,http=_network_transport(send_http)
    root=Path(task_dir).resolve()
    for parent in (root,*root.parents):
        if (parent/'local-replay.json').exists():raise ValueError('local replay cannot call a model')
        if parent!=root and ((parent/MARKER).exists() or (parent/'api-ledger.jsonl').exists()):
            raise ValueError('must use the existing task root request ledger')
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.review-transport.lock').open('a+', encoding='utf-8') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        marker=root/MARKER
        if marker.exists():
            record=json.loads(marker.read_text(encoding='utf-8'))
            if record.get('root')!=str(root):raise ValueError('task root marker mismatch')
            if record.get('request_limit')!=request_limit:raise ValueError('task request limit cannot change')
        else:write_json(marker,{'root':str(root),'request_limit':request_limit})
        body={'model':os.environ.get('FLOW_DS_MODEL','').strip() or 'deepseek-flash',
              'messages':messages,'max_tokens':393216,'thinking':{'type':'enabled'},
              'reasoning_effort':'high','stream':True,'stream_options':{'include_usage':True}}
        if tools:body.update(tools=tools,tool_choice='auto')
        # Cache identity is independent of remaining money. A completed turn
        # remains reusable even after another task spends the rest of the budget.
        body,capacity=budget_request(body)
        identity=json.dumps(body,ensure_ascii=False,sort_keys=True).encode('utf-8')
        token=hashlib.sha256(identity).hexdigest()
        folder=root/'model-turns'/token;folder.mkdir(parents=True,exist_ok=True)
        if (folder/'response.json').exists():return _message(json.loads((folder/'response.json').read_text(encoding='utf-8')))
        if (folder/'attempt.json').exists():raise ValueError('this turn was already attempted; no retry')
        from figfox_plus.cost_budget import input_budget_for_full_output, CostBudgetError
        allowance=input_budget_for_full_output(body['model'],body['max_tokens'])
        body,capacity=budget_request(body,input_token_limit=allowance)
        endpoint='https://api.deepseek.com/chat/completions'
        write_json(folder/'context-budget.json',capacity)
        if capacity['status']!='ready':
            if 'input cost budget' in capacity['violations']:
                raise CostBudgetError('figure cost budget cannot fund the full planned reply after evidence compaction; no HTTP request sent')
            raise ContextCapacityError('input_capacity_exceeded: '+', '.join(capacity['violations'])+'; no model request sent')
        def once(ticket, encoded):
            write_json(folder/'attempt.json',{'request_id':token})
            # Fake HTTP tests need no credential; real transport always requires it.
            headers={'Content-Type':'application/json'}
            if send_http is None:headers['Authorization']='Bearer '+load_key('DEEPSEEK_API_KEY')
            request=urllib.request.Request(endpoint,encoded,headers)
            live_page(folder)
            started=time.monotonic(); trace={'timeout_seconds':300,'automatic_retry':False,'http_route':route}
            progress=RequestProgress(folder,body['model']);failure=None;raw={}
            try:
                if ticket:ticket['sent']=True
                with http(request,timeout=300) as response:
                    progress.attach(response)
                    trace.update(status=getattr(response,'status',None),
                        time_to_headers_seconds=round(time.monotonic()-started,3),
                        headers={key:response.headers.get(key) for key in (
                            'Date','Content-Type','Content-Length','Transfer-Encoding','Connection',
                            'Server','Via','CF-Ray','X-Request-ID','X-DS-Request-ID','Traceparent')
                            if response.headers.get(key)})
                    write_json(folder/'http-transport.json',trace)
                    if 'text/event-stream' in response.headers.get('Content-Type',''):
                        raw=_read_stream(response,folder,progress)
                    else:
                        raw=json.loads(response.read())
                        progress.check()
                write_json(folder/'usage.json',raw.get('usage') if isinstance(raw.get('usage'),dict) else {})
                msg=_message(raw)
                write_json(folder/'response.json',raw)
                (folder/'reasoning.txt').write_text(msg.get('reasoning_content') or '',encoding='utf-8')
                live_page(folder,msg.get('reasoning_content') or '',msg.get('content') or '','API 返回完成；工具等待本地执行')
                return msg
            except Exception as error:
                failure=progress.interrupt_when_stalled(error)
                error=failure
                details={'type':type(error).__name__,'message':str(error),'retry_allowed':False}
                if raw:
                    # Keep fully received but invalid/truncated replies as paid
                    # evidence, without allowing them into the success cache.
                    write_json(folder/'response.invalid.json',raw)
                if isinstance(error,urllib.error.HTTPError):
                    details.update(status=error.code,response_body=error.read(65536).decode('utf-8',errors='replace'))
                write_json(folder/'error.json',details)
                live_page(folder,
                    (folder/'reasoning.txt').read_text(encoding='utf-8') if (folder/'reasoning.txt').exists() else '',
                    (folder/'content.partial.txt').read_text(encoding='utf-8') if (folder/'content.partial.txt').exists() else '',
                    '请求未完成；已有片段已保存，不自动重试')
                progress.check()
                raise
            finally:
                progress.finish(error=failure,usage=raw.get('usage'))
                trace['elapsed_seconds']=round(time.monotonic()-started,3)
                write_json(folder/'http-transport.json',trace)
        # Identical bodies in separately authorized tasks are separate paid calls.
        # The same folder remains protected by attempt.json and the task ledger.
        reservation_id=hashlib.sha256(str(folder.resolve()).encode('utf-8')).hexdigest()
        with cost_guard(body['model'],reservation_id,folder,capacity['after']['input_token_upper_bound'],body['max_tokens']) as ticket:
            if ticket:body['max_tokens']=ticket['max_output_tokens']
            encoded=json.dumps(body,ensure_ascii=False,sort_keys=True).encode('utf-8')
            write_json(folder/'request.json',{'endpoint':endpoint,'body':body})
            return request_once('deepseek',uuid4().hex,root/'api-ledger.jsonl',lambda:once(ticket,encoded),{'deepseek':request_limit})
