import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('benchmark_workspace', Path(__file__).resolve().parents[1]/'scripts/benchmark.py')
workspace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workspace)


def test_dataset_preserves_inputs_and_detects_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace,'WORKSPACE',tmp_path/'benchmark')
    image = tmp_path/'source.png'; image.write_bytes(b'unchanged source bytes')
    folder = workspace.add_dataset('fixture-v1',[image],'fixture')
    dataset = workspace.load_dataset(folder/'dataset.json')
    sample = dataset['samples'][0]
    assert (folder/sample['image']).read_bytes() == image.read_bytes()
    assert sample['id'] == 'sample-0001'
    (folder/sample['image']).write_bytes(b'changed pixels')
    with pytest.raises(ValueError,match='hash mismatch'):
        workspace.load_dataset(folder/'dataset.json')


def test_dataset_cannot_overwrite_an_existing_version(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace,'WORKSPACE',tmp_path/'benchmark')
    image = tmp_path/'source.png'; image.write_bytes(b'input')
    workspace.add_dataset('fixture-v1',[image],'fixture')
    with pytest.raises(FileExistsError):
        workspace.add_dataset('fixture-v1',[image],'fixture')


def test_collect_maps_results_by_fixed_id_and_keeps_failures(tmp_path):
    run = tmp_path/'run'
    workspace.write(run/'run.json',{'method_id':'figfox','raw_dir':'raw',
                                   'case_map':{'case-001':'sample-0007','case-002':'sample-0012'}})
    workspace.write(run/'dataset.json',{'id':'fixture-v1','samples':[
        {'id':'sample-0007','sha256':'hash-a','original_filename':'a.png'},
        {'id':'sample-0012','sha256':'hash-b','original_filename':'b.png'}]})
    for case, digest, code in [('case-001','hash-a',0),('case-002','hash-b',1)]:
        workspace.write(run/'raw'/f'{case}-fixture/summary.json',{
            'source_sha256':digest,'status':'visual_review_pending' if code == 0 else 'failed',
            'exit_code':code,'elapsed_seconds':12,'model_requests':1,'estimated_usd':0.1,
            'cost_complete':True,'output_stage':'review' if code == 0 else 'none','visual_passed':False,
            'api_cost_mode':'target','api_cost_target_usd':1,'cost_target_status':'within_target'})
    (run/'raw/case-001-fixture/final.svg').write_text('<svg/>')
    rows = workspace.collect(run)
    assert [r['sample_id'] for r in rows] == ['sample-0007','sample-0012']
    assert (run/'samples/sample-0007/final.svg').read_text() == '<svg/>'
    assert not (run/'samples/sample-0012/final.svg').exists()
    assert workspace.read(run/'run.json')['status'] == 'has_failures'
    assert workspace.read(run/'summary.json')['estimated_usd'] == 0.2
    assert workspace.read(run/'samples/sample-0007/sample.json')['api_cost_target_usd'] == 1
    assert rows[0]['cost_target_status']=='within_target' and rows[0]['api_cost_mode']=='target'
    assert '费用目标 $1' in (run/'index.html').read_text(encoding='utf-8')
    failed = run/'raw/case-002-fixture/summary.json'
    summary = workspace.read(failed)
    summary.update(cost_complete=False,estimated_usd=0)
    workspace.write(failed,summary)
    workspace.collect(run)
    assert workspace.read(run/'samples/sample-0012/sample.json')['estimated_usd'] is None
    assert workspace.read(run/'summary.json')['estimated_usd'] is None
    assert workspace.read(run/'summary.json')['known_estimated_usd'] == 0.1


def test_runner_uses_registered_order_and_records_preflight_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace,'WORKSPACE',tmp_path/'benchmark')
    images = [tmp_path/'z.png',tmp_path/'a.png']
    for image in images:image.write_bytes(b'fixture')
    folder = workspace.add_dataset('fixture-v1',images,'fixture')
    workspace.write(workspace.WORKSPACE/'methods/figfox/method.json',{'id':'figfox'})
    commands = []
    def fake_run(command, **kwargs):
        from types import SimpleNamespace
        commands.append(command)
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr(workspace.subprocess,'run',fake_run)
    assert workspace.run_figfox('fixture-v1','test-001') == 2
    manifest = workspace.read(folder/'dataset.json')
    assert commands[0][3:5] == [str(folder/s['image']) for s in manifest['samples']]
    run = workspace.WORKSPACE/'runs/fixture-v1/figfox/test-001'
    assert workspace.read(run/'run.json')['status'] == 'failed_before_results'
    assert workspace.read(run/'run.json')['case_map'] == {'case-001':'sample-0001','case-002':'sample-0002'}
    with pytest.raises(ValueError,match='already exists'):
        workspace.run_figfox('fixture-v1','test-001')
    assert len(commands) == 1
