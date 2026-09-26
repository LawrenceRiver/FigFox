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
    file=PLUS_ROOT.parent/'.env.local'
    if file.exists():
        for line in file.read_text().splitlines():
            if line.startswith(name+'='):return line.split('=',1)[1].strip().strip('"').strip("'")
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


def call_gpt55(prompt,images,run_dir,purpose,*,rerun_authorization=None):
    try:key=load_key('OPENAI_API_KEY')
    except ValueError:
        # Read the already configured legacy credential without importing its script.
        import ast
        tree=ast.parse((PLUS_ROOT.parent/'output/gpt55-once.py').read_text())
        key=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='OPENAI_API_KEY' for t in n.targets))
    run=Path(run_dir);run.mkdir(parents=True,exist_ok=True);rid=uuid4().hex
    content=[{'type':'input_text','text':prompt}];manifest=[]
    for image in images:
        path=Path(image);data=path.read_bytes();manifest.append(dict(path=str(path.resolve()),sha256=hashlib.sha256(data).hexdigest()))
        content.append({'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(data).decode(),'detail':'original'})
    endpoint='https://api.openai.com/v1/responses'
    body=dict(model='gpt-5.5',reasoning={'effort':'medium'},input=[{'role':'user','content':content}],stream=True,store=False)
    write_json(run/'request.json',dict(request_id=rid,purpose=purpose,model='gpt-5.5',prompt=prompt,images=manifest,rerun_authorization=rerun_authorization))
    req=urllib.request.Request(endpoint,json.dumps(body).encode(),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    def send():
        pieces=[];completed=False
        with urllib.request.urlopen(req,timeout=1800) as response,(run/'events.jsonl').open('w') as events:
            for raw in response:
                line=raw.decode('utf-8','replace').strip()
                if not line.startswith('data:') or line[5:].strip()=='[DONE]':continue
                event=json.loads(line[5:].strip());events.write(json.dumps(event)+'\n');events.flush()
                if event.get('type')=='response.output_text.delta':pieces.append(event.get('delta',''))
                if event.get('type')=='response.completed':completed=True;write_json(run/'response.json',event['response'])
                if event.get('type') in ('response.failed','response.incomplete','error'):raise ValueError('GPT response incomplete or failed')
        text=''.join(pieces);(run/'response.txt').write_text(text)
        if not completed:raise ValueError('GPT stream ended without completion')
        return text
    try:return request_once('gpt-5.5',rid,PLUS_ROOT/'runs/session-ledger.jsonl',send,image_hash=manifest[0]['sha256'],rerun_authorization=rerun_authorization)
    except Exception as error:
        write_json(run/'error.json',dict(type=type(error).__name__,http_status=getattr(error,'code',None)));raise
