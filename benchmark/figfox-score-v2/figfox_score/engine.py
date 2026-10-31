"""Conservative rules over explicitly attested manifests. No visual inference."""
import copy, hashlib, json, math
from pathlib import Path
from collections import Counter, defaultdict
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
REGISTRY=json.loads((Path(__file__).parent/'registry.json').read_text())

def strict_json(path):
 def pairs(items):
  out={}
  for k,v in items:
   if k in out: raise ValueError('duplicate JSON key: '+k)
   out[k]=v
  return out
 return json.loads(Path(path).read_text(encoding='utf-8'),object_pairs_hook=pairs,parse_constant=lambda v: (_ for _ in ()).throw(ValueError('nonfinite '+v)))

def check(value,schema,path='$'):
 """Implements exactly the JSON Schema vocabulary used by bundled contracts."""
 if 'enum' in schema and value not in schema['enum']: raise ValueError(path+': enum')
 types=schema.get('type',[]); types=[types] if isinstance(types,str) else types
 predicates={'object':lambda x:isinstance(x,dict),'array':lambda x:isinstance(x,list),'string':lambda x:isinstance(x,str),'boolean':lambda x:type(x) is bool,'integer':lambda x:type(x) is int,'number':lambda x:type(x) in (int,float) and math.isfinite(x),'null':lambda x:x is None}
 if types and not any(predicates[t](value) for t in types): raise ValueError(path+': type')
 if type(value) in (int,float):
  if not math.isfinite(value): raise ValueError(path+': finite required')
  if 'minimum' in schema and value<schema['minimum']: raise ValueError(path+': minimum')
  if 'exclusiveMinimum' in schema and value<=schema['exclusiveMinimum']: raise ValueError(path+': exclusiveMinimum')
 if isinstance(value,str) and len(value)<schema.get('minLength',0): raise ValueError(path+': empty')
 if isinstance(value,list):
  if len(value)<schema.get('minItems',0) or len(value)>schema.get('maxItems',float('inf')): raise ValueError(path+': length')
  for i,x in enumerate(value): check(x,schema['items'],f'{path}[{i}]')
 if isinstance(value,dict):
  props=schema.get('properties',{})
  if set(schema.get('required',[]))-value.keys(): raise ValueError(path+': missing required keys')
  if schema.get('additionalProperties') is False and value.keys()-props.keys(): raise ValueError(path+': unknown keys '+str(value.keys()-props.keys()))
  for k,v in value.items():
   if k in props: check(v,props[k],path+'.'+k)

def validate_input(d):
 check(d,strict_json(ROOT/'schemas/input.schema.json'))
 for side in ['reference','candidate']:
  m=d[side]; ids=[o['id'] for o in m['objects']]; edges=[e['id'] for e in m['edges']]
  if len(set(ids+edges))!=len(ids+edges): raise ValueError(side+': duplicate semantic ID')
  for o in m['objects']:
   if o['bbox'][2]<=0 or o['bbox'][3]<=0: raise ValueError('positive bbox sizes required')
   if o['parent'] is not None and (o['parent'] not in ids or o['parent']==o['id']): raise ValueError('invalid parent')
   parents={x['id']:x['parent'] for x in m['objects']}; seen={o['id']}; par=o['parent']
   while par is not None:
    if par in seen: raise ValueError('container cycle')
    seen.add(par);par=parents[par]
  for e in m['edges']:
   if e['start'] not in ids or e['end'] not in ids: raise ValueError('unknown edge endpoint')
 refs={o['id'] for o in d['reference']['objects']}; cands={o['id'] for o in d['candidate']['objects']}
 if len({x['ref'] for x in d['matches']})!=len(d['matches']) or len({x['candidate'] for x in d['matches']})!=len(d['matches']): raise ValueError('matches must be one-to-one; unmatched objects stay explicit')
 if any(x['ref'] not in refs or x['candidate'] not in cands for x in d['matches']): raise ValueError('unknown match ID')
 er={e['id'] for e in d['reference']['edges']};ec={e['id'] for e in d['candidate']['edges']}
 em=d['edge_matches']
 if len({x['ref'] for x in em})!=len(em) or len({x['candidate'] for x in em})!=len(em) or any(x['ref'] not in er or x['candidate'] not in ec for x in em): raise ValueError('invalid edge one-to-one matches')
 allrefs=refs|{e['id'] for e in d['reference']['edges']}
 for item,a in d['applicability'].items():
  units=a['units'];ids=[x['id'] for x in units]
  if len(ids)!=len(set(ids)) or (a['state']=='na' and units): raise ValueError(item+': inconsistent units/NA')
  if a['state']=='applicable' and not units: raise ValueError(item+': applicable requires expected units')
  if any(set(u['ref_ids'])-allrefs for u in units): raise ValueError(item+': unknown reference unit')
 if d['semantic_evidence']['verified'] and d['semantic_evidence']['source']!='human': raise ValueError('semantic verification requires human attestation')
 constraints={'D03':bool(refs),'D05':bool(d['reference']['edges']),'D02':any(o['kind']=='formula' for o in d['reference']['objects']),'D17':any(o['native_bitmap'] for o in d['reference']['objects']),'D18':any(o['kind']=='chart' for o in d['reference']['objects'])}
 for item,present in constraints.items():
  if present and d['applicability'][item]['state']=='na': raise ValueError(item+': NA contradicts reference inventory')
 for e in d['evidence']:
  validate_finding(e,d)
  if e['verified'] and e['source']!='human': raise ValueError('only human attestation may be verified in imported evidence')
 for e in d['edit_evidence']:
  if e['object_id'] not in cands: raise ValueError('unknown edit object')
 from .measurements import validate_image_case,validate_chart_case
 for item,cases in [('D17',d.get('local_images',{}).get('comparisons',[])),('D18',d.get('chart_checks',[]))]:
  ids=[a['unit_id'] for a in cases]
  if len(ids)!=len(set(ids)):raise ValueError('duplicate measurement unit')
  if cases and d['applicability'][item]['state']!='applicable':raise ValueError('measurement contradicts applicability')
  for a in cases:
   if a['unit_id'] not in {u['id'] for u in d['applicability'][item]['units']}:raise ValueError('unknown measurement unit')
   proof=a['identity_evidence'] if item=='D17' else a['evidence']
   if proof['verified'] and proof['source']!='human':raise ValueError('measurement attestation must be human')
   (validate_image_case if item=='D17' else validate_chart_case)(a)
 return d

def validate_finding(f,d):
 a=d['applicability'][f['item_id']]
 if f['unit_id'] not in {u['id'] for u in a['units']}: raise ValueError('unknown unit in finding')
 if f['status']=='na': raise ValueError('NA is determined by task applicability, not response')
 if f['status'] in ['pass','fail'] and not f['evidence']: raise ValueError('decision needs evidence references')
 if f['status']=='pass' and (f['severity']!='none' or f['repair_scope']!='none'): raise ValueError('pass with defect fields')
 if f['status']=='fail' and f['severity']=='none': raise ValueError('failure severity required')

def validate_response(response,d):
 check(response,strict_json(ROOT/'schemas/model-response.schema.json'))
 if response['task_id']!=d['task_id']: raise ValueError('task_id mismatch')
 seen=set()
 for f in response['findings']:
  validate_finding(f,d); key=(f['item_id'],f['unit_id'])
  if key in seen: raise ValueError('duplicate finding')
  seen.add(key)
 return response

def _attested(p): return p['source']=='human' and p['verified'] and bool(p.get('refs',p.get('evidence',[])))

def file_probe(path,confirmed_missing=False):
 if path is None or not path.exists(): return {'status':'fail' if confirmed_missing else 'unknown','reason':'output_confirmed_missing' if confirmed_missing else 'caller_material_missing','verification':'verified' if confirmed_missing else 'unverified'}
 try:
  if path.stat().st_size>10*1024*1024: return dict(status='unknown',reason='parser_limit_10MiB',verification='unverified')
  if path.suffix.lower()!='.svg': return dict(status='unknown',reason='unsupported_format; actual software evidence required',verification='unverified')
  data=path.read_bytes()
  if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper(): return dict(status='unknown',reason='unsafe_XML_declaration_rejected',verification='unverified')
  root=ET.fromstring(data)
  if root.tag.split('}')[-1]!='svg': raise ValueError('not SVG')
  active=any(n.tag.split('}')[-1] in ['script','foreignObject'] or any(k.lower().startswith('on') for k in n.attrib) for n in root.iter())
  return dict(status='unknown',reason='SVG_parseable_proxy_only'+('; active content detected, never executed' if active else ''),verification='proxy')
 except (ET.ParseError,ValueError): return dict(status='fail',reason='confirmed_unparseable_SVG',verification='verified')
 except OSError as e: return dict(status='unknown',reason='environment_read_error:'+type(e).__name__,verification='unverified')

def _normal(objects):
 if not objects:return {}
 x=min(o['bbox'][0] for o in objects); y=min(o['bbox'][1] for o in objects)
 span=max(max(o['bbox'][0]+o['bbox'][2] for o in objects)-x,max(o['bbox'][1]+o['bbox'][3] for o in objects)-y)
 return {o['id']:[(o['bbox'][0]-x)/span,(o['bbox'][1]-y)/span,o['bbox'][2]/span,o['bbox'][3]/span] for o in objects}

def evaluate(d,base=Path('.')):
 validate_input(d);base=Path(base)
 result={'version':'2.0','task_id':d['task_id'],'synthetic':d['synthetic'],'items':[],'issues':[],'proxies':[],'model_reviews':[]}
 trusted=_attested(d['semantic_evidence']) and not d['source_conflict']
 ref={o['id']:o for o in d['reference']['objects']};cand={o['id']:o for o in d['candidate']['objects']};match={x['ref']:x['candidate'] for x in d['matches']};back={v:k for k,v in match.items()}
 proof=d['semantic_evidence']['refs']; rb=_normal(list(ref.values()));cb=_normal([cand[c] for c in match.values()])
 file=d['candidate']['file'];probe=file_probe(base/file if file else None,d['candidate']['output_confirmed_missing']);result['proxies'].append(probe)
 render=d['candidate']['render'];result['proxies'].append({'render_exists':bool(render and (base/render).is_file()),'verification':'proxy','reason':'existence never proves visibility'})
 def add(units,item,uid,status,reason,evidence=None,critical=False,scope='local',root=None,source='rule',verification='verified',related=None):
  units.append(dict(item_id=item,unit_id=uid,status=status,score=None,evidence=evidence or [],reason=reason,primary_category=item,related_categories=related or [],severity=('critical' if critical else 'major') if status=='fail' else 'none',repair_scope=scope if status=='fail' else 'none' if status=='pass' else 'unknown',root_cause=root or f'{item}:{uid}',source=source,verification=verification))
 for r in REGISTRY:
  item=r['id'];a=d['applicability'][item];units=[];metrics={}
  if item=='D16' and probe['status']=='fail':
   a=dict(a,state='applicable',units=a['units'] or [dict(id='file',ref_ids=[],critical=True)])
  if a['state']!='applicable':
   result['items'].append(dict(item_id=item,title=r['title'],status='na' if a['state']=='na' else 'unknown',units=[],metrics={},applicability_reason=a['reason'],coverage=None if a['state']=='na' else 0));continue
  if trusted and item=='D05':
   def sig(e,is_candidate=False):
    s,t=e['start'],e['end']
    if is_candidate:s,t=back.get(s,'extra:'+s),back.get(t,'extra:'+t)
    return (s,t,e['directed']) if e['directed'] else (*sorted([s,t]),False)
   pool=defaultdict(list); explicit={x['ref']:x['candidate'] for x in d['edge_matches']}; ced={e['id']:e for e in d['candidate']['edges']}
   for e in d['candidate']['edges']:
    if e['id'] not in explicit.values():pool[sig(e,True)].append(e)
   correct=missing=incorrect=0
   for e in d['reference']['edges']:
    ev=[f'reference.edge:{e["id"]}']+proof
    if e['id'] in explicit:
     ce=ced[explicit[e['id']]];ok=sig(e)==sig(ce,True);ev.append('candidate.edge:'+ce['id'])
     correct+=int(ok);incorrect+=int(not ok);reason='explicit edge endpoint/direction comparison'
    else:
     available=pool[sig(e)];ok=bool(available)
     if ok:ev.append('candidate.edge:'+available.pop(0)['id']);correct+=1
     else:missing+=1
     reason='multigraph endpoint/direction match' if ok else 'missing edge'
    add(units,item,e['id'],'pass' if ok else 'fail',reason,ev,e['critical'],'relation',root='edge:'+e['id'])
   extra=0
   for es in pool.values():
    for e in es:
     extra+=1;add(units,item,'extra:'+e['id'],'fail','extra/duplicate edge retained',['candidate.edge:'+e['id']]+proof,e['critical'],'relation',root='edge-extra:'+e['id'])
   metrics=dict(correct=correct,missing=missing,extra=extra,incorrect=incorrect)
  elif trusted and item=='D03':
   for rid,o in ref.items():
    c=cand.get(match.get(rid));ok=c is not None and c['identity']==o['identity']
    add(units,item,rid,'pass' if ok else 'fail','identity match' if ok else 'missing or incorrect identity',[f'reference.object:{rid}']+([f'candidate.object:{c["id"]}'] if c else [])+proof,o['critical'],'object',root='object:'+rid)
   for cid in cand.keys()-back.keys():add(units,item,'extra:'+cid,'fail','unmatched extra object',['candidate.object:'+cid]+proof,cand[cid]['critical'],'object',root='object-extra:'+cid)
   metrics=dict(correct=sum(u['status']=='pass' for u in units),missing=sum(rid not in match for rid in ref),extra=len(cand.keys()-back.keys()),incorrect_identity=sum(rid in match and ref[rid]['identity']!=cand[match[rid]]['identity'] for rid in ref))
  else:
   for u in a['units']:
    uid=u['id'];status='unknown';reason='requires rendered semantic or actual editing evidence';ev=[];critical=u['critical'];root=None;scope='local'
    c=cand.get(match.get(uid));o=ref.get(uid)
    if trusted and item in ['D01','D04','D07'] and o:
     if c is None:reason='reference object absent';root='object:'+uid;status='fail';scope='object'
     elif item=='D01':
      if 'text' in o and 'text' in c:status='pass' if o['text']==c['text'] else 'unknown';reason='attested exact transcription match' if status=='pass' else 'different transcription; semantic equivalence needs review'
     elif item=='D04':status='pass' if o['count']==c['count'] else 'fail';reason=f'count {o["count"]} vs {c["count"]}';scope='object';root='count:'+uid
     elif item=='D07':
      expected=match.get(o['parent']) if o['parent'] else None
      status='pass' if c['parent']==expected and (o['parent'] is None or o['parent'] in match) else 'fail';reason='explicit container parent comparison';scope='relation';root='parent:'+uid
     ev=['reference.object:'+uid]+(['candidate.object:'+c['id']] if c else [])+proof
    elif trusted and item=='D08' and match and uid=='bbox_layout':
     deviations={rid:max(abs(v-w) for v,w in zip(rb[rid],cb[cid])) for rid,cid in match.items()}
     metrics={'normalized_bbox_deviations':deviations,'tolerance':d['tolerances']['normalized_bbox']}
     complete=len(match)==len(ref)
     status=('pass' if max(deviations.values())<=d['tolerances']['normalized_bbox'] else 'fail') if complete else 'unknown'
     reason='matched bbox layout, isotropic normalization; scope is configured geometry only';ev=proof+list(match);scope='global'
    elif item=='D13' and o and c:
     if not o['editable_required']:status='na';reason='native material exempt from content editing'
     else:
      edits=[x for x in d['edit_evidence'] if x['object_id']==c['id'] and _attested(x)]
      if edits:
       ok=all(x['success'] and x['changed_actual_content'] for x in edits);status='pass' if ok else 'fail';reason='attested actual content edit';ev=[s for x in edits for s in x['evidence']];scope='object'
    elif trusted and item=='D15' and d['candidate']['whole_page_bitmap'] and any(x['editable_required'] and not x['native_bitmap'] for x in ref.values()):
     status='fail';reason='confirmed whole-page raster includes editable structures';ev=proof+['candidate.whole_page_bitmap'];scope='global';root='whole-page-raster';critical=True
    elif item=='D17':
     from .measurements import measure_local_image
     config=d.get('local_images',{'enabled':False,'comparisons':[]})
     case=next((x for x in config['comparisons'] if x['unit_id']==uid),None)
     measurement=measure_local_image(case,base,config['enabled']) if case and not d['source_conflict'] else dict(state='unknown' if config['enabled'] else 'disabled',computed=False,reason='no_correspondence_or_source_conflict' if config['enabled'] else 'opt_in_disabled')
     metrics.setdefault('local_images',{})[uid]=measurement
     reason='local image metric is auxiliary; identity/crop/key details still need review; '+measurement.get('reason',measurement['state'])
     if measurement.get('computed'):ev=case['identity_evidence']['refs']+[case['reference_file'],case['candidate_file']]
    elif item=='D18':
     from .measurements import compare_chart
     case=next((x for x in d.get('chart_checks',[]) if x['unit_id']==uid),None)
     measurement=compare_chart(case) if case and not d['source_conflict'] else dict(data_status='unknown',computed=False,reason='underlying_data_missing_or_source_conflict')
     metrics.setdefault('chart_data',{})[uid]=measurement
     reason=measurement['reason']+'; rendered chart properties remain unverified'
     if measurement.get('computed'):
      ev=case['evidence']['refs']+['chart_checks:'+uid+':reference','chart_checks:'+uid+':candidate']
      if measurement['data_status']=='fail':
       status='fail';root='chart-data:'+uid;scope='object';reason=f'{len(measurement["errors"])} explicit data/metadata errors; rendered properties still require review'
       ev += [f'chart_checks:{uid}:errors[{i}]' for i in range(len(measurement['errors']))]
    elif item=='D16':
     if probe['status']=='fail':status='fail';reason=probe['reason'];ev=[file or 'confirmed missing output'];critical=True;scope='global';root='file-failure'
     else:
      ops=[x for x in d['operation_evidence'] if _attested(x) and x['software']==d['display']['software']]
      if ops:
       ok=all(all(x[k] for k in ['opened','modified','saved','reopened','preserved']) for x in ops);status='pass' if ok else 'fail';reason='attested target-software operation chain';ev=[s for x in ops for s in x['evidence']];critical=not ok;scope='global'
      else:reason=probe['reason']+'; no verified operation chain'
    add(units,item,uid,status,reason,ev,critical,scope,root,verification='verified' if status in ['pass','fail','na'] else 'unverified')
  # Rule inventories must not silently omit declared units; declarations cannot hide reference errors.
  known={u['unit_id'] for u in units}
  for u in a['units']:
   if u['id'] not in known:add(units,item,u['id'],'unknown','declared unit has no rule evaluation',verification='unverified')
  for h in d['evidence']:
   if h['item_id']!=item:continue
   target=next(x for x in units if x['unit_id']==h['unit_id'])
   if _attested(h):
    if target['status'] in ['pass','fail'] and target['status']!=h['status']:
     target.update(reason='conflicting rule/human evidence; conservative failure retained pending adjudication',verification='conflict',evidence=target['evidence']+h['evidence'])
     if target['status']=='pass':
      target.update({k:h[k] for k in ['status','severity','repair_scope','root_cause']})
    elif target['status']=='unknown':
     target.update({k:h[k] for k in ['status','evidence','reason','severity','repair_scope','root_cause','source']});target['verification']='verified'
   else:result['model_reviews'].append(h)
  if item=='D13':
   grouped=defaultdict(lambda:{'required':0,'verified_editable':0})
   for u in units:
    o=ref.get(u['unit_id'])
    if o and o['editable_required']:
     grouped[o['kind']]['required']+=1;grouped[o['kind']]['verified_editable']+=int(u['status']=='pass')
   metrics['editable_by_type']={k:dict(v,ratio=v['verified_editable']/v['required']) for k,v in grouped.items()}
  result['items'].append(dict(item_id=item,title=r['title'],status='unknown',units=units,metrics=metrics,applicability_reason=a['reason'],coverage=0))
 return summarize(result,d)

def summarize(result,d):
 issues={};counts=Counter();resolved=total=0
 for item in result['items']:
  us=[u for u in item['units'] if u['status']!='na']
  if item['status']=='na' and not us:counts['na']+=1;continue
  states=[u['status'] for u in us]
  item['status']='fail' if 'fail' in states else 'unknown' if 'unknown' in states or not states else 'pass'
  item['coverage']=sum(s in ['pass','fail'] for s in states)/len(states) if states else 0
  item['distribution']=dict(Counter(states));counts[item['status']]+=1;total+=len(us);resolved+=sum(s in ['pass','fail'] for s in states)
  for u in us:
   if u['status']!='fail':continue
   key=u['root_cause'];iid='I-'+hashlib.sha256(key.encode()).hexdigest()[:10];u['issue_id']=iid
   if key not in issues:issues[key]=dict(issue_id=iid,root_cause=key,primary_category=item['item_id'],related_categories=[],severity=u['severity'],repair_scope=u['repair_scope'],evidence=[],units=[])
   p=issues[key]
   if item['item_id']!=p['primary_category'] and item['item_id'] not in p['related_categories']:p['related_categories'].append(item['item_id'])
   if ['none','minor','major','critical'].index(u['severity'])>['none','minor','major','critical'].index(p['severity']):p['severity']=u['severity']
   p['evidence']=list(dict.fromkeys(p['evidence']+u['evidence']));p['units'].append(item['item_id']+':'+u['unit_id'])
 for item in result['items']:
  for u in item['units']:
   u['coverage']=None if u['status']=='na' else int(u['status'] in ['pass','fail']);u['applicability']='na' if u['status']=='na' else 'applicable'
   if u.get('issue_id'):
    p=issues[u['root_cause']];u['related_categories']=[x for x in [p['primary_category']]+p['related_categories'] if x!=u['item_id']]
 result['issues']=list(issues.values());result['coverage']=dict(resolved=resolved,total=total,ratio=resolved/total if total else 0,item_status_counts=dict(counts))
 result['usability']='pending_reference' if d['source_conflict'] else 'unusable' if any(p['severity']=='critical' for p in issues.values()) else 'needs_revision' if issues else 'pending_verification' if counts['unknown'] else 'usable'
 result['aggregation_note']='No ordinal average or fixed penalties. Unknown units remain in coverage denominator; NA excluded. Critical failures gate usability.'
 return result

def prepare_request(d,base=Path('.')):
 validate_input(d);base=Path(base)
 attachments=[]
 local_files=[(f'local_image:{x["unit_id"]}:{side}',x[side+'_file']) for x in d.get('local_images',{}).get('comparisons',[]) for side in ['reference','candidate']]
 for role,path in [('source',d['source']['image']),('method_text',d['source']['method_text']),('candidate_render',d['candidate']['render']),('candidate_structure',d['candidate']['file'])]+local_files:
  if path:
   p=base/path; attachments.append(dict(role=role,path=str(p.resolve()),exists=p.is_file(),sha256=hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and p.stat().st_size<=10*1024*1024 else None))
 return dict(task_id=d['task_id'],mode='prepared_only_no_API_call',system=(ROOT/'prompts/system.md').read_text(),items=[dict(item_id=r['id'],prompt=(ROOT/f'prompts/{r["id"]}.md').read_text(),applicability=d['applicability'][r['id']]) for r in REGISTRY],final_review=(ROOT/'prompts/final_review.md').read_text(),input=d,attachments=attachments,response_schema=strict_json(ROOT/'schemas/model-response.schema.json'))

def merge_response(result,response,d):
 validate_response(response,d);out=copy.deepcopy(result)
 for f in response['findings']:
  record=dict(f,source=response['source'],verification='unverified' if response['source']=='model' else 'synthetic_mock')
  out['model_reviews'].append(record)
 # Provider JSON validity does not prove semantics. Human reviewed findings enter input.evidence.
 return summarize(out,d)
