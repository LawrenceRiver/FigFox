#!/usr/bin/env python3
"""Single-command formal runner. Import and --plan never contact providers."""
import argparse, collections, csv, hashlib, html, json, os, subprocess, sys, uuid, time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import budget, live_api, native_receipt_recovery
BASE=Path(__file__).resolve().parent.parent
V=BASE/'experiments/final-architecture-20261023/convergence-v2'
MATRIX=V/'v6-finalization-ablation-20261028/four-cell-run-matrix.json'
REGISTRY=Path('/Users/lawrenceriver/Downloads/FigFox_评分标准_v2/figfox_score/registry.json')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def write(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);t=p.with_name(p.name+'.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str));os.replace(t,p)
def module(path):
 import importlib.util
 s=importlib.util.spec_from_file_location('bound_bridge',path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def validate(config,fixture=False):
 matrix=Path(config.get('matrix_path',MATRIX));registry=Path(config.get('registry_path',REGISTRY))
 if not fixture:
  for key,path in [('expected_matrix_sha256',matrix),('expected_registry_sha256',registry)]:
   if not config.get(key) or sha(path)!=config[key]:raise ValueError('predeclared frozen hash missing/mismatch: '+key)
 rows=read(matrix)['rows'];groups=collections.defaultdict(list)
 for r in rows:
  groups[r['sample_id']].append(r)
  if sha(r['source_image_path'])!=r['source_image_sha256']:raise ValueError('source SHA mismatch: '+r['sample_id'])
 for sample,rs in groups.items():
  if {r['cell'] for r in rs}!={'S0C0','S0C1','S1C0','S1C1'} or len(rs)!=4:raise ValueError('four-cell matrix mismatch')
  if len({(r['source_image_sha256'],r['source_group'],r['fc_bin'],r['dataset_id']) for r in rs})!=1:raise ValueError('sample source identity mismatch')
  for r in rs:
   if r['cell']!=f"S{int(r['sam'])}C{int(r['external_code'])}":raise ValueError('factor mismatch')
 if not fixture:
  if matrix.resolve()!=MATRIX.resolve() or registry.resolve()!=REGISTRY.resolve():raise ValueError('frozen matrix/registry paths required')
  if len(rows)!=320 or len(groups)!=80 or len({r['source_group'] for r in rows})!=67:raise ValueError('historical80 identity/count mismatch')
  if sorted(collections.Counter(rs[0]['fc_bin'] for rs in groups.values()).values())!=[20]*4:raise ValueError('four balanced bins required')
 rub=read(registry)
 if not isinstance(rub,list) or [x['id'] for x in rub]!=[f'D{i:02}' for i in range(1,19)]:raise ValueError('canonical 18-rule registry required')
 bridge=module(config.get('bridge_path',V/'generic-cell-input-bridge-20261029/prepare_cell.py'))
 adapter=Path(config.get('adapter_root',V/'insertion-parity-adapter-20261029'))
 source=Path(config.get('native_source_root',adapter/'source')).resolve()
 manifest=bridge.source_manifest(source,adapter/'source')
 runtime=read(config['runtime_json'])
 if set(runtime)!=set(bridge.RUNTIME_KEYS):raise ValueError('explicit exact runtime binding required')
 for p in runtime.values():
  if not Path(p).exists():raise ValueError('runtime path missing: '+p)
 for r in rows:r.update(provider='deepseek',slot_providers={'first':'openai','score':'deepseek_score'})
 binding={'matrix':sha(matrix),'registry':sha(registry),'native_source':digest(manifest),'adapter':digest({str(p.relative_to(adapter)):sha(p) for p in sorted(adapter.rglob('*')) if p.is_file() and 'source' not in p.relative_to(adapter).parts and '__pycache__' not in p.parts and (p.parent==adapter and p.suffix=='.py' and not p.name.startswith('test_') or p.relative_to(adapter).parts[0] in ('docs','prompts'))}),'bridge':sha(bridge.__file__),'runtime':sha(config['runtime_json']),'source_rows':digest(rows),'controller_runtime':{p.name:sha(p) for p in (Path(__file__),Path(live_api.__file__),Path(budget.__file__),Path(native_receipt_recovery.__file__))}}
 return rows,groups,binding

def plan(config):
 rows,groups,binding=validate(config);missing=[]
 for name,p in config.get('providers',{}).items():
  if not os.environ.get(p.get('key_env','')) and not (p.get('env_file') and Path(p['env_file']).is_file()):missing.append(name+': credential unavailable (presence only)')
 slots=budget.plan_block(config,rows);summary=budget.inspect_budget(config['ledger_path'],config['expected_cap_usd']);first=budget.plan_block(config,next(iter(groups.values())))
 required=sum((s['reserve_usd'] for s in first),Decimal(0));total=sum((s['reserve_usd'] for s in slots),Decimal(0))
 if 'sample_cap_usd' in config:
  required=budget.money(config['sample_cap_usd']);total=required*len(groups)
 caches=config.get('sam_catalogs',{})
 for sample in groups:
  if not caches.get(sample) and not config.get('sam_service_url'):missing.append(sample+': SAM cache/service unavailable')
 return {'mode':'offline_plan','http_calls':0,'reservations':0,'samples':len(groups),'cells':len(rows),'bindings':binding,'budget':summary,'first_block_upper_usd':required,'first_block_shortage_usd':max(Decimal(0),required-summary['available_usd']),'all_cells_upper_usd':total,'all_cells_shortage_usd':max(Decimal(0),total-summary['available_usd']),'missing':missing}

def native(command,config,log):
 if len(command)>4 and Path(command[2]).name=='flow.py' and '--root' in command:
  root=Path(command[command.index('--root')+1])
  if any((root/'runs').glob('*/round-*/verifier/corrections/*/correction.json')):
   command=[*command[:2],native_receipt_recovery.__file__,command[2],*command[3:]]
 result=subprocess.run(command,env=live_api.clean_env(),capture_output=True,text=True,timeout=config.get('native_timeout_seconds',7200));write(log,{'argv':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
 if result.returncode:raise RuntimeError('native command failed: '+str(log))
 return result.stdout

def sam_for(row,config,folder):
 target=folder/'sam-catalog.json'
 supplied=str(target) if target.exists() else config.get('sam_catalogs',{}).get(row['sample_id'])
 if supplied:catalog=read(supplied)
 else:
  if not config.get('sam_service_url'):raise ValueError('SAM unavailable before first API spend')
  preparer=config.get('sam_preparer_source_root',config['native_source_root'])
  if preparer!=config['native_source_root']:
   if not config.get('sam_preparer_files') or any(sha(path)!=value for path,value in config['sam_preparer_files'].items()):raise ValueError('SAM preparer dependency hash mismatch')
  code="import sys,json;sys.path.insert(0,sys.argv[1]+'/src');from figfox_plus.sam import prepare_assets;x=prepare_assets(sys.argv[2],sys.argv[3],service_url=sys.argv[4]);open(sys.argv[5],'x').write(json.dumps(x))"
  native([config.get('native_python',sys.executable),'-B','-c',code,preparer,row['source_image_path'],str(folder/'sam-cache'),config['sam_service_url'],str(target)],config,folder/'sam-prepare-log.json');catalog=read(target)
 # Reviewed source-bound native validator, keyless and network denied.
 code="import sys,json;sys.path.insert(0,sys.argv[1]);import first_stage;first_stage.validate_sam(json.load(open(sys.argv[2])),__import__('pathlib').Path(sys.argv[3]))"
 if supplied and Path(supplied).resolve()!=target.resolve():write(target,catalog)
 native([config.get('native_python',sys.executable),'-B','-c',code,str(Path(config['adapter_root']).parent/'first-stage-harness-bridge-20261029'),str(target),row['source_image_path']],config,folder/'sam-validation-log.json')
 return str(target)

def reusable_finished_native(state_path,row):
 state=read(state_path);checkpoint=Path(state_path).parent/'checkpoint';policy={'version':'capabilities-v1','sam':row['sam'],'code_methods':row['external_code']};hashes=state.get('evidence_hashes',{})
 if state.get('runtime_finished_monotonic_ns') is None or state.get('capabilities')!=policy or sha(row['source_image_path'])!=row['source_image_sha256'] or hashes.get('original_png')!=row['source_image_sha256'] or hashes.get('current_svg')!=sha(checkpoint/'current.svg') or hashes.get('current_png')!=sha(checkpoint/'current.png') or state.get('revision')!=hashes.get('current_svg'):raise ValueError('finished native source/capability/artifact identity mismatch')
 return {'final_svg':str(checkpoint/'current.svg'),'final_png':str(checkpoint/'current.png'),'final_svg_sha256':hashes['current_svg'],'final_png_sha256':hashes['current_png'],'native_state':state}

def reusable_first(receipt,row):
 first=read(receipt);provenance=read(first['provenance']);policy={'version':'capabilities-v1','sam':row['sam'],'code_methods':row['external_code']}
 if provenance.get('origin')!='actual frozen native.pipeline.first automatic isolated provider callback' or sha(first['original'])!=row['source_image_sha256'] or sha(row['source_image_path'])!=row['source_image_sha256'] or provenance.get('original_png_sha256')!=row['source_image_sha256'] or provenance.get('initial_svg_sha256')!=sha(first['stage0_scene']) or provenance.get('capability_sha256')!=digest(policy):raise ValueError('prior first-stage source/capability/artifact identity mismatch')
 return first

def cell(row,config,lease,folder,sam,first_receipt=None,resume_cell_root=None):
 started=time.monotonic();phases={};phase_started=started
 if resume_cell_root is not None and first_receipt is None:raise ValueError('native phase resume requires verified first-stage receipt')
 c={**config,'current_sample_id':row['sample_id'],'current_cell':row['cell']};policy={'version':'capabilities-v1','sam':row['sam'],'code_methods':row['external_code']};caps={'policy':policy,'sha256':digest(policy)}
 if first_receipt is not None:
  first=reusable_first(first_receipt,row);write(folder/'first-reuse.json',{'receipt':str(first_receipt),'receipt_sha256':sha(first_receipt),'source_image_sha256':row['source_image_sha256'],'new_generation_request':False})
 else:first=live_api.run_first({'output_root':str(folder/'first'),'adapter':c['adapter_root'],'native_source_root':c['native_source_root'],'runtime_json':c['runtime_json'],'original_png':row['source_image_path'],'capabilities':policy,**({'sam_catalog':sam} if row['sam'] else {})},c,lease)
 phases['first_seconds']=time.monotonic()-phase_started;phase_started=time.monotonic()
 root=folder/'cell';spec={'adapter':c['adapter_root'],'native_source_root':c['native_source_root'],'output_root':str(root),'original_png':first['original'],'initial_svg':first['stage0_scene'],'runtime_json':first['runtime'],'runtime_binding':first['runtime_binding'],'registry':c['registry_path'],'capabilities':caps,'first_stage_provenance':first['provenance'],'python':c.get('native_python',sys.executable)}
 if resume_cell_root is not None:root=Path(resume_cell_root).resolve();spec['output_root']=str(root)
 if row['sam']:spec['sam_catalog']=first['sam_neutral']
 write(folder/'prepare-spec.json',spec)
 if resume_cell_root is None:native([spec['python'],'-B',c['bridge_path'],'--spec',str(folder/'prepare-spec.json')],c,folder/'prepare-log.json')
 else:
  state=read(root/'runs/run1/state.json')
  prior_spec=read(root.parent/'prepare-spec.json');prior_spec['output_root']=str(Path(prior_spec['output_root']).resolve());mismatches=[key for key in set(spec)|set(prior_spec) if spec.get(key)!=prior_spec.get(key)]
  if state.get('capabilities')!=policy:mismatches.append('state.capabilities')
  if state.get('evidence_hashes',{}).get('original_png')!=row['source_image_sha256']:mismatches.append('state.original_png')
  if sha(root/'flow.py')!=sha(Path(c['adapter_root'])/'flow.py'):mismatches.append('flow.py')
  if mismatches:raise ValueError('native resume immutable source/capability/spec mismatch: '+','.join(sorted(mismatches)))
  write(folder/'native-phase-reuse.json',{'cell_root':str(root),'state_sha256_before':sha(root/'runs/run1/state.json'),'initial_svg_sha256':sha(first['stage0_scene']),'prior_receipts_retained':True})
 phases['preparation_seconds']=time.monotonic()-phase_started;phase_started=time.monotonic()
 index=0
 def flow(*args):
  nonlocal index
  index+=1;return native([spec['python'],'-B',str(root/'flow.py'),'--root',str(root),*map(str,args)],c,folder/f'flow-{index:03}.json')
 def role(name,r=None):
  role_folder=root/'runs/run1'/('detection/'+name if r is None else 'round-'+str(r)+'/'+name)
  if name=='verifier':role_folder=native_receipt_recovery.verifier_path(root,'run1',r)
  if (role_folder/'raw.json').is_file():
   if sha(role_folder/'raw.json')!=read(role_folder/'receipt.json')['sha256']:raise ValueError('prior native role receipt hash mismatch')
   if name=='verifier' and native_receipt_recovery.invalid_schema(read(role_folder/'raw.json')):
    recovery_config={**c,'verifier_schema_recovery':{'old_raw_sha256':sha(role_folder/'raw.json'),'old_schema_keys':list(read(role_folder/'raw.json'))}}
    output=live_api.run_role(root,'run1',name,r,recovery_config,lease)
    corrected=native_receipt_recovery.append_correction(root,'run1',r,output)
    write(folder/f'verifier-schema-correction-{r}.json',{'correction_path':str(corrected),'correction_sha256':sha(corrected/'correction.json'),'original_raw_sha256':sha(role_folder/'raw.json'),'frozen_flow_sha256':sha(root/'flow.py'),'recovery_runtime_sha256':sha(native_receipt_recovery.__file__),'all_native_accept_validators_unchanged':True})
   return
  args=['dispatch','run1',name,'--agent-id','api-'+str(uuid.uuid4())]
  if r:args+=['--round',r]
  if not (role_folder/'dispatch.json').exists():flow(*args)
  output=live_api.run_role(root,'run1',name,r,c,lease);args=['receive','run1',name,output]
  if r:args+=['--round',r]
  flow(*args)
 if (root/'runs/run1/state.json').exists():flow('status','run1')
 else:flow('begin-run','run1')
 for name in ('main','semantic'):role(name)
 if not (root/'runs/run1/merged.json').exists():flow('merge','run1')
 for r in range(1,4):
  state=read(root/'runs/run1/state.json')
  if r<=state.get('last_round',0):
   if state.get('status')!='needs_followup':break
   continue
  role('planner',r)
  if not (root/'runs/run1'/('round-'+str(r))/'candidate.json').exists():flow('execute','run1',r)
  role('verifier',r);flow('accept','run1',r)
  state=read(root/'runs/run1/state.json')
  if state.get('status')!='needs_followup':break
 if read(root/'runs/run1/state.json').get('runtime_finished_monotonic_ns') is None:flow('finish-run','run1')
 checkpoint=root/'runs/run1/checkpoint';svg=checkpoint/'current.svg';png=checkpoint/'current.png'
 if not svg.is_file() or not png.is_file():raise ValueError('committed final output missing')
 phases['flow_seconds']=time.monotonic()-phase_started;phase_started=time.monotonic()
 scores=live_api.score_cell(first['original'],str(svg),str(png),c['registry_path'],folder,c,lease)
 phases['scoring_seconds']=time.monotonic()-phase_started
 return {'elapsed_monotonic_seconds':time.monotonic()-started,'terminal_utc':datetime.now(timezone.utc).isoformat(),'phase_durations':phases,'status':'complete','row':row,'final_svg':str(svg),'final_png':str(png),'final_svg_sha256':sha(svg),'final_png_sha256':sha(png),'scores':scores,'editable_human_proof':'unknown','native_state':read(root/'runs/run1/state.json')}

def complete_valid(record,binding):
 return record.get('status')=='complete' and record.get('bindings')==binding and all(Path(record[k]).is_file() and sha(record[k])==record[k+'_sha256'] for k in ('final_svg','final_png'))
def cluster_bootstrap(records):
 """Frozen design: image-weighted paired cluster percentile bootstrap."""
 if len(records)!=320 or any(x.get('status') not in ('complete','terminal_failed') for x in records):return {'status':'unknown_not_computed_incomplete_cohort'}
 import random
 groups=collections.defaultdict(list)
 for x in records:groups[x['row']['source_group']].append(x)
 if len(groups)!=67:return {'status':'unknown_source_group_mismatch'}
 values={}
 for group,items in groups.items():
  sums=collections.Counter();counts=collections.Counter()
  for item in items:
   reviews=item.get('scores',{}).get('reviews',[]);c=item['row']['cell'];counts[c]+=1
   sums[c]+=int(len(reviews)==2 and all(z['status'] in ('pass','NA') for review in reviews for z in review['items']))
  values[group]=(sums,counts)
 def effect(r):return {'sam_primary':r['S1C1']-r['S0C1'],'code_primary':r['S1C1']-r['S1C0'],'sam_average':((r['S1C1']-r['S0C1'])+(r['S1C0']-r['S0C0']))/2,'code_average':((r['S1C1']-r['S1C0'])+(r['S0C1']-r['S0C0']))/2,'interaction':(r['S1C1']-r['S1C0'])-(r['S0C1']-r['S0C0'])}
 def rates(sample):
  sums=collections.Counter();counts=collections.Counter()
  for group in sample:
   a,b=values[group];sums.update(a);counts.update(b)
  return {c:sums[c]/counts[c] for c in ('S0C0','S0C1','S1C0','S1C1')}
 rng=random.Random(20261028);keys=sorted(groups);point=effect(rates(keys));effects={k:[] for k in point}
 for _ in range(10000):
  for name,value in effect(rates(rng.choices(keys,k=67))).items():effects[name].append(value)
 def quantile(v,p):
  v=sorted(v);index=(len(v)-1)*p;lo=int(index);return v[lo]+(v[min(lo+1,len(v)-1)]-v[lo])*(index-lo)
 return {'status':'computed','unit':'source_group','weighting':'images equal within sampled source groups; four cells paired','groups':67,'replicates':10000,'invalid_replicates':0,'seed':20261028,'quantile':'linear index=(n-1)*p; standard-library implementation version 1','metric':'both judges all18 pass_or_NA; unknown/nonoutputs=0','point_effects':point,'percentile_95':{k:[quantile(v,.025),quantile(v,.975)] for k,v in effects.items()},'primary_bonferroni_97_5':{k:[quantile(effects[k],.0125),quantile(effects[k],.9875)] for k in ('sam_primary','code_primary')},'exploratory':['sam_average','code_average','interaction']}

def report(run,rows,records):
 budget_capped=sum(x.get('status')=='budget_capped' for x in records)
 result={'expected_samples':80,'expected_cells':320,'completed_cells':sum(x.get('status')=='complete' for x in records),'terminal_failed_cells':sum(x.get('status')=='terminal_failed' for x in records),'unknown_cells':320-sum(x.get('status') in ('complete','terminal_failed') for x in records),'not_complete_cells':320-sum(x.get('status')=='complete' for x in records),'primary_usable_denominator':80,'cells':records,'source_group_bootstrap':cluster_bootstrap(records),'editability_human_coverage':'unknown'}
 result['conditions']={}
 result['budget_capped_cells']=budget_capped
 for condition in ('S0C0','S0C1','S1C0','S1C1'):
  cells=[x for x in records if x['row']['cell']==condition];rules={f'D{i:02}':collections.Counter() for i in range(1,19)};usable=0
  for item in cells:
   reviews=item.get('scores',{}).get('reviews',[])
   if len(reviews)!=2:continue
   maps=[{x['id']:x['status'] for x in review['items']} for review in reviews]
   for criterion in rules:
    a,b=(m[criterion] for m in maps);rules[criterion][a if a==b else 'disagreement_unknown']+=1
   if all(m[k] in ('pass','NA') for m in maps for k in rules):usable+=1
  result['conditions'][condition]={'usable':usable,'denominator':80,'primary_usable_rate':usable/80,'rule_statuses':{k:dict(v) for k,v in rules.items()},'unscored_unknown':80-sum(len(x.get('scores',{}).get('reviews',[]))==2 for x in cells),'human_editability':'unknown'}
 write(run/'overall.json',result)
 for group in sorted({r['source_group'] for r in rows}):write(run/'groups'/f'{group}.json',{'source_group':group,'cells':[x for x in records if x['row']['source_group']==group]})
 with (run/'overall.csv').open('w') as f:
  w=csv.writer(f);w.writerow(['sample_id','cell','source_group','status','error']);w.writerows([x['row']['sample_id'],x['row']['cell'],x['row']['source_group'],x['status'],x.get('error','')] for x in records)
 (run/'overall.html').write_text('<meta charset="utf-8"><title>Formal ablation</title><h1>Formal ablation receipts</h1><pre>'+html.escape(json.dumps(result,ensure_ascii=False,indent=2,default=str))+'</pre>')

def terminal_valid(record,binding,out):
 if record.get('status')=='complete':return complete_valid(record,binding)
 if record.get('status') not in ('terminal_failed','budget_capped') or record.get('bindings')!=binding:return False
 return all((out/path).is_file() and sha(out/path)==value for path,value in record.get('terminal_artifacts',{}).items()) and bool(record.get('terminal_artifacts'))
def terminal_artifacts(out):return {str(p.relative_to(out)):sha(p) for p in sorted(out.rglob('*')) if p.is_file() and p.name not in ('result.json','result.json.tmp')}

def execute(config,resume=None):
 admission=plan(config)
 if admission['missing']:raise ValueError('execution preflight missing configuration/credentials: '+json.dumps(admission['missing']))
 if not resume and (admission['budget']['blocked'] or admission['first_block_shortage_usd']>0):raise ValueError('execution preflight budget unavailable: '+json.dumps(admission,default=str))
 rows,groups,binding=validate(config);run=Path(resume or (Path(config['output_root'])/str(uuid.uuid4()))).resolve();identity=run/'identity.json'
 if identity.exists():
  old=read(identity)
  if old['config_sha256']!=digest(config) or old['bindings']!=binding:raise ValueError('immutable resume binding changed')
  run_uuid=old['run_uuid']
 else:
  if resume:raise ValueError('resume identity missing')
  run.mkdir(parents=True,exist_ok=False);run_uuid=run.name;write(identity,{'run_uuid':run_uuid,'config_sha256':digest(config),'bindings':binding,'config':config})
 records=[]
 for sample,block in groups.items():
  folder=run/sample;folder.mkdir(exist_ok=True)
  # SAM admission for both ON cells before any model call or reservation.
  sam=sam_for(block[0],config,folder)
  lease=budget.reserve_block(config,run_uuid,block,folder)
  sample_capped=False
  for row in block:
   out=folder/row['cell'];receipt=out/'result.json'
   if receipt.exists():
    record=read(receipt)
    if terminal_valid(record,binding,out):
     if record['status']=='budget_capped':sample_capped=True
     lease.retire_cell(row['sample_id'],row['cell']);records.append(record)
     if record['status']!='complete':raise RuntimeError('recover failed condition before advancing: '+str(receipt))
     continue
    raise ValueError('unresolved prior cell receipt; automatic replay prohibited: '+str(receipt))
   if out.exists():
    # Crash between durable cell marker and any native/API work is safely restartable.
    entries=list(out.iterdir())
    if len(entries)==1 and entries[0].name=='started.json' and read(entries[0]).get('bindings')==binding:
     entries[0].unlink();out.rmdir()
    else:raise ValueError('native/API attempt directory exists without terminal receipt; inspect preserved receipts; automatic replay prohibited: '+str(out))
   out.mkdir();write(out/'started.json',{'row':row,'bindings':binding})
   try:
    if sample_capped:raise budget.SampleBudgetExceeded('earlier condition reached sample budget guard; no further model calls')
    record=cell(row,config,lease,out,sam)
   except Exception as exc:
    unresolved=[x for x in lease.inspect_attempts() if x['sample_id']==row['sample_id'] and x['cell']==row['cell']]
    capped=isinstance(exc,budget.SampleBudgetExceeded) and not unresolved
    if capped:sample_capped=True
    unsafe=not capped and (isinstance(exc,(budget.BudgetError,subprocess.TimeoutExpired)) or bool(unresolved) or any(word in str(exc).lower() for word in ('hash mismatch','source changed','binding changed','immutable','tamper')))
    record={'status':'budget_capped' if capped else 'blocked_unknown' if unsafe else 'terminal_failed','row':row,'error_type':type(exc).__name__,'error':str(exc),'unresolved_attempts':unresolved,'not_usable':True,'terminal_artifacts':terminal_artifacts(out)}
   record['terminal_utc']=record.get('terminal_utc',datetime.now(timezone.utc).isoformat());record['bindings']=binding;write(receipt,record);records.append(record);report(run,rows,records)
   if record['status']=='blocked_unknown':raise RuntimeError('unsafe unresolved attempt; no automatic replay: '+str(receipt))
   lease.retire_cell(row['sample_id'],row['cell'])
   if record['status']!='complete':raise RuntimeError('recover failed condition before advancing: '+str(receipt))
 report(run,rows,records);return str(run)
def main():
 p=argparse.ArgumentParser();p.add_argument('--config',default=str(Path(__file__).with_name('config.json')));g=p.add_mutually_exclusive_group();g.add_argument('--plan',action='store_true');g.add_argument('--execute',action='store_true');p.add_argument('--resume');a=p.parse_args()
 if a.resume and not a.execute:p.error('--resume requires --execute')
 try:
  c=read(a.config);print(json.dumps(execute(c,a.resume) if a.execute else plan(c),ensure_ascii=False,indent=2,default=str))
 except Exception as e:print(json.dumps({'status':'blocked','error_type':type(e).__name__,'error':str(e),'http_calls':'none in plan' if not a.execute else 'inspect durable receipts'}));return 2
 return 0
if __name__=='__main__':sys.exit(main())
