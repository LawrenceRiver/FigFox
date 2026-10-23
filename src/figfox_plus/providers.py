"""Durable attempt budgets and single-shot DeepSeek vision transport."""
import base64
import fcntl
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
from uuid import uuid4
from .state import PLUS_ROOT,write_json
BUDGET={'gpt-5.5':None,'deepseek':None}


def request_once(role,request_id,ledger,send,budget=None,image_hash=None,rerun_authorization=None):
    budget=BUDGET if budget is None else budget
    if role not in budget:raise ValueError('unknown budget role')
    ledger=Path(ledger);ledger.parent.mkdir(parents=True,exist_ok=True)
    with ledger.open('a+') as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.seek(0)
        records=[json.loads(line) for line in f if line.strip()]
        if any(r.get('request_id')==request_id for r in records):raise ValueError('duplicate request ID')
        if rerun_authorization and any(r.get('event')=='sending' and r.get('rerun_authorization')==rerun_authorization for r in records):
            raise ValueError('rerun authorization already consumed')
        if role=='gpt-5.5' and image_hash and not rerun_authorization:
            prior_ids=set()
            for path in ledger.parent.glob('formal-*/gpt55/request.json'):
                prior=json.loads(path.read_text())
                if prior.get('images') and prior['images'][0]['sha256']==image_hash:prior_ids.add(prior.get('request_id'))
            if any(r.get('event')=='sending' and r.get('role')==role and (r.get('image_hash')==image_hash or r.get('request_id') in prior_ids) for r in records):
                raise ValueError('GPT-5.5 already attempted for this original; reuse saved response')
        if budget[role] is not None and sum(r.get('event')=='sending' and r.get('role')==role for r in records)>=budget[role]:raise ValueError('request budget exhausted')
        f.write(json.dumps(dict(event='sending',role=role,request_id=request_id,image_hash=image_hash,rerun_authorization=rerun_authorization,at=time.time()))+'\n');f.flush();os.fsync(f.fileno())
        fcntl.flock(f,fcntl.LOCK_UN)
    status='error'
    try:
        result=send();status='ok';return result
    except Exception:
        status='error';raise
    finally:
        with ledger.open('a') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            f.write(json.dumps(dict(event=status,role=role,request_id=request_id,at=time.time()))+'\n');f.flush();os.fsync(f.fileno())


def load_key(name):
    value=os.environ.get(name,'').strip()
    if value:return value
    explicit=os.environ.get('FLOW_ENV_FILE')
    files=([Path(explicit).expanduser()] if explicit else [])+[PLUS_ROOT/'.env.local',PLUS_ROOT/'.env']
    for file in files:
        if not file.is_file():continue
        for line in file.read_text().splitlines():
            line=line.strip()
            if line.startswith('export '):line=line[7:].strip()
            if line.startswith(name+'='):
                value=line.split('=',1)[1].strip().strip('"').strip("'").strip()
                if value:return value
    raise ValueError('missing credential '+name)


def call_deepseek(prompt,images,run_dir,purpose):
    key=load_key('DEEPSEEK_API_KEY');run=Path(run_dir);run.mkdir(parents=True,exist_ok=True)
    request_id=uuid4().hex;endpoint='https://api.deepseek.com/chat/completions'
    model=os.environ.get('FLOW_DS_MODEL','deepseek-v4-flash-vision-exp')
    content=[{'type':'text','text':prompt}];manifest=[]
    for image in images:
        path=Path(image)
        # Full-resolution diagnostic copy: JPEG encoding reduces transport bytes only.
        from PIL import Image
        copy_path=run/'input-images'/f'{len(manifest):03d}.jpg';copy_path.parent.mkdir(exist_ok=True)
        with Image.open(path) as im:im.convert('RGB').save(copy_path,quality=95,subsampling=0)
        data=copy_path.read_bytes();manifest.append(dict(path=str(copy_path.resolve()),source_path=str(path.resolve()),sha256=hashlib.sha256(data).hexdigest(),encoding='jpeg95',dimensions_preserved=True))
        content.append({'type':'text','text':f'Image {len(manifest)} - {path.stem}. Match this index to the supplied original/current image order.'})
        content.append({'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(data).decode(),'detail':'original'}})
    body={'model':model,'messages':[{'role':'user','content':content}],'max_tokens':24000 if purpose.startswith('native') else 12000,'thinking':{'type':'disabled'}}
    if purpose.startswith('native'):body['response_format']={'type':'json_object'}
    write_json(run/'request.json',dict(request_id=request_id,purpose=purpose,endpoint=endpoint,model=model,prompt=prompt,images=manifest))
    req=urllib.request.Request(endpoint,json.dumps(body).encode(),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    def send():
        with urllib.request.urlopen(req,timeout=240) as response:raw=json.loads(response.read())
        write_json(run/'response.json',raw)
        text=raw['choices'][0]['message']['content'];(run/'response.txt').write_text(text);return text
    try:return request_once('deepseek',request_id,PLUS_ROOT/'runs/session-ledger.jsonl',send)
    except Exception as error:
        details=error.read().decode('utf-8','replace')[:3000] if hasattr(error,'read') else str(error)[:1000]
        write_json(run/'error.json',dict(type=type(error).__name__,http_status=getattr(error,'code',None),details=details))
        raise


def _image_mime(data):
    if data.startswith(b'\x89PNG\r\n\x1a\n'):return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):return 'image/jpeg'
    if data.startswith((b'GIF87a',b'GIF89a')):return 'image/gif'
    if data.startswith(b'RIFF') and data[8:12]==b'WEBP':return 'image/webp'
    raise ValueError('unsupported image content')


def _openai_config():
    model=os.environ.get('FLOW_OPENAI_MODEL','gpt-5.5').strip()
    effort=os.environ.get('FLOW_OPENAI_REASONING_EFFORT','medium').strip()
    limit=os.environ.get('FLOW_OPENAI_MAX_OUTPUT_TOKENS','32768').strip()
    if not model:raise ValueError('FLOW_OPENAI_MODEL must be nonempty')
    if effort not in {'none','minimal','low','medium','high','xhigh'}:
        raise ValueError('FLOW_OPENAI_REASONING_EFFORT is invalid')
    if not limit.isdecimal() or not 1<=int(limit)<=128000:
        raise ValueError('FLOW_OPENAI_MAX_OUTPUT_TOKENS must be 1..128000')
    return model,effort,int(limit)


def call_gpt55(prompt,images,run_dir,purpose,*,rerun_authorization=None,send_http=None,ledger=None):
    model,effort,limit=_openai_config()
    # Injected transports are offline fixtures and require no credential.
    key=load_key('OPENAI_API_KEY') if send_http is None else None
    run=Path(run_dir)
    if (run/'request.json').exists():raise ValueError('this request directory was already attempted; no implicit retry')
    content=[{'type':'input_text','text':prompt}];manifest=[]
    for image in images:
        path=Path(image);data=path.read_bytes();mime=_image_mime(data)
        manifest.append(dict(path=str(path.resolve()),sha256=hashlib.sha256(data).hexdigest(),mime=mime))
        content.append({'type':'input_image','image_url':f'data:{mime};base64,'+base64.b64encode(data).decode(),'detail':'original'})
    endpoint='https://api.openai.com/v1/responses';rid=uuid4().hex
    body=dict(model=model,reasoning={'effort':effort},max_output_tokens=limit,input=[{'role':'user','content':content}],stream=True,store=False)
    body_bytes=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode('utf-8')
    headers={'Content-Type':'application/json'}
    if key is not None:headers['Authorization']='Bearer '+key
    req=urllib.request.Request(endpoint,body_bytes,headers)
    run.mkdir(parents=True,exist_ok=True)
    write_json(run/'request.json',dict(request_id=rid,purpose=purpose,endpoint=endpoint,model=model,prompt=prompt,images=manifest,rerun_authorization=rerun_authorization,body=body,body_sha256=hashlib.sha256(body_bytes).hexdigest()))
    started=time.monotonic()
    def send():
        pieces=[];completed=False
        transport=urllib.request.urlopen if send_http is None else send_http
        try:
            with transport(req,timeout=1800) as response,(run/'events.jsonl').open('w') as events:
                for raw in response:
                    line=raw.decode('utf-8','replace').strip()
                    if not line.startswith('data:') or line[5:].strip()=='[DONE]':continue
                    event=json.loads(line[5:].strip());events.write(json.dumps(event,ensure_ascii=False)+'\n');events.flush()
                    kind=event.get('type')
                    if kind=='response.output_text.delta':pieces.append(event.get('delta',''))
                    if kind in ('response.completed','response.incomplete','response.failed'):
                        final=event.get('response')
                        if final is not None:
                            write_json(run/'response.json',final)
                            if final.get('usage') is not None:write_json(run/'usage.json',final['usage'])
                    if kind=='response.completed':
                        completed=True
                        if event.get('response',{}).get('status')!='completed':raise ValueError('GPT response incomplete or failed')
                    if kind in ('response.failed','response.incomplete','error'):raise ValueError('GPT response incomplete or failed')
        finally:
            (run/'response.txt').write_text(''.join(pieces))
        if not completed:raise ValueError('GPT stream ended without completion')
        return ''.join(pieces)
    try:
        return request_once('gpt-5.5',rid,ledger or PLUS_ROOT/'runs/session-ledger.jsonl',send,image_hash=manifest[0]['sha256'] if manifest else None,rerun_authorization=rerun_authorization)
    except Exception as error:
        details=error.read().decode('utf-8','replace')[:3000] if hasattr(error,'read') else str(error)[:1000]
        if key:details=details.replace(key,'[REDACTED]')
        write_json(run/'error.json',dict(type=type(error).__name__,http_status=getattr(error,'code',None),details=details))
        raise
    finally:
        write_json(run/'timings.json',dict(elapsed_seconds=time.monotonic()-started))
