"""Validated, resumable local transactions shared by both constructor phases."""
from copy import deepcopy
import fcntl
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from .scene import digest, descendants, assert_target_scope, write_checkpoint
from .sandbox import run_code
from .quality import crop_gate, validate_contract, converge
from ..document import validate
from ..single_call.executor import _perform as _base_perform, _resolve_id, _relation_report
from ..tp_alarms import compare_reports
from ..tight_tp import measure_tight
from ..single_call.contract import MUTATIONS


def _perform(root,step,issue,original,folder,aliases,results):
    if step.get('method')=='bp_program':
        values=[];actual=[];reports=[]
        for index,child in enumerate(step['args']['operations']):
            value,args,child_reports=_perform(root,child,issue,original,folder/f'nested-{index}',aliases,results)
            if child.get('id'):results[child['id']]=deepcopy(value)
            values.append(value);actual.append(args);reports.extend(child_reports)
        return {'operations':values},{'operations':actual},reports
    if step.get('method')=='check_tp':
        report=_relation_report(root,issue.get('relations',[]),aliases)
        return report,deepcopy(step.get('args',{})),[]
    return _base_perform(root,step,issue,original,folder,aliases,results)


def _atomic_json(path,data):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(path)


def _contains_measure(value):
    if isinstance(value,dict):return '$measure' in value or any(_contains_measure(v) for v in value.values())
    if isinstance(value,list):return any(_contains_measure(v) for v in value)
    return False


def _measurement_references(value):
    refs=set()
    if isinstance(value,dict):
        if '$measure' in value:
            spec=value['$measure']
            if not isinstance(spec,dict) or not isinstance(spec.get('ids'),list) or any(not isinstance(x,str) for x in spec['ids']):raise ValueError('measurement requires explicit current object IDs')
            refs.update(spec['ids'])
        for child in value.values():refs.update(_measurement_references(child))
    elif isinstance(value,list):
        for child in value:refs.update(_measurement_references(child))
    return refs


def _walk_operations(operations):
    for operation in operations:
        yield operation
        if operation.get('method')=='bp_program':
            yield from _walk_operations(operation['args']['operations'])


def _compile_typed_scope(program,root):
    existing={n.get('id') for n in root.iter() if n.get('id')}
    created=set();writes=set();sources=[]
    def visit(operations,path):
        if not isinstance(operations,list):raise ValueError('typed operations must be array')
        for index,op in enumerate(operations):
            if not isinstance(op,dict) or not isinstance(op.get('target_ids'),list) or any(not isinstance(t,str) for t in op['target_ids']):raise ValueError('typed target_ids must be explicit strings')
            ids=set(op['target_ids']);where=path+[index]
            if not ids<=existing|created:raise ValueError('typed operation references unknown or not-yet-created ID')
            if op.get('method') in MUTATIONS|{'bp_program'}:
                writes.update(ids);sources.append({'path':where+['target_ids'],'target_ids':list(op['target_ids'])})
            args=op.get('args',{})
            if not isinstance(args,dict):raise ValueError('typed args must be object')
            for anchor in ('parent_id','before_id','after_id'):
                if anchor in args and args[anchor]!='@parent' and args[anchor] not in existing|created:raise ValueError('typed anchor references unknown or not-yet-created ID')
            if op.get('method') not in MUTATIONS|{'sample_colors','measure','check_tp','bp_program'}:raise ValueError('unsupported typed module method')
            if op.get('method')!='bp_program' and not _measurement_references(args)<=existing|created:raise ValueError('measurement references unknown or not-yet-created ID')
            if op.get('method')=='bp_program':visit(args.get('operations'),where+['args','operations'])
            if op.get('method')=='bp_add':
                fragment=ET.fromstring('<g>'+args.get('svg','')+'</g>')
                fresh=[n.get('id') for n in list(fragment.iter())[1:]]
                if not fresh or any(not i for i in fresh) or len(set(fresh))!=len(fresh) or set(fresh)&(existing|created):raise ValueError('new SVG IDs must be explicit and unique')
                created.update(fresh)
    visit(program.get('args',{}).get('operations',[]),['args','operations'])
    visit(program.get('convergence',{}).get('repairs',[]),['convergence','repairs'])
    return {'existing_write_ids':sorted(writes&existing),'created_write_ids':sorted(writes&created),'created_ids':sorted(created),'sources':sources,'basis':'explicit typed mutation target_ids only'}


def _execution_targets(program):
    if program.get('route')=='module_program':
        return program.get('compiled_scope',{}).get('existing_write_ids',[]) or program['target_ids']
    return program['target_ids']


def validate_programs(programs,issues,images):
    if not isinstance(programs,list) or not isinstance(issues,list):raise ValueError('programs and issues must be arrays')
    issue_map={i['id']:i for i in issues};seen={};last_order={};touched={};scope={};issue_sets={}
    result_ids={p.get('id') for p in programs if isinstance(p,dict) and isinstance(p.get('id'),str)}
    roots={im:ET.fromstring(Path(v['svg']).read_text()) for im,v in images.items()}
    for im,v in images.items():
        if digest(v['svg'])!=v['revision']:raise ValueError('input SVG revision changed')
        validate(roots[im])
    for p in programs:
        pid=p.get('id');im=p.get('image_id')
        if not isinstance(pid,str) or not pid or pid in seen:raise ValueError('program identity must be unique')
        if im not in images or p.get('base_revision')!=images[im]['revision']:raise ValueError('program base revision mismatch')
        if p.get('phase') not in ('preconstructor','reconstructor'):raise ValueError('unknown constructor phase')
        deps=p.get('depends_on',[])
        if not isinstance(deps,list) or any(d not in seen or seen[d]['image_id']!=im for d in deps):raise ValueError('dependencies must be previous same-image programs')
        trigger=p.get('when')
        if trigger is not None:
            if not isinstance(trigger,dict) or trigger.get('program') not in deps or trigger.get('status') not in ('failed','blocked','changed_unverified','executed_no_change'):raise ValueError('conditional trigger must name a preceding same-image dependency and supported execution status')
        refs=p.get('issue_ids')
        if not isinstance(refs,list) or not refs or any(r not in issue_map or issue_map[r]['image_id']!=im for r in refs):raise ValueError('unknown issue reference')
        selected=[issue_map[r] for r in refs]
        categories=[i.get('category') for i in selected]
        if any(c not in ('A','B','C','D','E','F','S1','S2','S3','S4') for c in categories):raise ValueError('unknown issue category')
        ranks=[ord(c)-ord('A') for c in categories if len(c)==1]
        if ranks:
            # Inspection priority is distinct from execution dependency order.
            last_order[im]=max(ranks)
        target_ids=p.get('target_ids')
        if not isinstance(target_ids,list) or not target_ids or any(not isinstance(t,str) for t in target_ids):raise ValueError('explicit target_ids required')
        allowed={t for i in selected for t in i.get('target_ids',[])+i.get('neighbor_ids',[])}
        allowed=descendants(roots[im],list(allowed))
        destructive=descendants(roots[im],list({t for i in selected for t in i.get('target_ids',[])}))
        if p.get('route')=='module_program':
            existing_ids={n.get('id') for n in roots[im].iter() if n.get('id')}
            if not set(target_ids)<=existing_ids:raise ValueError('declared target is unknown current object')
            p['compiled_scope']=_compile_typed_scope(p,roots[im])
            objects=descendants(roots[im],p['compiled_scope']['existing_write_ids'])
            destructive=objects
        else:
            p.pop('compiled_scope',None)
            if not set(target_ids)<=allowed:raise ValueError('target outside issue scope')
            objects=descendants(roots[im],target_ids)
        ancestors=set(deps)
        for dep in deps:ancestors.update(seen[dep]['_ancestors'])
        for old,old_targets in touched.get(im,[]):
            if objects & old_targets and old not in ancestors:raise ValueError('same-object programs require explicit dependency')
        touched.setdefault(im,[]).append((pid,objects))
        read_scope={n.get('id') for n in roots[im].iter() if n.get('id')}
        read_refs=set()
        rules=p.get('relations',[])
        if not isinstance(rules,list):raise ValueError('relations must be an array')
        for rule in rules:
            if not isinstance(rule,dict) or rule.get('predicate') not in ('contain','separate','legal_overlap'):raise ValueError('unsupported relation')
            if rule.get('subject_id') not in read_scope or rule.get('object_id') not in read_scope:raise ValueError('relation references unknown current object')
            read_refs.update((rule['subject_id'],rule['object_id']))
            if not isinstance(rule.get('reference_evidence'),str) or not rule['reference_evidence'].strip():raise ValueError('relation requires original evidence')
        convergence_refs=_measurement_references(p.get('convergence',{}))
        if not convergence_refs<=read_scope:raise ValueError('convergence measurement references unknown current object')
        read_refs.update(convergence_refs)
        validate_contract(p,selected,read_scope,objects)
        for check in p.get('convergence',{}).get('alignment_checks',[]):
            refs=check.get('target_ids',[])+check.get('reference_ids',[])
            if not set(refs)<=read_scope:raise ValueError('alignment check references unknown current object')
            read_refs.update(refs)
        if p.get('route')=='generated_python':
            if not set(target_ids)<=destructive:raise ValueError('generated replacement cannot target a mere neighbor')
            if not isinstance(p.get('source_code'),str) or not p['source_code'].strip():raise ValueError('source_code required')
        elif p.get('route')=='module_program':
            ops=p.get('args',{}).get('operations')
            if not isinstance(ops,list) or (not ops and not p.get('convergence',{}).get('repairs')):raise ValueError('module operations or convergence repairs required')
            created=set();existing={n.get('id') for n in roots[im].iter() if n.get('id')}
            for op in _walk_operations(ops):
                crop_gate(op,images[im]['original'])
                operation_id=op.get('id')
                if operation_id is not None:
                    if not isinstance(operation_id,str) or not operation_id or operation_id in result_ids:raise ValueError('operation result identity collides with another operation or program')
                    result_ids.add(operation_id)
                if op.get('method') not in MUTATIONS|{'sample_colors','measure','check_tp','bp_program'}:raise ValueError('unsupported module method')
                if not isinstance(op.get('args'),dict) or not isinstance(op.get('target_ids'),list):raise ValueError('operation args and target_ids required')
                if not set(op['target_ids'])<=((read_scope if op['method'] in ('measure','check_tp') else objects)|created):raise ValueError('operation outside declared transaction scope')
                expression_refs=set() if op['method']=='bp_program' else _measurement_references(op.get('args',{}))
                if not expression_refs<=read_scope|created:raise ValueError('measurement references unknown current object')
                read_refs.update(expression_refs)
                if op['method'] in ('measure','check_tp'):read_refs.update(op['target_ids'])
                if op['method'] in ('sp_replace','sp_photo','bp_remove') and not set(op['target_ids'])<=destructive|created:raise ValueError('destructive operation cannot target a mere neighbor')
                for name in ('parent_id','before_id','after_id'):
                    value=op['args'].get(name)
                    if value == '@parent' and name=='parent_id':
                        if set(op['target_ids'])&created:raise ValueError('new objects require explicit parent anchor')
                        parents={child:parent for parent in roots[im].iter() for child in parent}
                        by={n.get('id'):n for n in roots[im].iter() if n.get('id')}
                        selected_parents={parents.get(by[t]) for t in op['target_ids']}
                        if len(selected_parents)!=1 or None in selected_parents:raise ValueError('parent anchor requires one common existing container')
                    elif value is not None and value not in objects|created:raise ValueError('insertion anchor outside scope')
                if op['method']=='bp_add':
                    try:fragment=ET.fromstring('<g>'+op['args'].get('svg','')+'</g>')
                    except ET.ParseError as exc:raise ValueError('invalid insertion fragment') from exc
                    nodes=list(fragment.iter())[1:];fresh=[n.get('id') for n in nodes]
                    if not fresh or any(not i for i in fresh) or len(set(fresh))!=len(fresh) or set(fresh)&(existing|created):
                        raise ValueError('new SVG IDs must be explicit and unique')
                    created.update(fresh)
                if op['method'] in ('sp_photo','sample_colors'):
                    location=p.get('source_location',{})
                    if location.get('basis')!='original_semantic' or not location.get('description','').strip():raise ValueError('independent original semantic location required')
                    boxes=[op['args'].get('source_crop')] if op['method']=='sp_photo' else op['args'].get('regions')
                    if not isinstance(boxes,list) or not boxes:raise ValueError('original source requires literal boxes')
                    for box in boxes:
                        if not isinstance(box,list) or len(box)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in box) or min(box[2:])<=0:raise ValueError('original source requires literal finite xywh')
        else:raise ValueError('unsupported program route')
        p['read_only_references']=sorted(read_refs)
        seen[pid]=dict(p,_ancestors=ancestors);scope[pid]=objects;issue_sets[pid]=selected
    return issue_sets


def execute_programs(programs,issues,images,folder):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    with (folder/'execution.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _execute(programs,issues,images,folder)


def _execute(programs,issues,images,folder):
    selected=validate_programs(programs,issues,images)
    signature=hashlib.sha256(json.dumps({'programs':programs,'issues':issues,'images':images},sort_keys=True).encode()).hexdigest()
    path=folder/'state.json'
    if path.exists():
        state=json.loads(path.read_text())
        if state['signature']!=signature:raise ValueError('cannot resume a different execution plan')
        for data in state['images'].values():
            if digest(data['svg'])!=data['revision']:raise ValueError('checkpoint modified')
    else:
        state={'signature':signature,'images':{im:{k:v[k] for k in ('svg','png','revision','original')} for im,v in images.items()},'aliases':{im:{} for im in images},'rcd':[],'results':{}}
    done={r['program_id']:r for r in state['rcd']}
    for index,p in enumerate(programs):
        pid=p['id'];im=p['image_id']
        if pid in done:continue
        current=state['images'][im]
        record={'program_id':pid,'issue_ids':p['issue_ids'],'image_id':im,'phase':p['phase'],'route':p['route'],'before_revision':current['revision'],'after_revision':current['revision'],'target_ids':p['target_ids'],'rcd_predescription':p.get('rcd_predescription',''),'visual_acceptance':'pending','read_only_references':p.get('read_only_references',[]),'compiled_scope':deepcopy(p.get('compiled_scope')),'effective_target_ids':_execution_targets(p)}
        trigger=p.get('when');trigger_matched=True
        if trigger:
            actual=done[trigger['program']]['status'];trigger_matched=actual==trigger['status']
            record['trigger']={'program':trigger['program'],'expected_status':trigger['status'],'actual_status':actual,'matched':trigger_matched}
        if not trigger_matched:
            record.update(status='skipped_condition',reason='declared execution-status condition did not match')
        elif any(done[d]['status'] not in ('changed_unverified','executed_no_change') for d in p.get('depends_on',[]) if not trigger or d!=trigger['program']):
            record.update(status='blocked',error='dependency did not execute')
        else:
            try:
                before=ET.fromstring(Path(current['svg']).read_text());trial=deepcopy(before)
                local_results=deepcopy(state['results'])
                aliases=deepcopy(state['aliases'][im]);work=folder/f'program-{index:04d}';work.mkdir(exist_ok=True)
                rules=p.get('relations',[])
                initial=_relation_report(before,rules,aliases) if rules else None
                if p['route']=='generated_python':
                    attempt=work/'sandbox'
                    if attempt.exists():
                        # Crash before transaction commit: preserve old attempt, execute in a fresh isolated folder.
                        n=1
                        while (work/f'sandbox-{n}').exists():n+=1
                        attempt=work/f'sandbox-{n}'
                    snapshot_ids=sorted({_resolve_id(t,aliases) for q in selected[pid] for t in q.get('target_ids',[])+q.get('neighbor_ids',[])}|{_resolve_id(t,aliases) for t in p.get('read_only_references',[])})
                    tp_snapshot=measure_tight(trial,snapshot_ids)
                    tp_snapshot['revision']=current['revision']
                    result=run_code(p['source_code'],current['svg'],attempt,current_tp=tp_snapshot)
                    record['tool_receipt']=result
                    if result.get('status')!='executed':raise ValueError(result.get('error','sandbox execution failed'))
                    trial=ET.fromstring(Path(result['svg']).read_text());assert_target_scope(before,trial,[_resolve_id(t,aliases) for t in p['target_ids']])
                    old_images={n.get('href') or n.get('{http://www.w3.org/1999/xlink}href') for n in before.iter() if n.tag.rsplit('}',1)[-1]=='image'}
                    if any((n.get('href') or n.get('{http://www.w3.org/1999/xlink}href')) not in old_images for n in trial.iter() if n.tag.rsplit('}',1)[-1]=='image'):
                        raise ValueError('generated raster insertion requires audited sp_photo route')
                    record['source_code_sha256']=hashlib.sha256(p['source_code'].encode()).hexdigest()
                else:
                    group=selected[pid]
                    issue={'id':pid,'category':group[0]['category'],'target_ids':_execution_targets(p),'neighbor_ids':list({t for q in group for t in q.get('neighbor_ids',[])}),'description':' / '.join(q.get('description','') for q in group),'original_evidence':' / '.join(str(q.get('original_evidence','')) for q in group)}
                    results=[];actual=[]
                    issue['relations']=rules
                    ops=p['args']['operations']
                    # Sampling/measurement are host read-only capabilities; all mutations share the trial transaction.
                    executable = [{'method':'bp_program','target_ids':_execution_targets(p),'args':{'operations':ops}}] if len(ops)>1 and all(op['method'] in MUTATIONS and not op.get('id') for op in ops) else ops
                    for op_index,op in enumerate(executable):
                        step=dict(op)
                        result,args,reports=_perform(trial,step,issue,images[im]['original'],work/f'op-{op_index}',aliases,local_results)
                        if op.get('id'):local_results[op['id']]=deepcopy(result)
                        results.append(result);actual.append(args)
                    result=results[0] if len(ops)==1 else {'operations':results};record['actual_parameters']=actual
                if any(q['category'] in ('E','F') for q in selected[pid]):
                    issue={'id':pid,'category':selected[pid][0]['category'],'target_ids':_execution_targets(p),'neighbor_ids':list({t for q in selected[pid] for t in q.get('neighbor_ids',[])}),'description':' / '.join(q.get('description','') for q in selected[pid]),'original_evidence':' / '.join(str(q.get('original_evidence','')) for q in selected[pid])}
                    record['convergence']=converge(trial,p,issue,images[im]['original'],work,aliases,local_results)
                validate(trial)
                if rules:
                    post=_relation_report(trial,rules,aliases)
                    focus={_resolve_id(t,aliases) for t in _execution_targets(p)}
                    live={n.get('id') for n in trial.iter() if n.get('id')}
                    focus.update(descendants(trial,list(focus & live)))
                    target_rules=[r for r in rules if {_resolve_id(r['subject_id'],aliases),_resolve_id(r['object_id'],aliases)} & focus]
                    record['tp_check']=_relation_report(trial,target_rules,aliases)
                    record['neighbor_check']=compare_reports(initial,post)
                    record['relation_check']=post
                    if record['neighbor_check']['new_alarm_ids'] or record['neighbor_check']['missing_relation_ids']:raise ValueError('new neighbor TP alarm; transaction rolled back')
                else:
                    record['tp_check']={'status':'not_assessed','reason':'no declared original-justified relations'}
                    record['neighbor_check']={'status':'not_assessed','reason':'no declared original-justified relations'}
                checkpoint,measurement=write_checkpoint(trial,folder/'checkpoints',index)
                checkpoint['original']=images[im]['original']
                record.update(status='changed_unverified' if ET.tostring(before)!=ET.tostring(trial) else 'executed_no_change',after_revision=checkpoint['revision'],measurement=measurement)
                state['images'][im]=checkpoint;state['aliases'][im]=aliases;local_results[pid]=result;state['results']=local_results
            except Exception as exc:
                record.update(status='failed',error=str(exc),rolled_back=True)
        state['rcd'].append(record);done[pid]=record;_atomic_json(path,state)
    # Earlier convergence can be invalidated by later edits. Audit the final scene.
    for p in programs:
        rec=next(r for r in state['rcd'] if r['program_id']==p['id'])
        if rec['status'] not in ('changed_unverified','executed_no_change') or not any(q['category'] in ('E','F') for q in selected[p['id']]):continue
        audit=deepcopy(p);audit['convergence']['repairs']=[];audit['convergence']['max_iterations']=2
        try:
            final_root=ET.fromstring(Path(state['images'][p['image_id']]['svg']).read_text())
            rec['final_scene_check']=converge(final_root,audit,{},images[p['image_id']]['original'],folder/'final-audit',state['aliases'][p['image_id']],{})
        except Exception as exc:
            rec['final_scene_check']={'status':'unresolved','error':str(exc)}
            rec['convergence']['status']='invalidated_by_later_edit'
    _atomic_json(path,state)
    result={k:state[k] for k in ('images','rcd','aliases')};result['visual_acceptance']='pending'
    _atomic_json(folder/'result.json',result)
    return result
