"""Single-attempt transport with persistent identities and charge reserves."""
import base64
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
import urllib.error
from uuid import uuid4
from ..state import write_json


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def request(folder,prompt,images,settings,*,http=None):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    identity=digest({'prompt':prompt,'images':[hashlib.sha256(Path(x).read_bytes()).hexdigest() for x in images],'settings':settings})
    receipt=folder/'receipt.json'
    if receipt.exists():
        saved=json.loads(receipt.read_text())
        if saved['input_sha256']!=identity:raise ValueError('frozen request input changed')
        if saved['status']!='completed':raise ValueError('uncertain or failed request retained; no automatic resend')
        data=(folder/'response.json').read_bytes()
        if hashlib.sha256(data).hexdigest()!=saved['response_sha256']:raise ValueError('response hash mismatch')
        return json.loads(data)['text']
    reserve=(settings['max_input_tokens']*settings['input_usd_per_million']+settings['max_output_tokens']*settings['output_usd_per_million'])/1e6
    if reserve>settings['budget_usd']:raise ValueError('request reserve exceeds remaining budget')
    key=None if http else os.environ.get(settings['key_env'])
    if not http and not key:raise ValueError('missing credential '+settings['key_env'])
    protocol=settings.get('protocol','responses')
    content=[{'type':'input_text' if protocol=='responses' else 'text','text':prompt}]
    for path in images:
        data=Path(path).read_bytes();mime='image/jpeg' if data.startswith(b'\xff\xd8') else 'image/png';url='data:'+mime+';base64,'+base64.b64encode(data).decode()
        content.append({'type':'input_image','image_url':url,'detail':'original'} if protocol=='responses' else {'type':'image_url','image_url':{'url':url}})
    # UTF-8 bytes conservatively bound text tokens; image tokens use a per-tile upper bound.
    from PIL import Image
    import math
    bound=len(prompt.encode())
    for path in images:
        with Image.open(path) as im:bound+=4096*math.ceil(im.width/512)*math.ceil(im.height/512)+4096
    if bound>settings['max_input_tokens']:raise ValueError('complete request exceeds configured input bound before HTTP')
    body={'model':settings['model']}
    if protocol=='responses':body.update(input=[{'role':'user','content':content}],max_output_tokens=settings['max_output_tokens'],reasoning={'effort':'medium'},store=False)
    else:body.update(messages=[{'role':'user','content':content}],max_tokens=settings['max_output_tokens'],response_format={'type':'json_object'})
    record={'request_id':uuid4().hex,'input_sha256':identity,'status':'uncertain','reserved_usd':reserve,'model':settings['model']}
    write_json(receipt,record);start=time.monotonic()
    try:
        if http:raw=http(body)
        else:
            req=urllib.request.Request(settings['endpoint'],json.dumps(body).encode(),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=settings.get('timeout_seconds',900)) as response:raw=json.loads(response.read())
        if protocol=='responses':
            if raw.get('status') not in (None,'completed'):raise ValueError('provider response is incomplete')
            text=''.join(c.get('text','') for item in raw.get('output',[]) for c in item.get('content',[]) if c.get('type')=='output_text')
        else:
            if raw['choices'][0].get('finish_reason')!='stop':raise ValueError('provider response is incomplete')
            text=raw['choices'][0]['message']['content']
        if not text:raise ValueError('empty provider output')
        usage=raw.get('usage',{});inp=usage.get('input_tokens',usage.get('prompt_tokens'));out=usage.get('output_tokens',usage.get('completion_tokens'))
        cached=usage.get('input_tokens_details',usage.get('prompt_tokens_details',{})).get('cached_tokens',0)
        known=(((inp-cached)*settings['input_usd_per_million']+cached*settings.get('cached_usd_per_million',settings['input_usd_per_million'])+out*settings['output_usd_per_million'])/1e6) if inp is not None and out is not None else None
        write_json(folder/'response.json',{'text':text,'provider':raw})
        record.update(status='completed',usage=usage,known_usd=known,reserved_usd=reserve if known is None else 0,response_sha256=hashlib.sha256((folder/'response.json').read_bytes()).hexdigest())
        return text
    except Exception as error:
        record.update(error_type=type(error).__name__)
        # Ambiguous transport failures keep their entire reserve and request identity.
        raise
    finally:
        record['seconds']=time.monotonic()-start;write_json(receipt,record)


def sender(config,root):
    root=Path(root)
    def send(stage,prompt,payload,images,folder):
        provider=dict(config['stages'][stage]);exposure=0
        for file in root.glob('**/receipt.json'):
            r=json.loads(file.read_text());exposure+=float(r.get('known_usd') or 0)+float(r.get('reserved_usd') or 0)
        provider['budget_usd']=config['budget_usd']-exposure
        # Budget is a cohort control, not part of the immutable request identity.
        existing=Path(folder)/'receipt.json'
        if existing.exists():
            saved_config=Path(folder)/'provider.json'
            if saved_config.exists():provider=json.loads(saved_config.read_text())
        else:write_json(Path(folder)/'provider.json',provider)
        text=request(folder,prompt+'\n'+json.dumps(payload,ensure_ascii=False),images,provider)
        return text if stage=='G0' else json.loads(text.removeprefix('```json').removesuffix('```').strip())
    return send
