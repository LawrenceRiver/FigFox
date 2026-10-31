"""One explicit assessment of uncertified discovery with complete source evidence.

Offline preparation verifies the original failed run and actual provider prefix.
Only the injected sender can perform IO with a provider; no implicit retry exists.
The original discovery remains blocked and all visual claims remain unverified.
"""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import shutil

from ..capabilities import freeze_policy, load_policy
from . import capacity_workflow as shared
from .capacity_contracts import contract, parse_response, validate_schema
from .capacity_merge import _namespace_payload, plan_repair_components
from .capacity_partition import CapacityError, _read_source, digest, write_json
from .context_budget import plan_context

VERSION='capacity-diagnostic-content-json-v1'
RESPONSE_CONTRACT={'accepted_formats':['tool_call','content_json'],
    'content_json':'Exactly one literal JSON object in complete stop content, no tool call or refusal; same schema and guards.',
    'raw_response_rewritten':False}


def _read(path):
    return json.loads(Path(path).read_text())


def _budget(messages, tools, baseline):
    budget=plan_context(messages,tools,provider_prefixes=[baseline])
    required={'context_window_tokens':1048576,'requested_output_tokens':64000,
              'max_output_tokens':64000,'safety_tokens':32768}
    if any(budget[key]!=value for key,value in required.items()):
        raise CapacityError('diagnostic requires context 1048576, output 64000 and safety 32768',budget)
    if budget.get('provider_prefix_prompt_tokens')!=baseline['prompt_tokens']:
        raise ValueError('exact provider prefix required')
    return budget


def _image_blocks(messages):
    return Counter(json.dumps(block,sort_keys=True) for message in messages
                   if isinstance(message.get('content'),list)
                   for block in message['content'] if block.get('type')=='image_url')


def _history(source, plan, prior_request, source_responses):
    """Bind calibration to completed original outcomes, including response usage."""
    if set(source_responses)!={'A','B'}:raise ValueError('both original responses required')
    original_result=_read(source/'run/result.json')
    if original_result['status']!='blocked_discovery':raise ValueError('diagnostic requires original blocked discovery')
    records=_read(source/'run/discovery-results.json')
    if set(records)!={'A','B'} or any(r['valid'] for r in records.values()):
        raise ValueError('diagnostic requires two explicitly uncertified source branches')
    files=[source/'plan.json',source/'prepared-files.json',source/'run/result.json',source/'run/discovery-results.json']
    files.extend(source/name for name in _read(source/'prepared-files.json'))
    rows={'issues':[],'observations':[]};provenance={};responses={}
    for branch in ('A','B'):
        record=records[branch];path=Path(source_responses[branch]).resolve()
        original_path=Path(record['raw']['response_path']).resolve()
        if path!=original_path:raise ValueError('response must be original bound source path')
        outcome_path=source/'run/discovery'/('DS1-'+branch)/'outcome.json'
        outcome=_read(outcome_path)
        if outcome['status']!='completed' or outcome.get('response_sha256')!=digest(path):
            raise ValueError('original complete response hash mismatch')
        raw=_read(path);payload=parse_response(raw,'submit_capacity_discovery')
        choice=raw['choices'][0]
        if any(choice[key]!=record['raw'].get(key) for key in ('message','finish_reason')):
            raise ValueError('original response envelope mismatch')
        if payload!=record['raw_payload']:raise ValueError('original raw payload mismatch')
        validate_schema(payload,plan['tools'][0]['function']['parameters'])
        for field in rows:
            ids=[row['id'] for row in payload[field]]
            if len(ids)!=len(set(ids)):raise ValueError('duplicate raw row identity')
        normalized=_namespace_payload(payload,branch)
        for field in rows:rows[field].extend(normalized[field])
        assigned=set(plan['branches'][branch]['assignment']['pair_ids'])
        supplied=set(plan['branches'][branch]['asset_ids'])
        citations=[]
        for field in rows:
            for row in payload[field]:
                pairs=sorted(set(row['evidence_pair_ids'])-assigned)
                assets=sorted(set(row['evidence_asset_ids'])-supplied)
                if pairs or assets:citations.append({'row_type':field,'row_id':row['id'],'pairs':pairs,'assets':assets})
        provenance[branch]={'original_valid':False,'original_errors':deepcopy(record['errors']),
            'raw_payload':deepcopy(payload),'response_path':str(path),'response_sha256':digest(path),
            'original_supplied_image_asset_ids':sorted(supplied),
            'unsupported_inspected_pair_ids':sorted(set(payload['inspected_pair_ids'])-assigned),
            'unsupported_citations':citations}
        files.extend([path,outcome_path]);responses[branch]=raw
    request_path=Path(prior_request).resolve()
    if request_path!=Path(source_responses['A']).resolve().with_name('request.json'):
        raise ValueError('calibration requires original A request alongside response')
    request=_read(request_path)
    body=request['body'];branch=plan['branches']['A']
    if body['messages']!=branch['messages'] or body.get('tools')!=branch['tools']:
        raise ValueError('original A exact prefix/tools mismatch')
    if body.get('max_tokens')!=64000:raise ValueError('original A output contract mismatch')
    if not body.get('model') or body['model']!=responses['A'].get('model'):
        raise ValueError('original A calibration model mismatch')
    usage=responses['A'].get('usage',{})
    if any(type(usage.get(k)) is not int or usage[k]<0 for k in ('prompt_tokens','completion_tokens','total_tokens')):
        raise ValueError('complete original provider usage required')
    if usage['prompt_tokens']<=0 or usage['total_tokens']!=usage['prompt_tokens']+usage['completion_tokens']:
        raise ValueError('inconsistent original provider usage')
    files.append(request_path)
    baseline={'messages':deepcopy(body['messages']),'tools':deepcopy(body['tools']),'prompt_tokens':usage['prompt_tokens']}
    provenance={'discovery_uncertified':True,'original_run_status':'blocked_discovery',
        'original_discovery_passed':False,'visual_inspection_proven':False,'all_findings_identified':False,
        'later_evidence_does_not_certify_prior_inspection':True,'sources':provenance,
        'provider_usage':deepcopy(usage),'calibration_request':str(request_path),
        'calibration_request_sha256':digest(request_path)}
    return rows,provenance,baseline,responses,{str(p.resolve()):digest(p) for p in files}


def _packet(plan, rows, provenance, baseline, responses, components, policy):
    messages=deepcopy(baseline['messages'])
    assistant=deepcopy(responses['A']['choices'][0]['message'])
    messages.append(assistant)
    messages.append({'role':'tool','tool_call_id':assistant['tool_calls'][0]['id'],
        'content':json.dumps({'discovery_uncertified':True,'instruction':
            'The prior discovery failed evidence checks. Every finding is only a hypothesis. '
            'The following newly supplied evidence was not seen by that discovery. '
            'Assess every hypothesis against the complete evidence; never certify prior inspection.'},ensure_ascii=False)})
    supplied=set(plan['branches']['A']['asset_ids']);missing=set(plan['image_asset_ids'])-supplied
    appended=set()
    for message,assets in zip(plan['source_messages'],plan['message_assets']):
        if missing.intersection(assets):
            if not set(assets)<=missing:raise ValueError('partial source evidence message')
            messages.append(deepcopy(message));appended.update(assets)
    if appended!=missing or _image_blocks(messages)!=_image_blocks(plan['source_messages']):
        raise ValueError('complete unchanged source image multiset required')
    messages.append({'role':'user','content':json.dumps(contract(policy),ensure_ascii=False)})
    messages.append({'role':'user','content':json.dumps({'uncertified_discovery_provenance':provenance},ensure_ascii=False)})
    messages.append({'role':'user','content':json.dumps({'capacity_repair':{
        'discovery_uncertified':True,'base_revision':components['base_revision'],
        'components':components['components'],'conflicts':components.get('conflicts',[]),
        'instruction':'Return an explicit evidence-backed disposition for every issue and observation. '
        'All rows are uncertified hypotheses, including preserve/equivalent and unsupported claims. '
        'Do not silently discard any row. Use submit_capacity_repair with the strict program contract '
        'and nested args.operations. Preserve complete component scope, exact revision, dependency, '
        'capability, SP, crop, arrow, typed and neighbor guards. Full source evidence is now supplied; '
        'it does not validate any earlier inspection claim. Receipts do not establish visual success.'}},ensure_ascii=False)})
    batch={'component_ids':[c['id'] for c in components['components']],
        'issue_ids':[r['id'] for r in rows['issues']],'observation_ids':[r['id'] for r in rows['observations']],
        'write_ids':sorted({i for c in components['components'] for i in c['write_ids']}),
        'read_ids':sorted({i for c in components['components'] for i in c['read_ids']}),
        'unknown_scope':any(c['unknown_scope'] for c in components['components']),
        'asset_ids':sorted(plan['image_asset_ids']),'base_revision':components['base_revision'],
        'messages':messages,'tools':deepcopy(plan['repair_tools'])}
    batch['capacity']=_budget(messages,batch['tools'],baseline)
    return batch


def prepare(source_workflow, task_dir, *, prior_request, source_responses, capabilities=None):
    """Freeze a single complete diagnostic packet from a read-only failed workflow.

    prior_request is the original saved A request.json (endpoint/body envelope).
    source_responses maps A/B to the exact original complete response.json paths.
    No feasibility candidate, evaluation file, provider, or credential is consulted.
    """
    source=Path(source_workflow).resolve();root=Path(task_dir).resolve()
    if root==source or source in root.parents:raise ValueError('diagnostic output must be outside original workflow')
    if root.exists() and any(root.iterdir()):raise ValueError('diagnostic preparation requires new empty directory')
    plan=_read(source/'plan.json');shared._integrity(source,plan)
    policy=load_policy(source,capabilities)
    fresh=_read_source(Path(plan['source_review']))
    for key in fresh:
        if key=='source_messages':
            if plan[key][:-1]!=fresh[key]:raise ValueError('source message reconstruction mismatch')
        elif key=='message_assets':
            if plan[key][:-1]!=fresh[key]:raise ValueError('source image ownership reconstruction mismatch')
        elif plan[key]!=fresh[key]:raise ValueError('source reconstruction mismatch: '+key)
    if plan['source_messages'][-1]['role']!='user' or json.loads(plan['source_messages'][-1]['content'])!=contract(policy):
        raise ValueError('original active contract mismatch')
    rows,provenance,baseline,responses,hashes=_history(source,plan,prior_request,source_responses)
    # The planner's readiness flag here only permits graph construction. Never
    # modify or merge the original invalid discovery records into a valid DS1.
    planning_input={**rows,'ready_for_repair':True}
    components=plan_repair_components(planning_input,next(iter(plan['initial_images'].values()))['svg'],plan)
    batch=_packet(plan,rows,provenance,baseline,responses,components,policy)
    root.mkdir(parents=True,exist_ok=True);freeze_policy(root,policy)
    for ident,image in plan['initial_images'].items():
        for key in ('svg','png','original'):
            old=Path(image[key]);target=root/'initial'/ident/old.name
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(old,target);image[key]=str(target)
    plan.update(version=VERSION,response_contract=deepcopy(RESPONSE_CONTRACT),discovery_uncertified=True,source_workflow=str(source),
        source_provenance_hashes=hashes,provider_prefix_baseline=baseline,provenance=provenance,
        issues=rows['issues'],observations=rows['observations'],component_plan=components,batch=batch)
    for filename,value in [('messages.json',batch['messages']),('tools.json',batch['tools']),
        ('capacity-audit.json',batch['capacity']),('provenance.json',provenance),
        ('component-plan.json',components),('provider-prefix-baseline.json',baseline),('plan.json',plan)]:write_json(root/filename,value)
    write_json(root/'prepared-files.json',{str(p.relative_to(root)):digest(p) for p in sorted(root.rglob('*')) if p.is_file()})
    if batch['capacity']['status']!='admitted':
        raise CapacityError('complete diagnostic exceeds capacity',batch['capacity'])
    return plan


def _integrity(root,plan):
    shared._integrity(root,plan)
    if plan.get('version')!=VERSION or plan.get('response_contract')!=RESPONSE_CONTRACT:
        raise ValueError('diagnostic response contract requires a new versioned preparation')
    for path,expected in plan['source_provenance_hashes'].items():
        if digest(path)!=expected:raise ValueError('original diagnostic provenance changed: '+path)


def run(task_dir, *, sender, capabilities=None):
    """Invoke one DS2 sender once and use the original shared guarded executor."""
    root=Path(task_dir).resolve();plan=_read(root/'plan.json');out=root/'run'
    try:out.mkdir()
    except FileExistsError as exc:raise ValueError('diagnostic run already started; no implicit resends') from exc
    result={'status':'blocked_integrity','version':plan.get('version'),'discovery_uncertified':True,'provenance':deepcopy(plan['provenance']),
        'images':deepcopy(plan['initial_images']),'terminal_source':'frozen_initial',
        'issues':deepcopy(plan['issues']),'observations':deepcopy(plan['observations']),
        'decisions':[],'rcd':[],'rejected_programs':[],'errors':[],'call_schedule':[],'repair_results':[],
        'component_plan':deepcopy(plan['component_plan']),
        'response_contract':deepcopy(plan.get('response_contract'))}
    try:
        integrity=lambda:_integrity(root,plan)
        integrity();policy=load_policy(root,capabilities)
        batch=plan['batch']
        outcomes=shared._dispatch([('DS2-diagnostic',batch,out/'repair/DS2-diagnostic')],sender,root,plan,1,
            integrity=integrity,budget_planner=lambda messages,tools:_budget(messages,tools,plan['provider_prefix_baseline']))
        result['call_schedule']=[{k:v for k,v in o.items() if k!='response'} for o in outcomes]
        record=shared._repair(outcomes[0],batch,plan,plan['component_plan']['components'],
            parser=lambda raw,tool:parse_response(raw,tool,allow_content_json=True))
        result['repair_results']=[record];write_json(out/'repair-results.json',[record])
        data=record['raw_payload']
        if isinstance(data,dict) and isinstance(data.get('decisions'),list):
            result['decisions']=[{**d,'request_name':record['request_name']} for d in data['decisions'] if isinstance(d,dict)]
        result['status']='blocked_repair_response'
        if record['valid']:
            def execution_integrity():
                integrity()
                outcome=outcomes[0]
                if digest(outcome['response']['response_path'])!=outcome['response_sha256']:
                    raise ValueError('saved diagnostic response changed before execution')
            shared._execute_repairs(out,result,[record],[batch],plan['component_plan'],policy,execution_integrity)
    except Exception as exc:
        result['errors'].append({'type':type(exc).__name__,'error':str(exc),'audit':getattr(exc,'audit',None)})
        shared._restore_terminal(out,result)
    return shared._finish(out,result)
