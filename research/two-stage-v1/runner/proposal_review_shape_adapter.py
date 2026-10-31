"""Lossless lowering of actual finding-shaped model reviews into native syntax.

No host visual verdict is created: decision, targets and all evidence come from
that exact model review. Public observer-kind names alias native category names.
Original findings stay frozen; these are separate explicitly sourced findings.
"""
from copy import deepcopy
CATEGORY={'text_mask_overlap_group':'F','text_low_visible_ink':'F','continuous_orthogonal_path':'D'}
def normalize(payload,proposals):
 result=deepcopy(payload);audit=[];known={p['id']:p for p in proposals['proposals']};added=[];reviews=[]
 for raw in result.get('proposal_reviews',[]):
  if 'proposal_id' in raw:reviews.append(raw);continue
  ident=raw.get('id');kind=raw.get('kind',raw.get('category'));decision=raw.get('decision')
  if ident not in known or kind!=known[ident]['kind'] or kind not in CATEGORY or raw.get('category')!=kind or decision not in ('confirmed','uncertain'):raise ValueError('unsupported finding-shaped review; no category/decision inference')
  if 'target_ids' not in raw and isinstance(raw.get('target_id'),str):raw['target_ids']=[raw['target_id']]
  if not isinstance(raw.get('target_ids'),list) or set(raw['target_ids'])!=set(known[ident]['target_ids']):raise ValueError('review targets do not match actual proposal')
  for key in ('description','original_evidence','current_evidence'):
   if not isinstance(raw.get(key),str) or not raw[key].strip():raise ValueError('actual model evidence required')
  native_id='model-review:'+ident
  finding={'id':native_id,'image_id':'case','category':CATEGORY[kind],'decision':decision,'description':raw['description'],'original_evidence':raw['original_evidence'],'current_evidence':raw['current_evidence'],'target_ids':raw['target_ids'],'neighbor_ids':raw.get('neighbor_ids',[]),'container_id':raw.get('container_id')}
  added.append(finding);reviews.append({'proposal_id':ident,'decision':'required' if decision=='confirmed' else 'uncertain','issue_ids':[native_id],'source_evidence':raw['original_evidence'],'current_evidence':raw['current_evidence'],'necessity_reason':raw['description']})
  audit.append({'operation':'same actual model finding-shaped review lowered to native finding plus review reference','source_review':raw,'native_finding_id':native_id,'category_alias':{kind:CATEGORY[kind]},'decision_and_evidence_unchanged':True})
 result['proposal_reviews']=reviews;result['new_semantic_issues']=result.get('new_semantic_issues',[])+added
 return result,audit
