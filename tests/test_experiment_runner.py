import importlib.util
from pathlib import Path
import json
import pytest
from PIL import Image

spec = importlib.util.spec_from_file_location('batch_experiment', Path(__file__).resolve().parents[1]/'scripts/batch-experiment.py')
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def test_costs_count_cache_and_do_not_double_count_reasoning():
    result = batch.estimate_usage('gpt-5.5', {'input_tokens': 2000, 'input_tokens_details': {'cached_tokens': 1000},
        'output_tokens': 1000, 'output_tokens_details': {'reasoning_tokens': 600}}, 1790494446)
    assert result['estimated_usd'] == 0.0355
    result = batch.estimate_usage('deepseek-flash', {'prompt_tokens': 2000, 'prompt_cache_hit_tokens': 1000,
                                                  'completion_tokens': 1000}, 1790494446)  # Sunday
    assert result['price_period'] == 'offpeak'
    assert result['estimated_usd'] == 0.000753


def test_failed_request_has_unknown_cost(tmp_path):
    case = tmp_path/'case'; case.mkdir()
    batch.write_json(case/'case.json', {'id':'case-001','original':'input.png','exit_code':1})
    batch.write_json(case/'run/native-fixture/gpt55/request.json', {'model':'gpt-5.5'})
    result = batch.collect_case(case)
    assert result['unknown_cost_requests'] == 1 and not result['cost_complete']
    assert result['status'] == 'failed' and result['outputs'] == {}
    assert result['input_tokens'] is None and not result['token_usage_complete']


def test_token_summary_handles_both_providers_and_included_reasoning():
    result=batch.token_summary([
        {'usage':{'input_tokens':100,'input_tokens_details':{'cached_tokens':50},'output_tokens':20,
                  'output_tokens_details':{'reasoning_tokens':10}}},
        {'usage':{'prompt_tokens':200,'prompt_cache_hit_tokens':100,'completion_tokens':40,
                  'completion_tokens_details':{'reasoning_tokens':30}}}])
    assert result['input_tokens']==300 and result['cached_input_tokens']==150
    assert result['output_tokens']==60 and result['reasoning_tokens']==40
    assert result['total_tokens']==360 and result['token_usage_complete']


def test_followup_output_takes_precedence(tmp_path):
    case = tmp_path/'case'; case.mkdir()
    batch.write_json(case/'case.json', {'id':'case-001','original':'input.png','exit_code':0})
    for name, color in (('base','red'),('new','blue')):
        (case/(name+'.svg')).write_text(f'<svg width="2" height="2"><rect id="box" width="2" height="2" fill="{color}"/></svg>')
        Image.new('RGB',(2,2),color).save(case/(name+'.png'))
    batch.write_json(case/'run/review/case-001/result.json', {'status':'visual_review_pending', 'images':{
        'case-001':{'svg':str(case/'base.svg'),'png':str(case/'base.png')}}})
    batch.write_json(case/'run/review/case-001-followup/execution/state.json', {'images':{
        'case-001':{'svg':str(case/'new.svg'),'png':str(case/'new.png')}}})
    result = batch.collect_case(case)
    assert result['output_stage'] == 'followup'
    assert (case/'final.svg').read_bytes() == (case/'new.svg').read_bytes()
    assert result['execution_status']=='completed'
    assert result['review_status']=='visual_review_pending'
    assert result['visual_passed'] is False


def test_recovery_history_is_counted_once_and_unknown_usage_stays_unknown(tmp_path):
    case=tmp_path/'case'
    batch.write_json(case/'case.json',{'id':'case-001','original':'input.png','exit_code':1,
        'recovery_source':'previous/case','previous_estimated_usd':0.0035})
    batch.write_json(case/'run/native-fixture/gpt55/request.json',{'model':'gpt-5.5'})
    batch.write_json(case/'run/native-fixture/gpt55/response.json',{'model':'gpt-5.5',
        'created_at':1790494446,'usage':{'input_tokens':100,'output_tokens':100}})
    batch.write_json(case/'prior-costs.json',{'calls':[{'request':'historical/deepseek/request.json',
        'model':'deepseek-flash','usage':{},'cost':None}]})
    for _ in range(2):
        result=batch.collect_case(case)
        assert result['model_requests']==2
        assert result['estimated_usd']==0.0035
        assert result['additional_estimated_usd']==0
        assert result['unknown_cost_requests']==1
        assert result['known_tokens']['total_tokens']==200
        assert result['total_tokens'] is None


def test_missing_export_is_not_reported_as_completed(tmp_path):
    case=tmp_path/'case'
    batch.write_json(case/'case.json',{'id':'case-001','original':'input.png','exit_code':0})
    batch.write_json(case/'run/review/case-001/result.json',{'status':'visual_review_pending','images':{
        'case-001':{'svg':str(case/'missing.svg'),'png':str(case/'missing.png')}}})
    result=batch.collect_case(case)
    assert result['status']=='failed'
    assert result['review_status']=='visual_review_pending'


def test_active_case_without_export_is_running(tmp_path):
    case=tmp_path/'case'
    batch.write_json(case/'case.json',{'id':'case-001','original':'input.png','exit_code':None})
    assert batch.collect_case(case)['status']=='running'


def test_offline_block_is_distinct_from_execution_failure_and_not_an_api_call(tmp_path):
    case=tmp_path/'case'
    batch.write_json(case/'case.json',{'id':'case-001','original':'input.png','exit_code':1})
    batch.write_json(case/'blocked-model-stage.json',{'reason':'offline_mode_requires_missing_model_response','model_request_sent':False})
    result=batch.collect_case(case)
    assert result['status']=='blocked' and result['model_requests']==0


def test_failed_review_exports_baseline_with_explicit_incomplete_status(tmp_path):
    case=tmp_path/'case';stage=case/'run/native-fixture/stage-0';stage.mkdir(parents=True)
    (stage/'scene.svg').write_text('<svg/>');Image.new('RGB',(2,2),'white').save(stage/'preview.png')
    batch.write_json(case/'case.json',{'id':'case-001','original':'input.png','exit_code':1})
    result=batch.collect_case(case)
    assert result['output_stage']=='baseline_only' and set(result['outputs'])=={'svg','png'}
    assert (case/'baseline.svg').is_file() and (case/'final.svg').read_text()=='<svg/>'
    assert result['status']=='failed' and result['review_complete'] is False
    assert result['visual_passed'] is False


@pytest.mark.parametrize('target,missing_usage,expected',[(0.003,False,'exceeded'),(1,False,'within_target'),(1,True,'unknown'),(0.003,True,'exceeded')])
def test_cost_target_reports_usage_without_turning_excess_into_pipeline_failure(tmp_path,target,missing_usage,expected):
    case=tmp_path/'case'
    batch.write_json(case/'case.json',{'id':'case-001','original':'input.png','exit_code':0,'api_cost_target_usd':target})
    stage=case/'run/native-fixture/stage-0';stage.mkdir(parents=True)
    (stage/'scene.svg').write_text('<svg/>');Image.new('RGB',(2,2),'white').save(stage/'preview.png')
    batch.write_json(case/'run/native-fixture/gpt55/request.json',{'model':'gpt-5.5'})
    batch.write_json(case/'run/native-fixture/gpt55/response.json',{'model':'gpt-5.5','created_at':1790494446,
        'usage':{'input_tokens':100,'output_tokens':100}})
    if missing_usage:batch.write_json(case/'run/review/case-001/model-turns/unknown/request.json',{'body':{'model':'deepseek-flash'}})
    row=batch.collect_case(case)
    assert row['cost_target_status']==expected
    assert row['estimated_usd']==0.0035 and row['exit_code']==0
    assert row['status']!='blocked' and 'api_budget_usd' not in row
    assert not (case/'api-budget.json').exists()


def test_summary_distinguishes_resolved_history_from_effective_failure(tmp_path):
    case=tmp_path/'case'
    batch.write_json(case/'case.json',{'id':'case-001','original':'input.png','exit_code':0})
    scene=case/'scene.svg';scene.parent.mkdir(parents=True,exist_ok=True);scene.write_text('<svg/>')
    png=case/'preview.png';Image.new('RGB',(2,2),'white').save(png)
    repaired={'program_id':'p','issue_ids':['S2-1'],'status':'changed_unverified'}
    batch.write_json(case/'run/review/case-001/result.json',{'status':'visual_review_pending',
        'coverage':{'records_complete':True},
        'issues':[{'id':'S2-1','decision':'confirmed'}],
        'rcd':[{'program_id':'p','issue_ids':['S2-1'],'status':'failed','error':'invalid box shape'}],
        'followup':{'status':'completed','issue_ids':['S2-1'],'rcd':[repaired]},
        'images':{'case-001':{'svg':str(scene),'png':str(png)}}})
    batch.write_json(case/'run/review/case-001-followup/execution/state.json',{
        'images':{'case-001':{'svg':str(scene),'png':str(png)}},'rcd':[repaired]})
    row=batch.collect_case(case)
    assert row['historical_failed_or_blocked_programs']==1
    assert row['effective_failed_or_blocked_programs']==0 and row['execution_status']=='completed'


@pytest.mark.parametrize('hard_limit',[None,'2'])
@pytest.mark.parametrize('explicit_target',[False,True])
def test_target_runner_preserves_explicit_hard_limit_and_avoids_inherited_case_ledger(tmp_path,monkeypatch,hard_limit,explicit_target):
    from types import SimpleNamespace
    image=tmp_path/'input.png';Image.new('RGB',(2,2),'white').save(image)
    out=tmp_path/'batch'
    monkeypatch.setenv('FIGFOX_COST_LIMIT_USD','0.001')
    monkeypatch.setenv('FIGFOX_COST_BUDGET_FILE',str(tmp_path/'other-case-budget.json'))
    monkeypatch.setattr(batch,'load_environment',lambda:None)
    monkeypatch.setattr(batch.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    captured=[]
    def child(command,**kwargs):
        captured.append(kwargs['env'])
        return SimpleNamespace(stdout=[],wait=lambda:0)
    monkeypatch.setattr(batch.subprocess,'Popen',child)
    args=['batch-experiment.py',str(image),'--out',str(out)]
    if explicit_target:args+=['--target-usd','1']
    if hard_limit is not None:args+=['--budget-usd',hard_limit]
    monkeypatch.setattr(batch.sys,'argv',args)
    assert batch.main()==0
    env=captured[0]
    if hard_limit is None:
        assert 'FIGFOX_COST_LIMIT_USD' not in env and 'FIGFOX_COST_BUDGET_FILE' not in env
    else:
        assert env['FIGFOX_COST_LIMIT_USD']=='2.0'
        assert env['FIGFOX_COST_BUDGET_FILE']==str(out/'case-001-input/api-budget.json')
    row=json.loads((out/'case-001-input/summary.json').read_text())
    assert row['api_cost_target_usd']==1
    assert row['api_cost_mode']==('hard_limit' if hard_limit is not None else 'target')
    assert batch.os.environ['FIGFOX_COST_LIMIT_USD']=='0.001'
    assert batch.os.environ['FIGFOX_COST_BUDGET_FILE']==str(tmp_path/'other-case-budget.json')


def test_default_cost_target_warns_and_exports_after_exceeding_one_dollar(tmp_path,monkeypatch,capsys):
    from types import SimpleNamespace
    image=tmp_path/'input.png';Image.new('RGB',(2,2),'white').save(image)
    out=tmp_path/'batch'
    monkeypatch.setattr(batch,'load_environment',lambda:None)
    monkeypatch.setattr(batch.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    def child(command,**kwargs):
        assert 'FIGFOX_COST_LIMIT_USD' not in kwargs['env']
        case=out/'case-001-input';stage=case/'run/native-fixture/stage-0'
        stage.mkdir(parents=True)
        (stage/'scene.svg').write_text('<svg width="2" height="2"/>')
        Image.new('RGB',(2,2),'white').save(stage/'preview.png')
        batch.write_json(case/'run/native-fixture/gpt55/request.json',{'model':'gpt-5.5'})
        batch.write_json(case/'run/native-fixture/gpt55/response.json',{'model':'gpt-5.5',
            'created_at':1790494446,'usage':{'input_tokens':100000,'output_tokens':20000}})
        batch.write_json(case/'run/review/case-001/result.json',{'status':'visual_review_pending','images':{
            'case-001':{'svg':str(stage/'scene.svg'),'png':str(stage/'preview.png')}}})
        return SimpleNamespace(stdout=[],wait=lambda:0)
    monkeypatch.setattr(batch.subprocess,'Popen',child)
    monkeypatch.setattr(batch.sys,'argv',['batch-experiment.py',str(image),'--out',str(out)])
    assert batch.main()==0
    events=[json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith('{')]
    warning=next(event for event in events if event['event']=='cost_warning')
    assert warning['estimated_usd']==1.1 and warning['api_cost_target_usd']==1
    assert warning['cost_target_status']=='exceeded' and warning['generation_stopped_by_target'] is False
    finished=next(event for event in events if event['event']=='case_finished')
    assert finished['cost_target_status']=='exceeded' and finished['status']=='completed'
    row=batch.read(out/'case-001-input/summary.json')
    assert row['artifact_status']=='available' and set(row['outputs'])=={'svg','png'}


@pytest.mark.parametrize('flag',['--target-usd','--budget-usd'])
@pytest.mark.parametrize('amount',['nan','inf','0','-1'])
def test_invalid_cost_policy_is_rejected_before_any_runtime_or_model_call(tmp_path,monkeypatch,flag,amount):
    monkeypatch.setattr(batch.sys,'argv',['batch-experiment.py','--out',str(tmp_path/'batch'),flag,amount])
    monkeypatch.setattr(batch.subprocess,'run',lambda *a,**k:pytest.fail('invalid policy must fail before runtime checks'))
    with pytest.raises(SystemExit):batch.main()
    assert not (tmp_path/'batch').exists()
