"""Durable attempt budgets and single-shot DeepSeek vision transport."""
import base64
from figfox_plus import file_lock as fcntl
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
from uuid import uuid4
from .state import PLUS_ROOT,write_json
from .cost_budget import cost_guard, gpt_input_upper_bound
from .progress import RequestProgress
BUDGET={'gpt-5.5':None,'deepseek':None}


def request_once(role,request_id,ledger,send,budget=None,image_hash=None,rerun_authorization=None):
    budget=BUDGET if budget is None else budget
    if role not in budget:raise ValueError('unknown budget role')
    ledger=Path(ledger);ledger.parent.mkdir(parents=True,exist_ok=True)
    with ledger.open('a+', encoding='utf-8') as f:
        fcntl.flock(f,fcntl.LOCK_EX);f.seek(0)
        records=[json.loads(line) for line in f if line.strip()]
        if any(r.get('request_id')==request_id for r in records):raise ValueError('duplicate request ID')
        if rerun_authorization and any(r.get('event')=='sending' and r.get('rerun_authorization')==rerun_authorization for r in records):
            raise ValueError('rerun authorization already consumed')
        if role=='gpt-5.5' and image_hash and not rerun_authorization:
            prior_ids=set()
            for path in ledger.parent.glob('formal-*/gpt55/request.json'):
                prior=json.loads(path.read_text(encoding='utf-8'))
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
        with ledger.open('a', encoding='utf-8') as f:
            fcntl.flock(f,fcntl.LOCK_EX)
            f.write(json.dumps(dict(event=status,role=role,request_id=request_id,at=time.time()))+'\n');f.flush();os.fsync(f.fileno())


def load_key(name):
    value=os.environ.get(name,'').strip()
    if value:return value
    for file in (PLUS_ROOT/'.env.local', PLUS_ROOT/'.env', PLUS_ROOT.parent/'.env.local'):
        if not file.is_file():continue
        for line in file.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if line.startswith('export '):line=line[7:].lstrip()
            if not line or line.startswith('#') or '=' not in line:continue
            key,value=line.split('=',1)
            value=value.strip().strip('"').strip("'")
            if key.strip()==name and value:
                return value
    raise ValueError('missing credential '+name)


def call_deepseek(prompt,images,run_dir,purpose):
    key=load_key('DEEPSEEK_API_KEY');run=Path(run_dir);run.mkdir(parents=True,exist_ok=True)
    request_id=uuid4().hex;endpoint='https://api.deepseek.com/chat/completions'
    model=os.environ.get('FLOW_DS_MODEL','').strip() or 'deepseek-flash'
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
        text=raw['choices'][0]['message']['content'];(run/'response.txt').write_text(text, encoding='utf-8');return text
    try:return request_once('deepseek',request_id,PLUS_ROOT/'runs/session-ledger.jsonl',send)
    except Exception as error:
        details=error.read().decode('utf-8','replace')[:3000] if hasattr(error,'read') else str(error)[:1000]
        write_json(run/'error.json',dict(type=type(error).__name__,http_status=getattr(error,'code',None),details=details))
        raise


def call_gpt55(prompt,images,run_dir,purpose,*,rerun_authorization=None):
    key=load_key('OPENAI_API_KEY')
    run=Path(run_dir);run.mkdir(parents=True,exist_ok=True);rid=uuid4().hex
    content=[{'type':'input_text','text':prompt}];manifest=[]
    for image in images:
        path=Path(image);data=path.read_bytes();manifest.append(dict(path=str(path.resolve()),sha256=hashlib.sha256(data).hexdigest()))
        content.append({'type':'input_image','image_url':'data:image/png;base64,'+base64.b64encode(data).decode(),'detail':'original'})
    endpoint='https://api.openai.com/v1/responses'
    requested_output=int(os.environ.get('FIGFOX_GPT_MAX_OUTPUT_TOKENS','128000'))
    if not 1 <= requested_output <= 128000:
        raise ValueError('FIGFOX_GPT_MAX_OUTPUT_TOKENS must be between 1 and 128000')
    body=dict(model='gpt-5.5',reasoning={'effort':'medium'},input=[{'role':'user','content':content}],
              max_output_tokens=requested_output,stream=True,store=False)
    input_bound=gpt_input_upper_bound(prompt,images) if os.environ.get('FIGFOX_COST_LIMIT_USD') else 0
    with cost_guard('gpt-5.5',rid,run,input_bound,requested_output) as ticket:
        body.update(service_tier='default')
        write_json(run/'request.json',dict(request_id=rid,purpose=purpose,model='gpt-5.5',prompt=prompt,images=manifest,
            rerun_authorization=rerun_authorization,max_output_tokens=body.get('max_output_tokens'),input_token_upper_bound=input_bound or None))
        req=urllib.request.Request(endpoint,json.dumps(body).encode(),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        def send():
            pieces=[];completed=False;usage=None;failure=None
            progress=RequestProgress(run,'gpt-5.5')
            if ticket:ticket['sent']=True
            try:
                with urllib.request.urlopen(req,timeout=1800) as response,(run/'events.jsonl').open('w', encoding='utf-8') as events:
                    progress.attach(response)
                    for raw in response:
                        progress.wire(raw)
                        line=raw.decode('utf-8','replace').strip()
                        if not line.startswith('data:') or line[5:].strip()=='[DONE]':continue
                        event=json.loads(line[5:].strip());events.write(json.dumps(event)+'\n');events.flush()
                        kind=event.get('type','')
                        usage=(event.get('response') or {}).get('usage') or event.get('usage') or usage
                        progress.delta(content=event.get('delta','') if kind=='response.output_text.delta' else '',
                            reasoning=event.get('delta','') if kind in ('response.reasoning_summary_text.delta','response.reasoning_text.delta') else '',
                            usage=usage)
                        if kind=='response.output_text.delta':pieces.append(event.get('delta',''))
                        if event.get('type')=='response.completed':completed=True;write_json(run/'response.json',event['response'])
                        if event.get('type') in ('response.failed','response.incomplete','error'):
                            if event.get('response'):write_json(run/'response.json',event['response'])
                            raise ValueError('GPT response incomplete or failed')
                progress.check()
                if not completed:raise ValueError('GPT stream ended without completion')
                return ''.join(pieces)
            except Exception as error:
                failure=progress.interrupt_when_stalled(error)
                progress.check()
                raise
            finally:
                (run/'response.txt').write_text(''.join(pieces),encoding='utf-8')
                progress.finish(error=failure,usage=usage)
        try:return request_once('gpt-5.5',rid,PLUS_ROOT/'runs/session-ledger.jsonl',send,image_hash=manifest[0]['sha256'],rerun_authorization=rerun_authorization)
        except Exception as error:
            write_json(run/'error.json',dict(type=type(error).__name__,http_status=getattr(error,'code',None)));raise
