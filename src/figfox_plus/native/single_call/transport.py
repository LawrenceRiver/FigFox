"""One persisted attempt, one JSON response. No tool continuation or retries."""
import json
import html
import os
import time
from pathlib import Path
import urllib.request
from uuid import uuid4
from ...providers import load_key, request_once
from ...providers_tools import redact
from ...state import write_json


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # a redirect must not turn one attempt into another HTTP call


def _open_http(request, timeout):
    return urllib.request.build_opener(_NoRedirect()).open(request,timeout=timeout)


def live_page(folder, reasoning='', content='', status='等待 API 返回'):
    refresh='<meta http-equiv="refresh" content="3">' if status in ('等待 API 返回','接收中') else ''
    page='<!doctype html><meta charset="utf-8">'+refresh+'<title>DeepSeek 实时返回</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto;padding:0 20px}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f6f8;padding:18px;line-height:1.6}</style><h1>DeepSeek · 单次请求实时返回</h1><p>'+html.escape(status)+'</p><p>下方为 API 返回的原文。接收中每 3 秒刷新；不是本地执行结果。</p><h2>reasoning_content</h2><pre>'+html.escape(reasoning or '尚未收到 reasoning 片段')+'</pre><h2>最终答案 content</h2><pre>'+html.escape(content or '尚未收到最终答案')+'</pre>'
    temp=folder/'live.tmp.html';temp.write_text(page,encoding='utf-8');temp.replace(folder/'live.html')


def _read_stream(response, folder):
    reasoning=[];content=[];meta={};usage={};finish=None;tools_seen=False;done=False;last=0
    try:
        with (folder/'events.jsonl').open('w', encoding='utf-8') as events,(folder/'reasoning.txt').open('w', encoding='utf-8') as rf,(folder/'content.partial.txt').open('w', encoding='utf-8') as cf:
            for line in response:
                line=line.decode('utf-8').strip()
                if not line.startswith('data:'):continue
                data=line[5:].strip()
                if data=='[DONE]':done=True;break
                chunk=json.loads(data);events.write(json.dumps(chunk,ensure_ascii=False)+'\n');events.flush()
                if chunk.get('error'):raise ValueError('stream error: '+str(chunk['error']))
                meta.update({k:chunk[k] for k in ('id','model','created','system_fingerprint') if k in chunk})
                if chunk.get('usage'):usage=chunk['usage']
                for choice in chunk.get('choices',[]):
                    if choice.get('index',0)!=0:continue
                    delta=choice.get('delta',{})
                    if delta.get('reasoning_content'):
                        text=delta['reasoning_content'];reasoning.append(text);rf.write(text);rf.flush()
                    if delta.get('content'):
                        text=delta['content'];content.append(text);cf.write(text);cf.flush()
                    tools_seen=tools_seen or bool(delta.get('tool_calls'))
                    if choice.get('finish_reason'):finish=choice['finish_reason']
                if time.monotonic()-last>=2:
                    live_page(folder,''.join(reasoning),''.join(content),'接收中');last=time.monotonic()
            if not done:raise ValueError('stream ended without DONE; no retry')
    except Exception:
        live_page(folder,''.join(reasoning),''.join(content),'接收中断；已保存片段，不重试')
        raise
    message={'role':'assistant','reasoning_content':''.join(reasoning),'content':''.join(content)}
    if tools_seen:message['tool_calls']=[{'unsupported':True}]
    live_page(folder,message['reasoning_content'],message['content'],'API 返回完成；执行状态另见运行记录')
    return {**meta,'object':'chat.completion','choices':[{'index':0,'finish_reason':finish,'message':message}],'usage':usage}


def _send(messages, folder):
    key=load_key('DEEPSEEK_API_KEY')
    body={'model':os.environ.get('FLOW_DS_MODEL','deepseek-v4-flash-vision-exp'),
          'messages':messages, 'response_format':{'type':'json_object'},
          'max_tokens':64000, 'thinking':{'type':'enabled'},'reasoning_effort':'high',
          'stream':True,'stream_options':{'include_usage':True}}
    endpoint='https://api.deepseek.com/chat/completions'
    write_json(folder/'request.json',{'endpoint':endpoint,'body':redact(body)})
    request=urllib.request.Request(endpoint,json.dumps(body,ensure_ascii=False).encode(),
        {'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    live_page(folder)
    with _open_http(request,timeout=300) as response:
        if 'text/event-stream' in getattr(response,'headers',{}).get('Content-Type',''):
            raw=_read_stream(response,folder)
        else:
            raw=json.loads(response.read())
            msg=raw['choices'][0]['message']
            (folder/'reasoning.txt').write_text(msg.get('reasoning_content') or '',encoding='utf-8')
            live_page(folder,msg.get('reasoning_content') or '',msg.get('content') or '','API 返回完成（非流式）')
    write_json(folder/'response.json',raw)
    choice=raw['choices'][0]
    if choice.get('finish_reason')!='stop' or choice['message'].get('tool_calls'):
        raise ValueError('incomplete response or tool continuation is forbidden')
    write_json(folder/'usage.json',raw.get('usage',{}))
    return choice['message']['content']


def request_plan(messages, task_dir, *, send=None):
    task_dir=Path(task_dir)
    if (task_dir/'local-replay.json').exists():raise ValueError('local replay cannot call a model')
    if (task_dir/'feedback-link.json').exists():raise ValueError('feedback must use parent request budget')
    folder=task_dir/'api'; folder.mkdir(parents=True,exist_ok=True)
    def once():
        value=(send or _send)(messages,folder)
        if not isinstance(value,str):raise ValueError('transport must return one JSON string')
        (folder/'response.txt').write_text(value,encoding='utf-8')
        plan=json.loads(value)
        if not isinstance(plan,dict):raise ValueError('plan must be a JSON object')
        write_json(task_dir/'response-plan.json',plan)
        return plan
    # Reserve under flock + fsync BEFORE transport; timeouts and malformed replies
    # consume the attempt. A new process/request ID cannot reset this task budget.
    return request_once('deepseek',uuid4().hex,task_dir/'api-ledger.jsonl',once,{'deepseek':1})
