"""Two discovery responsibilities, at most two connected-component repair calls.

Preparation is offline. Run appends durable audits and calls only the injected
sender, then uses the original serial guarded transaction executor exactly once.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import shutil
import time

from ..capabilities import freeze_policy, load_policy
from .capacity_bounds import verified_bounds
from .capacity_contracts import contract, discovery_tools, repair_tools, parse_response, validate_schema
from .capacity_merge import validate_branch_result, merge_branch_results, plan_repair_components, build_repair_batches
from .capacity_partition import CapacityError, digest, plan_capacity_context, prepare_branches, write_json
from .capacity_scope import guard_program, dependency_order
from .programs import execute_programs
from .replay import filter_program_shapes, select_valid_programs


def prepare(source_review, assignments, task_dir, *, capabilities=None):
    root=Path(task_dir).resolve()
    if root.exists() and any(root.iterdir()):raise ValueError('capacity preparation requires a new empty directory')
    root.mkdir(parents=True,exist_ok=True)
    policy=load_policy(source_review,capabilities)
    freeze_policy(root,policy)
    plan=prepare_branches(source_review,assignments,root)
    plan['source_review']=str(Path(source_review).resolve())
    if len(plan['context']['images'])!=1:raise ValueError('capacity workflow requires one exact scene')
    plan['node_bounds'],plan['node_bounds_audit']=verified_bounds(next(iter(plan['context']['images'].values())))
    write_json(root/'node-bounds-audit.json',plan['node_bounds_audit'])
    plan['tools']=discovery_tools();plan['repair_tools']=repair_tools()
    wire_contract=contract(policy)
    instruction={'role':'user','content':json.dumps(wire_contract,ensure_ascii=False)}
    # Both phase packets retain all source messages. This explicit active output
    # contract resolves legacy envelope instructions without changing their bytes.
    plan['source_messages'].append(deepcopy(instruction))
    plan['message_assets'].append([])
    plan['source_capacity']=plan_capacity_context(plan['source_messages'],plan['tools'])
    for name,branch in plan['branches'].items():
        branch['messages'].append(deepcopy(instruction));branch['tools']=deepcopy(plan['tools'])
        branch['capacity']=plan_capacity_context(branch['messages'],branch['tools'])
        write_json(root/name/'messages.json',branch['messages']);write_json(root/name/'tools.json',branch['tools'])
    write_json(root/'capacity-audit.json',{k:b['capacity'] for k,b in plan['branches'].items()})
    plan['initial_images']={}
    for image_id,scene in plan['context']['images'].items():
        folder=root/'initial'/image_id;folder.mkdir(parents=True)
        image={}
        for output,key in [('svg','current_svg'),('png','current_png'),('original','original_png')]:
            target=folder/(output+Path(scene[key]['path']).suffix)
            shutil.copyfile(scene[key]['path'],target);image[output]=str(target)
        image['revision']=digest(image['svg']);plan['initial_images'][image_id]=image
    write_json(root/'output-contract.json',wire_contract)
    write_json(root/'plan.json',plan)
    write_json(root/'prepared-files.json',{str(p.relative_to(root)):digest(p) for p in sorted(root.rglob('*')) if p.is_file()})
    if any(b['capacity']['status']!='admitted' for b in plan['branches'].values()):
        audit={'status':'blocked_before_http','reason':'strict capacity packet exceeds context','evidence_discarded':False}
        write_json(root/'prepare-failure.json',audit)
        raise CapacityError(audit['reason'],audit)
    return plan


def _integrity(root,plan):
    for name,expected in json.loads((root/'prepared-files.json').read_text()).items():
        if digest(root/name)!=expected:raise ValueError('prepared file changed: '+name)
    source=Path(plan['source_review'])
    for name,expected in plan['source_hashes'].items():
        if digest(source/name)!=expected:raise ValueError('source file changed: '+name)
    for asset in plan['assets'].values():
        if digest(asset['path'])!=asset['sha256']:raise ValueError('source asset changed: '+asset['asset_id'])


def _dispatch(jobs,sender,root,plan,max_workers, *, integrity=None, budget_planner=None):
    """Join every started sender; one response/error outcome per logical slot."""
    integrity = integrity or (lambda: _integrity(root,plan))
    budget_planner = budget_planner or plan_capacity_context
    def call(job):
        name,packet,folder=job;folder.mkdir(parents=True,exist_ok=False)
        outcome={'request_name':name,'started_monotonic':time.monotonic(),'started_at':time.time(),'request_limit':1,'sender_invoked':False,'task_dir':str(folder)}
        try:
            integrity()
            budget=budget_planner(packet['messages'],packet['tools'])
            write_json(folder/'capacity.json',budget)
            if budget['status']!='admitted':raise ValueError('capacity blocked before sender')
            outcome['sender_invoked']=True
            raw=sender(deepcopy(packet['messages']),deepcopy(packet['tools']),folder,request_name=name,request_limit=1)
            outcome['response']=raw
            write_json(folder/'response-envelope.json',raw)
            # Root binds completion to response_path; also verify the saved bytes
            # here rather than trusting a synthetic inferred finish state.
            if not isinstance(raw,dict) or not isinstance(raw.get('response_path'),str):raise ValueError('sender must bind saved response_path')
            saved=json.loads(Path(raw['response_path']).read_text())
            if not isinstance(saved,dict) or not isinstance(saved.get('choices'),list) or len(saved['choices'])!=1 or not isinstance(saved['choices'][0],dict):raise ValueError('saved response choice malformed')
            choice=saved['choices'][0]
            if choice.get('message')!=raw.get('message') or choice.get('finish_reason')!=raw.get('finish_reason'):raise ValueError('saved response envelope mismatch')
            outcome.update(status='completed',response_sha256=digest(raw['response_path']))
        except Exception as exc:
            outcome.update(status='failed',error=type(exc).__name__+': '+str(exc))
        outcome.update(finished_monotonic=time.monotonic(),finished_at=time.time())
        write_json(folder/'outcome.json',outcome)
        return outcome
    # Context manager waits for all outstanding calls even if a sibling failed.
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures=[pool.submit(call,job) for job in jobs]
        return [f.result() for f in futures]


def _discovery(outcome,branch,plan):
    raw=outcome.get('response',{'error':outcome.get('error')})
    record=validate_branch_result(branch,raw,plan['branches'][branch])
    try:
        if outcome['status']!='completed':raise ValueError(outcome['error'])
        data=parse_response(raw,'submit_capacity_discovery')
        record['raw_payload']=deepcopy(data)
        validate_schema(data,plan['tools'][0]['function']['parameters'])
        for field in ('issues','observations'):
            for row in data[field]:
                if row['image_id'] not in plan['context']['images']:raise ValueError('unknown discovery image')
                if not set(row['evidence_pair_ids'])<=set(plan['branches'][branch]['assignment']['pair_ids']):raise ValueError('unknown or unsupplied evidence pair')
                if not set(row['evidence_asset_ids'])<=set(plan['branches'][branch]['asset_ids']):raise ValueError('unknown or unsupplied evidence asset')
                if field=='observations' and row['decision']=='repair' and not row['issue_ids']:raise ValueError('actionable observation must link explicit issue')
    except Exception as exc:
        record['valid']=False;record['errors'].append(type(exc).__name__+': '+str(exc))
    return record


def _repair(outcome,batch,plan,components, *, parser=None):
    record={'request_name':outcome['request_name'],'raw':outcome.get('response'),'raw_payload':None,'valid':False,'errors':[]}
    try:
        if outcome['status']!='completed':raise ValueError(outcome['error'])
        data=(parser or parse_response)(outcome['response'],'submit_capacity_repair');record['raw_payload']=deepcopy(data)
        if parser is not None:
            raw=outcome['response'];choice=raw['choices'][0] if 'choices' in raw else raw
            record['parsed_format']='tool_call' if choice['message'].get('tool_calls') else 'content_json'
        validate_schema(data,plan['repair_tools'][0]['function']['parameters'])
        expected={('issue',i) for i in batch['issue_ids']}|{('observation',o) for o in batch['observation_ids']}
        keys=[(d['row_type'],d['row_id']) for d in data['decisions']]
        if len(keys)!=len(set(keys)) or set(keys)!=expected:raise ValueError('repair decision coverage incomplete or duplicated')
        ids=[p['id'] for p in data['programs']]
        if len(ids)!=len(set(ids)):raise ValueError('duplicate local program identity')
        decisions={key:d for key,d in zip(keys,data['decisions'])}
        for decision in data['decisions']:
            if not set(decision['program_ids'])<=set(ids):raise ValueError('decision references unknown program')
            if decision['decision']=='repair' and not decision['program_ids']:raise ValueError('repair disposition requires explicit program')
            if decision['decision']!='repair' and decision['program_ids']:raise ValueError('nonrepair disposition cannot assign programs')
        for program in data['programs']:
            if not program['issue_ids']:raise ValueError('program requires issue references')
            for issue_id in program['issue_ids']:
                decision=decisions.get(('issue',issue_id))
                if not decision or decision['decision']!='repair' or program['id'] not in decision['program_ids']:raise ValueError('program not supported by assigned repair decision')
        record['valid']=True
    except Exception as exc:record['errors'].append(type(exc).__name__+': '+str(exc))
    return record


def _finish(out,result):
    # Unverified receipts never prove visual resolution. Keep every original row
    # with its disposition and relevant real receipts, including explicit keeps.
    result['unresolved_rows']=[{'row_type':kind,'row':row,'visual_status':'unverified',
        'decisions':[d for d in result['decisions'] if d.get('row_type')==kind and d.get('row_id')==row['id']],
        'receipts':[r for r in result['rcd'] if row['id'] in r.get('issue_ids',[])]}
        for kind,rows in [('issue',result['issues']),('observation',result['observations'])] for row in rows]
    result['visual_passed']=False;result['visual_acceptance']='unverified'
    result['sender_calls']=sum(row['sender_invoked'] for row in result['call_schedule'])
    result['completed_model_responses']=sum(row['status']=='completed' for row in result['call_schedule'])
    result['model_calls']=None if result['sender_calls'] else 0
    result['model_call_count_basis']='Actual HTTP attempts/usage belong to injected sender ledger; invocation or cached response is not proof.'
    write_json(out/'call-schedule.json',result['call_schedule'])
    write_json(out/'report-ledger.json',result)
    write_json(out/'result.json',result)
    return result


def _execute_repairs(out,result,repairs,batches,component_plan,policy,integrity):
    """Shared original guard, selector and once-only serial executor path."""
    programs=[];audits=[]
    for record,batch in zip(repairs,batches):
        for raw in record['raw_payload']['programs']:
            try:
                program,normalization,scope=guard_program(raw,batch,component_plan['components'],result['images'],record['request_name'])
                programs.append(program);audits.append({'raw_program':raw,'normalization':normalization,'scope':scope,'program_id':program['id']})
            except Exception as exc:
                rejection={'stage':'capacity_scope','program_id':raw.get('id'),'issue_ids':raw.get('issue_ids',[]),'raw_program':raw,'error':type(exc).__name__+': '+str(exc),'normalization':getattr(exc,'normalization_log',[])}
                result['rejected_programs'].append(rejection)
    write_json(out/'scope-audit.json',audits)
    programs,blocked=dependency_order(programs)
    raw_by_id={a['program_id']:a['raw_program'] for a in audits}
    for program in blocked:
        result['rejected_programs'].append({'stage':'dependency_order','program_id':program['id'],
            'raw_program':raw_by_id[program['id']],'error':'unknown or cyclic program dependencies'})
    shaped,shape_rejections=filter_program_shapes(programs)
    accepted,rejected=select_valid_programs(shaped,result['issues'],result['images'],capabilities=policy)
    raw_by_id={a['program_id']:a['raw_program'] for a in audits}
    for row in shape_rejections+rejected:
        row.update(stage='original_selector',raw_program=raw_by_id.get(row['program_id']))
    result['rejected_programs'].extend(shape_rejections+rejected)
    write_json(out/'program-preflight.json',{'accepted':accepted,'rejected':result['rejected_programs']})
    result['status']='blocked_execution'
    integrity()
    executed=execute_programs(accepted,result['issues'],result['images'],out/'execution',capabilities=policy)
    result.update(images=executed['images'],rcd=executed['rcd'],terminal_source='public_executor',status='visual_unverified')


def _restore_terminal(out,result):
    # If the public executor committed before an exceptional final return,
    # its durable state is the terminal. Never select an earlier nicer image.
    state_path=out/'execution'/'state.json'
    if state_path.exists():
        state=json.loads(state_path.read_text())
        if all(digest(im['svg'])==im['revision'] for im in state['images'].values()):
            result.update(images=state['images'],rcd=state['rcd'],terminal_source='public_executor_state')


def run(task_dir, *, sender, capabilities=None, max_workers=2):
    if type(max_workers) is not int or max_workers not in (1,2):raise ValueError('max_workers must be 1 or 2')
    root=Path(task_dir).resolve();plan=json.loads((root/'plan.json').read_text())
    out=root/'run'
    try:out.mkdir()
    except FileExistsError as exc:raise ValueError('capacity run already started; no implicit resends') from exc
    result={'status':'blocked_integrity','images':deepcopy(plan['initial_images']),'terminal_source':'frozen_initial',
            'issues':[],'observations':[],'decisions':[],'rcd':[],'rejected_programs':[],'errors':[], 'call_schedule':[], 'discovery':{},'repair_results':[]}
    try:
        policy=load_policy(root,capabilities);_integrity(root,plan)
        jobs=[('DS1-'+b,plan['branches'][b],out/'discovery'/('DS1-'+b)) for b in ('A','B')]
        outcomes=_dispatch(jobs,sender,root,plan,max_workers)
        result['call_schedule'].extend({k:v for k,v in o.items() if k!='response'} for o in outcomes)
        result['discovery']={b:_discovery(o,b,plan) for b,o in zip(('A','B'),outcomes)}
        write_json(out/'discovery-results.json',result['discovery'])
        merged=merge_branch_results(result['discovery'],plan)
        result.update(issues=merged['issues'],observations=merged['observations'],merge=merged,status='blocked_discovery')
        write_json(out/'merged.json',merged)
        if not merged['ready_for_repair']:return _finish(out,result)
        result['status']='blocked_repair_capacity'
        image=next(iter(result['images'].values()))
        component_plan=plan_repair_components(merged,image['svg'],plan)
        result['component_plan']=component_plan;write_json(out/'components.json',component_plan)
        batches=build_repair_batches(component_plan,plan,out/'repair-plan',max_batches=2)
        result['batch_plan']=batches
        jobs=[('DS2-'+str(i),batch,out/'repair'/('DS2-'+str(i))) for i,batch in enumerate(batches['batches'])]
        outcomes=_dispatch(jobs,sender,root,plan,max_workers if batches['parallel_safe'] else 1)
        result['call_schedule'].extend({k:v for k,v in o.items() if k!='response'} for o in outcomes)
        repairs=[_repair(o,b,plan,component_plan['components']) for o,b in zip(outcomes,batches['batches'])]
        result['repair_results']=repairs;write_json(out/'repair-results.json',repairs)
        for record in repairs:
            data=record['raw_payload']
            if isinstance(data,dict) and isinstance(data.get('decisions'),list):
                result['decisions'].extend({**d,'request_name':record['request_name']} for d in data['decisions'] if isinstance(d,dict))
        result['status']='blocked_repair_response'
        if any(not r['valid'] for r in repairs):return _finish(out,result)
        _execute_repairs(out,result,repairs,batches['batches'],component_plan,policy,lambda: _integrity(root,plan))
    except Exception as exc:
        result['errors'].append({'type':type(exc).__name__,'error':str(exc),'audit':getattr(exc,'audit',None)})
        _restore_terminal(out,result)
    return _finish(out,result)
