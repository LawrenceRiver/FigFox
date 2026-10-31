"""OpenAI Responses adapter, versioned separately; one inference per image."""
import ast,fcntl,hashlib,json,time,urllib.request,urllib.error
from pathlib import Path
from uuid import uuid4
from ...providers import load_key,request_once
from ...state import write_json,PLUS_ROOT
from ..single_call.transport import _open_http
MARKER='.review-task.json'

def credential():
    try:return load_key('OPENAI_API_KEY')
    except ValueError:
        tree=ast.parse((PLUS_ROOT.parent/'output/gpt55-once.py').read_text())
        return next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='OPENAI_API_KEY' for t in n.targets))

def body_for(messages,tools):
    inputs=[]
    for message in messages:
        content=message['content']
        if isinstance(content,str):parts=[{'type':'input_text','text':content}]
        else:
            parts=[]
            for item in content:
                if item['type']=='text':parts.append({'type':'input_text','text':item['text']})
                elif item['type']=='image_url':parts.append({'type':'input_image','image_url':item['image_url']['url'],'detail':'original'})
                else:raise ValueError('unsupported input block')
        inputs.append({'role':message['role'],'content':parts})
    return {'model':'gpt-6-luna','input':inputs,'tools':[dict(type='function',strict=False,**t['function']) for t in tools],
        'tool_choice':{'type':'function','name':'execute_review_program'},'parallel_tool_calls':False,
        'reasoning':{'effort':'high','summary':'auto'},'max_output_tokens':128000,'stream':True,'store':False}

def message_from(raw):
    if raw.get('status')!='completed':raise ValueError('OpenAI response not completed; no retry')
    calls=[];text=[];summary=[]
    for item in raw.get('output',[]):
        if item['type']=='function_call':calls.append({'id':item['call_id'],'type':'function','function':{'name':item['name'],'arguments':item['arguments']}})
        elif item['type']=='message':text.extend(c.get('text','') for c in item.get('content',[]) if c['type']=='output_text')
        elif item['type']=='reasoning':summary.extend(c.get('text','') for c in item.get('summary',[]))
    return {'role':'assistant','content':'\n'.join(text),'tool_calls':calls,'reasoning_summary':'\n'.join(summary)}

def send(messages,tools,task_dir,*,send_http=None,request_limit=1):
    if request_limit!=1:raise ValueError('Luna v1 permits exactly one inference per image')
    root=Path(task_dir).resolve()
    for parent in (root,*root.parents):
        if (parent/'local-replay.json').exists():raise ValueError('no model calls in local replay')
        if parent!=root and (parent/MARKER).exists():raise ValueError('nested request budget forbidden')
    root.mkdir(parents=True,exist_ok=True)
    with (root/'.openai.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        write_json(root/MARKER,{'root':str(root),'provider':'openai','model':'gpt-6-luna','request_limit':1})
        body=body_for(messages,tools);encoded=json.dumps(body,ensure_ascii=False).encode();token=hashlib.sha256(encoded).hexdigest();folder=root/'model-turns'/token;folder.mkdir(parents=True,exist_ok=True)
        if (folder/'response.json').exists():return message_from(json.loads((folder/'response.json').read_text()))
        if (folder/'attempt.json').exists():raise ValueError('already attempted; no retry')
        if len(encoded)>48*1024*1024:raise ValueError('request exceeds conservative 48MiB transport budget')
        write_json(folder/'request.json',{'endpoint':'https://api.openai.com/v1/responses','body':body})
        def once():
            write_json(folder/'attempt.json',{'id':token})
            headers={'Content-Type':'application/json'}
            if send_http is None:headers['Authorization']='Bearer '+credential()
            request=urllib.request.Request('https://api.openai.com/v1/responses',encoded,headers)
            try:
                final=None;progress={'summary_chars':0,'tool_argument_chars':0};last=0
                with (send_http or _open_http)(request,timeout=1800) as response,(folder/'events.jsonl').open('w') as log:
                    for line in response:
                        line=line.decode() if isinstance(line,bytes) else line
                        if not line.startswith('data:'):continue
                        data=line[5:].strip()
                        if data=='[DONE]':break
                        event=json.loads(data);log.write(json.dumps(event,ensure_ascii=False)+'\n');log.flush();kind=event.get('type','')
                        if kind=='response.reasoning_summary_text.delta':progress['summary_chars']+=len(event.get('delta',''))
                        if kind=='response.function_call_arguments.delta':progress['tool_argument_chars']+=len(event.get('delta',''))
                        if time.monotonic()-last>2:write_json(folder/'progress.json',progress);last=time.monotonic()
                        if kind=='response.completed':final=event['response'];break
                        if kind in ('error','response.failed','response.incomplete'):
                            write_json(folder/'provider-failure.json',event);raise ValueError('OpenAI stream failed or incomplete')
                if final is None:raise ValueError('stream ended before completed')
                write_json(folder/'response.json',final);write_json(folder/'usage.json',final.get('usage',{}));return message_from(final)
            except Exception as exc:
                record={'type':type(exc).__name__,'message':str(exc),'retry_allowed':False}
                if isinstance(exc,urllib.error.HTTPError):record.update(status=exc.code,response_body=exc.read(65536).decode(errors='replace'))
                write_json(folder/'error.json',record);raise
        return request_once('openai-luna',uuid4().hex,root/'api-ledger.jsonl',once,{'openai-luna':1})
