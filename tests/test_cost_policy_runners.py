import hashlib
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'scripts'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


batch = script('batch-experiment')


def case_fixture(case, *, baseline=True, large_cost=False):
    case.mkdir(parents=True)
    original = case/'original.png'
    Image.new('RGB', (2, 2), 'white').save(original)
    manifest = {'id': 'case-001', 'original': str(original), 'exit_code': 1, 'elapsed_seconds': 3,
        'source_sha256': hashlib.sha256(original.read_bytes()).hexdigest(),
        'api_budget_usd': 10 if large_cost else 1}
    batch.write_json(case/'case.json', manifest)
    native = case/'run/native-fixture'
    batch.write_json(native/'gpt55/request.json', {'model': 'gpt-5.5'})
    usage = {'input_tokens': 750000 if large_cost else 100, 'output_tokens': 10}
    batch.write_json(native/'gpt55/response.json', {'status': 'completed', 'model': 'gpt-5.5',
        'created_at': 1790494446, 'usage': usage, 'output': []})
    native_cost = batch.estimate_usage('gpt-5.5', usage, 1790494446)['estimated_usd']
    batch.write_json(case/'api-budget.json', {'limit_usd': manifest['api_budget_usd'],
        'accounted_usd': native_cost, 'calls': [{'request_id': 'original', 'model': 'gpt-5.5',
            'status': 'usage_received', 'accounted_usd': native_cost, 'reserved_usd': native_cost}]})
    if baseline:
        stage = native/'stage-0'
        stage.mkdir()
        (stage/'scene.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"/>')
        Image.new('RGB', (2, 2), 'white').save(stage/'preview.png')
    return manifest, native


def review_result(run, ident, *, baseline=None):
    stage = baseline or next(run.glob('native-*/stage-0'))
    result = {'status': 'visual_review_pending', 'issues': [], 'rcd': [],
        'coverage': {'records_complete': True},
        'images': {ident: {'svg': str(stage/'scene.svg'), 'png': str(stage/'preview.png')}}}
    batch.write_json(run/'review'/ident/'result.json', result)
    return result


def saved_files(folder):
    return {p.relative_to(folder): p.read_bytes() for p in folder.rglob('*') if p.is_file()}


def inherited_guard(monkeypatch, folder):
    monkeypatch.setenv('FIGFOX_COST_LIMIT_USD', '0.001')
    monkeypatch.setenv('FIGFOX_COST_BUDGET_FILE', str(folder/'foreign-ledger.json'))


def test_target_policy_restores_environment_even_when_generation_raises(tmp_path, monkeypatch):
    inherited_guard(monkeypatch, tmp_path)
    manifest = {'api_budget_usd': 1}
    with pytest.raises(RuntimeError, match='interrupted'):
        with batch.cost_policy(tmp_path, manifest) as environment:
            assert 'FIGFOX_COST_LIMIT_USD' not in environment
            assert 'FIGFOX_COST_BUDGET_FILE' not in environment
            assert manifest['api_cost_target_usd'] == 1 and 'api_budget_usd' not in manifest
            raise RuntimeError('interrupted')
    assert os.environ['FIGFOX_COST_LIMIT_USD'] == '0.001'
    assert os.environ['FIGFOX_COST_BUDGET_FILE'] == str(tmp_path/'foreign-ledger.json')


@pytest.mark.parametrize('hard_limit', [None, '1'])
def test_resume_preserves_history_and_only_reactivates_an_explicit_hard_limit(tmp_path, monkeypatch, hard_limit):
    resume = script('resume-experiment')
    case = tmp_path/'batch/case-001-input'
    previous, native = case_fixture(case, baseline=False)
    response = (native/'gpt55/response.json').read_bytes()
    ledger = (case/'api-budget.json').read_bytes()
    inherited_guard(monkeypatch, tmp_path)
    monkeypatch.setattr(resume.batch, 'load_environment', lambda: None)
    calls = []
    def child(command, **kwargs):
        calls.append(command)
        assert '--resume-first' in command
        environment = kwargs['env']
        if hard_limit is None:
            assert 'FIGFOX_COST_LIMIT_USD' not in environment
        else:
            assert environment['FIGFOX_COST_LIMIT_USD'] == '1.0'
            assert environment['FIGFOX_COST_BUDGET_FILE'] == str(case/'api-budget.json')
        stage = native/'stage-0'; stage.mkdir()
        (stage/'scene.svg').write_text('<svg width="2" height="2"/>')
        Image.new('RGB', (2, 2), 'white').save(stage/'preview.png')
        review_result(case/'run', previous['id'])
        return SimpleNamespace(stdout=[], wait=lambda: 0)
    monkeypatch.setattr(resume.subprocess, 'Popen', child)
    args = ['resume-experiment.py', str(case)]
    if hard_limit is not None: args += ['--budget-usd', hard_limit]
    monkeypatch.setattr(resume.sys, 'argv', args)
    assert resume.main() == 0 and len(calls) == 1
    history = batch.read(case/'recovery.json')
    assert history['previous_case'] == previous and history['raw_response_unchanged']
    current = batch.read(case/'summary.json')
    assert current['api_cost_target_usd'] == 1 and current['artifact_status'] == 'available'
    assert ('api_budget_usd' in current) == (hard_limit is not None)
    assert current['model_requests'] == 1 and current['cost_complete']
    assert (native/'gpt55/response.json').read_bytes() == response
    assert (case/'api-budget.json').read_bytes() == ledger
    assert os.environ['FIGFOX_COST_LIMIT_USD'] == '0.001'


def test_hard_resume_cannot_start_a_new_ledger_to_forget_previous_costs(tmp_path, monkeypatch):
    resume = script('resume-experiment')
    case = tmp_path/'case'
    case_fixture(case, baseline=False)
    (case/'api-budget.json').unlink()
    monkeypatch.setattr(resume.sys, 'argv', ['resume-experiment.py', str(case), '--budget-usd', '1'])
    monkeypatch.setattr(resume.subprocess, 'Popen', lambda *a, **k: pytest.fail('no request may be started'))
    with pytest.raises(SystemExit): resume.main()
    assert not (case/'recovery.json').exists()


@pytest.mark.parametrize('has_ledger,hard_limit', [(False, None), (True, None), (True, 1.5)])
def test_explicit_ds_retry_defaults_to_target_and_counts_prior_calls_once(tmp_path, monkeypatch, has_ledger, hard_limit):
    retry = script('retry-deepseek-step')
    case = tmp_path/'old'; out = tmp_path/'retry'
    manifest, native = case_fixture(case)
    batch.collect_case(case)
    if not has_ledger: (case/'api-budget.json').unlink()
    review = case/'run/review/case-001'
    batch.write_json(review/'phase-1/message.json', {'role': 'assistant', 'content': '{}'})
    messages = [{'role': 'user', 'content': 'fixture'}]
    body = {'model': 'deepseek-flash', 'messages': messages, 'tools': [], 'max_tokens': 131072,
        'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high'}
    plan = {'manifest': manifest, 'review': review, 'failed': review/'model-turns/interrupted',
        'body': body, 'budget': case/'api-budget.json', 'source_hashes': {},
        'inputs': {'images': {'case-001': {'current_svg': {'path': str(native/'stage-0/scene.svg')},
            'current_png': {'path': str(native/'stage-0/preview.png')}}}}}
    monkeypatch.setattr(retry, 'retry_plan', lambda _: plan)
    inherited_guard(monkeypatch, tmp_path)
    before = saved_files(case)
    calls = []
    def send(incoming, tools, task, *, request_limit, **kwargs):
        calls.append(request_limit)
        assert request_limit == 1 and incoming == messages
        if hard_limit is None: assert 'FIGFOX_COST_LIMIT_USD' not in os.environ
        else: assert os.environ['FIGFOX_COST_LIMIT_USD'] == '1.5'
        turn = task/'model-turns/completed'
        batch.write_json(turn/'request.json', {'body': body})
        batch.write_json(turn/'response.json', {'model': 'deepseek-flash', 'created': 1790494446,
            'usage': {'prompt_tokens': 100, 'completion_tokens': 10}})
        return {'role': 'assistant', 'content': '{}'}
    monkeypatch.setattr(retry.transport, 'send', send)
    def run(task, *, sender, request_limit):
        assert request_limit == 2
        sender(messages, [], task, request_limit=2)
        return review_result(out/'run', manifest['id'], baseline=out/'run/native-reused/stage-0')
    monkeypatch.setattr(retry.orchestrator, 'run', run)
    result = retry.retry(case, out, authorization='explicit one-time retry', budget_usd=hard_limit)
    assert calls == [1] and result['exit_code'] == 0 and result['artifact_status'] == 'available'
    assert result['api_cost_target_usd'] == 1 and result['model_requests'] == 2
    assert result['estimated_usd'] > result['previous_estimated_usd']
    assert ('api_budget_usd' in result) == (hard_limit is not None)
    if hard_limit is None: assert saved_files(case) == before
    else:
        ledger = batch.read(case/'api-budget.json')
        assert ledger['limit_usd'] == 1.5 and len(ledger['calls']) == 1
        assert batch.read(out/'previous-api-budget.json')['limit_usd'] == 1
    assert os.environ['FIGFOX_COST_LIMIT_USD'] == '0.001'


@pytest.mark.parametrize('entry', ['recover-figfox-batch', 'continue-figfox-review'])
def test_batch_recovery_continues_above_target_without_a_hidden_five_dollar_cap(tmp_path, monkeypatch, entry):
    module = script(entry)
    bench = script('benchmark')
    source = tmp_path/'old-batch'; case = source/'raw/case-001-input'
    manifest, native = case_fixture(case, large_cost=True)
    result = review_result(case/'run', manifest['id'])
    batch.write_json(source/'dataset.json', {'id': 'fixture-v1', 'samples': [
        {'id': 'sample-0001', 'sha256': manifest['source_sha256'], 'original_filename': 'input.png'}]})
    batch.write_json(source/'method.json', {'id': 'figfox'})
    batch.write_json(source/'run.json', {'raw_dir': 'raw', 'method_id': 'figfox', 'status': 'has_failures',
        'case_map': {manifest['id']: 'sample-0001'}, 'run_id': 'old-batch'})
    batch.collect_case(case)
    original_files = saved_files(source)
    monkeypatch.setattr(module, 'module', lambda name: batch if name == 'batch-experiment' else bench)
    monkeypatch.setattr(batch, 'load_environment', lambda: None)
    inherited_guard(monkeypatch, tmp_path)
    from figfox_plus import assets
    from figfox_plus.native import chain
    from figfox_plus.native.review_problem_first_v13 import followup, transport
    monkeypatch.setattr(assets, 'rmbg_runtime', lambda: 'fixture')
    calls = []
    def send(messages, tools, task, *, request_limit):
        calls.append(request_limit)
        assert 'FIGFOX_COST_LIMIT_USD' not in os.environ
        turn = task/'model-turns/completed'
        batch.write_json(turn/'request.json', {'body': {'model': 'deepseek-flash'}})
        batch.write_json(turn/'response.json', {'model': 'deepseek-flash', 'created': 1790494446,
            'usage': {'prompt_tokens': 100, 'completion_tokens': 10}})
        return {'role': 'assistant', 'content': '{}'}
    monkeypatch.setattr(transport, 'send', send)
    if entry == 'recover-figfox-batch':
        def chain_run(image, out, *, image_id, review_sender, **kwargs):
            review_sender([], [], out/'review'/image_id, request_limit=2)
            review_result(out, image_id)
        monkeypatch.setattr(chain, 'run_chain', chain_run)
        args = [entry, str(source), '--run-id', 'new-target-recovery']
    else:
        monkeypatch.setattr(followup, 'open_issues', lambda current: [{'id': 'pending'}] if not calls else [])
        monkeypatch.setattr(followup, 'reconcile_followup', lambda current, state: current)
        def run_followup(review, task, *, sender):
            sender([], [], task, request_limit=1)
            return {'status': 'completed', 'rcd': []}
        monkeypatch.setattr(followup, 'run_followup', run_followup)
        args = [entry, str(source), '--run-id', 'new-target-recovery', '--execute']
    monkeypatch.setattr(module.sys, 'argv', args)
    module.main()
    row = batch.read(tmp_path/'new-target-recovery/raw/case-001-input/summary.json')
    assert row['estimated_usd'] > 5 and row['cost_target_status'] == 'exceeded'
    assert row['api_cost_mode'] == 'target' and 'api_budget_usd' not in row
    assert row['artifact_status'] == 'available' and row['exit_code'] == 0
    assert row['model_requests'] == 2 and len(calls) == 1
    assert saved_files(source) == original_files
    assert os.environ['FIGFOX_COST_LIMIT_USD'] == '0.001'
