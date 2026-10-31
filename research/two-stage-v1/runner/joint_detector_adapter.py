"""Explicit schema bridge for one joint detector response, not quality rewriting.

Original model response and both frozen role receipts remain untouched. Derived
native reports add only provably empty protocol arrays and route complete finding
objects to a permitted native role. Native merge validators still run unchanged.
"""
import copy,json,pathlib,hashlib,sys,importlib.util,re,xml.etree.ElementTree as ET
MAIN={'F','E','B','S1','D','S2'};ALL=MAIN|{'A','C','S4'}
def sha(path):return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(pathlib.Path(path).read_text())
def freeze(path,value):
 path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('x') as stream:json.dump(value,stream,ensure_ascii=False,indent=2)
def bind_duplicate_scope_uncertainty(reports,proposals):
 """Reference an existing real uncertainty only for duplicate attention footprints."""
 if proposals is None:return []
 catalog={p['id']:p for p in proposals['proposals']};reviews=reports['semantic'].get('proposal_reviews',[]);sources=copy.deepcopy(reviews);uncertain={x['id']:x for x in reports['semantic']['issues'] if x.get('decision')=='uncertain'};audit=[]
 for review in reviews:
  if review.get('decision')!='uncertain' or review.get('issue_ids')!=[]:continue
  proposal=catalog.get(review.get('proposal_id'))
  if not proposal or not proposal.get('target_ids') or not isinstance(proposal.get('bbox'),list) or len(proposal['bbox'])!=4:continue
  candidates={};evidence=proposal.get('evidence',{})
  for prior in sources:
   if prior.get('decision')!='uncertain' or not prior.get('issue_ids') or prior.get('proposal_id')==review.get('proposal_id'):continue
   other=catalog.get(prior.get('proposal_id'))
   if not other or set(other.get('target_ids',[]))!=set(proposal['target_ids']) or other.get('bbox')!=proposal['bbox'] or other.get('evidence',{}).get('revision')!=evidence.get('revision') or not evidence.get('evidence_hashes') or other.get('evidence',{}).get('evidence_hashes')!=evidence['evidence_hashes']:continue
   for link in prior['issue_ids']:
    ident=link if link in uncertain else link.split(':',1)[1] if link.startswith('semantic:') and link.split(':',1)[1] in uncertain else None
    if ident and set(uncertain[ident].get('target_ids',[]))==set(proposal['target_ids']):candidates.setdefault(ident,[]).append(prior['proposal_id'])
  if len(candidates)==1:
   ident=next(iter(candidates));original=copy.deepcopy(review);review['issue_ids']=[ident];audit.append({'operation':'uncertain actual review with empty references binds one existing actual uncertainty already cited by a duplicate native attention footprint; no new finding or judgment','original_model_review':original,'actual_existing_uncertain_id':ident,'same_scope_original_review_proposal_ids':candidates[ident],'exact_target_ids':proposal['target_ids'],'exact_bbox':proposal['bbox'],'same_source_evidence_hashes':evidence['evidence_hashes'],'no_positive_quality_credit_or_edit_authority_added':True})
 return audit

def normalize(original,proposals,valid_ids=None,readonly_aliases=None):
 if not {'main','semantic'}<=set(original) or set(original)-{'main','semantic','proposal_reviews','programs','semantic_extra'}:raise ValueError('joint detector requires both reports with only explicit review-wrapper alias')
 reports={role:copy.deepcopy(original[role]) for role in ('main','semantic')};audit=[]
 if 'semantic_extra' in original:
  if original['semantic_extra']!={}:raise ValueError('nonempty unrequested semantic_extra cannot be discarded')
  audit.append({'operation':'omit literal empty unrequested semantic_extra wrapper; original raw retained','original_value':{},'no_quality_effect':True})
 if 'programs' in original:
  if original['programs']!=[]:raise ValueError('nonempty top-level detector programs cannot be discarded')
  audit.append({'operation':'omit redundant explicitly empty non-executable top-level programs wrapper; role reports and all judgments retained','no_quality_effect':True})
 if 'proposal_reviews' in original:
  actual=original['proposal_reviews']
  if not isinstance(actual,list):raise ValueError('review wrapper alias requires actual array')
  if 'proposal_reviews' in reports['semantic'] and reports['semantic']['proposal_reviews']!=actual:
   nested=reports['semantic']['proposal_reviews'];evidence_keys={'source_evidence','current_evidence','necessity_reason'}
   if not isinstance(nested,list) or len(nested)!=len(actual):raise ValueError('conflicting actual top-level and semantic reviews')
   combined=[]
   for left,right in zip(nested,actual):
    if not isinstance(left,dict) or not isinstance(right,dict) or {k:v for k,v in left.items() if k not in evidence_keys}!={k:v for k,v in right.items() if k not in evidence_keys}:raise ValueError('conflicting actual top-level and semantic reviews')
    row=copy.deepcopy(left)
    for key in evidence_keys:
     a,b=left.get(key),right.get(key)
     if not isinstance(a,str) or not a.strip() or not isinstance(b,str) or not b.strip():raise ValueError('both actual review evidence texts required')
     row[key]=a if a==b else '[Actual semantic review] '+a+'\n[Actual top-level review] '+b
    combined.append(row)
   audit.append({'operation':'coalesce two actual review wrappers only with identical ordered proposal identities, decisions, links and other non-evidence fields; retain both actual evidence texts verbatim','original_semantic_reviews':copy.deepcopy(nested),'original_top_level_reviews':copy.deepcopy(actual),'no_quality_judgment_changed':True})
   actual=combined
  reports['semantic']['proposal_reviews']=copy.deepcopy(actual);audit.append({'operation':'move actual top-level proposal_reviews to native semantic slot; exact judgments/evidence unchanged'})
 for role,report in reports.items():
  for issue in report.get('issues',[]):
   if issue.get('decision') in ('unresolved','unecertain','qualified'):
    source_decision=issue['decision'];issue['decision']='uncertain';audit.append({'operation':'non-confirming unsupported confidence enum retains the actual finding as uncertain; original model judgment preserved','role':role,'issue_id':issue['id'],'original_decision':source_decision,'effective_decision':'uncertain','no_positive_quality_claim_added':True})
  if not isinstance(report.get('issues'),list):raise ValueError('model issues array required')
  if 'programs' not in report:report['programs']=[];audit.append({'role':role,'operation':'default omitted non-executable detection programs to empty','no_quality_effect':True})
  if report['programs']!=[]:raise ValueError('cannot discard model programs or treat detection as execution')
 moved=[];kept=[]
 for issue in reports['main']['issues']:
  if issue.get('category') not in ALL:raise ValueError('unknown model category cannot be inferred')
  if issue['category'] not in MAIN:moved.append(issue)
  else:kept.append(issue)
 if moved:
  existing={row['id'] for row in reports['semantic']['issues']}
  if any(row['id'] in existing for row in moved):raise ValueError('joint finding identity collision')
  reports['main']['issues']=kept;reports['semantic']['issues'].extend(moved);audit.append({'operation':'route complete joint findings to permitted semantic native role','ids':[row['id'] for row in moved],'all_issue_fields_unchanged':True})
 if proposals is not None and 'proposal_reviews' not in reports['semantic']:
  if proposals.get('proposals')!=[]:raise ValueError('nonempty proposal catalog requires actual model reviews')
  reports['semantic']['proposal_reviews']=[];audit.append({'role':'semantic','operation':'default review array for proven empty proposal catalog','proposal_count':0})
 if isinstance(reports['semantic'].get('proposal_reviews'),dict):
  wrapper=reports['semantic']['proposal_reviews']
  disabled_note=wrapper.get('mode')=='disabled_by_assignment' and wrapper.get('reviewed')==[] and set(wrapper)<= {'mode','reviewed','note'} and isinstance(wrapper.get('note',''),str)
  if proposals is None or proposals.get('proposals')!=[] or not (wrapper in ({},{'mode':'disabled_by_assignment'},{'mode':'disabled_by_assignment','proposal_reviews':[]}) or disabled_note):raise ValueError('unsupported review object wrapper; actual nonempty reviews require correction')
  reports['semantic']['proposal_reviews']=[];audit.append({'operation':'unwrap explicit disabled empty review metadata for proven empty native catalog','original_model_wrapper':wrapper,'no_quality_effect':True})
 if reports['semantic'].get('proposal_reviews','absent') is None:
  if proposals is None or proposals.get('proposals')!=[]:raise ValueError('null review array requires correction unless actual proposal catalog is empty')
  reports['semantic']['proposal_reviews']=[];audit.append({'operation':'null review collection becomes empty only for proven empty native catalog','no_quality_effect':True})
 audit.extend(bind_duplicate_scope_uncertainty(reports,proposals))
 for review in reports['semantic'].get('proposal_reviews',[]):
  if review.get('decision') in ('no_finding','reject'):
   if review.get('issue_ids')!=[] or any(not isinstance(review.get(key),str) or not review[key].strip() for key in ('source_evidence','current_evidence','necessity_reason')):raise ValueError('no-finding enum alias requires actual evidence and no linked findings')
   source_decision=review['decision'];review['decision']='qualified';audit.append({'proposal_id':review['proposal_id'],'operation':'explicit no_finding semantic enum maps to native qualified','source_decision':source_decision,'quality_judgment_unchanged':True})
 for review in reports['semantic'].get('proposal_reviews',[]):
  links=review.get('issue_ids',[]);normalized_links=[]
  for link in links:
   literal=[item for item in reports['semantic']['issues'] if item['id']==link]
   if literal and ':' in link and link.split(':',1)[0] in ('main','semantic'):
    prefix,tail=link.split(':',1)
    if any(item['id']==tail for item in reports[prefix]['issues']):raise ValueError('ambiguous literal source ID versus role-qualified reference')
    normalized_links.append(link);audit.append({'operation':'literal complete semantic source ID contains a colon; retain exact raw ID instead of stripping its first component','actual_raw_finding_id':link,'no_new_finding_or_judgment':True});continue
   if not (':' in link and link.split(':',1)[0] in ('main','semantic')) and not any(item['id']==link for item in reports['semantic']['issues']):
    exact_main=[item for item in reports['main']['issues'] if item['id']==link]
    if len(exact_main)==1:
     audit.append({'operation':'raw joint link has one exact existing main source; canonical source namespace only','original_link':link,'source_link':'main:'+link,'no_finding_or_judgment_created':True});link='main:'+link
   if ':' in link and link.split(':',1)[0] in ('main','semantic'):
    source_role,raw_id=link.split(':',1);matches=[item for item in reports[source_role]['issues'] if item['id']==raw_id]
    if not matches:
     exact=[(role,item) for role in ('main','semantic') for item in reports[role]['issues'] if item['id']==raw_id]
     if len(exact)==1:
      actual_role,item=exact[0];matches=[item];audit.append({'operation':'role-prefix metadata correction uses one exact immutable reported finding ID; no fuzzy matching or new finding','original_link':link,'actual_existing_role':actual_role,'same_raw_finding_id':raw_id});source_role=actual_role
    if len(matches)!=1:raise ValueError('proposal link cannot bind an exact reported joint finding')
    if source_role=='main' and matches[0] in reports['main']['issues']:
     if any(item['id']==raw_id for item in reports['semantic']['issues']):raise ValueError('proposal routing identity collision')
     reports['main']['issues'].remove(matches[0]);reports['semantic']['issues'].append(matches[0]);audit.append({'operation':'route complete existing joint main finding into semantic role for actual proposal reference','source_id':link,'native_semantic_id':raw_id,'all_finding_fields_unchanged':True})
    normalized_links.append(raw_id)
   else:normalized_links.append(link)
  review['issue_ids']=normalized_links
  if review.get('decision')=='confirmed':
   actual={item['id']:item for item in reports['semantic']['issues']}
   if not normalized_links or any(ident not in actual or actual[ident]['decision']!='confirmed' for ident in normalized_links):raise ValueError('confirmed review requires actual linked confirmed finding')
   review['decision']='required';audit.append({'operation':'confirmed review enum maps to native required only for actual confirmed linked findings','proposal_id':review['proposal_id'],'quality_judgment_unchanged':True})
 before=copy.deepcopy([row for role in ('main','semantic') for row in original[role]['issues']]);
 for row in before:
  if row.get('decision') in ('unresolved','unecertain','qualified'):row['decision']='uncertain'
 after=[row for role in ('main','semantic') for row in reports[role]['issues']]
 key=lambda row:json.dumps(row,sort_keys=True)
 if sorted(map(key,before))!=sorted(map(key,after)):raise ValueError('joint finding preservation proof failed')
 if valid_ids is not None:
  for role,report in reports.items():
   for issue in report['issues']:
    for field in ('target_ids','neighbor_ids','container_id'):
     values=issue.get(field)
     if values is None:continue
     original_values=values if isinstance(values,list) else [values];normalized=[]
     for value in original_values:
      canonical=value
      if value not in valid_ids:
       matched=re.fullmatch(r'plus_node([0-9]+)',value)
       canonical='plus_node_'+matched.group(1) if matched else None
       if field=='neighbor_ids' and value in (readonly_aliases or {}):
        canonical=readonly_aliases[value]
        if canonical not in valid_ids:raise ValueError('read-only alias destination not in exact native scene')
        audit.append({'operation':'explicit audited read-only neighbor spelling correction; no target/container authority','source':value,'native':canonical,'finding_quality_unchanged':True})
       if canonical not in valid_ids and field=='neighbor_ids':
        audit.append({'operation':'omit nonexistent read-only neighbor reference; actual target/container authority and visual judgment unchanged','role':role,'issue_id':issue['id'],'original_neighbor_reference':value});continue
       if canonical not in valid_ids and field=='target_ids':
        issue.setdefault('unresolved_target_references',[]).append(value);audit.append({'operation':'withhold nonexistent edit target; preserve finding and block positive closure until localized','role':role,'issue_id':issue['id'],'unresolved_original_target':value,'no_guessed_or_new_edit_authority':True});continue
       if canonical not in valid_ids:raise ValueError('unresolvable native object ID; no fuzzy binding allowed: '+value)
       audit.append({'role':role,'issue_id':issue['id'],'field':field,'operation':'canonical native plus_node_<integer> spelling','source':value,'native':canonical,'quality_judgment_unchanged':True})
      normalized.append(canonical)
     if len(normalized)!=len(set(normalized)):raise ValueError('native ID canonicalization would create duplicates')
     if field=='target_ids' and not normalized and issue.get('container_id') not in valid_ids:raise ValueError('all targets unlocalized and no actual model-supplied container; cannot manufacture location')
     issue[field]=normalized if isinstance(values,list) else normalized[0]
 return reports,audit

def validate_supplement(original,supplemental):
 if not isinstance(supplemental,dict) or not isinstance(supplemental.get('proposal_reviews'),list):raise ValueError('actual model proposal reviews required')
 for key,value in original.items():
  if key=='issues':
   if supplemental.get('issues',[])[:len(value)]!=value:raise ValueError('supplement cannot erase or rewrite prior findings')
  elif key!='proposal_reviews' and supplemental.get(key)!=value:raise ValueError('supplement changed original semantic report field: '+key)

def localization_errors(original,valid_ids):
 errors=[]
 for role in ('main','semantic'):
  for issue in original[role]['issues']:
   def exists(value):
    match=re.fullmatch(r'plus_node([0-9]+)',value) if isinstance(value,str) else None
    return value in valid_ids or (match is not None and 'plus_node_'+match.group(1) in valid_ids)
   if not any(exists(value) for value in issue.get('target_ids',[])) and issue.get('container_id') not in valid_ids:
    errors.append({'role':role,'issue_id':issue['id'],'unlocalized_target_ids':issue.get('target_ids',[]),'actual_model_container':issue.get('container_id')})
 return errors

def apply_actual_model_bindings(original,bindings,valid_ids):
 if not isinstance(bindings,list):raise ValueError('actual model localization bindings must be an array')
 result=copy.deepcopy(original);needed={(x['role'],x['issue_id']) for x in localization_errors(original,valid_ids)};seen=set();audit=[]
 for binding in bindings:
  if not isinstance(binding,dict) or set(binding)-{'role','issue_id','target_ids','neighbor_ids','container_id','evidence'}:raise ValueError('localization cannot change model judgments or finding fields')
  ident=(binding.get('role'),binding.get('issue_id'))
  if ident not in needed or ident in seen:raise ValueError('localization must refer to one exact unbound original finding')
  if not isinstance(binding.get('evidence'),str) or not binding['evidence'].strip():raise ValueError('actual model localization evidence required')
  for key in ('target_ids','neighbor_ids'):
   values=binding.get(key)
   if not isinstance(values,list) or len(values)!=len(set(values)) or any(not isinstance(x,str) or x not in valid_ids for x in values):raise ValueError('model localization must name actual unique current objects')
  if not binding['target_ids'] or binding.get('container_id') is not None and binding['container_id'] not in valid_ids:raise ValueError('explicit current model target required')
  issue=next(x for x in result[ident[0]]['issues'] if x['id']==ident[1]);prior=copy.deepcopy(issue)
  evidence_slots=[]
  for field in ('original_evidence','current_evidence'):
   if field in issue:continue
   source=prior.get('description') if field=='original_evidence' else binding['evidence']
   marker=r'\b(original|reference|source)\b' if field=='original_evidence' else r'\b(current|candidate|render|rendered|SVG)\b'
   if not isinstance(source,str) or not source.strip() or re.search(marker,source,re.I) is None:raise ValueError('missing evidence cannot be fabricated from a description without an explicit view reference')
   issue[field]=source;evidence_slots.append({'native_field':field,'actual_source_field':'original_finding.description' if field=='original_evidence' else 'actual_model_binding.evidence','verbatim_text_sha256':hashlib.sha256(source.encode()).hexdigest(),'combined_source_current_narrative_not_independent_observations':True})
  for key in ('target_ids','neighbor_ids'):issue[key]=copy.deepcopy(binding[key])
  if binding.get('container_id') is None:issue.pop('container_id',None)
  else:issue['container_id']=binding['container_id']
  seen.add(ident);audit.append({'operation':'same second-stage actual model explicitly localizes previously unbound first-stage finding; no host ID guessing or visual judgment change','original_finding':prior,'actual_model_binding':binding,'verbatim_evidence_slot_projections':evidence_slots,'judgment_and_description_unchanged':True})
 if seen!=needed:raise ValueError('actual model must localize every unbound original finding')
 return result,audit

def combine_missing_reviews(previous,correction,missing_ids):
 previous=copy.deepcopy(previous);correction=copy.deepcopy(correction)
 old=previous['proposal_reviews'];new=correction['proposal_reviews']
 if len({x['proposal_id'] for x in old})!=len(old) or len({x['proposal_id'] for x in new})!=len(new):raise ValueError('duplicate review sources')
 if {x['proposal_id'] for x in new}!=set(missing_ids) or {x['proposal_id'] for x in old}&set(missing_ids):raise ValueError('correction must contain exactly previously missing reviews')
 issues=copy.deepcopy(previous['new_semantic_issues']);known={x['id']:x for x in issues}
 for issue in correction['new_semantic_issues']:
  if issue['id'] in known:
   if known[issue['id']]!=issue:raise ValueError('conflicting actual supplemental finding')
  else:issues.append(issue);known[issue['id']]=issue
 return {**correction,'proposal_reviews':old+new,'new_semantic_issues':issues}

def register(root,run,model_file,supplemental_file=None):
 root=pathlib.Path(root);base=root/'runs'/run;parent=base/'joint-detector-adapter';folder=parent;manifest=folder/'manifest.json';supersedes=None
 versions=sorted((parent/'versions').glob('*/manifest.json'))
 selected=versions[-1] if versions else manifest
 if selected.exists():
  prior=read(selected)
  if prior['model_sha256']!=sha(prior['model_file']) or prior['native_flow_sha256']!=sha(root/'flow.py'):raise ValueError('cannot migrate changed detector sources')
  for role,binding in prior['original_sources'].items():
   if binding['raw']!=sha(base/'detection'/role/'raw.json') or binding['receipt']!=sha(base/'detection'/role/'receipt.json'):raise ValueError('cannot migrate changed original role receipt')
  same_supplement=supplemental_file is None or (prior.get('supplemental_model') and prior['supplemental_model']['sha256']==sha(supplemental_file))
  if prior['adapter_runtime_sha256']==sha(__file__) and same_supplement:validate(root,run);return
  if supplemental_file is None and prior.get('supplemental_model'):supplemental_file=prior['supplemental_model']['path']
  supersedes={'path':str(selected),'sha256':sha(selected),'runtime_sha256':read(selected)['adapter_runtime_sha256']}
  folder=parent/'versions'/f'{len(versions)+1:04}';manifest=folder/'manifest.json'
 original=read(model_file);combined=copy.deepcopy(original);supplemental_binding=None;envelope_proof=None;binding_operations=[]
 ids={node.get('id') for node in ET.parse(base/'checkpoint/current.svg').getroot().iter() if node.get('id')}
 # The original frozen report remains byte-identical; only the derived native machine envelope is bound.
 import model_envelope_binding
 stage=pathlib.Path(model_file).stem.removesuffix('-model')
 source_folder=pathlib.Path(model_file).parent
 if (source_folder/'api').exists() and list((source_folder.parent.parent/'trace').glob('*-'+source_folder.parent.name+'-'+stage+'.json')):
  combined,envelope_proof=model_envelope_binding.bind(source_folder,stage,original)
 if supplemental_file is not None:
  payload=read(supplemental_file)
  import proposal_review_shape_adapter
  payload,review_shape_audit=proposal_review_shape_adapter.normalize(payload,read(root/'inputs/analysis/proposals.json'))
  review_base_file=pathlib.Path(supplemental_file).with_suffix('.review-base.json');review_base_proof=None
  if review_base_file.exists():
   review_base_proof=read(review_base_file);prior_payload=pathlib.Path(review_base_proof['previous_model_file'])
   if sha(prior_payload)!=review_base_proof['previous_model_sha256'] or sha(supplemental_file)!=review_base_proof['correction_model_sha256']:raise ValueError('actual partial review sources changed')
   payload=combine_missing_reviews(read(prior_payload),payload,review_base_proof['only_missing_proposal_ids'])
  if 'semantic_report' in payload:supplemental=payload['semantic_report'];pointer='/semantic_report'
  else:
   if not isinstance(payload.get('proposal_reviews'),list) or not isinstance(payload.get('new_semantic_issues'),list):raise ValueError('actual second-stage review and new-issue arrays required')
   supplemental={**original['semantic'],'proposal_reviews':payload['proposal_reviews'],'issues':original['semantic']['issues']+payload['new_semantic_issues']};pointer={'proposal_reviews':'/proposal_reviews','appended_issues':'/new_semantic_issues','unchanged_base':'first-stage /semantic'}
  validate_supplement(original['semantic'],supplemental);combined['semantic']=supplemental
  supplemental_binding={'path':str(pathlib.Path(supplemental_file).resolve()),'sha256':sha(supplemental_file),'json_pointer':pointer,'actual_second_stage_model_response':True,'review_shape_projection':review_shape_audit,'append_only_actual_review_combination':review_base_proof}
 if supplemental_file is not None and 'finding_bindings' in payload:
  combined,binding_operations=apply_actual_model_bindings(combined,payload['finding_bindings'],ids)
 if envelope_proof and envelope_proof['operations']:
  for op in envelope_proof['operations']:combined[op['pointer']].update(copy.deepcopy(op['canonical_snapshot']))
 proposals_path=root/'inputs/analysis/proposals.json';proposals=read(proposals_path) if proposals_path.exists() else None
 if proposals is None and read(base/'state.json')['capabilities']['code_methods'] is False:proposals={'proposals':[],'provenance':'native C0 capability disables observation catalog'}
 ids={node.get('id') for node in ET.parse(base/'checkpoint/current.svg').getroot().iter() if node.get('id')};alias_file=root.parent/'readonly-id-aliases.json';alias_proof=None;aliases=None
 if alias_file.exists():
  alias_proof=read(alias_file)
  if alias_proof['source_svg_sha256']!=sha(base/'checkpoint/current.svg') or alias_proof['source_model_sha256']!=sha(model_file):raise ValueError('read-only alias proof does not bind current source')
  aliases=alias_proof['readonly_neighbor_aliases']
 reports,audit=normalize(combined,proposals,ids,readonly_aliases=aliases);audit=binding_operations+audit
 import bounded_verifier_binding
 pack=read(base/'checkpoint/pack/pack.json')
 for role in reports:
  reports[role],coverage=bounded_verifier_binding.bind_region_coverage_conservatively(reports[role],pack['frames']);audit.extend({'role':role,**operation} for operation in coverage)
 bindings={}
 for role in ('main','semantic'):
  old=base/'detection'/role
  if read(old/'raw.json')!=original[role] or read(old/'receipt.json')['sha256']!=sha(old/'raw.json'):raise ValueError('joint response does not match frozen source role')
  bindings[role]={'raw':sha(old/'raw.json'),'receipt':sha(old/'receipt.json')}
  output=folder/role;freeze(output/'raw.json',reports[role]);freeze(output/'receipt.json',{'sha256':sha(output/'raw.json'),'source_file':str(pathlib.Path(model_file).resolve()),'source_model_sha256':sha(model_file),'source_json_pointer':'/'+role,'schema_bridge':'joint-detector-native-role-adapter-v1'});freeze(output/'dispatch.json',{**read(old/'dispatch.json'),'derived_from_joint_detector':True,'source_dispatch_sha256':sha(old/'dispatch.json')})
 freeze(manifest,{'format':'joint-detector-native-role-adapter-v1','same_request_envelope_proof':envelope_proof,'readonly_alias_proof':{'path':str(alias_file),'sha256':sha(alias_file)} if alias_proof else None,'supersedes':supersedes,'supplemental_model':supplemental_binding,'original_sources':bindings,'model_file':str(pathlib.Path(model_file).resolve()),'model_sha256':sha(model_file),'adapter_runtime_sha256':sha(__file__),'native_flow_sha256':sha(root/'flow.py'),'schema_operations':audit,'all_model_findings_and_quality_judgments_preserved':True,'derived_reports':{role:sha(folder/role/'raw.json') for role in reports},'proposal_catalog_sha256':sha(proposals_path) if proposals_path.exists() else None})

def validate(root,run):
 root=pathlib.Path(root);base=root/'runs'/run;folder=base/'joint-detector-adapter';versions=sorted((folder/'versions').glob('*/manifest.json'))
 if versions:folder=versions[-1].parent
 m=read(folder/'manifest.json')
 if m.get('readonly_alias_proof') and sha(m['readonly_alias_proof']['path'])!=m['readonly_alias_proof']['sha256']:raise ValueError('read-only alias proof changed')
 if m.get('supersedes') and sha(m['supersedes']['path'])!=m['supersedes']['sha256']:raise ValueError('joint schema bridge history changed')
 if m.get('supplemental_model') and sha(m['supplemental_model']['path'])!=m['supplemental_model']['sha256']:raise ValueError('actual supplemental model report changed')
 if m['model_sha256']!=sha(m['model_file']) or m['adapter_runtime_sha256']!=sha(__file__) or m['native_flow_sha256']!=sha(root/'flow.py'):raise ValueError('joint detector bridge source/runtime changed')
 for role,binding in m['original_sources'].items():
  original=base/'detection'/role
  if binding['raw']!=sha(original/'raw.json') or binding['receipt']!=sha(original/'receipt.json') or m['derived_reports'][role]!=sha(folder/role/'raw.json'):raise ValueError('joint detector bridge immutable receipt changed')
 return folder

def main():
 flow=pathlib.Path(sys.argv[1]).resolve();args=sys.argv[2:];sys.path.insert(0,str(flow.parent));spec=importlib.util.spec_from_file_location('unchanged_native_flow_with_joint_detector_schema_bridge',flow);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);original=module.Flow
 class JointFlow(original):
  def role_path(self,run,role,round_number=None):
   path=super().role_path(run,role,round_number)
   if role in ('main','semantic') and (self.path(run)/'joint-detector-adapter/manifest.json').exists():return validate(self.root,run)/role
   return path
 module.Flow=JointFlow;sys.argv=[str(flow),*args];module.main()
if __name__=='__main__':main()

def proposal_review_error(root,original,native_python):
 """Actual frozen native validator, zero HTTP and no draft-check counter mutation."""
 import subprocess
 root=pathlib.Path(root);catalog=root/'inputs/analysis/proposals.json'
 if not catalog.exists() or read(catalog).get('proposals')==[]:return None
 try:reports,_=normalize(original,None)
 except ValueError as exc:return str(exc)
 code="import sys,json;sys.path.insert(0,sys.argv[1]);from detection_contract import validate_proposal_reviews;x=json.load(sys.stdin);validate_proposal_reviews(x['report'],x['proposals'],x['state'])"
 result=subprocess.run([native_python,'-I','-B','-c',code,str(root)],input=json.dumps({'report':reports['semantic'],'proposals':read(catalog),'state':read(root/'runs/run1/state.json')}),text=True,capture_output=True,env={},timeout=30)
 if result.returncode:return result.stderr.strip().splitlines()[-1]
 return None
