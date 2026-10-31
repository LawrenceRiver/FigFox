#!/usr/bin/env python3
"""Offline, explicit-input preparation only. Never starts a role or a run."""
import argparse
from copy import deepcopy
import hashlib
import json
import math
import stat
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime,timezone
import re
import xml.etree.ElementTree as ET

RUNTIME_KEYS=('NODE_PATH','PLUS_PLAYWRIGHT_MODULE','PLUS_CHROMIUM','PLUS_VECTOR_PYTHON','PLUS_NODE')
DISABLED={'format':'sam-disabled-catalog-v1','status':'disabled_by_assignment','assets':[],'missing_assets':[],'complete_available_catalog':True}

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def _pairs(rows):
    result={}
    for key,value in rows:
        if key in result:raise ValueError('duplicate JSON key: '+key)
        result[key]=value
    return result
def read(path):return json.loads(Path(path).read_text(),object_pairs_hook=_pairs)
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(value,stream,indent=2);stream.write('\n')
def source_manifest(source, expected_root=None):
    """Bind the intentional root link; reject all nested links, even in exclusions.

    No dependency closure is inferred. Nested links, special files and dangling
    links fail closed instead of being omitted or followed outside the binding.
    """
    source=Path(source)
    frozen=source.resolve(strict=True)
    if expected_root is not None and frozen!=Path(expected_root).resolve(strict=True):
        raise ValueError('native source root mismatch')
    if not frozen.is_dir():raise ValueError('native source directory required')
    result={}
    def walk(folder,excluded=False):
        for entry in sorted(folder.iterdir()):
            relative=entry.relative_to(frozen)
            mode=entry.lstat().st_mode
            if stat.S_ISLNK(mode):raise ValueError('nested source symlink forbidden: '+str(relative))
            skip=excluded or entry.name in ('__pycache__','.git','.pytest_cache')
            if stat.S_ISDIR(mode):walk(entry,skip)
            elif not stat.S_ISREG(mode):raise ValueError('unsupported native source entry: '+str(relative))
            elif not skip:result[str(relative)]=sha(entry)
    walk(frozen)
    return result
def _file(value):
    p=Path(value).absolute()
    if not p.exists():raise ValueError('required file unavailable: '+str(p))
    if not p.is_file():raise ValueError('required regular file: '+str(p))
    return p

def admit(spec):
    required={'adapter','output_root','original_png','initial_svg','runtime_json','runtime_binding','registry','capabilities','first_stage_provenance','python','native_source_root'}
    if not isinstance(spec,dict) or not required<=set(spec) or set(spec)-required-{'sam_catalog','shared_first_stage','empty_sam_execution_proof'}:raise ValueError('explicit preparation spec required: '+','.join(sorted(required)))
    s=deepcopy(spec);adapter=Path(s['adapter']).resolve(strict=True)
    if not adapter.is_dir():raise ValueError('adapter directory required')
    output=Path(s['output_root']).absolute()
    if output.exists() or output.is_symlink():raise ValueError('output already exists; immutable preparation')
    for k in ('original_png','initial_svg','runtime_json','runtime_binding','registry','first_stage_provenance','python'):s[k]=str(_file(s[k]))
    svg_text=Path(s['initial_svg']).read_text()
    try:tree=ET.fromstring(svg_text)
    except ET.ParseError as exc:raise ValueError('initial SVG must be XML') from exc
    for node in tree.iter():
        if node.tag.split('}')[-1].lower() in ('script','foreignobject'):raise ValueError('active SVG content forbidden offline')
        for key,value in node.attrib.items():
            name=key.split('}')[-1].lower()
            if name.startswith('on') or (name in ('href','src') and not value.startswith(('#','data:'))):raise ValueError('external/active SVG reference forbidden offline')
    if re.search(r'(?:@import|url\(\s*[\"\']?(?!#|data:))',svg_text,re.I):raise ValueError('external SVG resource forbidden offline')
    cap=s['capabilities'];policy=cap.get('policy') if isinstance(cap,dict) else None
    if not isinstance(policy,dict) or set(policy)!={'version','sam','code_methods'} or policy['version']!='capabilities-v1' or any(type(policy[k]) is not bool for k in ('sam','code_methods')) or set(cap)!={'policy','sha256'} or cap['sha256']!=digest(policy):raise ValueError('strict capability policy/hash required')
    runtime=read(s['runtime_json'])
    if set(runtime)!=set(RUNTIME_KEYS) or any(not isinstance(runtime[k],str) or not Path(runtime[k]).is_absolute() or not Path(runtime[k]).exists() for k in RUNTIME_KEYS):raise ValueError('installed explicit neutral runtime paths required')
    binding=read(s['runtime_binding'])
    if not isinstance(binding,dict) or binding.get('runtime_paths')!={k:str(Path(runtime[k]).resolve()) for k in RUNTIME_KEYS}:raise ValueError('runtime binding paths mismatch')
    source=adapter/'source'
    if not isinstance(s['native_source_root'],str) or not Path(s['native_source_root']).is_absolute():raise ValueError('explicit absolute native_source_root required')
    frozen=Path(s['native_source_root']).resolve(strict=True)
    manifest=source_manifest(source,expected_root=frozen)
    if not manifest:raise ValueError('native source unavailable')
    provenance=read(s['first_stage_provenance'])
    generation_capability_sha256=cap['sha256']
    if 'shared_first_stage' in s:
        shared=s['shared_first_stage'];generation_policy={**policy,'code_methods':False}
        if shared!={'format':'c-neutral-shared-initial-v1','generation_capability_sha256':digest(generation_policy),'source_provenance_sha256':sha(s['first_stage_provenance'])}:raise ValueError('shared first-stage phase binding mismatch')
        generation_capability_sha256=digest(generation_policy)
    expected={'original_png_sha256':sha(s['original_png']),'initial_svg_sha256':sha(s['initial_svg']),'capability_sha256':generation_capability_sha256,'native_source_manifest_sha256':digest(manifest)}
    if not isinstance(provenance,dict) or any(provenance.get(k)!=v for k,v in expected.items()):raise ValueError('first-stage capability/source/input provenance mismatch')
    if not isinstance(provenance.get('origin'),str) or not provenance['origin'].strip():raise ValueError('first-stage origin declaration required')
    assets=[];catalog=None
    if not policy['sam']:
        if 'sam_catalog' in s or 'empty_sam_execution_proof' in s:raise ValueError('SAM disabled: supplied catalog/proof forbidden')
    else:
        if 'sam_catalog' not in s:raise ValueError('SAM enabled: real catalog required')
        s['sam_catalog']=str(_file(s['sam_catalog']));catalog=read(s['sam_catalog'])
        if catalog.get('complete_available_catalog') is not True or catalog.get('missing_assets')!=[] or not isinstance(catalog.get('assets'),list):raise ValueError('complete real SAM catalog required')
        if not catalog['assets']:
            sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
            import empty_sam_execution
            empty_sam_execution.verify(s.get('empty_sam_execution_proof'),s['original_png'])
        elif 'empty_sam_execution_proof' in s:raise ValueError('empty execution proof cannot describe nonempty SAM catalog')
        ids=set()
        for item in catalog['assets']:
            if not isinstance(item,dict) or not all(k in item for k in ('id','role','source_crop','path','sha256')) or not isinstance(item['id'],str) or not item['id'].strip() or item['id']!=item['id'].strip() or item['id'] in ids or item['role'] not in ('picture','arrow_hint'):raise ValueError('SAM id/role/source_crop mapping required')
            crop=item['source_crop']
            if not isinstance(crop,list) or len(crop)!=4 or any(type(v) not in (int,float) or not math.isfinite(v) for v in crop) or crop[0]<0 or crop[1]<0 or crop[2]<=0 or crop[3]<=0:raise ValueError('SAM source_crop must be finite original-image pixel [left,top,width,height] crop')
            p=Path(item['path']);p=p if p.is_absolute() else Path(s['sam_catalog']).parent/p;p=_file(p)
            if sha(p)!=item['sha256']:raise ValueError('SAM asset hash mismatch')
            ids.add(item['id']);assets.append((item,p))
    for name in ('flow.py','brief.py','assignment_policy.py'):_file(adapter/name)
    s.update(adapter=str(adapter),output_root=str(output),native_source_root=str(frozen))
    return s,runtime,manifest,assets

def _worker(root):
    sys.path.insert(0,str(root));import flow,brief
    brief.P=Path(read(root/'attempt.json')['adapter'])
    policy=flow.read(root/'inputs/capabilities.json')['policy']
    if policy['code_methods']:
        flow.exclusive(root/'inputs/observation-preparation-start.json',{'format':'observation-preparation-start-v1','started_monotonic_ns':time.monotonic_ns(),'started_utc':datetime.now(timezone.utc).isoformat(),'mode':'V4; partial builds block begin'})
        flow.prepare_connector_policy(root/'inputs')
    snap=flow.render_snapshot(root/'inputs/supplied-initial.svg',root/'inputs/supplied-original.png',root/'inputs/initial',root=root)
    if policy['code_methods']:flow.prepare_observations(root/'inputs')
    docs=brief.prepare_contracts(root)
    contracts=flow.prepare_contracts(root)
    flow.assignment_policy.load(root)
    write(root/'inputs/prepared-snapshot.json',snap)
    write(root/'preparation-result.json',{'status':'prepared','snapshot':snap,'contracts':contracts,'docs':docs,'generic_input_hashes':flow.generic_inputs(root),'prompt_hashes':flow.prompt_hashes(root),'provider_calls':0,'roles_started':0,'runs_started':0})

def prepare_cell(spec):
    s,runtime,manifest,assets=admit(spec) # All admission mismatches precede output creation.
    root=Path(s['output_root']);root.mkdir(parents=True,exist_ok=False)
    try:
        write(root/'attempt.json',{'status':'preparing','adapter':s['adapter'],'native_source_root':s['native_source_root'],'started_ns':time.time_ns(),'capabilities':s['capabilities']})
        adapter=Path(s['adapter'])
        for p in sorted(adapter.glob('*.py')):
            if not p.name.startswith('test_'):shutil.copyfile(p,root/p.name)
        for folder in ('docs','prompts'):(root/folder).mkdir()
        (root/'source').symlink_to(s['native_source_root'],target_is_directory=True)
        inputs=root/'inputs';inputs.mkdir()
        for key,name in [('original_png','supplied-original.png'),('initial_svg','supplied-initial.svg'),('registry','policy.json'),('runtime_json','runtime.json'),('runtime_binding','runtime-binding.json'),('first_stage_provenance','first-stage-provenance.json')]:shutil.copyfile(s[key],inputs/name)
        write(inputs/'capabilities.json',s['capabilities'])
        p=s['capabilities']['policy'];write(inputs/'observer-assignment.json',{'format':'observer-assignment-v1','mode':'enabled' if p['code_methods'] else 'disabled_by_assignment','capability_sha256':s['capabilities']['sha256']})
        catalog=deepcopy(DISABLED)
        if p['sam']:
            (inputs/'sam').mkdir();rows=[]
            for i,(item,path) in enumerate(assets):
                target=inputs/'sam'/('asset-%04d'%i+path.suffix.lower());shutil.copyfile(path,target)
                row={k:deepcopy(item[k]) for k in ('id','role','source_crop')};row.update(path=str(target.resolve()),sha256=sha(target));rows.append(row)
            catalog={'assets':rows,'missing_assets':[],'complete_available_catalog':True,'source_crop_coordinates':'original-image-pixels-xywh'}
        write(inputs/'sam.json',catalog)
        write(inputs/'source-manifest.json',manifest)
        write(inputs/'provenance.json',{'supplied_inputs':{k:{'path':s[k],'sha256':sha(s[k])} for k in ('original_png','initial_svg','registry','runtime_json','runtime_binding','first_stage_provenance')},'native_source_root':s['native_source_root'],'native_source_manifest_sha256':digest(manifest),'capability_sha256':s['capabilities']['sha256'],'sam_catalog_source_sha256':sha(s['sam_catalog']) if p['sam'] else None,'sam_assets_copied':len(assets),'sam_asset_evidence_count':len(assets),'claims':'Caller supplied initial SVG; this preparer did not generate it and does not establish first-stage model compliance. Runtime binding is caller supplied, not independently health verified. Static capability admission does not establish efficacy.'})
        # Narrow environment, no inherited credentials/provider configuration.
        env={'PATH':'/usr/bin:/bin','HOME':str(root),'TMPDIR':os.environ.get('TMPDIR','/tmp'),'PYTHONDONTWRITEBYTECODE':'1',**runtime}
        proc=subprocess.run([s['python'],str(Path(__file__).resolve()),'--worker',str(root)],cwd=root,env=env,capture_output=True,text=True)
        (root/'preparation.stdout.log').write_text(proc.stdout);(root/'preparation.stderr.log').write_text(proc.stderr)
        if proc.returncode:raise RuntimeError('isolated preparation failed; see preparation.stderr.log')
        result=read(root/'preparation-result.json')
        if source_manifest(root/'source',expected_root=s['native_source_root'])!=manifest:raise RuntimeError('native source changed during preparation')
        write(root/'preparation-complete.json',{'status':'prepared','result_sha256':sha(root/'preparation-result.json'),'native_source_unchanged':True})
        return result
    except BaseException as exc:
        write(root/'quarantine.json',{'status':'failed_not_reusable','error_type':type(exc).__name__,'error':str(exc),'no_overwrite':True})
        raise

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--spec',type=Path);parser.add_argument('--worker',type=Path);args=parser.parse_args()
    if args.worker:_worker(args.worker.resolve())
    elif args.spec:print(json.dumps(prepare_cell(read(args.spec)),indent=2))
    else:parser.error('--spec required')
if __name__=='__main__':main()
