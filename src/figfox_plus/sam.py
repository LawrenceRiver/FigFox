"""Read-only bridge to existing SAM collector; no color/OCR and no retry."""
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from .state import PLUS_ROOT,new_run,write_json


def prepare_assets(image,out_dir,*,transport=None,service_url='http://127.0.0.1:18080',force_refresh=False):
    source=PLUS_ROOT/'adapters/raw_evidence.py'
    name='_plus_raw_evidence'
    if name not in sys.modules:
        spec=importlib.util.spec_from_file_location(name,source);module=importlib.util.module_from_spec(spec)
        sys.modules[name]=module;spec.loader.exec_module(module)
    m=sys.modules[name]
    prompts=tuple(p for p in m.DEFAULT_SAM_PROMPTS if p['id'] in ('picture','icon','arrow'))
    image=Path(image);digest=hashlib.sha256(image.read_bytes()).hexdigest()
    config={'mock':transport is not None,'prompts':prompts,'url':service_url,'adapter_hash':hashlib.sha256(source.read_bytes()).hexdigest()}
    key=hashlib.sha256((digest+json.dumps(config,sort_keys=True)).encode()).hexdigest()
    out=Path(out_dir);cache=out/(key+'.json')
    if cache.exists() and not force_refresh:
        saved=json.loads(cache.read_text(encoding='utf-8'))
        if all(Path(a['path']).is_file() and hashlib.sha256(Path(a['path']).read_bytes()).hexdigest()==a.get('asset_hash')
               for a in saved['assets']):return {**saved,'cache_hit':True}
    run=new_run(out,'sam');actual=transport or m._HttpJsonTransport(service_url)
    class LoggedTransport:
        def post_json(self,path,payload,timeout_seconds):
            with (out/'sam-ledger.jsonl').open('a', encoding='utf-8') as ledger:
                ledger.write(json.dumps({'event':'sending','time':time.time(),'source_hash':digest,'run':run.name,'mock':transport is not None})+'\n');ledger.flush();os.fsync(ledger.fileno())
            return actual.post_json(path,payload,timeout_seconds)
    class Once(m.RawEvidenceCollector):
        def _request_with_retry(self,source,path,payload,stage,canonical_image,image_size):
            response,duration,assets=self._request_one(source,path,payload,stage,canonical_image,image_size)
            return response,duration,assets,m._source_ready_assets(source,response,assets,image_size)
    result=Once(m.RawEvidenceOptions(service_base_url=service_url,timeout_seconds=120,sam_prompts=prompts),transport=LoggedTransport()).collect(image,run/'evidence',sources=('sam',))
    catalog=json.loads(result.catalog_path.read_text(encoding='utf-8'));assets=[]
    for a in catalog.get('assets',[]):
        l,t,r,b=a['bbox'];label=(a.get('prompt','')+' '+a.get('object_type','')).lower()
        assets.append({'id':'asset_'+a['asset_id'].replace('-','_'),'source_hash':digest,'source_crop':[l,t,r-l,b-t],
          'representation':'raster','path':str((result.catalog_path.parent/a['asset_path']).resolve()),
          'role':'arrow_hint' if 'arrow' in label else 'picture','method':'sam','raw':a,'asset_hash':a['sha256']})
    record={'source_hash':digest,'config':config,'assets':assets,'status':dict(result.source_status),'cache_hit':False,
            'catalog_path':str(result.catalog_path),'mock':transport is not None}
    write_json(run/'result.json',record)
    if all(v=='ok' for v in result.source_status.values()):write_json(cache,record)
    return record
