"""Versioned two-initial/four-parallel-branch execution; three DS calls per branch."""
import argparse,concurrent.futures,fcntl,json,os,time,uuid,threading,traceback,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timezone
import run_ablation as r,live_api as api,budget,bounded_trace as trace,joint_detector_adapter,bounded_native_profile,planner_execution_evidence,planner_packet_transport,bounded_plan_binding,bounded_verifier_binding
ROOT=Path(__file__).resolve().parent.parent
CONTROL=ROOT/'output/two-stage-20261030'
OLD=ROOT/'output/formal-ablation-80-capped/576e08ac-eb41-4e01-a33d-fa031846ec8a'
RUN_UUID=OLD.name
CFG=ROOT/'formal-ablation-runner/config-two-stage.json'
BRANCHES={'S0C0':1,'S0C1':2,'S1C0':3,'S1C1':4}
STOP=threading.Event()
BARRIER=None
def now():return datetime.now(timezone.utc).isoformat()
def semantic_view(document):
 from collections import Counter
 view={k:v for k,v in document.items() if k in ('format','status','revision','evidence_hashes','proposals')}
 limits=document.get('coverage_limits',[])
 view['coverage_limits']=[item for item in limits if not item.get('target_ids')]
 diagnostics=[item for item in limits if item.get('target_ids')]
 view['nonproposal_diagnostic_summary']={'count':len(diagnostics),'by_reason':dict(Counter(item.get('reason','unknown') for item in diagnostics)),'policy':'Per-object nonproposal diagnostics are internal trace, not defect or coverage certification. No actual proposal is removed. Independently judge original/current visuals.'}
 return view
def clean_brief(text):
 return '\n'.join(line for line in text.splitlines() if not line.startswith(('Allowed neutral inputs:','Allowed current stage inputs:','Read every listed enabled authoritative source and supplied method manual:')))
def index_svg(path):
 result=[];excluded=0
 for node in ET.parse(path).getroot().iter():
  tag=node.tag.rsplit('}',1)[-1];attrs=node.attrib;ident=attrs.get('id')
  if not ident:continue
  if tag=='path' and attrs.get('fill','').startswith('rgb(') and attrs.get('stroke')==attrs.get('fill'):
   excluded+=1;continue
  if tag not in ('text','tspan','g','rect','line','polyline','polygon','circle','ellipse','image','path'):continue
  fields={k:v for k,v in attrs.items() if k not in ('d','points') and not k.endswith('href')}
  result.append({'id':ident,'tag':tag,'attributes':fields,'text':''.join(node.itertext()) if tag in ('text','tspan') else None})
 return {'objects':result,'raster_trace_leaf_geometry_not_repeated':excluded,'policy':'Original and current rendered pixels remain attached. Raster tracing leaves are not semantic repair units; their parent groups and actual SVG remain available to local native execution.'}
def bind_current_representation(value,root):
 import current_representation_binding
 return current_representation_binding.bind(value,r.read(root/'runs/run1/state.json'),r.read(root/'runs/run1/round-1/candidate.json'))

def bind_saved_verifier_metadata(value,root,folder,branch_number):
 import verifier_request_proof
 snapshot=r.read(root/'runs/run1/round-1/candidate.json')
 if not snapshot.get('connector_paint'):return value,[]
 packet=r.read(root/'runs/run1/round-1/connector-paint/packet.json');ctx=r.read(root/'runs/run1/jobs/verifier-1/connector-concern-context.json')
 expected={**snapshot['connector_paint'],'candidate_receipt_sha256':ctx['candidate_receipt_sha256'],**{k:packet[k] for k in ('source_sha256','before','candidate','field_status')},'use':'attention_hint_only'}
 if value.get('connector_paint_ack')==expected:return value,[]
 stage=f'B{branch_number}3';recovery=folder/'stage-recoveries.json'
 if recovery.exists() and stage in r.read(recovery):stage=r.read(recovery)[stage]['recovery_stage']
 paths=list((CONTROL/'trace').glob(f'*{CURRENT_ROW["sample_id"]}-{stage}.json'))
 if len(paths)!=1:raise ValueError('exact verifier trace required')
 proof=verifier_request_proof.build(folder,r.read(paths[0]),snapshot)
 trace.write(folder/'verifier-request-binding-proof.json',proof)
 return bounded_verifier_binding.bind_host_ack(value,proof)

def planner_wire(data):
 original_digest=r.digest(data)
 source_svg=data.get('native_execution_evidence',{}).get('source_files',{}).get('svg',{}).get('path',data.get('runtime_svg_path',''))
 root_prefix=source_svg.split('/runs/run1/')[0]+'/' if '/runs/run1/' in source_svg else ''
 line_view=planner_packet_transport.encode_lines(data)
 if len(json.dumps(line_view,ensure_ascii=False))<len(json.dumps(data,ensure_ascii=False)):data=line_view
 templated=planner_packet_transport.encode(data)
 if len(json.dumps(templated,ensure_ascii=False))<len(json.dumps(data,ensure_ascii=False)):data=templated
 path_views,path_aliases=api.exact_string_prefix_views([data]);data=path_views[0]
 views,shared=api.exact_json_views([data]);short,table=planner_packet_transport.compact_refs(views[0],shared);views,keys=api.exact_json_key_views([short,table]);wire={'format':'lossless-planner-packet-v2','decode':'First replace every object key using key_aliases. In packet/shared_values recursively replace any sole $r entry (zero-based integer) with shared_values[its value], until none remain. Then recursively replace any string prefix from absolute_path_aliases by its full path. Finally apply field_templates decoding and then line_aliases decoding if present. Every original field/value is preserved; native originals are unchanged.','absolute_path_aliases':path_aliases,'key_aliases':keys,'packet':views[0],'shared_values':views[1],'original_json_sha256':original_digest}
 original=json.dumps({'format':'lossless-path-prefix-packet-v1','decode':'Replace every matching string prefix recursively using absolute_path_aliases, then apply field_templates and line_aliases decoding if present.','absolute_path_aliases':path_aliases,'packet':data} if path_aliases else data,ensure_ascii=False,separators=(',',':'));encoded=json.dumps(wire,ensure_ascii=False,separators=(',',':'))
 selected=encoded if len(encoded)<len(original) else original
 if root_prefix:
  projected,notice=api.exact_text_root_views([{'type':'text','text':selected}],root_prefix)
  if notice and len(projected[0]['text'])+len(notice['text'])<len(selected):return notice['text']+'\n'+projected[0]['text']
 return selected
def output_contract(data,kind):
 snapshot=data['snapshot']
 if kind=='joint':
  task='Return exactly {"main":<complete detector report>,"semantic":<complete detector report>}. Both have revision,evidence_hashes,examined_regions,unresolved_regions,issues,programs:[]. Semantic additionally has proposal_reviews, exactly partitioning the actual proposal IDs, even when empty. Never output the input transport packet.'
 elif kind in ('planner','review_planner'):
  task='Return one planner JSON object with revision,evidence_hashes,issue_ids,programs,unresolved_reasons. issue_ids references the entire frozen active finding queue; do not retype or reclassify finding objects. Supplemental review+plan may use the explicitly requested outer wrapper in the user message. This is the single repair attempt before verification: implement safely source-supported repairs now. Use actual image evidence for parameters, never infer them from names or boxes alone. Return specific unresolved reasons for unsupported repairs; do not merely repeat the finding list.'
 else:
  task='Return one VERIFIER REPORT JSON object, never an input/transport packet: revision,evidence_hashes,examined_regions,unresolved_regions,resolved_ids,unresolved_ids,not_required,new_required_findings,new_uncertain_findings,protected_regressions, plus applicable uncertainty/pending/connector reviews required by the supplied native contracts. Supply actual post-render judgments; unchanged SVG cannot resolve findings.'
 if kind=='review_planner':task='Return EXACTLY one top-level object with keys proposal_reviews, new_semantic_issues, plan. proposal_reviews MUST contain one actual source/current judgment for EVERY supplied proposal ID. new_semantic_issues MUST be an array (empty only when none). plan MUST contain the ordinary planner object as a NESTED value, not at top level. '+task.replace('Return one planner JSON object','The NESTED plan is a planner JSON object')
 if kind=='verifier':
  required=[x['id'] for x in data.get('active_required',[])];uncertain=[x['id'] for x in data.get('active_uncertain',[])]
  task+=' Confirmed-only partition: resolved_ids + unresolved_ids + not_required[].id must contain exactly these IDs once: '+json.dumps(required)+'. Never put uncertainty IDs in that partition; assess them only in uncertainty_reviews. Uncertain IDs: '+json.dumps(uncertain)+'.'
  if not data.get('connector_paint_ack_required_exact'):task+=' No connector observer was supplied for this capability: omit connector_paint_ack and all connector fields entirely; do not write a not_supplied object.'
 return {'role':'system','content':task+' Decode input aliases ONLY to read evidence, NOT as the requested output. No tools or followup calls. Output native schema without transport aliases. Copy the following EXACT_SNAPSHOT revision and key/value hash associations verbatim; never shift values between keys: '+json.dumps(snapshot,separators=(',',':'))}

def wire_payload(data):
 # The exact map is explicitly supplied once, uncompressed, in the system header.
 return {**data,'snapshot':{'source':'EXACT_SNAPSHOT in the system message; copy its exact key/value map'}}
def context(root,roles,round_number=None):
 state=r.read(root/'runs/run1/state.json');candidate=None
 if roles==['verifier']:candidate=r.read(root/f'runs/run1/round-{round_number}/candidate.json')
 snap=candidate or state;checkpoint=Path(snap.get('candidate_folder',root/'runs/run1/checkpoint'));pack=r.read(checkpoint/'pack/pack.json')
 prompts=[]
 for role in roles:
  tag=role+(f'-{round_number}' if round_number else '');job=root/'runs/run1/jobs'/tag;prompt=job/'dispatch-prompt.md'
  if not prompt.exists():
   args=[str(root/'brief.py'),'run1',role,'--root',str(root)]
   if round_number:args+=['--round',str(round_number)]
   api._keyless([CFG_NATIVE,'-B',*args],CURRENT_CONFIG)
  prompts.append({'role':role,'instructions':clean_brief(prompt.read_text())})
 if len(prompts)==2:prompts[1]['instructions']=planner_packet_transport.encode_shared_lines(prompts[1]['instructions'],prompts[0]['instructions'])
 data={'roles':prompts,'snapshot':{k:snap.get(k) for k in ('revision','evidence_hashes')},'capabilities':state['capabilities'],'active_required':state.get('required',[]),'active_uncertain':state.get('uncertain',[]),'pending_observations':state.get('pending_observations',[]),'connector_visual_concerns':state.get('connector_visual_concerns',[]),'pack':pack,'current_object_index':index_svg(checkpoint/'current.svg'),'runtime_svg_path':str(checkpoint/'current.svg')}
 if 'semantic' in roles:
  path=root/'inputs/analysis/proposals.json'
  if path.exists():
   data['semantic_observation_proposals']=semantic_view(r.read(path))
   data['observation_review_contract']=review_contract(root)
   data['mandatory_review_schema']='semantic.proposal_reviews is mandatory: exactly one review per actual proposal ID; decision required|uncertain|qualified; qualified links []; required/uncertain link actual same-report semantic finding raw IDs. Return all original role report fields plus this array.'
 if roles==['planner']:
  data['native_execution_evidence']=planner_execution_evidence.build(root,checkpoint,state)
  data['public_program_contract']=(root/'docs/native-contract.md').read_text()
  data['planner_issues_must_be_exact_unchanged_objects']='Return issue_ids listing every id from active_required + active_uncertain. Do not echo or rewrite issue objects: the host binds these references to exact frozen findings. All program issue_ids must use these exact ids.'
  tracked=state.get('required',[])+state.get('uncertain',[]);relevant={value for issue in tracked for key in ('target_ids','neighbor_ids') for value in issue.get(key,[])}|{issue['container_id'] for issue in tracked if issue.get('container_id')}
  data['current_object_index']['objects']=[obj for obj in data['current_object_index']['objects'] if obj['id'] in relevant or obj['tag']=='g']
  data['current_object_index']['scope']='All tracked targets, neighbors, containers and document groups. Native local code can inspect the complete actual runtime SVG; unrelated leaf indices are not repeated.'
  # Exact target/neighbor/container geometry and ancestor topology already include these IDs.
  # Do not serialize a second, less complete attribute-only index of the same objects.
  data.pop('current_object_index',None)
  data['object_index_location']='native_execution_evidence.svg_objects (exact attributes/parent topology) and native_measured_bounds'
  for file in ['method-pack.json','native-contract.json']:
   p=root/'inputs'/file
   if p.exists():
    document=r.read(p)
    data[file]={k:v for k,v in document.items() if k not in ('sources','native_sources','common_quality','common_conditional_policy','profile','full_contract')}
    if file=='method-pack.json':data[file]=planner_execution_evidence.scope_method_pack(data[file],state);data[file].pop('lean_inspection_prompt',None)
  sam_catalog=root/'inputs/sam.json'
  if state['capabilities']['sam'] and sam_catalog.exists():data['neutral_sam_catalog']=r.read(sam_catalog)
 if candidate:
  data['candidate_execution']={k:v for k,v in candidate.items() if k in ('before_revision','before_evidence_hashes','connector_paint')}
  data['candidate_execution']['svg_changed']=candidate['revision']!=candidate['before_revision']
  relevant_attributes={'x','y','width','height','cx','cy','rx','ry','r','x1','y1','x2','y2','transform','font-size','font-family','fill','stroke','stroke-width','text-anchor'}
  for obj in data['current_object_index']['objects']:obj['attributes']={k:v for k,v in obj['attributes'].items() if k in relevant_attributes}
  data['current_object_index']['attribute_scope']='All listed object IDs/text and geometric/font/paint attributes. Native bookkeeping/style serialization is not repeated; actual rendered images remain authoritative and unsupported details remain unknown.'
  data['candidate_program_outcomes']=[{k:v for k,v in item.items() if k in ('program_id','issue_ids','status','route','phase','rcd_predescription','convergence','visual_acceptance')} for item in candidate.get('native_result',{}).get('rcd',[])]
  necessity=root/f'runs/run1/round-{round_number}/necessity-review-requests.json'
  if necessity.exists():data['necessity_review_requests']=r.read(necessity)
  plan=root/f'runs/run1/round-{round_number}/plan.json'
  if plan.exists():data['executed_plan']=r.read(plan)
  observer=root/f'runs/run1/round-{round_number}/connector-paint/packet.json'
  concern_context=root/f'runs/run1/jobs/verifier-{round_number}/connector-concern-context.json'
  if observer.exists():
   packet=r.read(observer);observer_context=r.read(concern_context)
   data['connector_paint_packet']=packet;data['connector_concern_context']=observer_context
   data['connector_paint_ack_required_exact']={**candidate['connector_paint'],'candidate_receipt_sha256':observer_context['candidate_receipt_sha256'],**{k:packet[k] for k in ('source_sha256','before','candidate','field_status')},'use':'attention_hint_only'}
   contract=root/'docs/connector-paint-observation-contract.md'
   if contract.exists():
    text=contract.read_text()
    if '```json\n' in text:
     before,rest=text.split('```json\n',1);schema,after=rest.split('```',1);text=before+'```json\n'+json.dumps(json.loads(schema),separators=(',',':'))+'\n```'+after
    data['connector_contract']=text
 images=[Path(CURRENT_ROW['source_image_path']),checkpoint/'current.png']+[Path(frame['pair']) for frame in pack['frames']]
 if candidate:images.append(root/'runs/run1/checkpoint/current.png')
 unique={}
 for image in images:unique.setdefault(r.sha(image),image)
 content=[{'type':'text','text':'Execute exactly the assigned native role duties below. Return one complete JSON object, no prose or tool calls. No formal evaluation/scoring is requested. The packet deliberately excludes historical logs, duplicated source-code dumps and internal execution traces. Do not fabricate identifiers or hashes. All native contracts still apply. '+('Return {"main":<main report>,"semantic":<semantic report>}. These are two role reports in one JOINT detector request; not independent model calls.' if len(roles)>1 else 'Return the exact '+roles[0]+' schema.'+(' For planner return issue_ids instead of repeating issues; retain revision, evidence_hashes, programs and unresolved_reasons.' if roles==['planner'] else ''))+'\n'+planner_wire(wire_payload(data))}]
 for path in unique.values():content += [{'type':'text','text':'Actual image '+str(path)},* [item['content'] for item in api.inventory([path])]]
 return [output_contract(data,'joint' if len(roles)>1 else roles[0]),{'role':'user','content':content}],data
# Native process paths/config are per-process immutable. Per-thread source row is passed explicitly below.
CURRENT_CONFIG={};CFG_NATIVE='';CURRENT_ROW={}
def review_contract(root):
 text=(root/'docs/observation-contract.md').read_text()
 implementation=('Main and semantic may each call flow.py check-report','The local check executes no model/provider call itself.','Actual V4 preparation records its immutable preparation-start marker','The local build writes a new inputs/analysis directory only.','The immutable V4 manifest activates semantic proposal_reviews.','The existing current and all-text-hidden arrays provide white-composited','Every group always projects component detail')
 return 'Model-facing review duties; native preparation/check/cost implementation paragraphs are not repeated. Numeric contrast values and 2.0 are observational settings, never repair thresholds. Original native document/guards remain unchanged.\n\n'+'\n\n'.join(paragraph for paragraph in text.split('\n\n') if not paragraph.startswith(implementation))
def review_plan_context(root,original):
 messages,data=context(root,['planner'],1);reports,_=joint_detector_adapter.normalize(original,None)
 issues=[]
 for role,report in reports.items():
  for issue in report['issues']:issues.append({**issue,'source_issue_id':issue['id'],'id':role+':'+issue['id'],'source_role':role})
 # Supplemental detection may discover additional categories: preserve all original category cards.
 data['method-pack.json']['cards']=r.read(root/'inputs/method-pack.json')['cards'];data['method-pack.json'].pop('repair_card_scope',None)
 proposal_file=root/'inputs/analysis/proposals.json';proposals=semantic_view(r.read(proposal_file)) if proposal_file.exists() else {'proposals':[]}
 data.update(joint_detector_sources_preserved_by_host={role:{'path':str(root/'runs/run1/detection'/role/'raw.json'),'sha256':r.sha(root/'runs/run1/detection'/role/'raw.json')} for role in reports},semantic_observation_proposals=proposals,active_required=[x for x in issues if x['decision']=='confirmed'],active_uncertain=[x for x in issues if x['decision']=='uncertain'])
 data['method-pack.json']=planner_execution_evidence.scope_review_cards(data['method-pack.json'],{'required':data['active_required'],'uncertain':data['active_uncertain']})
 relevant={value for issue in issues for key in ('target_ids','neighbor_ids') for value in issue.get(key,[])}|{value for proposal in proposals['proposals'] for value in proposal.get('target_ids',[])}
 data['native_execution_evidence']=planner_execution_evidence.build(root,root/'runs/run1/checkpoint',{'required':data['active_required'],'uncertain':data['active_uncertain'],'capabilities':data['capabilities']},additional_ids={value for proposal in proposals['proposals'] for value in proposal.get('target_ids',[])})
 data.pop('object_index_location',None)
 messages[-1]['content'][0]['text']='This is the SECOND and final repair-planning call. Complete omitted proposal reviews and plan in this same call. Return {"proposal_reviews":[],"new_semantic_issues":[],"plan":{"revision":"exact snapshot","evidence_hashes":{},"issue_ids":[],"programs":[],"unresolved_reasons":[]}}. Reviews use required|uncertain|qualified, source_evidence,current_evidence,necessity_reason and raw same-semantic-report issue_ids; qualified links []. Preserve frozen findings in active_required/active_uncertain. Plan issue_ids reference every active finding; genuinely new semantic findings gain semantic: prefix. Apply complete native finding schema and source/current necessity rules from roles[0].instructions. Never invent repairs or passed judgments. No further tools, API followups or formal scoring.\n'+planner_wire({**wire_payload(data),'observation_review_contract':review_contract(root),'supplemental_review_scope':'B1 findings/coverage are frozen. Complete missing proposal reviews and plan repairs only; all shared native finding/necessity contracts apply.'})
 messages[0]=output_contract(data,'review_planner')
 ids={node.get('id') for node in ET.parse(root/'runs/run1/checkpoint/current.svg').getroot().iter() if node.get('id')};localization=joint_detector_adapter.localization_errors(original,ids)
 if localization:
  geometry=planner_execution_evidence.build(root,root/'runs/run1/checkpoint',{'required':data['active_required'],'uncertain':data['active_uncertain'],'capabilities':data['capabilities']},additional_ids=ids)
  contract={'unbound_original_findings':localization,'binding_schema':{'role':'main or semantic from the exact original report','issue_id':'exact original raw issue ID','target_ids':['actual existing SVG IDs only'],'neighbor_ids':[],'container_id':None,'evidence':'actual visual/topology evidence for this localization'},'duties':'Return an additional top-level finding_bindings array with exactly one binding for each unbound original finding. Preserve original finding decisions, descriptions and evidence; correct only current object localization. Use actual SVG/image evidence, not invented IDs. Plan in the same call using the corrected real targets. Preserve all source findings and complete proposal reviews. No extra API calls.'}
  messages[0]['content']='Finding_bindings are ONLY the explicitly requested corrections of unbound original object IDs; actual visual decisions/evidence remain frozen. '+messages[0]['content'].replace('Return EXACTLY one top-level object with keys proposal_reviews, new_semantic_issues, plan.','Return EXACTLY one top-level object with keys proposal_reviews, new_semantic_issues, plan, finding_bindings.')
  messages[-1]['content'][0]['text']=messages[-1]['content'][0]['text'].replace('Return {"proposal_reviews":[],"new_semantic_issues":[],"plan":','Return {"finding_bindings":[],"proposal_reviews":[],"new_semantic_issues":[],"plan":')
  messages[-1]['content'].insert(0,{'type':'text','text':'Same second call: correct exact object localization and plan; original detector findings remain frozen.\n'+planner_wire({'finding_binding_contract':contract,'actual_current_geometry':geometry})})
 return messages,data

def call_json(config,lease,folder,stage,suffix,messages):
 recovery_path=folder/'stage-recoveries.json'
 if recovery_path.exists() and stage in r.read(recovery_path):
  recovery=r.read(recovery_path)[stage];stage=recovery['recovery_stage'];config={**config,'stage_recovery':recovery}
 label=trace.name(config['image_index'],config['current_sample_id'],stage);receipt=CONTROL/'trace'/(label+'.json')
 if receipt.exists():
  record=r.read(receipt);raw=trace.cached(receipt,record['body_sha256'])
 else:
  if STOP.is_set():raise RuntimeError('bounded run stopped before HTTP')
  cfg={**config,'business_stage':stage};raw=api.request(cfg,'deepseek',api.slot(cfg,suffix),messages,lease,folder/'api')
 final,calls,_=api.extract(raw,'chat_completions')
 if calls:raise ValueError('bounded stage requested tool followup; no additional HTTP permitted')
 value,parse_audit=trace.parse_model_object(final)
 if parse_audit:trace.write(folder/(stage+'-parse-audit.json'),{'response_file':str(CONTROL/'responses'/(label+'.json')),'response_sha256':r.sha(CONTROL/'responses'/(label+'.json')),'content_sha256':__import__('hashlib').sha256(final.encode()).hexdigest(),'parse':parse_audit,'provider_requests_added':0})
 out=folder/(stage+'-model.json')
 if out.exists() and r.sha(out)!=r.digest(value):
  if r.read(out)!=value:raise ValueError('saved model stage result changed')
 if not out.exists():trace.write(out,value)
 if not {'main','semantic'}<=set(value) and (folder/'api').exists() and not config.get('_mock_send'):
  import model_envelope_binding
  value,envelope_proof=model_envelope_binding.bind(folder,stage,value);trace.write(folder/(stage+'-machine-envelope-proof.json'),envelope_proof)
 return value,out

def reuse_first(row,index,sam,c):
 s=int(row['sam']);stage='A2' if s else 'A1';folder=CONTROL/row['sample_id']/stage;folder.mkdir(parents=True,exist_ok=True)
 source_row={**row,'external_code':False,'cell':f'S{s}C0'};saved=folder/'result.json'
 if saved.exists():
  import initial_syntax_recovery
  return initial_syntax_recovery.close_redundant_asset_aliases(r.reusable_first(saved,source_row),c,saved)
 candidates=list((OLD/row['sample_id']/f'S{s}C0').glob('first/result.json'))+list((OLD/'recovery-20261029'/row['sample_id']/f'S{s}C0').glob('*/first/result.json'))
 for receipt in candidates:
  try:first=r.reusable_first(receipt,source_row)
  except (ValueError,OSError,KeyError):continue
  ledger=r.read(c['ledger_path']);rows=[v for v in ledger['requests'].values() if v.get('run_uuid')==RUN_UUID and v.get('sample_id')==row['sample_id'] and v.get('cell')==f'S{s}C0' and v.get('provider')=='openai' and v.get('formal_state')=='settled' and v.get('body_sha256')]
  for financial in rows:
   raws=list(OLD.rglob(financial['request_id']+'.response.json'))
   if not raws:continue
   # Match the actual initial artifact receipt location to its original ledger source.
   raw=r.read(raws[0])['response']
   actual_responses=[r.read(path).get('raw') for path in (receipt.parent/'api').glob('*-response.json')]
   if not any(value is not None and r.digest(value)==r.digest(raw) for value in actual_responses):continue
   label=trace.name(index,row['sample_id'],stage)
   response=CONTROL/'responses'/(label+'.json');trace.write(response,raw)
   record={'name':label,'stage':stage,'sample_id':row['sample_id'],'provider':'openai','model':'gpt-5.5','status':'completed','reused':True,'source_receipt':str(receipt),'source_receipt_sha256':r.sha(receipt),'request_id':financial['request_id'],'started_utc':datetime.fromtimestamp(financial['attempted_at'],timezone.utc).isoformat(),'ended_utc':datetime.fromtimestamp(financial['settled_at'],timezone.utc).isoformat(),'elapsed_seconds':financial['settled_at']-financial['attempted_at'],'response_file':str(response),'response_sha256':r.sha(response),'new_estimated_usd':0,**trace.usage(raw,c['providers']['openai'])}
   trace.write(CONTROL/'trace'/(label+'.json'),record);trace.write(saved,first);trace.write(folder/'shared-initial-provenance.json',{'receipt':str(receipt),'receipt_sha256':r.sha(receipt),'generation_policy':{'version':'capabilities-v1','sam':bool(s),'code_methods':False},'shared_downstream_cells':[f'S{s}C0',f'S{s}C1'],'initial_svg_sha256':r.sha(first['stage0_scene'])});trace.render(CONTROL);return first
 namespace=f'twostage-v1-a{s+1}';lease=budget.reserve_recovery(c,RUN_UUID,[source_row],folder,namespace)
 cfg={**c,'current_sample_id':row['sample_id'],'current_cell':f'S{s}C0','financial_slot_prefix':namespace,'trace_root':str(CONTROL),'image_index':index,'business_stage':stage}
 try:
  first=api.run_first({'output_root':str(folder/'first'),'adapter':c['first_stage_adapter_root'],'native_source_root':c['native_source_root'],'runtime_json':c['runtime_json'],'original_png':row['source_image_path'],'capabilities':{'version':'capabilities-v1','sam':bool(s),'code_methods':False},**({'sam_catalog':sam} if s else {})},cfg,lease)
 except RuntimeError:
  stderr=folder/'first/native-stderr.log'
  if not stderr.exists() or not any(error in stderr.read_text() for error in ('xml.etree.ElementTree.ParseError:','ValueError: unknown kept object','ValueError: invalid or duplicate replacement target:','ValueError: replacement would delete protected object')):raise
  import initial_syntax_recovery
  first=initial_syntax_recovery.recover(folder/'first',c)
 trace.write(saved,first);lease.close()
 import initial_syntax_recovery
 return initial_syntax_recovery.close_redundant_asset_aliases(first,c,saved)

def branch(row,index,first,c,bindings):
 cell=row['cell'];branch_number=BRANCHES[cell];folder=CONTROL/row['sample_id']/cell;folder.mkdir(parents=True,exist_ok=True);started=time.monotonic();root=Path(r.read(folder/'native-root.json')['root']) if (folder/'native-root.json').exists() else folder/'cell';namespace_file=folder/'financial-namespace.json';namespace=r.read(namespace_file)['namespace'] if namespace_file.exists() else f'twostage-v1-b{branch_number}'
 if not namespace_file.exists():trace.write(namespace_file,{'namespace':namespace})
 identity={'source_sha256':row['source_image_sha256'],'initial_sha256':r.sha(first['stage0_scene']),'policy':{'version':'capabilities-v1','sam':row['sam'],'code_methods':row['external_code']},'bindings':bindings,'protocol':'bounded-two-stage-v1'}
 marker=folder/'identity.json'
 if marker.exists() and r.read(marker)!=identity:
  import two_stage_identity_migration
  two_stage_identity_migration.verify(marker,identity,CONTROL)
 if not marker.exists():trace.write(marker,identity)
 if (folder/'result.json').exists():
  record=r.read(folder/'result.json')
  if record.get('status')=='complete' and r.sha(record['final_svg'])==record['final_svg_sha256'] and r.sha(record['final_png'])==record['final_png_sha256']:return record
  raise ValueError('old failed branch requires offline diagnosis, not replay')
 lease=budget.reserve_recovery(c,RUN_UUID,[row],folder,namespace);cfg={**c,'current_sample_id':row['sample_id'],'current_cell':cell,'financial_slot_prefix':namespace,'trace_root':str(CONTROL),'image_index':index}
 flow_index=max([int(path.stem.split('-')[-1]) for path in folder.glob('flow-*.json')]+[0])
 def flow(*args):
  nonlocal flow_index
  flow_index+=1;command=[c['native_python'],'-B',str(root/'flow.py'),'--root',str(root),*map(str,args)]
  if (root/'runs/run1/joint-detector-adapter/manifest.json').exists():command=[*command[:2],joint_detector_adapter.__file__,*command[2:]]
  return r.native(command,c,folder/f'flow-{flow_index:03}.json')
 def dispatch(role,number=None):
  role_folder=root/'runs/run1'/('detection/'+role if number is None else f'round-{number}/{role}')
  if not (role_folder/'dispatch.json').exists():flow('dispatch','run1',role,*(['--round',number] if number else []),'--agent-id','api-'+str(uuid.uuid4()))
 def receive(role,value,number=None):
  role_folder=root/'runs/run1'/('detection/'+role if number is None else f'round-{number}/{role}')
  if (role_folder/'raw.json').exists():
   if r.read(role_folder/'raw.json')!=value or r.sha(role_folder/'raw.json')!=r.read(role_folder/'receipt.json')['sha256']:raise ValueError('role receipt mismatch')
   return
  source=root/'runs/run1/jobs'/(role+(f'-{number}' if number else ''))/('bounded-model-'+r.digest(value)[:16]+'.json');
  if source.exists() and r.read(source)!=value:raise ValueError('immutable role draft changed')
  if not source.exists():trace.write(source,value)
  checked=folder/(role+'-check.json')
  if role in ('main','semantic','planner'):
   if checked.exists():
    if r.read(checked)['model_sha256']!=r.sha(source):raise ValueError('model output changed after native check')
   else:
    result=json.loads(flow('check-plan' if role=='planner' else 'check-report','run1',*([number] if role=='planner' else [role]),source))
    if role=='planner' and str(result.get('status','')).startswith('invalid'):raise ValueError('native planner draft rejected before freezing: '+json.dumps(result))
    trace.write(checked,{'model_sha256':r.sha(source),'native_check_log':str(folder/f'flow-{flow_index:03}.json'),'native_status':result.get('status'),'joint_source_probe_only':role in ('main','semantic'),'derived_detector_validation_authority':'unchanged native merge parser validates both effective reports'})
  flow('receive','run1',role,source,*(['--round',number] if number else []))
 try:
  if not root.exists():
   policy=identity['policy'];spec={'adapter':c['adapter_root'],'native_source_root':c['native_source_root'],'output_root':str(root),'original_png':first['original'],'initial_svg':first['stage0_scene'],'runtime_json':first['runtime'],'runtime_binding':first['runtime_binding'],'registry':c['registry_path'],'capabilities':{'policy':policy,'sha256':r.digest(policy)},'first_stage_provenance':first['provenance'],'python':c['native_python'],'shared_first_stage':{'format':'c-neutral-shared-initial-v1','generation_capability_sha256':r.digest({**policy,'code_methods':False}),'source_provenance_sha256':r.sha(first['provenance'])},**({'sam_catalog':first['sam_neutral']} if row['sam'] else {})}
   if row['sam'] and r.read(first['sam_neutral'])['assets']==[]:
    import empty_sam_execution
    sam_folder=CONTROL/row['sample_id']/'sam';spec['empty_sam_execution_proof']=empty_sam_execution.build(sam_folder/'sam-catalog.json',sam_folder/'sam-validation-log.json',row['source_image_path'])
   for old_name in ('prepare-spec.json','prepare-log.json'):
    prior=folder/old_name
    if prior.exists():
     preserved=folder/'prepare-history'/(r.sha(prior)+'-'+old_name)
     if not preserved.exists():trace.write(preserved,r.read(prior))
   trace.write(folder/'prepare-spec.json',spec);r.native([c['native_python'],'-B',c['bridge_path'],'--spec',str(folder/'prepare-spec.json')],c,folder/'prepare-log.json')
  if not (root/'runs/run1/state.json').exists():flow('begin-run','run1')
  if (root/'runs/run1/joint-detector-adapter/manifest.json').exists():joint_detector_adapter.register(root,'run1',folder/f'B{branch_number}1-model.json')
  if not (root/'runs/run1/merged.json').exists():
   for role in ['main','semantic']:dispatch(role)
   messages,_=context(root,['main','semantic']);api.admit(c['providers']['deepseek'],api.body_for(c['providers']['deepseek'],messages))
   if BARRIER is not None:BARRIER.wait(timeout=120)
   value,_=call_json(cfg,lease,folder,f'B{branch_number}1','main/TURN0',messages)
   if not {'main','semantic'}<=set(value) or set(value)-{'main','semantic','proposal_reviews','programs','semantic_extra'}:raise ValueError('joint detector requires both reports; unknown extra fields are not discarded')
   if 'programs' in value and value['programs']!=[]:raise ValueError('nonempty top-level detector programs cannot be discarded')
   if 'semantic_extra' in value and value['semantic_extra']!={}:raise ValueError('nonempty unrequested semantic_extra cannot be discarded')
   for role in ['main','semantic']:receive(role,value[role])
   proposals=root/'inputs/analysis/proposals.json';supplemental_file=None
   review_error=joint_detector_adapter.proposal_review_error(root,value,c['native_python'])
   valid_ids={node.get('id') for node in ET.parse(root/'runs/run1/checkpoint/current.svg').getroot().iter() if node.get('id')};localization=joint_detector_adapter.localization_errors(value,valid_ids)
   if review_error is not None or localization:
    messages,_=review_plan_context(root,value);messages[-1]['content'].insert(0,{'type':'text','text':'The frozen native validator requires correction of review/localization components: '+str(review_error or localization)+'. Correct the proposal reviews in this same second call. Do not alter any original finding/classification. An uncertain review must link an actual complete uncertain finding: add a genuinely supported new uncertain finding if needed, never attach it to a confirmed finding. All original reports remain retained.'});supplemental,supplemental_file=call_json(cfg,lease,folder,f'B{branch_number}2','planner/ROUND1/TURN0',messages)
    if set(supplemental)-{'finding_bindings'} not in ({'semantic_report','plan'},{'proposal_reviews','new_semantic_issues','plan'}):raise ValueError('review+plan call must supply actual semantic_report and plan')
   joint_detector_adapter.register(root,'run1',folder/f'B{branch_number}1-model.json',supplemental_file)
   flow('merge','run1')
  candidate=root/'runs/run1/round-1/candidate.json'
  if not candidate.exists():
   dispatch('planner',1);model_file=folder/f'B{branch_number}2-model.json'
   recovery_file=folder/'stage-recoveries.json'
   if recovery_file.exists() and f'B{branch_number}2' in r.read(recovery_file):model_file=folder/(r.read(recovery_file)[f'B{branch_number}2']['recovery_stage']+'-model.json')
   if model_file.exists() and 'plan' in r.read(model_file) and ('semantic_report' in r.read(model_file) or 'proposal_reviews' in r.read(model_file)):
    payload=r.read(model_file)
    if not c.get('_mock_send'):
     import model_envelope_binding
     payload,proof=model_envelope_binding.bind(folder,model_file.stem.removesuffix('-model'),payload);trace.write(folder/(f'B{branch_number}2-machine-envelope-proof.json'),proof)
    value=payload['plan']
   else:
    messages,_=context(root,['planner'],1);value,_=call_json(cfg,lease,folder,f'B{branch_number}2','planner/ROUND1/TURN0',messages)
   tracked=r.read(root/'runs/run1/state.json');ids={node.get('id') for node in ET.parse(root/'runs/run1/checkpoint/current.svg').getroot().iter() if node.get('id')};value,projection=bounded_plan_binding.bind(value,tracked['required']+tracked['uncertain'],ids,additional_unplanned_source_ids=[x['id'] for x in r.read(model_file).get('new_semantic_issues',[])]);trace.write(folder/'planner-binding-audit.json',{'source_model_sha256':r.sha(model_file),'operations':projection,'all_actual_finding_fields_unchanged':True,'effective_plan_sha256':r.digest(value)});receive('planner',value,1);flow('execute','run1',1)
  if not (root/'runs/run1/round-1/acceptance.json').exists():
   dispatch('verifier',1);messages,_=context(root,['verifier'],1);value,verifier_model_file=call_json(cfg,lease,folder,f'B{branch_number}3','verifier/ROUND1/TURN0',messages);value,request_projection=bind_saved_verifier_metadata(value,root,folder,branch_number);value,missing_collection_projection=bounded_verifier_binding.complete_unreported_finding_collections(value,r.read(Path(r.read(root/'runs/run1/round-1/candidate.json')['candidate_folder'])/'pack/pack.json')['frames']);api.validate_verifier_output(value);value,reference_projection=bounded_verifier_binding.bind_exact_finding_references(value,r.read(root/'runs/run1/state.json'));value,region_projection=bounded_verifier_binding.bind_region_coverage_conservatively(value,r.read(Path(r.read(root/'runs/run1/round-1/candidate.json')['candidate_folder'])/'pack/pack.json')['frames']);value,noop_projection=bounded_verifier_binding.omit_incomplete_noop_uncertainty_reviews(value,r.read(root/'runs/run1/state.json'));value,review_coalescing_projection=bounded_verifier_binding.coalesce_uncertainty_reviews(value);value,disabled_projection=bounded_native_profile.normalize(value,row['external_code']);value,uncertainty_projection=bounded_verifier_binding.bind_uncertain_adjudications(value,r.read(root/'runs/run1/state.json'));value,hash_projection=bounded_verifier_binding.bind(value,r.read(root/'runs/run1/round-1/candidate.json'));value,credit_projection=bounded_verifier_binding.reject_impossible_resolution_credit(value,r.read(root/'runs/run1/state.json'),r.read(root/'runs/run1/round-1/candidate.json'));value,unlocalized_projection=bounded_verifier_binding.withhold_unlocalized_target_credit(value,r.read(root/'runs/run1/state.json'));value,partition_conflict_projection=bounded_verifier_binding.conservative_partition_conflicts(value,[x['id'] for x in r.read(root/'runs/run1/state.json')['required']]);value,representation_projection=bind_current_representation(value,root);value,projection=bounded_native_profile.normalize(value,row['external_code']);projection=review_coalescing_projection+reference_projection+partition_conflict_projection+unlocalized_projection+missing_collection_projection+credit_projection+representation_projection+region_projection+noop_projection+disabled_projection+request_projection+uncertainty_projection+hash_projection+projection;trace.write(folder/'verifier-profile-audit.json',{'operations':projection,'original_model_sha256':r.sha(verifier_model_file),'original_model_report_preserved':True,'quality_fields_unchanged':not bool(representation_projection or review_coalescing_projection or partition_conflict_projection or unlocalized_projection or missing_collection_projection or credit_projection or uncertainty_projection or noop_projection or region_projection),'runtime_disposition_projection':'Native protocol can conservatively reject unverifiable credit or keep broader uncertainty; original model judgment remains in the immutable raw response. Formal quality scoring is deferred.'});receive('verifier',value,1);flow('accept','run1',1)
  if r.read(root/'runs/run1/state.json').get('runtime_finished_monotonic_ns') is None:flow('finish-run','run1')
  final=r.reusable_finished_native(root/'runs/run1/state.json',row);record={'status':'complete','protocol':'bounded-two-stage-v1','row':row,**final,'elapsed_seconds':time.monotonic()-started,'evaluation':'deferred by user; no score requests','completed_utc':now()};trace.write(folder/'result.json',record);lease.close();return record
 except BaseException as exc:
  if BARRIER is not None:BARRIER.abort()
  STOP.set();trace.write(CONTROL/'provider-pause.json',{'reason':'bounded stage requires diagnosis; no automatic retries','error_type':type(exc).__name__,'error':str(exc),'sample_id':row['sample_id'],'cell':cell,'timestamp':now()});trace.write(folder/'failure.json',{'error_type':type(exc).__name__,'error':str(exc),'timestamp':now(),'old_artifacts_retained':True});raise

def prepare_sam(row,c):
 folder=CONTROL/row['sample_id']/'sam';folder.mkdir(parents=True,exist_ok=True)
 supplied=OLD/row['sample_id']/'sam-catalog.json'
 cfg={**c,'adapter_root':c['first_stage_adapter_root'],'sam_catalogs':{**c.get('sam_catalogs',{}),**({row['sample_id']:str(supplied)} if supplied.exists() else {})}}
 return r.sam_for(row,cfg,folder)

def run(limit):
 global CURRENT_CONFIG,CFG_NATIVE,CURRENT_ROW,BARRIER
 CONTROL.mkdir(exist_ok=True,parents=True);lock=(ROOT/'output/formal-launch-20261029/full-run.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 c=r.read(CFG);rows,groups,bindings=r.validate(c);CURRENT_CONFIG=c;CFG_NATIVE=c['native_python']
 if (CONTROL/'provider-pause.json').exists():raise ValueError('bounded pipeline paused; diagnose existing receipt before resuming')
 status={'status':'running','pid':os.getpid(),'protocol':'bounded-two-stage-v1','started_utc':now(),'completed_images':0,'completed_tasks':0,'expected_images':80,'expected_tasks':320,'evaluation':'deferred'};trace.write(CONTROL/'status.json',status)
 try:
  for index,(sample,block) in enumerate(list(groups.items())[:limit],1):
   CURRENT_ROW=block[0]
   original=OLD/sample;original.mkdir(exist_ok=True);budget.reserve_block(c,RUN_UUID,block,original).close();sam=prepare_sam(block[0],c)
   with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
    a1=pool.submit(reuse_first,next(row for row in block if row['cell']=='S0C0'),index,None,c);a2=pool.submit(reuse_first,next(row for row in block if row['cell']=='S1C0'),index,sam,c);firsts={False:a1.result(),True:a2.result()}
   image_started=time.monotonic()
   waiting=sum(not (CONTROL/sample/row['cell']/'cell/runs/run1/merged.json').exists() for row in block)
   BARRIER=threading.Barrier(waiting) if waiting else None
   with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    futures=[pool.submit(branch,row,index,firsts[row['sam']],c,bindings) for row in block]
    for future in concurrent.futures.as_completed(futures):
     try:future.result()
     except BaseException:
      STOP.set()
      if BARRIER is not None:BARRIER.abort()
      raise
     status['completed_tasks']+=1;trace.write(CONTROL/'status.json',status)
   status['completed_images']+=1;status['last_image_parallel_B_seconds']=time.monotonic()-image_started;trace.write(CONTROL/'status.json',status)
  status.update(status='pilot_complete' if limit<80 else 'completed',ended_utc=now());trace.write(CONTROL/'status.json',status)
 except BaseException as exc:
  STOP.set();status.update(status='stopped_needs_diagnosis',error_type=type(exc).__name__,error=str(exc),ended_utc=now());trace.write(CONTROL/'status.json',status);raise
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=1);args=parser.parse_args();run(args.limit)
