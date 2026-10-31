"""Original-image assets; source crops remain distinct from target placement."""
import hashlib
import math
from pathlib import Path
from PIL import Image
from .state import write_json


def crop_asset(image,box,out_dir):
    if not isinstance(box,(list,tuple)) or len(box)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in box):
        raise ValueError('source_crop must be finite original-image xywh')
    x,y,w,h=box
    if w<=0 or h<=0:raise ValueError('empty crop')
    image=Path(image);source_hash=hashlib.sha256(image.read_bytes()).hexdigest()
    with Image.open(image) as source:
        W,H=source.size
        l=max(0,math.floor(x));t=max(0,math.floor(y));r=min(W,math.ceil(x+w));b=min(H,math.ceil(y+h))
        if r<=l or b<=t:raise ValueError('crop outside source image')
        if (l,t,r,b)==(0,0,W,H):raise ValueError('whole-source asset cannot replace local content')
        actual=[l,t,r-l,b-t]
        identity=hashlib.sha256((source_hash+str(actual)).encode()).hexdigest()[:20]
        out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
        path=out/(identity+'.png');source.crop((l,t,r,b)).save(path)
    asset={'id':'asset_'+identity,'source_hash':source_hash,'source_crop':actual,
           'requested_crop':list(box),'source_size':[W,H],'representation':'raster',
           'path':str(path.resolve()),'method':'original-image-crop'}
    write_json(out/(identity+'.json'),asset)
    return asset


def raster_part(data,assets):
    import base64
    import io
    matches=[a for a in assets if a['id']==data['asset_id']]
    if len(matches)!=1:raise ValueError('asset reference must resolve exactly once')
    asset=matches[0]
    if asset['representation']!='raster':raise ValueError('picture requires raster asset')
    values=[data.get(k) for k in ('x','y','width','height')]
    if any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in values):
        raise ValueError('picture placement requires finite xywh')
    x,y,w,h=values
    if min(w,h)<=0:raise ValueError('picture target must be positive')
    with Image.open(asset['path']) as im:
        iw,ih=im.size;scale=min(w/iw,h/ih);pw,ph=iw*scale,ih*scale
        buffer=io.BytesIO();im.save(buffer,format='PNG')
    x+=(w-pw)/2;y+=(h-ph)/2
    return {'part':'raster','tag':'image','points':[[x,y],[x+pw,y+ph]],
            'attrs':{'x':x,'y':y,'width':pw,'height':ph,'preserveAspectRatio':'xMidYMid meet',
                     'href':'data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode()}}


def vector_element(data,assets,owner):
    import re
    import xml.etree.ElementTree as ET
    matches=[a for a in assets if a['id']==data['asset_id']]
    if len(matches)!=1 or matches[0]['representation']!='vector':raise ValueError('vector asset reference invalid')
    root=ET.parse(matches[0]['path']).getroot();namespace='http://www.w3.org/2000/svg'
    allowed={'svg','g','defs','path','rect','circle','ellipse','polygon','polyline','line','linearGradient','radialGradient','stop','title','desc'}
    ids={}
    for node in root.iter():
        if node.tag.split('}')[-1] not in allowed:raise ValueError('unsupported vector asset element: '+node.tag)
        if node.get('id'):
            old=node.get('id')
            if old in ids:raise ValueError('duplicate asset ID')
            ids[old]='sp.asset.'+owner+'.'+old
    for node in root.iter():
        for key,value in list(node.attrib.items()):
            if key=='id':node.set(key,ids[value]);continue
            if key.lower().startswith('on'):raise ValueError('unsupported active asset attribute')
            if 'href' in key:
                if not value.startswith('#') or value[1:] not in ids:raise ValueError('external/unresolved asset reference')
                node.set(key,'#'+ids[value[1:]]);continue
            def replace(match):
                ref=match.group(1).strip(' \"\'')
                if not ref.startswith('#') or ref[1:] not in ids:raise ValueError('external/unresolved asset URL')
                return 'url(#'+ids[ref[1:]]+')'
            node.set(key,re.sub(r'url\(([^)]+)\)',replace,value))
    if root.get('viewBox'):box=list(map(float,root.get('viewBox').replace(',',' ').split()))
    else:box=[0,0,float(root.get('width')),float(root.get('height'))]
    if len(box)!=4 or not all(math.isfinite(v) for v in box) or min(box[2:])<=0:raise ValueError('invalid asset viewBox')
    x,y,w,h=[data[k] for k in ('x','y','width','height')]
    if not all(isinstance(v,(float,int)) and math.isfinite(v) for v in (x,y,w,h)) or min(w,h)<=0:raise ValueError('invalid vector target')
    scale=min(w/box[2],h/box[3]);pw,ph=box[2]*scale,box[3]*scale
    group=ET.Element('{'+namespace+'}g',{'transform':f'matrix({scale} 0 0 {scale} {x+(w-pw)/2-box[0]*scale} {y+(h-ph)/2-box[1]*scale})'})
    # Retain root presentation attributes, but use explicit viewBox mapping.
    for key,value in root.attrib.items():
        if key not in ('width','height','viewBox','version','xmlns','id','transform'):group.set(key,value)
    if root.get('transform'):raise ValueError('asset root transform not supported')
    group.extend(list(root));return group


def remove_background_asset(asset, out_dir):
    """Preserve crop coordinates and RGBA; fail explicitly instead of returning raw crop."""
    import json, os, subprocess, time
    from .state import PLUS_ROOT
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True)
    runtime=PLUS_ROOT.parent/'tools/drawai-official-20260815'
    runtime_root=runtime/'.local/drawai_runtime'
    runner=PLUS_ROOT/'runtime/rmbg_runner.py'
    model=runtime_root/'models/rmbg2/model.safetensors'
    if not model.is_file():raise ValueError('RMBG2 local model unavailable')
    signature={'crop_sha256':hashlib.sha256(Path(asset['path']).read_bytes()).hexdigest(),
               'runner_sha256':hashlib.sha256(runner.read_bytes()).hexdigest(),
               'runtime_sha256':hashlib.sha256((runtime/'src/drawai/local_runtime.py').read_bytes()).hexdigest(),
               'model_size':model.stat().st_size,'model_mtime_ns':model.stat().st_mtime_ns}
    key=hashlib.sha256(json.dumps(signature,sort_keys=True).encode()).hexdigest()[:24]
    target=out/(key+'-rmbg.png');metadata=target.with_suffix('.json')
    if target.exists() and metadata.exists():
        cached=json.loads(metadata.read_text())
        if cached.get('output_sha256')==hashlib.sha256(target.read_bytes()).hexdigest():
            return {**asset,**cached['derived'],'path':str(target.resolve())}
    payload={'source':asset['path'],'target':str(target.resolve()),'runtime_source':str(runtime/'src'), 'runtime_root':str(runtime_root)}
    event={'event':'local_rmbg_start','time':time.time(),'signature':signature,'source':asset['path'],'target':str(target)}
    with (out/'rmbg-ledger.jsonl').open('a') as ledger:
        ledger.write(json.dumps(event)+'\n');ledger.flush();os.fsync(ledger.fileno())
    start=time.monotonic()
    try:
        result=subprocess.run([str(runtime_root/'.venv/bin/python'),str(runner)],input=json.dumps(payload),text=True,capture_output=True,timeout=180)
        if result.returncode:raise ValueError('RMBG2 failed: '+result.stderr[-1000:])
        with Image.open(asset['path']) as source, Image.open(target) as image:
            if image.mode!='RGBA' or image.size!=source.size:raise ValueError('RMBG2 changed crop dimensions or omitted alpha')
        derived={'id':asset['id']+'_rmbg_'+key,'background_removal':{'method':'RMBG2','runtime':'local CPU','seconds':time.monotonic()-start,'source_asset_path':asset['path'],'signature':signature}}
        write_json(metadata,{'derived':derived,'output_sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    except Exception:
        target.unlink(missing_ok=True);metadata.unlink(missing_ok=True)
        raise
    return {**asset,**derived,'path':str(target.resolve())}
