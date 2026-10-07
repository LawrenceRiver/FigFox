"""Local module-program Reconstructor. No model transport, eval, or shell code."""
from figfox_plus.image_io import imread
from copy import deepcopy
from figfox_plus import file_lock as fcntl
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from ...state import write_json
from ..document import serialize, measure
from ..tight_tp import measure_tight
from ..repair_toolbox import execute_batch
from ..tp_alarms import evaluate_tp, compare_reports
from .contract import validate_plan, normalize_plan, MUTATIONS
from .qlist import BY_ID


def revision(root):return hashlib.sha256(serialize(root).encode()).hexdigest()


def _resolve_id(oid, aliases):
    seen=set()
    while oid in aliases and aliases[oid]!=oid:
        if oid in seen:raise ValueError('identity alias cycle')
        seen.add(oid);oid=aliases[oid]
    return oid


def _ids(ids, aliases):return list(dict.fromkeys(_resolve_id(i,aliases) for i in ids))


def _resolve(value, root, aliases, results):
    if isinstance(value,list):return [_resolve(v,root,aliases,results) for v in value]
    if not isinstance(value,dict):return value
    if '$measure' in value:
        spec=value['$measure'];ids=_ids(spec['ids'],aliases)
        objects=measure_tight(root,ids)['objects'];boxes=[]
        for oid in ids:
            item=objects.get(oid,{})
            if item.get('status')!='measured' or not item.get('tight_bbox'):raise ValueError('measurement unavailable for '+oid)
            boxes.append(item['tight_bbox'])
        b={k:(min if k in ('left','top') else max)(x[k] for x in boxes) for k in ('left','top','right','bottom')}
        b.update(width=b['right']-b['left'],height=b['bottom']-b['top'],cx=(b['left']+b['right'])/2,cy=(b['top']+b['bottom'])/2)
        return b[spec['edge']]
    if '$result' in value:
        spec=value['$result'];result=results[spec['step']]
        for key in spec.get('path',[]):result=result[key]
        return deepcopy(result)
    if '$calc' in value:
        values=[_resolve(v,root,aliases,results) for v in value['values']]
        if not values or any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in values):raise ValueError('expression requires finite numbers')
        name=value['$calc']
        if name in {'sub','div'} and len(values)!=2:raise ValueError('sub/div needs two values')
        answer={'add':lambda:sum(values),'sub':lambda:values[0]-values[1],
                'mul':lambda:math.prod(values),'div':lambda:values[0]/values[1],
                'min':lambda:min(values),'max':lambda:max(values)}[name]()
        if not math.isfinite(answer):raise ValueError('nonfinite expression result')
        return answer
    return {k:_resolve(v,root,aliases,results) for k,v in value.items()}


def _relation_report(root, rules, aliases):
    if not rules:return {'revision':revision(root),'relations':[],'alarms':[],'by_object':{},'uncertain_ids':[],
                         'hard_constraints_passed':False,'visual_passed':False,'reason':'no declared original-justified relations'}
    mapped=[]
    for rule in rules:
        item=dict(rule,subject_id=_resolve_id(rule['subject_id'],aliases),object_id=_resolve_id(rule['object_id'],aliases))
        mapped.append(item)
    ids=list({oid for r in mapped for oid in (r['subject_id'],r['object_id'])})
    rev=revision(root);known={n.get('id') for n in root.iter()};objects={};missing=[]
    found=measure_tight(root,[i for i in ids if i in known])['objects'] if set(ids)&known else {}
    for oid in ids:
        item=found.get(oid,{})
        if not item.get('tight_bbox'):missing.append(oid);continue
        objects[oid]={'bbox':item['tight_bbox'],'revision':rev,'bounds_complete':item.get('status')=='measured'}
    safe=[r for r in mapped if r['subject_id'] in objects and r['object_id'] in objects and r['subject_id']!=r['object_id']]
    report=evaluate_tp(objects,safe,revision=rev)
    for r in mapped:
        if r not in safe:
            report['relations'].append({'id':r['id'],'participants':[r['subject_id'],r['object_id']],
                'predicate':r['predicate'],'min_gap':r.get('min_gap',0),'padding':r.get('padding',0),
                'reference_evidence':r['reference_evidence'],'status':'uncertain','reason':'missing or merged participants'})
            report['uncertain_ids'].append(r['id']);report['hard_constraints_passed']=False
    report['missing_objects']=missing
    return report


def _sample_colors(original, regions):
    import cv2
    import numpy as np
    pixels=imread(str(original),cv2.IMREAD_COLOR)
    if pixels is None:raise ValueError('cannot read original image')
    samples=[]
    for x,y,w,h in regions:
        l,t,r,b=math.floor(x),math.floor(y),math.ceil(x+w),math.ceil(y+h)
        if w<=0 or h<=0 or min(l,t)<0 or r>pixels.shape[1] or b>pixels.shape[0]:raise ValueError('original ROI outside image')
        colors,counts=np.unique(pixels[t:b,l:r].reshape(-1,3),axis=0,return_counts=True)
        bgr=colors[counts.argmax()];rgb=[int(c) for c in bgr[::-1]]
        samples.append({'original_xywh':[x,y,w,h],'modal_rgb':rgb,'modal_hex':'#%02x%02x%02x'%tuple(rgb),'backend':'OpenCV'})
    return {'samples':samples}


def _perform(root, step, issue, original, folder, aliases, results):
    method=step['method']
    if method=='measure':return {'objects':measure_tight(root,_ids(step['target_ids'],aliases))['objects']},step['args'],[]
    if method=='sample_colors':return _sample_colors(original,step['args']['regions']),step['args'],[]
    if method=='check_tp':return {'check_only':True},step['args'],[]
    operations=step['args']['operations'] if method=='bp_program' else [step]
    trial=deepcopy(root);new_aliases=dict(aliases);reports=[];actual=[]
    def has_expression(value):
        if isinstance(value,dict):return any(str(k).startswith('$') or has_expression(v) for k,v in value.items())
        if isinstance(value,list):return any(has_expression(v) for v in value)
        return False
    # A literal patch program needs one atomic before/after measurement, not a
    # full-scene raster scan for every fill/text attribute in the same program.
    if method=='bp_program' and all(op['method']=='bp_patch' and not has_expression(op['args']) for op in operations):
        actual=[dict(method='bp_patch',target_ids=_ids(op['target_ids'],aliases),args=deepcopy(op['args'])) for op in operations]
        live={n.get('id') for n in trial.iter() if n.get('id')}
        targets=[i for i in _ids(issue['target_ids'],aliases) if i in live]
        targets=list(dict.fromkeys(targets+[i for op in actual for i in op['target_ids']]))
        native={'id':issue['id'],'types':BY_ID[issue['category']]['legacy_types'],
                'description':issue['description'],'original_evidence':issue['original_evidence'],
                'target_ids':targets,'neighbor_ids':[i for i in _ids(issue['neighbor_ids'],aliases) if i in live],
                'operations':actual}
        report=execute_batch(trial,[native],original,folder/'patch-program')
        item=report['issues'][0]
        if item['status']!='applied':raise ValueError('; '.join(item['errors']))
        root.attrib.clear();root.attrib.update(trial.attrib);root[:]=list(trial)
        return {'operations':[report]},{'operations':actual},[report]
    for index,op in enumerate(operations):
        args=_resolve(op['args'],trial,new_aliases,results)
        ids=_ids(op['target_ids'],new_aliases)
        live={n.get('id') for n in trial.iter() if n.get('id')}
        targets=[i for i in _ids(issue['target_ids'],new_aliases) if i in live]
        neighbors=[i for i in _ids(issue['neighbor_ids'],new_aliases) if i in live]
        # Newly created IDs are validated within the issue's scope by the contract.
        targets=list(dict.fromkeys(targets+ids))
        native={'id':issue['id'],'types':BY_ID[issue['category']]['legacy_types'],
                'description':issue['description'],'original_evidence':issue['original_evidence'],
                'target_ids':targets,'neighbor_ids':neighbors,
                'operations':[{'method':op['method'],'target_ids':ids,'args':args}]}
        report=execute_batch(trial,[native],original,folder/f'op-{index:03d}')
        item=report['issues'][0]
        if item['status']!='applied':raise ValueError('; '.join(item['errors']))
        for entry in item['applied_operations']:
            result=entry['result'];replacement=result.get('replacement_id')
            if replacement:
                for old in result.get('target_ids',ids):new_aliases[old]=replacement
        reports.append(report);actual.append({'method':op['method'],'target_ids':ids,'args':args})
    root.attrib.clear();root.attrib.update(trial.attrib);root[:]=list(trial)
    aliases.clear();aliases.update(new_aliases)
    return {'operations':reports},actual[0]['args'] if method!='bp_program' else {'operations':actual},reports


def execute_plan(plan, manifest, task_dir):
    """Apply a validated ordered module program, checkpoint after each operation."""
    task_dir=Path(task_dir).resolve()
    with (task_dir/'execute.lock').open('a', encoding='utf-8') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        return _execute(plan,manifest,task_dir)


def _execute(plan,manifest,task_dir):
    from .runner import verify_inputs,digest
    plan,_=normalize_plan(plan,manifest)
    verify_inputs(task_dir,manifest);validated=validate_plan(plan,manifest)
    signature=hashlib.sha256(json.dumps(plan,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    folder=task_dir/'execution';folder.mkdir(exist_ok=True);state_path=folder/'state.json'
    if state_path.exists():
        state=json.loads(state_path.read_text(encoding='utf-8'))
        if state['plan_sha256']!=signature:raise ValueError('cannot resume with a different plan')
        for im,data in state['images'].items():
            if digest(data['svg'])!=data['sha256']:raise ValueError('execution checkpoint changed')
        if state.get('complete'):return json.loads((task_dir/'result.json').read_text(encoding='utf-8'))
    else:
        state={'plan_sha256':signature,'images':{im:{'svg':v['svg'],'sha256':digest(v['svg'])} for im,v in manifest['images'].items()},
               'rcd':[],'results':{},'aliases':{im:{} for im in manifest['images']},'complete':False}
    roots={im:ET.fromstring(Path(data['svg']).read_text(encoding='utf-8')) for im,data in state['images'].items()}
    completed={r['operation_id']:r for r in state['rcd']}
    success={'executed_changed','executed_no_change'}
    for index,step in enumerate(plan['ask_data']):
        if step['id'] in completed:continue
        issue=validated['issues'][step['issue_id']];im=issue['image_id'];root=roots[im]
        aliases=state['aliases'][im];rules=plan.get('relations',{}).get(im,[])
        before_rev=revision(root)
        record={'operation_id':step['id'],'image_id':im,'issue_id':issue['id'],'target_ids':_ids(step['target_ids'],aliases),
                'executor':step['phase'],'module':step['method'],'predescription':step['rcd_predescription'],
                'actual_parameters':None,'before_revision':before_rev,'soft_review':'pending','return_chain':[]}
        trigger=step.get('when');skip=False;blocked=False
        if trigger and completed[trigger['step']]['execution_status']!=trigger['status']:skip=True
        for dep in step['depends_on']:
            if completed[dep]['execution_status'] not in success and not (trigger and dep==trigger['step'] and not skip):blocked=True
        if skip:record['execution_status']='skipped_condition'
        elif blocked:record.update(execution_status='blocked',error='predecessor did not execute successfully')
        else:
            checkpoint=deepcopy(root);saved_aliases=dict(aliases)
            try:
                initial=_relation_report(root,rules,aliases)
                for attempt in range(step.get('max_attempts',1)):
                    start=revision(root)
                    result,args,reports=_perform(root,step,issue,manifest['images'][im]['original'],
                                                 folder/f'step-{index:04d}'/f'attempt-{attempt}',aliases,state['results'])
                    state['results'][step['id']]=result;record['actual_parameters']=args
                    post=_relation_report(root,rules,aliases)
                    # The original target pair and the wider neighbourhood are
                    # separate checks. An unrelated existing alarm cannot keep
                    # moving an already-correct target indefinitely.
                    focus=set(_ids(step['target_ids'],aliases))
                    target_rules=[r for r in rules if {_resolve_id(r['subject_id'],aliases),_resolve_id(r['object_id'],aliases)} & focus]
                    target_report=_relation_report(root,target_rules,aliases)
                    record['tp_check']=target_report
                    record['neighbor_check']=compare_reports(initial,post)
                    record['neighbor_check']['spatial_evidence']=[r['issues'][0].get('checks',{}) for r in reports]
                    record['return_chain'].append({'attempt':attempt+1,'before_revision':start,'after_revision':revision(root),
                                                  'actual_parameters':args,
                                                  'hard_constraints_passed':target_report['hard_constraints_passed']})
                    if step.get('until')!='relations_satisfied' or (target_report['hard_constraints_passed'] and record['neighbor_check']['no_new_neighbor_alarms']):break
                    if revision(root)==start:
                        record['stop_reason']='no_progress';break
                else:record['stop_reason']='local_attempt_limit'
                record['execution_status']='executed_changed' if revision(root)!=before_rev else 'executed_no_change'
            except Exception as exc:
                root.attrib.clear();root.attrib.update(checkpoint.attrib);root[:]=list(checkpoint)
                aliases.clear();aliases.update(saved_aliases);state['results'].pop(step['id'],None)
                record.update(execution_status='failed',error=type(exc).__name__+': '+str(exc))
                record['rolled_back']=True
        record['after_revision']=revision(root)
        # Checkpoints are immutable files. The single atomic state pointer commits
        # scene + RCD together; interruption cannot cause a committed step to repeat.
        dest=folder/f'checkpoint-{index:04d}.svg';dest.write_text(serialize(root), encoding='utf-8')
        state['images'][im]={'svg':str(dest),'sha256':digest(dest)}
        state['rcd'].append(record);completed[step['id']]=record
        write_json(state_path,state)
        print(json.dumps({'RCD':{k:record.get(k) for k in ('operation_id','target_ids','executor','module',
            'predescription','actual_parameters','execution_status','soft_review','error')}},ensure_ascii=False),flush=True)
    outputs={};global_checks={}
    for index,(im,root) in enumerate(roots.items()):
        svg=folder/f'final-{index:03d}.svg';png=folder/f'final-{index:03d}.png'
        svg.write_text(serialize(root), encoding='utf-8');measure(root,png)
        outputs[im]={'svg':str(svg),'png':str(png),'revision':revision(root),'sha256':digest(svg)}
        global_checks[im]=_relation_report(root,plan.get('relations',{}).get(im,[]),state['aliases'][im])
    issue_results=[]
    for issue in plan['issues']:
        records=[r for r in state['rcd'] if r['issue_id']==issue['id']]
        status=issue['decision'] if issue['decision']!='confirmed' else (
            'blocked' if not records else 'changed_unverified' if any(r['execution_status']=='executed_changed' for r in records) else 'unresolved')
        issue_results.append({'id':issue['id'],'status':status,'unresolved_reason':issue.get('unresolved_reason'),
                              'operations':[r['operation_id'] for r in records]})
    result={'status':'pending_review','images':outputs,'rcd':state['rcd'],'issues':issue_results,
            'global_checks':global_checks,'unresolved_relations':plan.get('unresolved_relations',{}),
            'human_visual_passed':False,'model_requests_limit':1}
    write_json(task_dir/'result.json',result)
    (task_dir/'rcd.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in state['rcd']), encoding='utf-8')
    from .report import write_report
    write_report(task_dir,manifest,result)
    state['complete']=True;write_json(state_path,state)
    return result
