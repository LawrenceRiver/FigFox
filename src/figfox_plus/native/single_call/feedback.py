"""One explicitly requested feedback pass; shared durable ceiling of two requests.

Only runtime evidence is read. This module has no acceptance-label input or search.
"""
import fcntl
import json
from pathlib import Path
from uuid import uuid4
from ...providers import request_once
from ...state import write_json, PLUS_ROOT
from .transport import _send


def execution_evidence(plan, compilation, result):
    return {'previous_model_issues':plan.get('issues',[]),
            'compiler_blocked':compilation.get('blocked',[]),
            'unresolved_relations':compilation.get('unresolved_relations',{}),
            'actual_rcd':[{k:r.get(k) for k in (
                'operation_id','issue_id','image_id','execution_status','actual_parameters',
                'error','rolled_back','tp_check','neighbor_check')} for r in result.get('rcd',[])],
            'issue_results':result.get('issues',[]),
            'global_checks':result.get('global_checks',{}),
            'first_stage_error':result.get('first_stage_error'),
            'human_acceptance_included':False}


def validate_review(plan, prior):
    expected={i['id']:i for i in prior};seen=set()
    issues={i['id']:i for i in plan.get('issues',[])}
    for row in plan.get('prior_issue_results',[]):
        oid=row.get('issue_id')
        if oid not in expected or oid in seen:raise ValueError('invalid previous issue review identity')
        seen.add(oid)
        if row.get('status') not in {'resolved','persists','false_positive','uncertain'}:
            raise ValueError('invalid previous issue review status')
        if not isinstance(row.get('evidence'),str) or not row['evidence'].strip():
            raise ValueError('review requires visual evidence')
        links=row.get('issue_ids',[])
        if not isinstance(links,list) or any(i not in issues or issues[i]['image_id']!=expected[oid]['image_id'] for i in links):
            raise ValueError('invalid review issue links')
        if row['status']=='persists' and not links:raise ValueError('persistent issue needs new issue links')
    if seen!=set(expected):raise ValueError('incomplete previous issue review')


def request_feedback(messages, task_dir, *, send=None):
    root=Path(task_dir).resolve()
    if (root/'local-replay.json').exists():raise ValueError('local replay cannot request feedback')
    if (root/'feedback-link.json').exists():raise ValueError('feedback cannot spawn a third request')
    ledger=root/'api-ledger.jsonl'
    records=[json.loads(s) for s in ledger.read_text().splitlines() if s.strip()] if ledger.exists() else []
    if not any(r.get('event')=='sending' and r.get('role')=='deepseek' for r in records):
        raise ValueError('feedback requires a recorded first request')
    folder=root/'feedback';folder.mkdir(exist_ok=True)
    api=folder/'api';api.mkdir(exist_ok=True)
    def once():
        value=(send or _send)(messages,api)
        if not isinstance(value,str):raise ValueError('transport must return JSON text')
        (api/'response.txt').write_text(value)
        plan=json.loads(value)
        if not isinstance(plan,dict):raise ValueError('plan must be an object')
        write_json(folder/'response-plan.json',plan)
        return plan
    return request_once('deepseek',uuid4().hex,ledger,once,{'deepseek':2})


def run_feedback(task_dir, *, send=None, execute=True):
    """Reuse the first response; execute and review with at most ONE extra send."""
    from .runner import prepare,run_prepared,verify_inputs,digest
    root=Path(task_dir).resolve()
    if (root/'feedback-link.json').exists():raise ValueError('cannot continue a feedback task')
    if not (root/'response-plan.json').exists():
        raise ValueError('a complete first response is required; no implicit fresh first request')
    with (root/'feedback.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        initial=json.loads((root/'input-manifest.json').read_text());verify_inputs(root,initial)
        prior=json.loads((root/'response-plan.json').read_text())
        child=root/'feedback'
        if not (child/'input-manifest.json').exists():
            result=run_prepared(root,execute=True)
            for output in result['images'].values():
                if digest(output['svg'])!=output['sha256']:raise ValueError('actual output changed before feedback')
            sources={im:{'original':d['original'],'svg':result['images'][im]['svg']}
                     for im,d in initial['images'].items()}
            manifest=prepare(sources,child)
            compilation=json.loads((root/'compilation.json').read_text())
            evidence=execution_evidence(prior,compilation,result)
            write_json(child/'execution-evidence.json',evidence)
            messages=json.loads((child/'messages.json').read_text())
            messages[0]['content']+='\n'+(PLUS_ROOT/'prompts/bounded-feedback.md').read_text()
            messages[1]['content'].insert(1,{'type':'text','text':json.dumps(evidence,ensure_ascii=False)})
            write_json(child/'messages.json',messages)
            manifest['request_budget']=0  # never use the independent one-call transport here
            manifest['total_task_request_ceiling']=2
            manifest['files']['messages.json']=digest(child/'messages.json')
            manifest['files']['execution-evidence.json']=digest(child/'execution-evidence.json')
            link={'parent':str(root),'prior_response_sha256':digest(root/'response-plan.json'),
                  'first_result_sha256':digest(root/'result.json')}
            write_json(child/'feedback-link.json',link)
            manifest['files']['feedback-link.json']=digest(child/'feedback-link.json')
            write_json(child/'input-manifest.json',manifest)
        manifest=json.loads((child/'input-manifest.json').read_text());verify_inputs(child,manifest)
        link=json.loads((child/'feedback-link.json').read_text())
        if link['parent']!=str(root) or link['prior_response_sha256']!=digest(root/'response-plan.json') or link['first_result_sha256']!=digest(root/'result.json'):
            raise ValueError('feedback provenance changed')
        response=child/'response-plan.json'
        plan=json.loads(response.read_text()) if response.exists() else request_feedback(
            json.loads((child/'messages.json').read_text()),root,send=send)
        validate_review(plan,prior['issues'])
        result=run_prepared(child,execute=execute)
        write_json(root/'bounded-workflow.json',{'total_request_ceiling':2,'feedback_dir':str(child),
                   'human_visual_passed':False,'status':'pending_review','third_request_allowed':False})
        return result
