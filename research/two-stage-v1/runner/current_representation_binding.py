"""Rebind unresolved findings to exact surviving DOM ancestors after scoped execution.

This is structural provenance, not visual adjudication. No finding is resolved,
reclassified or dropped; absent objects never become fabricated dummy SVG nodes.
"""
from pathlib import Path
from copy import deepcopy
import xml.etree.ElementTree as ET
import run_ablation as r

def bind(report,state,candidate):
 # Native before checkpoint belongs to this run; candidate_folder is run/round/candidate.
 current=Path(candidate['candidate_folder'])/'current.svg';run=current.parents[2];before=run/'checkpoint/current.svg'
 old=ET.parse(before).getroot();new=ET.parse(current).getroot();old_nodes={n.get('id'):n for n in old.iter() if n.get('id')};current_ids={n.get('id') for n in new.iter() if n.get('id')};parents={c:p for p in old.iter() for c in p}
 scopes=set()
 for item in candidate.get('native_result',{}).get('rcd',[]):
  if item.get('tool_receipt',{}).get('status')=='executed':scopes.update(item.get('effective_target_ids',item.get('target_ids',[])))
 result=deepcopy(report);audit=[];known_uncertain={x['id'] for x in state['uncertain']};reviews=[]
 for entry in result.get('uncertainty_reviews',[]):
  refs=[v for key in ('target_ids','neighbor_ids') for v in entry.get(key,[])]+([entry['container_id']] if entry.get('container_id') else [])
  if entry.get('id') in known_uncertain and entry.get('decision')=='confirmed' and set(refs)-current_ids:
   audit.append({'operation':'withhold unlocalizable uncertainty promotion; exact prior uncertainty retained, original model confirmation preserved separately','original_model_review':entry,'missing_current_ids':sorted(set(refs)-current_ids),'no_positive_closure_or_edit_authority_added':True});continue
  reviews.append(entry)
 if 'uncertainty_reviews' in result:result['uncertainty_reviews']=reviews
 bindings=result.setdefault('current_bindings',[]);existing={x['id'] for x in bindings};review={x['id']:x['decision'] for x in reviews}
 tracked=[x for x in state['required'] if x['id'] in report['unresolved_ids']]+[x for x in state['uncertain'] if review.get(x['id'],'uncertain')=='uncertain']
 for issue in tracked:
  if issue['id'] in existing:continue
  values=[v for key in ('target_ids','neighbor_ids') for v in issue.get(key,[])]+([issue['container_id']] if issue.get('container_id') else []);missing=set(values)-current_ids
  if not missing:continue
  mapping={}
  for ident in missing:
   if ident not in old_nodes:raise ValueError('missing finding object has no immutable before provenance')
   node=old_nodes[ident];ancestors=[];cursor=node
   while cursor is not None:
    ancestors.append(cursor.get('id'));cursor=parents.get(cursor)
   if not scopes.intersection(ancestors):raise ValueError('deleted reference outside exact executed program scope')
   replacement=next((x for x in ancestors if x in current_ids),None)
   if replacement is None:raise ValueError('no exact surviving ancestor; no dummy or guessed object allowed')
   mapping[ident]=replacement
  def refs(key):return list(dict.fromkeys(mapping.get(x,x) for x in issue.get(key,[])))
  evidence='Structural post-render binding only, not a visual pass: scoped native execution deleted '+str(sorted(missing))+'; exact surviving before-DOM ancestors in the rendered candidate are '+str(mapping)+'. Native disposition remains unresolved/uncertain; the original model judgment is retained separately. Original evidence: '+issue['current_evidence']
  binding={'id':issue['id'],'target_ids':refs('target_ids'),'neighbor_ids':refs('neighbor_ids'),'evidence':evidence}
  if issue.get('container_id'):binding['container_id']=mapping.get(issue['container_id'],issue['container_id'])
  bindings.append(binding);audit.append({'operation':'structural current-representation binding; unresolved status unchanged','id':issue['id'],'mapping':mapping,'before_svg_sha256':r.sha(before),'candidate_svg_sha256':r.sha(current),'executed_scope_ids':sorted(scopes),'no_svg_nodes_added':True})
 return result,audit
