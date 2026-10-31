"""Bind planning references to immutable detector findings without new judgments."""
from copy import deepcopy

def bind(plan,tracked,valid_ids,additional_unplanned_source_ids=()):
    result=deepcopy(plan);audit=[];by_id={row['id']:row for row in tracked}
    if len(by_id)!=len(tracked):raise ValueError('duplicate tracked identity')
    rows=result.get('issues')
    if rows is None:
        refs=result.pop('issue_ids',None)
        if not isinstance(refs,list) or any(not isinstance(ref,str) for ref in refs) or len(refs)!=len(set(refs)):raise ValueError('planner references must partition exact tracked queue')
        mapping={}
        for ref in refs:
            if ref in by_id:mapping[ref]=ref;continue
            raw=ref.split(':',1)[-1]
            matches=[item['id'] for item in tracked if item.get('source_issue_id') in (ref,raw)]
            if len(matches)!=1:raise ValueError('unknown/ambiguous raw source finding reference')
            mapping[ref]=matches[0]
        missing=set(by_id)-set(mapping.values())
        generated_review_ids={ident for ident in missing if by_id[ident].get('source_issue_id','').startswith('model-review:')}
        actual_new_uncertain={ident for ident in missing if by_id[ident].get('decision')=='uncertain' and by_id[ident].get('source_issue_id') in set(additional_unplanned_source_ids)}
        generated_review_ids|=actual_new_uncertain
        if missing!=generated_review_ids or len(set(mapping.values()))!=len(refs):raise ValueError('planner references must partition exact tracked queue')
        if actual_new_uncertain:audit.append({'operation':'retain actual same-second-call new uncertain findings as unplanned; no repair, resolution, or visual judgment supplied by host','native_ids':sorted(actual_new_uncertain),'actual_source_ids':[by_id[x]['source_issue_id'] for x in sorted(actual_new_uncertain)]})
        # These are actual model review findings, introduced during schema lowering.
        # Preserve them as unplanned tracked findings; never supply a repair/resolution.
        for ident in sorted(generated_review_ids):mapping[ident]=ident;refs.append(ident)

        result['issues']=[deepcopy(by_id[mapping[ident]]) for ident in refs]
        for program in result.get('programs',[]):program['issue_ids']=[mapping.get(ident,ident) for ident in program.get('issue_ids',[])]
        for reason in result.get('unresolved_reasons',[]):
            if isinstance(reason,dict) and 'issue_id' in reason:reason['issue_id']=mapping.get(reason['issue_id'],reason['issue_id'])
        return result,[{'operation':'bind ID-only references to exact frozen detection findings','mapping':mapping},*audit]
    if not isinstance(rows,list):raise ValueError('planner issues or issue_ids required')
    seen=set();mapping={};effective=[]
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('id'),str):raise ValueError('invalid planner issue echo')
        source=row.get('source_issue_id',row['id'].split(':',1)[-1])
        candidates=[item for item in tracked if item.get('source_issue_id',item['id'].split(':',1)[-1])==source]
        if len(candidates)!=1:raise ValueError('ambiguous source finding reference')
        original=candidates[0];comparison=deepcopy(row);expected=deepcopy(original)
        for value in (comparison,expected):
            for key in ('id','source_issue_id','source_role'):value.pop(key,None)
        if 'container_id' not in expected and comparison.get('container_id')==source and source not in valid_ids:
            comparison.pop('container_id');audit.append({'issue_id':row['id'],'operation':'discard nonexistent container equal only to raw finding identity; original detector supplied no container','value':source})
        if comparison!=expected:raise ValueError('planner changed actual finding quality, targets, geometry or evidence')
        if original['id'] in seen:raise ValueError('duplicate planner finding reference')
        seen.add(original['id']);mapping[row['id']]=original['id'];effective.append(deepcopy(original))
        if row!=original:audit.append({'operation':'bind planning echo to exact frozen finding; only provenance namespace metadata differs','model_id':row['id'],'native_id':original['id']})
    if seen!=set(by_id):raise ValueError('planner omitted tracked findings')
    result['issues']=effective
    for program in result.get('programs',[]):program['issue_ids']=[mapping.get(ident,ident) for ident in program.get('issue_ids',[])]
    for reason in result.get('unresolved_reasons',[]):
        if isinstance(reason,dict) and 'issue_id' in reason:reason['issue_id']=mapping.get(reason['issue_id'],reason['issue_id'])
    return result,audit


def same_data_constructor_envelope_intent(old,new):
 """Recognize only the documented data-envelope relocation, never edit a program."""
 if old==new:return True
 if {k:v for k,v in old.items() if k!='args'}!={k:v for k,v in new.items() if k!='args'}:return False
 a=old.get('args');b=new.get('args')
 if not isinstance(a,dict) or not isinstance(b,dict):return False
 if a.get('method')=='sp_replace' and b.get('method')=='sp_replace':
  if {k:v for k,v in a.items() if k!='args'}!={k:v for k,v in b.items() if k!='args'}:return False
  a=a.get('args');b=b.get('args')
 if not isinstance(a,dict) or not isinstance(b,dict) or not {'kind','data'}<=set(a) or set(a)!=set(b) or a['kind'] not in ('formula','arrow','geometry') or b['kind']!='data' or not isinstance(a['data'],dict) or 'kind' in a['data']:return False
 if {k:v for k,v in a.items() if k not in ('kind','data')}!={k:v for k,v in b.items() if k not in ('kind','data')}:return False
 return b['data']=={'kind':a['kind'],**a['data']}
