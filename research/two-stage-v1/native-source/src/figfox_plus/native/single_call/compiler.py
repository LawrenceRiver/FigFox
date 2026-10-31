"""Compile a saved proposal into schema-valid independent local operations.

Never changes a diagnosis, target, argument, or original evidence. Invalid
operations and their declared dependants remain explicitly blocked.
"""
from copy import deepcopy
import xml.etree.ElementTree as ET
from .contract import normalize_plan,validate_plan
from .qlist import MAIN_ORDER


def compile_plan(raw,manifest):
    plan,normalizations=normalize_plan(raw,manifest)
    steps=plan.get('ask_data',[])
    if not isinstance(steps,list) or any(not isinstance(s,dict) or not s.get('id') for s in steps):
        raise ValueError('invalid operation identities')
    ids=[s['id'] for s in steps]
    if len(ids)!=len(set(ids)):raise ValueError('duplicate operation identities')
    compiled=deepcopy(plan);compiled['ask_data']=[]
    for issue in compiled.get('issues',[]):
        if issue.get('decision')=='confirmed':issue.setdefault('unresolved_reason','No compiled operation yet.')
    # Validate immutable source identities, diagnoses, scope declarations and audit
    # completeness before admitting ANY mutation. Do not repair stale inputs.
    validate_plan(compiled,manifest,_defer_relation_objects=True)
    issues={i['id']:i for i in plan['issues']};by={s['id']:s for s in steps}
    index={s['id']:i for i,s in enumerate(steps)}
    order={};data_deps={};previous={}
    for s in steps:
        sid=s['id'];deps=s.get('depends_on',[])
        if not isinstance(deps,list):raise ValueError('invalid dependency list')
        data_deps[sid]=set(deps)
        if s.get('when'):data_deps[sid].add(s['when'].get('step'))
        order[sid]=set(data_deps[sid])
        if s.get('issue_id') in previous:order[sid].add(previous[s['issue_id']])
        previous[s.get('issue_id')]=sid
    for a in steps:
        ia=issues.get(a.get('issue_id'),{});ca=ia.get('category')
        for b in steps:
            ib=issues.get(b.get('issue_id'),{});cb=ib.get('category')
            if ia.get('image_id')==ib.get('image_id') and ca in MAIN_ORDER and cb in MAIN_ORDER and MAIN_ORDER.index(ca)<MAIN_ORDER.index(cb):
                order[b['id']].add(a['id'])
    pending=set(ids);resolved=set();blocked=[];failed=set()
    while pending:
        ready=[sid for sid in pending if order[sid]<=resolved]
        # Unknown dependencies and genuine cycles are never guessed away.
        if not ready:
            for sid in sorted(pending,key=index.get):
                blocked.append({'operation_id':sid,'issue_id':by[sid].get('issue_id'),'reason':'unresolved dependency or category-order cycle'})
            break
        sid=min(ready,key=index.get);step=by[sid];reason=None
        if data_deps[sid]&failed:reason='predecessor was rejected during compilation'
        else:
            trial=deepcopy(compiled);trial['ask_data'].append(step)
            try:validate_plan(trial,manifest,_defer_relation_objects=True)
            except (ValueError,KeyError,TypeError) as exc:reason=str(exc)
            else:compiled=trial
        if reason:
            failed.add(sid);blocked.append({'operation_id':sid,'issue_id':step.get('issue_id'),'reason':reason})
        pending.remove(sid);resolved.add(sid)
    # A rejected replacement must not leave an earlier deletion committed.
    failed_issues={b['issue_id'] for b in blocked}
    destructive_issues=set()
    for step in steps:
        ops=step.get('args',{}).get('operations',[]) if step.get('method')=='bp_program' else [step]
        if any(op.get('method') in {'bp_remove','sp_replace','sp_photo'} for op in ops):
            destructive_issues.add(step.get('issue_id'))
    unsafe_issues=failed_issues&destructive_issues
    removed={s['id'] for s in compiled['ask_data'] if s['issue_id'] in unsafe_issues}
    while True:
        extra={s['id'] for s in compiled['ask_data'] if data_deps[s['id']]&removed}
        if extra<=removed:break
        removed.update(extra)
    for s in compiled['ask_data']:
        if s['id'] in removed:
            blocked.append({'operation_id':s['id'],'issue_id':s['issue_id'],
                            'reason':'incomplete destructive repair or dependency; preserve original objects'})
    compiled['ask_data']=[s for s in compiled['ask_data'] if s['id'] not in removed]
    # Relations may name objects created by later admitted steps. Check membership
    # only after compiling the whole program, with the ordinary strict validator
    # still required before execution. Never silently discard a required check:
    # an unresolved participant blocks ALL mutations for that image.
    known={im:set(v['object_ids']) for im,v in manifest['images'].items()}
    for step in compiled['ask_data']:
        im=issues[step['issue_id']]['image_id']
        ops=step['args']['operations'] if step['method']=='bp_program' else [step]
        for op in ops:
            if op['method']=='bp_add':
                known[im].update(n.get('id') for n in ET.fromstring('<g>'+op['args']['svg']+'</g>').iter() if n.get('id'))
    blocked_images={im for im,rules in compiled.get('relations',{}).items()
                    if any(not {r['subject_id'],r['object_id']}<=known[im] for r in rules)}
    unresolved_relations={im:deepcopy(compiled['relations'][im]) for im in sorted(blocked_images)}
    removed={s['id'] for s in compiled['ask_data'] if issues[s['issue_id']]['image_id'] in blocked_images}
    while True:
        extra={s['id'] for s in compiled['ask_data'] if data_deps[s['id']]&removed}
        if extra<=removed:break
        removed.update(extra)
    for s in compiled['ask_data']:
        if s['id'] in removed:
            blocked.append({'operation_id':s['id'],'issue_id':s['issue_id'],
                            'reason':'required relation participant unavailable; image or dependency blocked'})
    compiled['ask_data']=[s for s in compiled['ask_data'] if s['id'] not in removed]
    for im in blocked_images:compiled['relations'].pop(im)
    compiled['unresolved_relations']=unresolved_relations
    accepted={s['issue_id'] for s in compiled['ask_data']}
    for issue,original in zip(compiled['issues'],plan['issues']):
        reasons=[b['reason'] for b in blocked if b['issue_id']==issue['id']]
        if issue['decision']=='confirmed':
            if reasons:issue['unresolved_reason']='Compiler blocked some/all operations: '+'; '.join(dict.fromkeys(reasons))
            elif issue['id'] in accepted:
                if 'unresolved_reason' not in original:issue.pop('unresolved_reason',None)
            else:issue['unresolved_reason']=original.get('unresolved_reason') or 'No executable operation was provided.'
    validate_plan(compiled,manifest)
    result_ids=[s['id'] for s in compiled['ask_data']]
    return compiled,{'normalizations':normalizations,'blocked':blocked,
        'blocked_images':sorted(blocked_images),'unresolved_relations':unresolved_relations,
        'original_step_order':ids,'execution_step_order':result_ids,
        'reordered':result_ids!=[i for i in ids if i in result_ids],
        'diagnoses_and_parameters_invented':False,'visual_acceptance':False}
