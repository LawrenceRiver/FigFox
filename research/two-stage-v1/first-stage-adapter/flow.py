#!/usr/bin/env python3
"""File bridge for fresh Harness roles; existing native code owns SVG execution."""
import argparse
import assignment_policy
import insertion_guard
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pending_observations import capture_pending, triage_pending
from construction_budget import reject_proven_budget
import connector_paint_bridge as connector_bridge
import connector_paint_contract as connector_contract
from connector_paint_bridge import prepare_policy as prepare_connector_policy
from promotion_contract import promote_uncertainty
from detection_contract import (MAIN_CATEGORIES, EXTRA_CATEGORIES, PROFILE_CATEGORIES, SEMANTIC_CATEGORIES, PROFILE_ID, validate_issues, bound_report, validate_detection_report, proposal_catalog)

BASE = Path(__file__).resolve().parent
PYTHON = '/Users/lawrenceriver/Desktop/7月/plus/.venv/bin/python'
SOURCE_REPO = Path('/Users/lawrenceriver/Desktop/figfox-debug/figfox-arrow-paint-fixed')
SOURCE_COMMIT = '556b61ec345d4d2476befc1f60ba1320900ad7ec'
SVG_HASH = '260d6339c12663cf5159591ad6f3ddf1d519e1c1071081366464c32ee62db093'
PATCH_HASH = 'abebc9736452f318137041a9b42de3f63f62946a243a7b19ab7dcaeacbfd448f'
PROGRAM_HASH = '8170cb1d3d8d233477d89389021119ebd5fa3f4066a9eafc4c6234edeb2c0fde'
RUNTIME_KEYS = ('NODE_PATH','PLUS_PLAYWRIGHT_MODULE','PLUS_CHROMIUM','PLUS_VECTOR_PYTHON','PLUS_NODE')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');temp.replace(path)


def exclusive(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def evidence(folder, sam):
    folder=Path(folder)
    names={'original_png':'original.png','current_svg':'current.svg','current_png':'current.png','public_svg':'public.svg','bounds':'bounds.json'}
    hashes={k:sha(folder/v) for k,v in names.items()}
    pairs={p.name:sha(p) for p in sorted((folder/'pack').glob('*-pair.png'))}
    metadata=read(folder/'pack'/'pack.json') if (folder/'pack'/'pack.json').exists() else None
    if metadata:
        for frame in metadata.get('frames',[]):
            expected=folder/'pack'/Path(frame['pair']).name
            if Path(frame['pair']).resolve()!=expected.resolve():raise ValueError('pack pair path escapes current evidence folder')
            frame['pair']=Path(frame['pair']).name
    hashes.update(pairs=digest(pairs),pack_pixels=digest({p.name:sha(p) for p in sorted((folder/'pack').glob('*.png'))}),pack_metadata=digest(metadata),sam_catalog=sha(sam))
    return {'revision':hashes['current_svg'],'evidence_hashes':hashes,'pair_hashes':pairs,'required_regions':[x['frame_id'] for x in (metadata or {}).get('frames',[])]}



def generic_inputs(root):
    inputs=Path(root)/'inputs'
    files={name:sha(inputs/name) if (inputs/name).exists() else None for name in ('policy.json','method-pack.json','native-contract.json','runtime-binding.json','runtime.json','sam.json','connector-paint-policy.json','capabilities.json','observer-assignment.json')}
    files.update({str(p.relative_to(inputs)):sha(p) for p in sorted((inputs/'sam').rglob('*')) if p.is_file()})
    files.update({str(p.relative_to(inputs)):sha(p) for p in sorted((inputs/'analysis').rglob('*')) if p.is_file()})
    for name in ('observation-build-timing.json','observation-preparation-start.json','connector-paint-preparation-start.json'):
        path=inputs/name
        if path.exists():files[name]=sha(path)
    source=BASE/'source'
    files['native_source_bytes']={str(p.relative_to(source)):sha(p) for p in sorted(source.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.cjs') and not p.name.startswith('test_') and (p.is_relative_to(source/'src') or p.is_relative_to(source/'runtime'))}
    return files


def prompt_hashes(root):
    prompts=Path(root)/'prompts'
    result={str(p.relative_to(prompts)):sha(p) for p in sorted(prompts.rglob('*')) if p.is_file()}
    for name in ('common-quality.md','common-conditional-policy.md','category-profile.md','native-contract.md','pending-observation-contract.md','observation-contract.md','necessity-review-contract.md','promotion-patch-contract.md','connector-paint-observation-contract.md','connector-paint-provenance.md','construction-budget-contract.md'):
        path=Path(root)/'docs'/name
        if path.exists():result['../docs/'+name]=sha(path)
    for name in ('flow.py','brief.py','category_profile.py','pending_observations.py','detection_contract.py','observation_probes.py','promotion_contract.py','connector_paint_contract.py','connector_paint_producer.py','connector_paint_producer_v3.py','connector_paint_producer_v4.py','connector_paint_bridge.py','construction_budget.py','assignment_policy.py','insertion_guard.py'):
        path=BASE/name
        if path.exists():result['../'+name]=sha(path)
    return result


def clone(source, dest):
    shutil.copytree(source,dest)
    pack=dest/'pack'/'pack.json'
    if pack.exists():
        data=read(pack)
        for row in data['frames']:row['pair']=str((dest/'pack'/Path(row['pair']).name).resolve())
        write(pack,data)


def issue_order_normalization(raw_issues, active_issues, raw_sha256):
    """Accept only a permutation of exact JSON finding objects; never rewrite rows."""
    def by_id(rows):
        if not isinstance(rows,list):raise ValueError('planner issues must be an array')
        result={}
        for row in rows:
            if not isinstance(row,dict):raise ValueError('planner issue must be an object')
            ident=row.get('id')
            if not isinstance(ident,str) or not ident or ident in result:raise ValueError('missing or duplicate planner issue ID')
            result[ident]=json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        return result
    if by_id(raw_issues)!=by_id(active_issues):raise ValueError('planner must preserve exact tracked issue objects and classifications regardless of row order')
    raw_order=[row['id'] for row in raw_issues];active_order=[row['id'] for row in active_issues]
    return {'raw_issue_id_order':raw_order,'active_issue_id_order':active_order,
            'raw_plan_sha256':raw_sha256,'order_changed':raw_order!=active_order,
            'no_finding_value_changed':True,'native_issue_order':'active_queue',
            'basis':'same unique finding IDs and exact JSON objects; only array order differs'}


def native_issue_bindings(rows, svg):
    """Bind only an explicitly supplied existing container for an absent object."""
    lowered=deepcopy(rows);receipts=[]
    existing={n.get('id') for n in ET.parse(svg).getroot().iter() if n.get('id')}
    for row in lowered:
        if row.get('target_ids')==[] and row.get('container_id'):
            container=row['container_id']
            if container not in existing:raise ValueError('unknown explicit container')
            row['target_ids']=[container]
            receipts.append({'issue_id':row['id'],'container_id':container,'kind':'explicit_missing_content_container_scope','raw_target_ids':[],'native_target_ids':[container],'basis':'verbatim model-declared existing container; no semantic or geometry inference'})
    return lowered,receipts


def insertion_scope_guard(program, issues, svg, mutations):
    """Prove canonical module writes do not borrow authority from missing anchors.

    Existing-target authority comes only from another linked finding's explicit
    targets (and their descendants), never from insertion anchors or neighbors.
    Read-only native validation still follows this conservative bridge check.
    """
    selected=[row for row in issues if row['id'] in program['issue_ids']]
    absent=[row for row in selected if row.get('target_ids')==[] and row.get('container_id')]
    if not absent:return None
    def reject(reason):raise ValueError('missing-content container is insertion scope only: '+reason)
    if program.get('route')=='generated_python':
        permission=insertion_guard.rights(program,issues,insertion_guard.parse(Path(svg).read_text()))
        return {'program_id':program['id'],'proof_required':'transactional_xml_before_checkpoint',**permission}
    if program.get('route')!='module_program':reject('unsupported insertion route')
    root=ET.parse(svg).getroot();by_id={node.get('id'):node for node in root.iter() if node.get('id')}
    parents={child:parent for parent in root.iter() for child in parent}
    def subtree(ids):
        return {node.get('id') for ident in ids if ident in by_id for node in by_id[ident].iter() if node.get('id')}
    anchors=subtree([row['container_id'] for row in absent])
    authorized=subtree([ident for row in selected if row.get('target_ids') for ident in row['target_ids']])
    created=set()
    def visit(operations):
        if not isinstance(operations,list):reject('cannot prove malformed operation list safe')
        for op in operations:
            if not isinstance(op,dict) or not isinstance(op.get('target_ids'),list) or not isinstance(op.get('args'),dict):reject('cannot prove malformed operation safe')
            targets=op['target_ids'];args=op['args'];method=op.get('method')
            if any(not isinstance(ident,str) for ident in targets):reject('operation targets must be explicit strings')
            if method=='bp_program':
                visit(args.get('operations'));continue
            if method in ('measure','check_tp','sample_colors'):continue
            if method=='bp_add':
                parent=args.get('parent_id')
                if parent=='@parent':
                    nodes=[by_id.get(ident) for ident in targets]
                    containers={parents.get(node) for node in nodes}
                    if not nodes or None in nodes or len(containers)!=1 or None in containers:reject('insertion parent is not provable')
                    parent=next(iter(containers)).get('id')
                if parent not in anchors|authorized|created:reject('insertion parent is outside explicit anchor/target scope')
                try:fragment=ET.fromstring('<g>'+args.get('svg','')+'</g>')
                except (ET.ParseError,TypeError) as exc:reject('insertion fragment is not provable: '+str(exc))
                fresh=[node.get('id') for node in list(fragment.iter())[1:]]
                if not fresh or any(not ident for ident in fresh) or len(fresh)!=len(set(fresh)) or set(fresh)&(set(by_id)|created):reject('insertion requires unique fresh identities')
                created.update(fresh);continue
            if method not in mutations:reject('cannot prove unknown method safe')
            for target in targets:
                if target in created:continue
                if target not in by_id:reject('mutation target is neither current nor freshly created')
                unauthorized=subtree([target])-authorized
                if unauthorized:reject('existing subtree write lacks a separately linked explicit target: '+', '.join(sorted(unauthorized)))
    visit(program.get('args',{}).get('operations',[]))
    visit(program.get('convergence',{}).get('repairs',[]))
    return {'program_id':program['id'],'missing_issue_ids':[row['id'] for row in absent],
            'insertion_anchor_ids':[row['container_id'] for row in absent],
            'separately_authorized_existing_ids':sorted(authorized),'created_ids':sorted(created),
            'basis':'canonical operations, nested BP operations and convergence repairs; existing subtrees require independent explicit target authority'}


def native(root=BASE):
    """Deny all key/provider calls before importing native modules; no response shim."""
    runtime=read(Path(root)/'inputs'/'runtime.json')
    for key in RUNTIME_KEYS:os.environ[key]=runtime[key]
    for key in list(os.environ):
        if any(x in key.upper() for x in ('API_KEY','ACCESS_TOKEN','FLOW_ENV_FILE')):os.environ.pop(key,None)
    sys.path.insert(0,str(BASE/'source'/'src'))
    import figfox_plus.providers as providers
    def denied(*args,**kwargs):raise RuntimeError('Provider and credential access disabled in zero-API Harness')
    for name in ('load_key','call_deepseek','call_gpt55','request_once'):setattr(providers,name,denied)
    import figfox_plus.sam as sam
    sam.prepare_assets=denied
    from figfox_plus.native import pipeline, document
    from figfox_plus.native.review_problem_first_v13 import replay, programs, methods
    return pipeline,document,replay,programs,methods


def render_snapshot(svg, original, folder, root=BASE):
    pipeline,document,_,_,_=native(root);folder=Path(folder)
    svg_root=document.parse(Path(svg).read_text())
    pipeline.stage(svg_root,original,folder/'native-stage')
    shutil.copy2(svg,folder/'current.svg');shutil.copy2(original,folder/'original.png')
    shutil.copy2(folder/'native-stage'/'preview.png',folder/'current.png')
    shutil.copy2(folder/'native-stage'/'bounds.json',folder/'bounds.json')
    shutil.copytree(folder/'native-stage'/'pack',folder/'pack')
    pack=read(folder/'pack'/'pack.json')
    for row in pack['frames']:row['pair']=str((folder/'pack'/Path(row['pair']).name).resolve())
    write(folder/'pack'/'pack.json',pack)
    (folder/'public.svg').write_text(document.public_svg(svg_root))
    write(folder/'serialization.json',{'input_svg_sha256':sha(svg),'native_serialized_sha256':sha(folder/'native-stage'/'scene.svg'),'bytes_changed':sha(svg)!=sha(folder/'native-stage'/'scene.svg'),'current_svg_preserves_input_bytes':True})
    return evidence(folder,Path(root)/'inputs'/'sam.json')


def bind_runtime(runtime):
    """Bind already-installed neutral tools; no download, inference, SAM or provider calls."""
    for key in RUNTIME_KEYS:
        if not Path(runtime[key]).exists():raise ValueError('installed runtime path unavailable: '+key)
    installed=SOURCE_REPO.parent/'tools'/'drawai-official-20260815'
    required=[installed/'.local/drawai_runtime/.venv/bin/python',installed/'.local/drawai_runtime/models/rmbg2/model.safetensors',installed/'src/drawai/local_runtime.py']
    if any(not p.is_file() for p in required):raise ValueError('existing local RMBG runtime unavailable')
    tools=BASE/'tools';tools.mkdir(exist_ok=True);link=tools/'drawai-official-20260815'
    if not link.exists():link.symlink_to(installed,target_is_directory=True)
    if link.resolve()!=installed.resolve():raise ValueError('unexpected installed tool binding')
    node=runtime['PLUS_NODE']
    if node is None:raise ValueError('Node unavailable')
    env={**os.environ,**{k:runtime[k] for k in RUNTIME_KEYS}}
    probe="JSON.stringify(['playwright','mathjax-full/js/mathjax.js','imagetracerjs'].map(n=>({name:n,path:require.resolve(n)})))"
    resolved=subprocess.run([node,'-p',probe],env=env,check=True,capture_output=True,text=True)
    vector=subprocess.run([runtime['PLUS_VECTOR_PYTHON'],'-c','import vtracer; print(vtracer.__file__)'],check=True,capture_output=True,text=True)
    return {'node':node,'node_version':subprocess.run([node,'--version'],check=True,capture_output=True,text=True).stdout.strip(),'node_modules':json.loads(resolved.stdout),'vector_module':vector.stdout.strip(),'runtime_paths':{k:str(Path(runtime[k]).resolve()) for k in RUNTIME_KEYS},'rmbg_binding':str(link),'rmbg_installed':str(installed),'rmbg_model_bytes':required[1].stat().st_size,'rmbg_python':str(required[0].resolve()),'rmbg_runtime_sha256':sha(required[2]),'executed':'module resolution/import/version only; no inference, SAM, program, render or API'}

def prepare_contracts(root):
    """Generate capability-specific neutral help before any cohort begins."""
    root=Path(root).resolve()
    if (root/'runs').exists() or (root/'inputs/frozen-generic-inputs.json').exists():raise ValueError('contract generation forbidden after cohort begins')
    capabilities=assignment_policy.load(root)
    # Documentation generation imports generic local modules only; no native work.
    sys.path.insert(0,str(BASE/'source/src'))
    from figfox_plus.native.review_problem_first_v13 import methods, lean_inspection
    from category_profile import build_profile_pack, build_native_contract
    pack=build_profile_pack(methods,lean_inspection,capabilities=capabilities)
    write(root/'inputs/method-pack.json',pack)
    write(root/'inputs/native-contract.json',build_native_contract(root,pack,capabilities=capabilities))
    return {'profile_id':PROFILE_ID,'capabilities':capabilities,'method_pack_sha256':sha(root/'inputs/method-pack.json'),'native_contract_sha256':sha(root/'inputs/native-contract.json')}

def validate_necessity_proposals(plan,state):
    """Untrusted requests never remove, relabel or authorize an active finding."""
    rows=plan.get('not_required_proposals',[])
    if not isinstance(rows,list):raise ValueError('not_required_proposals must be array')
    active={row['id'] for row in state['required']+state['uncertain']};seen=set()
    reasons=plan.get('unresolved_reasons',[])
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('issue_id'),str) or row['issue_id'] not in active or row['issue_id'] in seen:raise ValueError('necessity request must use unique active issue IDs')
        seen.add(row['issue_id'])
        for key in ('source_evidence','before_evidence','why_qualified'):
            if not isinstance(row.get(key),str) or not row[key].strip():raise ValueError('necessity request requires '+key)
        if not isinstance(reasons,list) or not any(isinstance(reason,dict) and reason.get('issue_id')==row['issue_id'] and isinstance(reason.get('reason'),str) and reason['reason'].strip() for reason in reasons):raise ValueError('necessity request must preserve an explicit unresolved reason')
    for program in plan.get('programs',[]):
        if isinstance(program,dict) and isinstance(program.get('issue_ids'),list) and any(i in seen for i in program['issue_ids'] if isinstance(i,str)):raise ValueError('program cannot cite proposed no-edit issue IDs')
    return deepcopy(rows)


def prepare_observations(inputs):
    """Additional local analysis only; production rendering stays native."""
    inputs=Path(inputs);started=time.monotonic_ns();utc=datetime.now(timezone.utc).isoformat()
    try:
        from observation_probes import build_observation_proposals
        _,document,_,_,_=native(root=inputs.parent)
        def repaint(svg_text,output_png):
            document.measure(document.parse(svg_text),output_png)
        return build_observation_proposals(inputs/'initial/current.svg',inputs/'initial/current.png',inputs/'initial/bounds.json',inputs/'analysis',repaint,pack_path=inputs/'initial/pack/pack.json')
    finally:
        ended=time.monotonic_ns()
        exclusive(inputs/'observation-build-timing.json',{'started_monotonic_ns':started,'ended_monotonic_ns':ended,'elapsed_seconds':(ended-started)/1e9,'started_utc':utc,'ended_utc':datetime.now(timezone.utc).isoformat(),'provider_calls':0,'purpose':'additional proposal build, including native repaint and text-hidden render'})


def prepare():
    inputs=BASE/'inputs'
    if inputs.exists():raise ValueError('inputs already exist; preparation is immutable')
    source=BASE/'source';patch=BASE.parent/'semantic-parallel-pilot-20261026'/'native-s1-photo.patch'
    if sha(patch)!=PATCH_HASH:raise ValueError('patch hash mismatch')
    if not source.exists():
        source.mkdir();archive=subprocess.run(['git','-C',str(SOURCE_REPO),'archive',SOURCE_COMMIT],check=True,capture_output=True).stdout
        subprocess.run(['tar','-x','-C',str(source)],input=archive,check=True)
        subprocess.run(['git','apply','--directory=source',str(patch)],cwd=BASE,check=True)
    if sha(source/'src/figfox_plus/native/review_problem_first_v13/programs.py')!=PROGRAM_HASH:raise ValueError('native program hash mismatch')
    initial_source=BASE.parent/'capacity-diagnostic-v2/workflow/initial/music'
    if sha(initial_source/'svg.svg')!=SVG_HASH:raise ValueError('initial SVG hash mismatch')
    inputs.mkdir()
    prepare_connector_policy(inputs)
    # Record V4 intent before any fallible input population or initial render.
    exclusive(inputs/'observation-preparation-start.json',{'format':'observation-preparation-start-v1','started_monotonic_ns':time.monotonic_ns(),'started_utc':datetime.now(timezone.utc).isoformat(),'mode':'V4; partial builds block begin'})
    runtime=read(BASE.parent/'capacity-diagnostic-v2/protocol.json')['runtime']
    runtime['PLUS_NODE']=shutil.which('node')
    if runtime['PLUS_NODE'] is None:raise ValueError('Node unavailable')
    write(inputs/'runtime.json',{key:runtime[key] for key in RUNTIME_KEYS})
    write(inputs/'runtime-binding.json',bind_runtime(runtime))
    policy=Path('/Users/lawrenceriver/Downloads/FigFox_评分标准_v2/figfox_score/registry.json')
    shutil.copy2(policy,inputs/'policy.json')
    catalog_path=BASE.parent/'original-github-comparison/current-music-full-run/chain/native-20261024T082245-f98a60552a/sam.json'
    catalog=read(catalog_path);assets=[];missing=[]
    (inputs/'sam').mkdir()
    for index,item in enumerate(catalog['assets']):
        path=Path(item['path']);name=f'asset-{index:04d}'+path.suffix.lower()
        row={key:deepcopy(item[key]) for key in ('id','role','source_crop')}
        if path.is_file():
            dest=inputs/'sam'/name;shutil.copy2(path,dest);row.update(path=str(dest.resolve()),sha256=sha(dest));assets.append(row)
        else:missing.append(dict(row,source_path=str(path)))
    write(inputs/'sam.json',{'assets':assets,'missing_assets':missing,'complete_available_catalog':True})
    snap=render_snapshot(initial_source/'svg.svg',initial_source/'original.png',inputs/'initial')
    prepare_observations(inputs)
    shutil.copy2(initial_source/'png.png',inputs/'initial'/'frozen-first-stage.png')
    from PIL import Image, ImageChops
    with Image.open(initial_source/'png.png') as a, Image.open(inputs/'initial'/'current.png') as b:
        pixel_equal=a.size==b.size and ImageChops.difference(a.convert('RGBA'),b.convert('RGBA')).getbbox() is None
    prepare_contracts()
    tracked=subprocess.run(['git','-C',str(SOURCE_REPO),'ls-tree','-r',SOURCE_COMMIT],check=True,capture_output=True,text=True).stdout
    provenance={'source_commit':SOURCE_COMMIT,'tracked_tree_listing_sha256':hashlib.sha256(tracked.encode()).hexdigest(),'patch_sha256':PATCH_HASH,'programs_sha256':PROGRAM_HASH,'original_inputs':{name:{'path':str(initial_source/name),'sha256':sha(initial_source/name)} for name in ('svg.svg','png.png','original.png')},'initial_evidence':snap,'observation_build':read(inputs/'observation-build-timing.json'),'observation_manifest_sha256':sha(inputs/'analysis/manifest.json'),'render_pixels_equal_frozen_png':pixel_equal,'serialization':read(inputs/'initial'/'serialization.json'),'policy_sha256':sha(policy),'sam_catalog_source_sha256':sha(catalog_path),'sam_assets_copied':len(assets),'sam_assets_missing':missing,'runtime':runtime,'provider_calls':0,'provider_fee':0,'harness_tokens':None,'boundary':'Only fixed SVG/PNG originals, runtime keys, generic policy, and all neutral catalog assets read; no saved labels, plans or corrected scene read.'}
    write(inputs/'provenance.json',provenance);write(BASE/'reports'/'task1-input-provenance.json',provenance)
    return provenance


class Flow:
    def __init__(self, root=BASE):self.root=Path(root).resolve()
    def path(self, run):
        if run not in ('run1','run2','run3'):raise ValueError('run must be run1, run2 or run3')
        return self.root/'runs'/run
    def state(self, run):return read(self.path(run)/'state.json')
    def save(self, run, state):write(self.path(run)/'state.json',state)
    def log(self, run, stage, event, **fields):
        state=self.state(run);now=time.monotonic_ns()
        row={'stage':stage,'event':event,'monotonic_ns':now,'elapsed_seconds':(now-state['started_monotonic_ns'])/1e9,'utc':datetime.now(timezone.utc).isoformat(),**fields}
        with (self.path(run)/'ledger.jsonl').open('a') as stream:stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    def connector_host(self,run):
        frozen=self.root/'inputs/frozen-initial-evidence.json'
        initial=read(frozen) if frozen.exists() else evidence(self.root/'inputs/initial',self.root/'inputs/sam.json')
        return connector_contract.Host(self.root,run,initial,lambda path:evidence(path,self.root/'inputs/sam.json'))
    def connector_bundle(self,run,round_number):
        return connector_bridge.bundle(self.connector_host(run),round_number)
    def parse_role(self,run,raw):
        state=self.state(run)
        return connector_contract.parse_raw(raw) if state.get('connector_paint_mode') else json.loads(raw)
    def checked_state(self, run):
        state=self.state(run)
        policy=assignment_policy.load(self.root)
        if state.get('capabilities')!=policy:raise ValueError('frozen state capability mismatch')
        if state['prompt_hashes']!=prompt_hashes(self.root):raise ValueError('frozen prompt bytes changed')
        frozen_inputs=self.root/'inputs'/'frozen-generic-inputs.json'
        if frozen_inputs.exists() and read(frozen_inputs)!=generic_inputs(self.root):raise ValueError('frozen generic input bytes changed')
        actual=evidence(self.path(run)/'checkpoint',self.root/'inputs'/'sam.json')
        if any(state[k]!=actual[k] for k in ('revision','evidence_hashes')):raise ValueError('checkpoint evidence hash mismatch')
        host=self.connector_host(run)
        if connector_bridge.policy(host,state):
            for name,expected in (('frozen-generic-inputs.json',generic_inputs(self.root)),('frozen-prompt-hashes.json',state['prompt_hashes']),('frozen-initial-evidence.json',host.frozen_initial)):
                frozen=host.path('inputs/'+name)
                connector_contract.require(connector_contract.parse_raw(frozen.read_bytes())==expected,'enabled frozen input/prompt binding mismatch: '+name)
            host.initial();host.validate_state(state)
            for n in (1,2,3):
                base=self.path(run)/f'round-{n}'
                if (base/'connector-paint-start.json').exists() or (base/'connector-paint').exists() or (base/'candidate.json').exists():self.connector_bundle(run,n)
        return state
    def active_state(self,run):
        state=self.checked_state(run)
        if state.get('runtime_finished_monotonic_ns') is not None:raise ValueError('runtime already finished')
        return state
    def begin(self, run):
        capability_policy=assignment_policy.load(self.root)
        folder=self.path(run)
        if folder.exists():raise ValueError('run already begun; never reset an existing run')
        initial=evidence(self.root/'inputs'/'initial',self.root/'inputs'/'sam.json')
        self.observation_proposals(initial)  # Partial/unsupported V4 builds must not become legacy mode.
        connector_policy=connector_bridge.policy(self.connector_host(run))
        prompts=prompt_hashes(self.root)
        frozen_inputs=self.root/'inputs'/'frozen-generic-inputs.json'
        current_inputs=generic_inputs(self.root)
        if frozen_inputs.exists() and read(frozen_inputs)!=current_inputs:raise ValueError('frozen generic input bytes changed')
        if not frozen_inputs.exists():exclusive(frozen_inputs,current_inputs)
        frozen=self.root/'inputs'/'frozen-prompt-hashes.json'
        if frozen.exists() and read(frozen)!=prompts:raise ValueError('frozen prompt bytes changed')
        if not frozen.exists():exclusive(frozen,prompts)
        initial=evidence(self.root/'inputs'/'initial',self.root/'inputs'/'sam.json')
        frozen_initial=self.root/'inputs'/'frozen-initial-evidence.json'
        if frozen_initial.exists() and read(frozen_initial)!=initial:raise ValueError('frozen initial evidence changed')
        if not frozen_initial.exists():exclusive(frozen_initial,initial)
        folder.mkdir(parents=True);clone(self.root/'inputs'/'initial',folder/'checkpoint')
        snap=evidence(folder/'checkpoint',self.root/'inputs'/'sam.json')
        state={**snap,'capabilities':capability_policy,'run':run,'started_monotonic_ns':time.monotonic_ns(),'started_utc':datetime.now(timezone.utc).isoformat(),'last_round':0,'required':[],'uncertain':[],'historical_finding_ids':[],'pending_observations':[],'pending_observation_receipts':[],'status':'awaiting_detection','resolved_total':0,'false_positive_total':0,'uncertain_resolved_total':0,'uncertain_false_positive_total':0,'visual_passed':False,'provider_fee':0,'provider_calls':0,'harness_tokens':None,'prompt_hashes':prompts}
        if connector_policy:state.update(connector_paint_mode=connector_contract.MODE,connector_visual_concerns=[],connector_concern_receipts=[])
        self.save(run,state);self.log(run,'ds1-main+semantic','started');return state
    def role_path(self, run, role, round_number=None):
        if role not in ('main','semantic','planner','verifier'):raise ValueError('unknown role')
        if role in ('main','semantic'):
            if round_number is not None:raise ValueError('detection has no round')
            return self.path(run)/'detection'/role
        if round_number not in (1,2,3):raise ValueError('round must be 1..3')
        return self.path(run)/f'round-{round_number}'/role
    def dispatch(self,run,role,agent_id,round_number=None):
        state=self.active_state(run)
        connector_dispatch={}
        if role=='verifier' and state.get('connector_paint_mode'):connector_dispatch={'candidate_receipt_sha256':self.connector_bundle(run,round_number).candidate_receipt_sha256}
        if not isinstance(agent_id,str) or not agent_id.strip():raise ValueError('fresh agent identity required')
        for path in (self.root/'runs').glob('**/dispatch.json'):
            if read(path)['agent_id']==agent_id:raise ValueError('agent identity already used; each role must start fork_none')
        folder=self.role_path(run,role,round_number)
        if (folder/'dispatch.json').exists():raise ValueError('role already dispatched')
        exclusive(folder/'dispatch.json',{**connector_dispatch,'agent_id':agent_id,'fork_turns':'none','role':role,'round':round_number,'orchestrator_attests_fresh_context':True,'monotonic_ns':time.monotonic_ns()})
        self.log(run,f'{role}-{round_number or 0}','dispatched',agent_id=agent_id)
    def receive(self,run,role,file,round_number=None):
        self.active_state(run)
        folder=self.role_path(run,role,round_number)
        dispatch=read(folder/'dispatch.json')
        if (folder/'raw.json').exists():raise ValueError('raw role receipt already exists')
        data=Path(file).read_bytes()
        folder.mkdir(parents=True,exist_ok=True)
        with (folder/'raw.json').open('xb') as stream:stream.write(data)
        exclusive(folder/'receipt.json',{'agent_id':dispatch['agent_id'],'sha256':sha(folder/'raw.json'),'source_file':str(Path(file).resolve()),'monotonic_ns':time.monotonic_ns()})
        self.log(run,f'{role}-{round_number or 0}','received',sha256=sha(folder/'raw.json'))
        self.parse_role(run,data)  # Freeze every final byte and receipt before parsing, even invalid JSON.
    def receipt(self,run,role,round_number=None):
        folder=self.role_path(run,role,round_number)
        if sha(folder/'raw.json')!=read(folder/'receipt.json')['sha256']:raise ValueError('immutable raw receipt changed')
        return self.parse_role(run,(folder/'raw.json').read_bytes())
    def bound_report(self,report,state, hashes=True):
        return bound_report(report,state,hashes)
    def observation_proposals(self,state=None):
        if assignment_policy.disabled(self.root):return None
        analysis=self.root/'inputs/analysis';marker=self.root/'inputs/observation-preparation-start.json'
        if not analysis.exists() or not marker.is_file():raise ValueError('enabled assignment requires complete observation preparation')
        try:
            manifest=read(analysis/'manifest.json');proposals=read(analysis/'proposals.json')
            expected={key:sha(self.root/'inputs/initial'/name) for key,name in [('current_svg','current.svg'),('current_png','current.png'),('bounds','bounds.json')]}
            for obj,fmt in ((manifest,'svg-observation-manifest-v1'),(proposals,'svg-observation-proposals-v1')):
                if not isinstance(obj,dict) or obj.get('format')!=fmt or obj.get('status')!='ready' or obj.get('revision')!=expected['current_svg'] or obj.get('evidence_hashes')!=expected:raise ValueError('not ready or input hashes mismatch')
            if state is not None and state['revision']!=expected['current_svg']:raise ValueError('initial revision mismatch')
            proposal_catalog(proposals)
            if manifest.get('repaint_rgba_exact') is not True:raise ValueError('normal repaint not verified')
            required={'base-repaint.png','text-hidden.svg','text-hidden.png','proposals.json'}
            if not isinstance(manifest.get('artifacts'),dict) or not required.issubset(manifest['artifacts']):raise ValueError('incomplete artifact manifest')
            for obj in (manifest,proposals):
                if not isinstance(obj.get('artifacts'),dict):raise ValueError('artifact hash map required')
                for name,artifact in obj['artifacts'].items():
                    path=analysis/name
                    if not isinstance(artifact,dict) or Path(name).name!=name or artifact.get('path')!=name or not path.is_file() or path.is_symlink() or artifact.get('sha256')!=sha(path):raise ValueError('artifact path/hash mismatch')
            return proposals
        except (OSError,ValueError,TypeError,KeyError) as exc:raise ValueError('observation preparation incomplete or inconsistent: '+str(exc)) from exc
    def check_report(self,run,role,draft):
        state=self.active_state(run)
        if role not in ('main','semantic'):raise ValueError('check-report detector role must be main or semantic')
        if state['status']!='awaiting_detection':raise ValueError('detection role no longer active')
        folder=self.role_path(run,role);dispatch=read(folder/'dispatch.json')
        if (folder/'raw.json').exists():raise ValueError('detector already submitted')
        draft=Path(draft);own=self.path(run)/'jobs'/role
        if not draft.is_absolute() or own.resolve()!=own or not draft.resolve().is_relative_to(own) or not draft.is_file():raise ValueError('draft must be absolute inside own detector output directory')
        draft=draft.resolve();audit=folder/'report-checks';audit.mkdir(exist_ok=True)
        for number in (1,2):
            slot=audit/str(number)
            try:slot.mkdir()
            except FileExistsError:continue
            break
        else:raise ValueError('maximum two local report checks per detector')
        started=time.monotonic_ns();raw=draft.read_bytes()
        with (slot/'draft.json').open('xb') as stream:stream.write(raw)
        invocation={'agent_id':dispatch['agent_id'],'run':run,'role':role,'check':number,'draft':str(draft),'draft_sha256':sha(slot/'draft.json'),'state_sha256':sha(self.path(run)/'state.json'),'revision':state['revision'],'started_monotonic_ns':started,'provider_calls':0,'programs_executed':0,'render_calls':0,'repair_attempts_consumed':0}
        exclusive(slot/'invocation.json',invocation)
        try:
            self.parse_role(run,raw)
            _,missing=validate_detection_report(raw,role,state,self.path(run)/'checkpoint/current.svg',proposals=self.observation_proposals() if role=='semantic' else None)
            result={'status':'valid_report','missing_region_declarations':missing}
        except Exception as exc:result={'status':'invalid_report','error':type(exc).__name__+': '+str(exc)}
        ended=time.monotonic_ns();exclusive(slot/'receipt.json',{**invocation,'ended_monotonic_ns':ended,'elapsed_seconds':(ended-started)/1e9,'result':result})
        return result
    def merge(self, run):
        state=self.active_state(run);out=self.path(run)/'merged.json'
        if out.exists():raise ValueError('merge already exists')
        issues=[];reports={};missing_regions={}
        for role in ('main','semantic'):
            self.receipt(run,role)  # Verify immutable receipt before the shared parser.
            report,missing_regions[role]=validate_detection_report((self.role_path(run,role)/'raw.json').read_bytes(),role,state,self.path(run)/'checkpoint/current.svg',proposals=self.observation_proposals() if role=='semantic' else None)
            reports[role]=report
            for item in report['issues']:
                row=deepcopy(item);row['source_issue_id']=row['id'];row['id']=role+':'+row['id'];row['source_role']=role;issues.append(row)
        duplicates=[]
        for index,a in enumerate(issues):
            for b in issues[index+1:]:
                overlap=set(a['target_ids'])&set(b['target_ids'])
                if overlap:duplicates.append({'issue_ids':[a['id'],b['id']],'shared_target_ids':sorted(overlap),'discarded':False})
        merged={'revision':state['revision'],'evidence_hashes':state['evidence_hashes'],'issues':issues,'programs':[],'possible_duplicate_targets':duplicates,'source_reports':reports,'missing_region_declarations':missing_regions}
        exclusive(out,merged);state['required']=[x for x in issues if x['decision']=='confirmed'];state['uncertain']=[x for x in issues if x['decision']=='uncertain'];state['historical_finding_ids']=[x['id'] for x in issues];state['status']='awaiting_planner';self.save(run,state);self.log(run,'merge','completed',confirmed=len(state['required']),uncertain=len(state['uncertain']));return merged
    def register_candidate(self,run,round_number,folder,result):
        state=self.active_state(run)
        if round_number not in (1,2,3) or round_number!=state['last_round']+1:raise ValueError('round out of sequence or exceeds limit')
        round_dir=self.path(run)/f'round-{round_number}';record=round_dir/'candidate.json'
        if record.exists():raise ValueError('candidate already registered')
        snap=evidence(folder,self.root/'inputs'/'sam.json')
        requests=round_dir/'necessity-review-requests.json'
        request_binding={'necessity_review_requests_sha256':sha(requests)} if requests.exists() else {}
        connector_binding={}
        if state.get('connector_paint_mode'):
            host=self.connector_host(run);reg=host.registration(round_number,connector_contract.full_from_state(state),snap)
            def repaint(text,png):
                _,document,_,_,_=native(self.root);document.measure(document.parse(text),png)
            connector_binding={'connector_paint':connector_bridge.build_observer(host,reg,repaint)}
        exclusive(record,{**connector_binding,**request_binding,'before_revision':state['revision'],'before_evidence_hashes':state['evidence_hashes'],'candidate_folder':str(Path(folder).resolve()),**snap,'native_result':result})
        if connector_binding:
            exclusive(round_dir/'connector-paint-registration-receipt.json',{'candidate_receipt_sha256':sha(record),'observer_artifacts':{p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted((round_dir/'connector-paint').iterdir()) if p.is_file()}})
            self.connector_bundle(run,round_number)
        self.log(run,f'execute-{round_number}','candidate_rendered',revision=snap['revision']);return snap
    def preflight(self,run,round_number,plan,plan_sha256):
        """Read-only native shape/scope/schema validation shared by check and execute."""
        state=self.active_state(run)
        if round_number not in (1,2,3) or round_number!=state['last_round']+1:raise ValueError('round out of sequence or exceeds limit')
        if not isinstance(plan,dict):raise ValueError('plan must be object')
        self.bound_report(plan,state,hashes=False)
        active=state['required']+state['uncertain']
        order=issue_order_normalization(plan.get('issues'),active,plan_sha256)
        necessity=validate_necessity_proposals(plan,state)
        checkpoint=self.path(run)/'checkpoint'
        images={'case':{'svg':str(checkpoint/'current.svg'),'png':str(checkpoint/'current.png'),'original':str(checkpoint/'original.png'),'revision':state['revision']}}
        native_issues,bindings=native_issue_bindings(active,checkpoint/'current.svg')
        _,_,replay,programs,_=native(self.root)
        shaped,shape_rejected=replay.filter_program_shapes(plan.get('programs'))
        rejected=[];safe=[];insertion_checks=[]
        for index,raw in enumerate(shaped):
            program=deepcopy(raw)
            try:
                # The same native relocation runs before both bridge and native checks.
                # The raw plan remains untouched; no authority or geometry is inferred.
                replay.canonicalize_program(program)
                checked=insertion_scope_guard(program,active,checkpoint/'current.svg',programs.MUTATIONS)
            except Exception as exc:
                rejected.append({'program_index':index,'program_id':raw['id'],'issue_ids':raw['issue_ids'],'status':'rejected_before_execution','error':type(exc).__name__+': '+str(exc)})
            else:
                if checked:insertion_checks.append(checked)
                safe.append(program)
        accepted,native_rejected=replay.select_valid_programs(safe,native_issues,images,capabilities=assignment_policy.load(self.root))
        # Native validation retains authority and runs before the optional proof.
        # Removing an impossible predecessor requires the same dependency checks
        # again, so a dependent never gains authority from a rejected program.
        feasible=[];budget_rejected=[]
        for index,program in enumerate(accepted):
            try:reject_proven_budget(program,BASE/'source')
            except ValueError as exc:
                budget_rejected.append({'program_index':index,'program_id':program['id'],'issue_ids':program['issue_ids'],'status':'rejected_before_execution','error':type(exc).__name__+': '+str(exc)})
            else:feasible.append(program)
        if budget_rejected:
            accepted,dependency_rejected=replay.select_valid_programs(feasible,native_issues,images,capabilities=assignment_policy.load(self.root))
            rejected.extend(budget_rejected+dependency_rejected)
        return {'accepted':[p['id'] for p in accepted],'rejected':shape_rejected+rejected+native_rejected,'programs':accepted,'native_issues':native_issues,'bindings':bindings,'images':images,'order_normalization':order,'insertion_scope_checks':insertion_checks,'not_required_proposals':necessity}
    def check_plan(self,run,round_number,draft):
        state=self.active_state(run)
        if round_number not in (1,2,3) or round_number!=state['last_round']+1:raise ValueError('round out of sequence or exceeds limit')
        folder=self.role_path(run,'planner',round_number)
        dispatch=read(folder/'dispatch.json')
        if (folder/'raw.json').exists() or (self.path(run)/f'round-{round_number}'/'native').exists():raise ValueError('planner already submitted or executed')
        draft=Path(draft).resolve();own=self.path(run)/'jobs'/f'planner-{round_number}'
        if own.resolve()!=own or not draft.is_relative_to(own) or not draft.is_file():raise ValueError('draft must be inside own planner output directory')
        audit=folder/'plan-checks';audit.mkdir(exist_ok=True)
        slot=None
        for number in (1,2):
            try:slot=audit/str(number);slot.mkdir()
            except FileExistsError:continue
            break
        else:raise ValueError('maximum two local plan checks per planner')
        started=time.monotonic_ns();draft_bytes=draft.read_bytes()
        invocation={'agent_id':dispatch['agent_id'],'run':run,'round':round_number,'check':number,'draft':str(draft),'draft_sha256':hashlib.sha256(draft_bytes).hexdigest(),'state_sha256':sha(self.path(run)/'state.json'),'revision':state['revision'],'started_monotonic_ns':started,'provider_calls':0,'programs_executed':0,'render_calls':0,'repair_attempts_consumed':0}
        exclusive(slot/'invocation.json',invocation)
        try:result=self.preflight(run,round_number,self.parse_role(run,draft_bytes),invocation['draft_sha256'])
        except Exception as exc:result={'status':'invalid_plan','error':type(exc).__name__+': '+str(exc),'accepted':[],'rejected':[]}
        ended=time.monotonic_ns()
        exclusive(slot/'receipt.json',{**invocation,'ended_monotonic_ns':ended,'elapsed_seconds':(ended-started)/1e9,'result':result})
        return result
    def execute(self,run,round_number):
        state=self.active_state(run)
        folder=self.path(run)/f'round-{round_number}'
        if (folder/'native').exists():raise ValueError('execution already attempted; preserve receipts')
        plan=self.receipt(run,'planner',round_number)
        checked=self.preflight(run,round_number,plan,sha(self.role_path(run,'planner',round_number)/'raw.json'))
        checkpoint=self.path(run)/'checkpoint'
        exclusive(folder/'necessity-review-requests.json',{'format':'necessity-review-requests-v1','raw_plan_sha256':sha(self.role_path(run,'planner',round_number)/'raw.json'),'before_revision':state['revision'],'before_evidence_hashes':deepcopy(state['evidence_hashes']),'not_required_proposals':deepcopy(checked['not_required_proposals']),'authority':'untrusted claims only; existing independent verifier adjudicates'})
        write(folder/'issue-order-normalization.json',checked['order_normalization'])
        self.log(run,f'execute-{round_number}','started')
        write(folder/'native-issues.json',checked['native_issues']);write(folder/'host-scope-bindings.json',checked['bindings'])
        write(folder/'insertion-scope-checks.json',checked['insertion_scope_checks'])
        write(folder/'preflight.json',{'accepted':checked['accepted'],'rejected':checked['rejected']});write(folder/'normalized-programs.json',checked['programs'])
        _,_,_,programs,_=native(self.root)
        with insertion_guard.transactions(programs,checked['programs'],state['required']+state['uncertain'],checked['images'],folder/'insertion-common-guard.jsonl') as guard:
            result=programs.execute_programs(checked['programs'],checked['native_issues'],checked['images'],folder/'native',capabilities=assignment_policy.load(self.root))
            guard.verify(result)
        result['rejected_programs']=checked['rejected'];write(folder/'native-result.json',result)
        render_snapshot(result['images']['case']['svg'],checkpoint/'original.png',folder/'candidate',root=self.root)
        return self.register_candidate(run,round_number,folder/'candidate',result)
    def accept(self,run,round_number):
        state=self.active_state(run)
        if round_number!=state['last_round']+1:raise ValueError('round out of sequence')
        folder=self.path(run)/f'round-{round_number}'
        if (folder/'acceptance.json').exists():raise ValueError('acceptance already recorded')
        candidate=read(folder/'candidate.json')
        requests=folder/'necessity-review-requests.json'
        if candidate.get('necessity_review_requests_sha256') is not None and (not requests.is_file() or sha(requests)!=candidate['necessity_review_requests_sha256']):raise ValueError('immutable necessity review requests changed')
        if candidate['before_revision']!=state['revision'] or candidate['before_evidence_hashes']!=state['evidence_hashes']:raise ValueError('candidate before checkpoint changed')
        snap=evidence(Path(candidate['candidate_folder']),self.root/'inputs'/'sam.json')
        if snap['evidence_hashes']!=candidate['evidence_hashes']:raise ValueError('candidate evidence changed')
        report=self.receipt(run,'verifier',round_number);missing_regions=self.bound_report(report,snap)
        if 'uncertain_findings' in report:raise ValueError('legacy uncertain_findings is ambiguous; use new_uncertain_findings and uncertainty_reviews')
        for field in ('resolved_ids','unresolved_ids','not_required','new_required_findings','new_uncertain_findings','protected_regressions'):
            if not isinstance(report.get(field),list):raise ValueError(field+' required')
        not_required=report['not_required']
        if any(not isinstance(x,dict) or not isinstance(x.get('evidence'),str) or not x['evidence'].strip() for x in not_required):raise ValueError('false positive adjudication requires evidence')
        partition=report['resolved_ids']+report['unresolved_ids']+[x.get('id') for x in not_required]
        expected={x['id'] for x in state['required']}
        if snap['revision']==state['revision'] and report['resolved_ids']:raise ValueError('unchanged SVG cannot resolve confirmed findings; adjudicate false positives as not_required')
        if any(not isinstance(x,str) for x in partition) or len(partition)!=len(set(partition)) or set(partition)!=expected:raise ValueError('verifier must exactly partition confirmed tracked IDs')
        validate_issues(report['new_required_findings']+report['new_uncertain_findings'],Path(candidate['candidate_folder'])/'current.svg')
        old_ids=set(state.get('historical_finding_ids',[]))|{x['id'] for x in state['required']+state['uncertain']+state.get('pending_observations',[])}
        old_ids.update(x['id'] for x in state.get('pending_observation_receipts',[]))
        if any(x['id'] in old_ids for x in report['new_required_findings']+report['new_uncertain_findings']):raise ValueError('new finding ID collides with tracked issue')
        if any(x['decision']!='confirmed' for x in report['new_required_findings']) or any(x['decision']!='uncertain' for x in report['new_uncertain_findings']):raise ValueError('new finding decision mismatch')
        reviews=report.get('uncertainty_reviews',[])
        if not isinstance(reviews,list):raise ValueError('uncertainty_reviews must be array')
        uncertain_map={x['id']:x for x in state['uncertain']};reviewed=set();promoted=[]
        for review in reviews:
            if not isinstance(review,dict) or not isinstance(review.get('id'),str) or review.get('id') not in uncertain_map or review['id'] in reviewed:raise ValueError('invalid uncertainty review identity')
            reviewed.add(review['id'])
            if review.get('decision') not in ('resolved','not_required','uncertain','confirmed') or not isinstance(review.get('evidence'),str) or not review['evidence'].strip():raise ValueError('uncertainty review requires decision and post-render evidence')
            if review['decision']=='resolved' and snap['revision']==state['revision']:raise ValueError('unchanged SVG cannot resolve uncertain finding; use not_required if disproved')
            if review['decision']=='confirmed':
                current=promote_uncertainty(uncertain_map[review['id']],review)
                validate_issues([current],Path(candidate['candidate_folder'])/'current.svg');promoted.append(current)
        bindings=report.get('current_bindings',[])
        if not isinstance(bindings,list):raise ValueError('current_bindings must be array')
        bindable={x['id']:x for x in state['required'] if x['id'] in report['unresolved_ids']}
        uncertainty_decisions={x['id']:x['decision'] for x in reviews}
        bindable.update({x['id']:x for x in state['uncertain'] if uncertainty_decisions.get(x['id'],'uncertain')=='uncertain'})
        binding_map={};binding_receipts=[]
        for binding in bindings:
            if not isinstance(binding,dict) or binding.get('id') not in bindable or binding['id'] in binding_map:raise ValueError('invalid current binding identity')
            if not isinstance(binding.get('evidence'),str) or not binding['evidence'].strip():raise ValueError('current binding requires post-render evidence')
            current=deepcopy(bindable[binding['id']])
            for key in ('target_ids','neighbor_ids'):
                if key not in binding:raise ValueError('current binding requires '+key)
                current[key]=binding[key]
            current.pop('container_id',None)
            if 'container_id' in binding:current['container_id']=binding['container_id']
            current['current_evidence']=binding['evidence'];validate_issues([current],Path(candidate['candidate_folder'])/'current.svg')
            binding_map[current['id']]=current
            binding_receipts.append({'id':current['id'],'before':bindable[current['id']],'after':current,'evidence':binding['evidence']})
        rollback=bool(report['protected_regressions'])
        fresh=report['new_required_findings']+report['new_uncertain_findings']
        dispositions={x['id']:x['decision'] for x in reviews}
        next_required=[x for x in state['required'] if x['id'] in report['unresolved_ids']]+report['new_required_findings']+promoted
        next_uncertain=[x for x in state['uncertain'] if dispositions.get(x['id'],'uncertain')=='uncertain']+report['new_uncertain_findings']
        next_required=[binding_map.get(x['id'],x) for x in next_required]
        next_uncertain=[binding_map.get(x['id'],x) for x in next_uncertain]
        candidate_svg=Path(candidate['candidate_folder'])/'current.svg'
        known_svg_ids={node.get('id') for node in ET.parse(candidate_svg).getroot().iter() if node.get('id')}
        triage=triage_pending(state.get('pending_observations',[]),report.get('pending_observation_reviews',[]),
                              active_issues=next_required+next_uncertain,known_svg_ids=known_svg_ids,
                              validate_current_issue=lambda rows:validate_issues(rows,candidate_svg))
        # Complete native validation precedes the pure residual transaction.
        if state.get('connector_paint_mode'):
            validate_issues(next_required+next_uncertain+triage['required']+triage['uncertain'],candidate_svg)
            survivors={row['id'] for row in next_required+next_uncertain+triage['required']+triage['uncertain']}
            reserved=connector_contract.native_ids(state)|{row['id'] for row in fresh}|survivors
            residual=connector_contract.transition(self.connector_host(run),self.connector_bundle(run,round_number),state,rollback=rollback,native_survivors=survivors,native_reserved_ids=reserved)
            state['connector_visual_concerns']=residual['connector_visual_concerns']
            state['connector_concern_receipts']=residual['connector_concern_receipts']
        # Reserve every reported ID, including rejected and later retired ones.
        state['historical_finding_ids']=list(dict.fromkeys(state.get('historical_finding_ids',[])+[x['id'] for x in fresh]))
        if rollback:
            # Candidate-specific triage is validated but cannot alter retained
            # checkpoint knowledge, bindings, queues or retirement receipts.
            state['pending_observations']=capture_pending(state.get('pending_observations',[]),fresh,
                raw_sha256=sha(self.role_path(run,'verifier',round_number)/'raw.json'),
                observed_revision=snap['revision'],retained_revision=state['revision'],
                before_evidence_hashes=state['evidence_hashes'],observed_evidence_hashes=snap['evidence_hashes'],
                round_number=round_number,report_path=str(self.role_path(run,'verifier',round_number).relative_to(self.path(run))/'raw.json'))
        else:
            state['pending_observations']=triage['pending']
            receipt_context={'reviewed_revision':snap['revision'],'reviewed_evidence_hashes':snap['evidence_hashes'],
                             'review_round':round_number,'review_raw_sha256':sha(self.role_path(run,'verifier',round_number)/'raw.json')}
            state['pending_observation_receipts']=state.get('pending_observation_receipts',[])+[{**row,**receipt_context} for row in triage['receipts']]
            state['required']=next_required+triage['required']
            state['uncertain']=next_uncertain+triage['uncertain']
            state['uncertain_resolved_total']+=sum(x['decision']=='resolved' for x in reviews)
            state['uncertain_false_positive_total']+=sum(x['decision']=='not_required' for x in reviews)
            state['resolved_total']+=len(report['resolved_ids']);state['false_positive_total']+=len(not_required)
            old=self.path(run)/f'checkpoint-before-{round_number}';(self.path(run)/'checkpoint').rename(old)
            clone(Path(candidate['candidate_folder']),self.path(run)/'checkpoint');state.update(snap)
        state['last_round']=round_number
        if rollback or state['required']:state['status']='needs_followup' if round_number<3 else 'unresolved_after_limit'
        elif state.get('pending_observations'):state['status']='needs_followup' if round_number<3 else 'inconclusive'
        elif state['uncertain'] or report['new_uncertain_findings'] or report['unresolved_regions'] or not report['examined_regions'] or missing_regions:state['status']='inconclusive'
        elif state.get('connector_visual_concerns'):state['status']='inconclusive'
        else:state['status']='runtime_clean_pending_evaluation'
        state['visual_passed']=False;state['last_acceptance']={'round':round_number,'rollback':rollback,'report_sha256':sha(self.role_path(run,'verifier',round_number)/'raw.json')}
        self.save(run,state);exclusive(folder/'acceptance.json',{'rollback':rollback,'state':state,'current_binding_receipts':[] if rollback else binding_receipts,'pending_observation_receipts':[] if rollback else triage['receipts'],'missing_region_declarations':missing_regions,'resolved_this_round':0 if rollback else len(report['resolved_ids']),'false_positives_this_round':0 if rollback else len(not_required)})
        self.log(run,f'accept-{round_number}','completed',status=state['status'],rollback=rollback)
        return state


    def finish(self,run):
        state=self.checked_state(run)
        if state.get('runtime_finished_monotonic_ns') is not None:raise ValueError('runtime already finished')
        if not state.get('last_acceptance'):raise ValueError('runtime requires post-render acceptance before finish')
        now=time.monotonic_ns();state['runtime_finished_monotonic_ns']=now
        state['runtime_elapsed_seconds']=(now-state['started_monotonic_ns'])/1e9
        state['runtime_finished_utc']=datetime.now(timezone.utc).isoformat()
        self.save(run,state);self.log(run,'runtime','finished',status=state['status'],runtime_elapsed_seconds=state['runtime_elapsed_seconds'])
        return state


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True);sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('prepare');sub.add_parser('prepare-contracts')
    for cmd in ('begin-run','merge','status','finish-run'):
        p=sub.add_parser(cmd);p.add_argument('run',choices=('run1','run2','run3'))
    for cmd in ('execute','accept','check-plan'):
        p=sub.add_parser(cmd);p.add_argument('run',choices=('run1','run2','run3'));p.add_argument('round',type=int)
        if cmd=='check-plan':p.add_argument('draft',type=Path)
    p=sub.add_parser('check-report');p.add_argument('run',choices=('run1','run2','run3'));p.add_argument('role',choices=('main','semantic'));p.add_argument('draft',type=Path)
    for cmd in ('dispatch','receive'):
        p=sub.add_parser(cmd);p.add_argument('run',choices=('run1','run2','run3'));p.add_argument('role',choices=('main','semantic','planner','verifier'));p.add_argument('--round',type=int)
        if cmd=='dispatch':p.add_argument('--agent-id',required=True)
        else:p.add_argument('file',type=Path)
    args=parser.parse_args();flow=Flow(args.root)
    if args.command=='prepare':raise ValueError('legacy prepare disabled: use reviewed frozen cell input preparation')
    elif args.command=='prepare-contracts':out=prepare_contracts(args.root)
    elif args.command=='begin-run':out=flow.begin(args.run)
    elif args.command=='dispatch':out=flow.dispatch(args.run,args.role,args.agent_id,args.round)
    elif args.command=='receive':out=flow.receive(args.run,args.role,args.file,args.round)
    elif args.command=='merge':out=flow.merge(args.run)
    elif args.command=='finish-run':out=flow.finish(args.run)
    elif args.command=='check-report':out=flow.check_report(args.run,args.role,args.draft)
    elif args.command=='check-plan':out=flow.check_plan(args.run,args.round,args.draft)
    elif args.command=='execute':out=flow.execute(args.run,args.round)
    elif args.command=='accept':out=flow.accept(args.run,args.round)
    else:out=flow.checked_state(args.run)
    if out is not None:print(json.dumps(out,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
