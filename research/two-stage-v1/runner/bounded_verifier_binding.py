"""Repair only a proven key permutation of the exact current evidence hash map."""
from copy import deepcopy
from collections import Counter

def bind(report,snapshot):
    if report.get('revision')!=snapshot['revision']:raise ValueError('stale verifier revision cannot be corrected')
    actual=report.get('evidence_hashes');expected=snapshot['evidence_hashes']
    if not isinstance(actual,dict) or set(actual)!=set(expected):raise ValueError('missing/extra verifier evidence keys')
    if actual==expected:return deepcopy(report),[]
    if Counter(actual.values())!=Counter(expected.values()):raise ValueError('stale/unknown verifier evidence values cannot be corrected')
    result=deepcopy(report);result['evidence_hashes']=deepcopy(expected)
    return result,[{'operation':'restore canonical evidence key/value association from exact same snapshot; value multiset and revision identical','source_mapping':actual,'canonical_mapping':expected,'all_quality_fields_unchanged':True}]

def bind_attention_ack(report,expected,request_proof):
    """Reassociate constant attention metadata proven in the SAME actual API request.

    Never creates a visual verdict, repair credit, observed fact or unknown hash.
    The exact model report remains immutable; caller stores an explicit derived receipt.
    """
    import re
    actual=report.get('connector_paint_ack')
    if not request_proof.get('exact_request_metadata_verified') or request_proof.get('expected_ack')!=expected:raise ValueError('actual request binding proof required')
    if not isinstance(actual,dict) or actual.get('candidate_receipt_sha256')!=expected['candidate_receipt_sha256'] or actual.get('source_sha256')!=expected['source_sha256']:raise ValueError('foreign candidate/source acknowledgment cannot be rebound')
    actual_hashes=set();expected_hashes=set()
    def inspect(a,e,path=()):
        if isinstance(e,dict):
            if not isinstance(a,dict) or set(a)!=set(e):raise ValueError('acknowledgment shape/key mismatch')
            for key in e:inspect(a[key],e[key],path+(key,))
        elif isinstance(e,str) and re.fullmatch('[0-9a-f]{64}',e):
            if not isinstance(a,str) or not re.fullmatch('[0-9a-f]{64}',a):raise ValueError('malformed metadata hash')
            actual_hashes.add(a);expected_hashes.add(e)
            if path[-1]=='revision' and a!=e:raise ValueError('stale endpoint revision')
        elif a!=e:raise ValueError('attention acknowledgment mode/status/judgment differs')
    inspect(actual,expected)
    if actual_hashes!=expected_hashes:
        # Missing copied constants can only come from a byte-verified saved request.
        import hashlib,json
        proof_path=request_proof.get('request_file')
        if not proof_path or not request_proof.get('expected_snapshot') or not actual_hashes<=expected_hashes:raise ValueError('unknown/missing metadata hash identity')
        from pathlib import Path
        saved=Path(proof_path)
        if hashlib.sha256(saved.read_bytes()).hexdigest()!=request_proof.get('request_sha256'):raise ValueError('saved request proof changed')
        body=json.loads(saved.read_text())['body']
        if hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()!=request_proof['body_sha256']:raise ValueError('saved request body changed')
    if actual==expected:return deepcopy(report),[]
    result=deepcopy(report);result['connector_paint_ack']=deepcopy(expected)
    return result,[{'operation':'reassociate constant attention-only metadata from the exact same saved native API request','same_candidate_receipt_and_source':True,'all_model_hashes_from_exact_request':True,'copied_constant_hash_set_complete':actual_hashes==expected_hashes,'all_quality_fields_unchanged':True,'body_sha256':request_proof['body_sha256']}]

def bind_from_same_request(report,snapshot,proof):
    """Recover machine-field association only with exact saved request/response proof.

    A short model copy error can put a policy hash in a raster field. Such a hash
    is accepted only if it is in the SAME proven packet, all acknowledgment hash
    identities are present, and source/candidate/revision identity remain exact.
    No quality field is edited or supplied by this operation.
    """
    import re
    if proof.get('expected_snapshot')!={'revision':snapshot['revision'],'evidence_hashes':snapshot['evidence_hashes']}:raise ValueError('request snapshot proof does not match native candidate')
    if report.get('revision')!=snapshot['revision']:raise ValueError('foreign/stale verifier revision')
    result,operations=bind_attention_ack(report,proof['expected_ack'],proof)
    actual=report.get('evidence_hashes');expected=snapshot['evidence_hashes']
    if not isinstance(actual,dict) or set(actual)!=set(expected):raise ValueError('incomplete verifier hash key set')
    def hashes(value):
        if isinstance(value,dict):return set().union(*(hashes(v) for v in value.values())) if value else set()
        if isinstance(value,list):return set().union(*(hashes(v) for v in value)) if value else set()
        return {value} if isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) else set()
    allowed=hashes(proof['expected_ack'])|set(expected.values())
    if any(value not in allowed for value in actual.values()):raise ValueError('unknown/foreign hash absent from actual request')
    if actual!=expected:
        result['evidence_hashes']=deepcopy(expected);operations.append({'operation':'reassociate machine evidence fields from exact same saved request snapshot; no unknown hash or quality judgment introduced','body_sha256':proof['body_sha256'],'all_quality_fields_unchanged':True,'source_mapping':actual,'canonical_mapping':expected})
    return result,operations

def bind_uncertain_adjudications(report,state):
 """Move actual not_required judgments to their exact native uncertainty slot."""
 import copy
 out=copy.deepcopy(report);required={x['id'] for x in state['required']};uncertain={x['id'] for x in state['uncertain']};operations=[];kept=[]
 reviews=out.setdefault('uncertainty_reviews',[]);seen={x['id'] for x in reviews}
 for item in out['not_required']:
  if item.get('id') in uncertain and item['id'] not in required:
   if set(item)!={'id','evidence'}:raise ValueError('ambiguous uncertainty adjudication')
   if item['id'] in seen:
    existing=next(x for x in reviews if x['id']==item['id'])
    if existing.get('decision')!='uncertain':raise ValueError('conflicting duplicate uncertainty disposition')
    operations.append({'operation':'exclude wrong confirmed-partition slot; preserve explicit native uncertain review conservatively','unapplied_wrong_slot_model_entry':item,'retained_native_review':existing});continue
   reviews.append({**item,'decision':'not_required'});seen.add(item['id']);operations.append({'operation':'same actual not_required judgment in native uncertainty slot','id':item['id'],'evidence':item['evidence']})
  else:kept.append(item)
 out['not_required']=kept
 retained=[]
 for ident in out.get('unresolved_ids',[]):
  if ident in uncertain and ident not in required:
   existing=next((x for x in reviews if x['id']==ident),None)
   if existing is None:
    # The model explicitly said unresolved, not resolved or a false positive.
    original=next(x for x in state['uncertain'] if x['id']==ident)
    existing={'id':ident,'decision':'uncertain','evidence':'Model explicitly retained this tracked uncertainty in unresolved_ids; no resolution or promotion claimed. Original finding: '+original.get('description',ident)};reviews.append(existing)
   operations.append({'operation':'exclude uncertainty ID from confirmed-only partition; keep actual explicit uncertainty review or unresolved state','id':ident,'retained_review':existing})
  else:retained.append(ident)
 if 'unresolved_ids' in out:out['unresolved_ids']=retained
 resolved=[]
 for ident in out.get('resolved_ids',[]):
  if ident in uncertain and ident not in required:
   existing=next((x for x in reviews if x['id']==ident),None)
   operations.append({'operation':'wrong confirmed-only resolution slot cannot override explicit uncertainty review; without evidence native default remains uncertain','id':ident,'actual_native_uncertainty_review':existing})
  else:resolved.append(ident)
 if 'resolved_ids' in out:out['resolved_ids']=resolved
 return out,operations

def bind_host_ack(report,proof):
 """Host owns cryptographic packet metadata; model owns every visual judgment.

 The exact saved request contains this packet. The exact saved provider response
 must contain the supplied report's acknowledgment. This never rewrites an issue,
 observation, concern review, quality disposition or source/current evidence text.
 """
 import hashlib,json,re
 from pathlib import Path
 import live_api,bounded_trace,planner_packet_transport
 request=Path(proof['request_file']);response=Path(proof['response_file'])
 if hashlib.sha256(request.read_bytes()).hexdigest()!=proof['request_sha256'] or hashlib.sha256(response.read_bytes()).hexdigest()!=proof['provider_response_sha256']:raise ValueError('saved request/response provenance changed')
 body=json.loads(request.read_text())['body']
 if hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()!=proof['body_sha256']:raise ValueError('request body changed')
 text,calls,_=live_api.extract(json.loads(response.read_text()),'chat_completions');original,_=bounded_trace.parse_model_object(text)
 if calls or original.get('connector_paint_ack')!=report.get('connector_paint_ack'):raise ValueError('actual model acknowledgment provenance mismatch')
 expected=proof['expected_ack'];actual=report.get('connector_paint_ack')
 # Verify the desired metadata is present verbatim in the actual input, not caller-invented.
 supplied=[]
 for message in body['messages']:
  if not isinstance(message.get('content'),list):continue
  for part in message['content']:
   if part.get('type')!='text':continue
   try:packet=planner_packet_transport.decode_wire(part['text'])
   except (ValueError,KeyError,TypeError):continue
   if isinstance(packet,dict) and 'connector_paint_ack_required_exact' in packet:supplied.append(packet['connector_paint_ack_required_exact'])
 if supplied!=[expected]:raise ValueError('ack metadata is not exact saved input')
 def validate(a,e):
  if isinstance(e,dict):
   if not isinstance(a,dict) or set(a)!=set(e):raise ValueError('ack shape differs; not a machine-copy error')
   for key in e:validate(a[key],e[key])
  elif isinstance(e,str) and re.fullmatch('[0-9a-f]{64}',e):
   if not isinstance(a,str):raise ValueError('non-string machine metadata field')
  elif a!=e:raise ValueError('non-cryptographic ack policy field differs')
 result=deepcopy(report);machine=deepcopy(actual);relocations=[]
 if isinstance(machine,dict):
  quality_fields=('resolved_ids','unresolved_ids','not_required','new_required_findings','new_uncertain_findings','protected_regressions','uncertainty_reviews','pending_observation_reviews','connector_visual_concerns','connector_concern_reviews','current_bindings')
  for field in quality_fields:
   if field not in machine:continue
   value=machine.pop(field)
   if not isinstance(value,list):raise ValueError('misnested verifier field must retain its actual array type')
   if field in result and result[field]!=value:raise ValueError('conflicting actual root/nested quality fields cannot be chosen by host')
   result[field]=deepcopy(value);relocations.append({'operation':'lossless relocation of actual verifier field from machine acknowledgment to report root; complete values/evidence unchanged','original_pointer':'/connector_paint_ack/'+field,'effective_pointer':'/'+field,'actual_value':value,'no_quality_judgment_added':True})
  candidate_machine=machine.get('candidate')
  if isinstance(candidate_machine,dict):
   for field in ('field_status','use'):
    if field not in candidate_machine:continue
    value=candidate_machine.pop(field)
    if field not in expected or value!=expected[field] or field in machine and machine[field]!=value:raise ValueError('misnested machine policy differs from exact input')
    machine[field]=value;relocations.append({'operation':'relocate exact input policy constant from candidate subobject to acknowledgment root','field':field,'actual_policy_value':value})
 if machine is not None:validate(machine,expected)
 result['connector_paint_ack']=deepcopy(expected)
 envelope=[{'operation':'host-bound cryptographic envelope from byte-verified SAME input and provider output; model copy retained in original raw','original_machine_ack':actual,'canonical_machine_ack':expected,'body_sha256':proof['body_sha256'],'all_model_visual_judgments_unchanged':True}] if actual!=expected else []
 return result,relocations+envelope

def omit_incomplete_noop_uncertainty_reviews(report,state):
 """An evidence-free 'still uncertain' entry grants no change or repair authority."""
 result=deepcopy(report);tracked={x['id'] for x in state['uncertain']};kept=[];audit=[]
 for review in result.get('uncertainty_reviews',[]):
  if review.get('decision')=='confirmed' and 'container_id' in review and review['container_id'] is None:
   del review['container_id'];audit.append({'operation':'omit null optional promotion container; native absence explicitly means no container, no targets/evidence/decision changed','id':review.get('id'),'no_quality_effect':True})
  if review.get('id') in tracked and review.get('decision')=='unresolved':
   original=deepcopy(review);review['decision']='uncertain';audit.append({'operation':'unresolved prior uncertainty stays uncertain; no confirmation or repair credit','original_model_entry':original})
  if review.get('id') in tracked and review.get('decision')=='uncertain' and not review.get('evidence'):
   audit.append({'operation':'omit incomplete no-op review; native default keeps exact prior uncertainty, no promotion/resolution','original_model_entry':review});continue
  kept.append(review)
 if 'uncertainty_reviews' in result:result['uncertainty_reviews']=kept
 return result,audit

def bind_region_coverage_conservatively(report,frames):
 """Unresolvable region references can only reduce certified coverage."""
 result=deepcopy(report);known=[x['frame_id'] for x in frames];allowed=set(known);audit=[]
 for key in ('examined_regions','unresolved_regions'):
  values=result.get(key)
  if not isinstance(values,list):raise ValueError('region references must be an array')
  if any(not isinstance(x,str) for x in values):
   original_values=deepcopy(values);refs=[]
   for value in values:
    if isinstance(value,str):refs.append(value)
    elif isinstance(value,dict) and isinstance(value.get('frame_id'),str):refs.append(value['frame_id'])
    else:raise ValueError('region object has no exact frame_id reference')
   values=refs;result[key]=values;audit.append({'operation':'extract explicitly supplied frame_id from actual model region objects; no new examined claim','field':key,'actual_model_objects':original_values,'effective_ids':values})
  unknown=[x for x in values if x not in allowed];dedup=list(dict.fromkeys(x for x in values if x in allowed))
  if unknown and key=='unresolved_regions':dedup=known[:]
  if unknown or dedup!=values:
   audit.append({'operation':'conservative native region coverage; never assert an unknown region examined','field':key,'actual_model_values':values,'unknown_references':unknown,'effective_native_values':dedup,'unknown_unresolved_region_scope':'all known regions remain uncertified' if unknown and key=='unresolved_regions' else None});result[key]=dedup
 return result,audit

def reject_impossible_resolution_credit(report,state,candidate):
 """Enforce native unchanged-SVG rule conservatively; no fabricated false-positive pass."""
 result=deepcopy(report);audit=[]
 if candidate['revision']!=state['revision']:return result,audit
 invalid=result.get('resolved_ids',[])
 if invalid:
  result['unresolved_ids']=list(dict.fromkeys(result.get('unresolved_ids',[])+invalid));result['resolved_ids']=[]
  audit.append({'operation':'no repair credit on unchanged SVG; retain unresolved state rather than invent not_required judgment','actual_model_resolved_ids':invalid,'before_revision':state['revision'],'candidate_revision':candidate['revision']})
 reviews=[]
 for review in result.get('uncertainty_reviews',[]):
  if review.get('decision')=='resolved':
   audit.append({'operation':'unchanged SVG cannot certify repaired uncertainty; native default retains previous uncertainty','unaccepted_original_model_claim':review});continue
  reviews.append(review)
 if 'uncertainty_reviews' in result:result['uncertainty_reviews']=reviews
 return result,audit

def complete_unreported_finding_collections(report,frames):
 """No items reported != certified absence: retain global coverage uncertainty."""
 result=deepcopy(report);missing=[]
 for key in ('new_required_findings','new_uncertain_findings'):
  if key not in result or result[key] is None:result[key]=[];missing.append(key)
 if not missing:return result,[]
 prior=deepcopy(result.get('unresolved_regions'));result['unresolved_regions']=[x['frame_id'] for x in frames]
 return result,[{'operation':'missing new-finding collection means no items reported, not absence certified; all regions remain uncertified','missing_fields':missing,'original_unresolved_regions':prior,'effective_unresolved_regions':result['unresolved_regions'],'original_model_report_preserved':True,'no_visual_pass_can_be_inferred':True}]

def withhold_unlocalized_target_credit(report,state):
 """Scope sanitation cannot turn an unlocalized finding into a certified pass."""
 result=deepcopy(report);blocked={x['id'] for x in state['required']+state['uncertain'] if x.get('unresolved_target_references')};required={x['id'] for x in state['required']};audit=[]
 rejected=set(result.get('resolved_ids',[]))&blocked
 false_positives=[x for x in result.get('not_required',[]) if x.get('id') in blocked];rejected.update(x['id'] for x in false_positives)
 result['resolved_ids']=[x for x in result.get('resolved_ids',[]) if x not in blocked];result['not_required']=[x for x in result.get('not_required',[]) if x.get('id') not in blocked]
 result['unresolved_ids']=list(dict.fromkeys(result.get('unresolved_ids',[])+sorted(rejected&required)))
 if rejected:audit.append({'operation':'unlocalized target cannot gain positive closure credit; original claims retained in source response','unaccepted_resolution_ids':sorted(rejected),'unaccepted_not_required_entries':false_positives})
 reviews=[]
 for review in result.get('uncertainty_reviews',[]):
  if review.get('id') in blocked and review.get('decision') in ('resolved','not_required'):
   audit.append({'operation':'unlocalized uncertainty retains native unresolved default','unaccepted_original_claim':review});continue
  reviews.append(review)
 if 'uncertainty_reviews' in result:result['uncertainty_reviews']=reviews
 return result,audit

def conservative_partition_conflicts(report,required_ids=None):
 """Contradictory closure claims never silently choose the positive disposition."""
 result=deepcopy(report);audit=[];resolved=list(dict.fromkeys(result['resolved_ids']));unresolved=list(dict.fromkeys(result['unresolved_ids']));negative=set(unresolved);positive=set(resolved);false_ids=[x.get('id') for x in result['not_required']]
 conflicts=(negative&positive)|(set(false_ids)&(negative|positive))|{x for x in false_ids if false_ids.count(x)>1}
 if conflicts:
  result['resolved_ids']=[x for x in resolved if x not in conflicts];result['unresolved_ids']=list(dict.fromkeys(unresolved+sorted(conflicts)));result['not_required']=[x for x in result['not_required'] if x.get('id') not in conflicts]
  audit.append({'operation':'conflicting duplicate partition dispositions remain unresolved; no positive claim selected','conflicting_ids':sorted(conflicts),'actual_model_resolved_ids':report['resolved_ids'],'actual_model_unresolved_ids':report['unresolved_ids'],'actual_model_not_required':report['not_required']})
 else:
  result['resolved_ids']=resolved;result['unresolved_ids']=unresolved
  if resolved!=report['resolved_ids'] or unresolved!=report['unresolved_ids']:audit.append({'operation':'coalesce identical repeated ID in same disposition; no state change'})
 if required_ids is not None:
  expected=set(required_ids);seen=set(result['resolved_ids']+result['unresolved_ids']+[x['id'] for x in result['not_required']])
  if seen-expected:raise ValueError('unknown partition findings cannot be silently dropped or guessed')
  missing=sorted(expected-seen)
  if missing:
   result['unresolved_ids']+=missing;audit.append({'operation':'unreported disposition cannot remove an existing confirmed obligation; exact tracked IDs remain natively unresolved','unreported_required_ids':missing,'original_model_dispositions_preserved':True,'no_model_judgment_or_quality_pass_fabricated':True})
 return result,audit

def bind_exact_finding_references(report,state):
 """Canonical role namespaces via unique immutable source_issue_id, no fuzzy ID matching."""
 result=deepcopy(report);tracked=state['required']+state['uncertain'];known={x['id'] for x in tracked};audit=[]
 def exact(ident):
  if not isinstance(ident,str) or ident in known:return ident
  raw=ident.split(':',1)[1] if ident.startswith(('main:','semantic:')) else ident
  matches=[x['id'] for x in tracked if x.get('source_issue_id') in (ident,raw)]
  if len(matches)==1:
   audit.append({'operation':'same exact immutable source finding; role namespace metadata only','original_id':ident,'native_id':matches[0]});return matches[0]
  return ident
 for key in ('resolved_ids','unresolved_ids'):
  if isinstance(result.get(key),list):result[key]=[exact(x) for x in result[key]]
 for key in ('not_required','uncertainty_reviews','current_bindings'):
  for entry in result.get(key,[]):
   if isinstance(entry,dict) and 'id' in entry:entry['id']=exact(entry['id'])
 return result,audit

def coalesce_uncertainty_reviews(report):
 """Combine actual same-decision evidence; conflicting duplicates retain uncertainty."""
 result=deepcopy(report);rows=result.get('uncertainty_reviews',[])
 if not isinstance(rows,list):raise ValueError('uncertainty_reviews must be array')
 grouped={}
 for row in rows:
  if not isinstance(row,dict) or not isinstance(row.get('id'),str):raise ValueError('actual uncertainty review identity required')
  grouped.setdefault(row['id'],[]).append(row)
 kept=[];audit=[]
 for ident,entries in grouped.items():
  if len(entries)==1:kept.extend(entries);continue
  combined={};conflict=False;evidence=[]
  for entry in entries:
   for key,value in entry.items():
    if key=='evidence':
     if isinstance(value,str) and value and value not in evidence:evidence.append(value)
     continue
    if key in combined and combined[key]!=value:conflict=True
    combined[key]=value
  if conflict:
   audit.append({'operation':'conflicting duplicate uncertainty reviews grant no promotion or resolution; native prior uncertainty retained','id':ident,'original_model_entries':entries});continue
  if evidence:combined['evidence']='\n\n'.join(evidence)
  kept.append(combined);audit.append({'operation':'coalesce same-ID same-decision reviews; all actual evidence strings retained without new judgment','id':ident,'original_model_entries':entries,'effective_review':combined})
 if 'uncertainty_reviews' in result:result['uncertainty_reviews']=kept
 return result,audit
