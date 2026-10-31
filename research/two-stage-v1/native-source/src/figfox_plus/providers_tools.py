"""Opt-in native tool-call transport. Existing first-stage providers are unchanged."""
import base64,hashlib,json,os,time,urllib.request
from pathlib import Path
from uuid import uuid4
from PIL import Image
from .providers import load_key,request_once
from .state import PLUS_ROOT,write_json

def image_content(paths,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);out=[]
    for i,p in enumerate(paths):
        p=Path(p);dest=folder/f'{i:03d}.jpg'
        with Image.open(p) as im:im.convert('RGB').save(dest,quality=95,subsampling=0)
        data=dest.read_bytes()
        out.extend([{'type':'text','text':f'Image {i+1}: {p.name}'},{'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(data).decode(),'detail':'original'}}])
    return out

def redact(value):
    if isinstance(value,dict):return {k:redact(v) for k,v in value.items()}
    if isinstance(value,list):return [redact(v) for v in value]
    if isinstance(value,str) and value.startswith('data:image/'):
        return {'embedded_image_sha256':hashlib.sha256(value.encode()).hexdigest(),'bytes_encoded':len(value)}
    return value

def send_deepseek_tools(messages,tools,run_dir,purpose='native TP SP BP tool repair',*,ledger=None):
    run=Path(run_dir);run.mkdir(parents=True,exist_ok=True)
    if (run/'request.json').exists():raise ValueError('this request directory was already attempted; no implicit retry')
    key=load_key('DEEPSEEK_API_KEY');rid=uuid4().hex;endpoint='https://api.deepseek.com/chat/completions'
    body={'model':os.environ.get('FLOW_DS_MODEL','deepseek-v4-flash-vision-exp'),'messages':messages,'tools':tools,'tool_choice':'auto','thinking':{'type':'disabled'}}
    write_json(run/'request.json',{'request_id':rid,'purpose':purpose,'endpoint':endpoint,'body':redact(body)})
    req=urllib.request.Request(endpoint,json.dumps(body,ensure_ascii=False).encode(),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    begin=time.monotonic()
    def send():
        with urllib.request.urlopen(req,timeout=300) as response:raw=json.loads(response.read())
        write_json(run/'response.json',raw)
        choice=raw['choices'][0];message=choice['message'];finish=choice.get('finish_reason')
        write_json(run/'usage.json',{'seconds':time.monotonic()-begin,'usage':raw.get('usage'),'finish_reason':finish,'request_id':rid})
        if finish not in ('stop','tool_calls'):raise ValueError('incomplete response: '+str(finish))
        if not isinstance(message,dict) or message.get('role')!='assistant':raise ValueError('invalid assistant message')
        calls=message.get('tool_calls') or [];ids=[]
        for c in calls:
            if c.get('type')!='function' or not isinstance(c.get('id'),str) or not c['id'] or not isinstance(c.get('function',{}).get('arguments'),str):raise ValueError('invalid native tool call')
            ids.append(c['id'])
        if len(ids)!=len(set(ids)):raise ValueError('duplicate tool call IDs in response')
        return message
    try:return request_once('deepseek',rid,ledger or PLUS_ROOT/'runs/session-ledger.jsonl',send)
    except Exception as e:
        details=e.read().decode('utf-8','replace')[:2000] if hasattr(e,'read') else str(e)
        write_json(run/'error.json',{'error':type(e).__name__,'details':details,'seconds':time.monotonic()-begin});raise
