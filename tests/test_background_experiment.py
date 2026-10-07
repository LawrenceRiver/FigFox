import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest


def script():
    spec=importlib.util.spec_from_file_location('background_experiment',Path(__file__).resolve().parents[1]/'scripts/background-experiment.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('chain',[False,True])
def test_background_launch_returns_without_waiting_for_generation_and_freezes_target(tmp_path,monkeypatch,chain):
    module=script();monkeypatch.setattr(module,'ROOT',tmp_path)
    image=tmp_path/'complex image.png';Image.new('RGB',(2,2),'white').save(image)
    out=tmp_path/'new-output';calls=[]
    def launch(command,**kwargs):
        calls.append((command,kwargs));return SimpleNamespace(pid=1234)
    monkeypatch.setattr(module.subprocess,'Popen',launch)
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:pytest.fail('launch must not wait or call models'))
    args=['background-experiment.py',str(image),'--out',str(out)]
    if chain:args+=['--chain','--id','figure']
    monkeypatch.setattr(module.sys,'argv',args)
    assert module.main()==0 and len(calls)==1 and not out.exists()
    job=next((tmp_path/'runs/jobs').iterdir())
    config=json.loads((job/'job.json').read_text(encoding='utf-8'))
    assert config['target_usd']==1 and config['budget_usd'] is None and config['chain']==chain
    assert config['images']==[str(image)] and '--worker-config' in calls[0][0]
    assert (job/'source-manifest.json').exists()


@pytest.mark.parametrize('arguments',[['--target-usd','nan'],['--target-usd','-1'],['--budget-usd','inf']])
def test_invalid_launch_costs_fail_before_background_or_api_processes(tmp_path,monkeypatch,arguments):
    module=script();monkeypatch.setattr(module,'ROOT',tmp_path)
    monkeypatch.setattr(module.sys,'argv',['background-experiment.py']+arguments)
    monkeypatch.setattr(module.subprocess,'Popen',lambda *a,**k:pytest.fail('invalid configuration must not launch'))
    with pytest.raises(SystemExit):module.main()


def test_background_chain_preflight_failure_never_sends_a_model_request(tmp_path,monkeypatch):
    module=script();job=tmp_path/'job';job.mkdir()
    (job/'job.json').write_text(json.dumps({'chain':True,'target_usd':1,'out':str(tmp_path/'out'),
        'images':[str(tmp_path/'image.png')],'command':['forbidden-model-command']}),encoding='utf-8')
    monkeypatch.setattr(module,'batch_module',lambda:SimpleNamespace(load_environment=lambda:None))
    monkeypatch.setattr(module.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1))
    monkeypatch.setattr(module.subprocess,'Popen',lambda *a,**k:pytest.fail('failed preflight cannot launch models'))
    monkeypatch.setattr(module,'start_monitor',lambda *a,**k:None)
    module.worker(job/'job.json')
    state=json.loads((job/'job-status.json').read_text(encoding='utf-8'))
    assert state['status']=='failed' and 'no model request sent' in state['error']
    assert 'worker_pid' not in state


def test_monitor_runs_during_preflight_before_generation_can_begin(tmp_path, monkeypatch):
    module = script(); job = tmp_path/'job'; job.mkdir()
    (job/'job.json').write_text(json.dumps({'chain':True,'target_usd':1,'out':str(tmp_path/'out'),
        'images':[str(tmp_path/'image.png')],'command':['fixture-worker']}),encoding='utf-8')
    monkeypatch.setattr(module,'batch_module',lambda:SimpleNamespace(load_environment=lambda:None))
    monitors = []
    monkeypatch.setattr(module, 'start_monitor', lambda *a, **k:monitors.append((a,k)))
    def preflight(*a, **k):
        assert monitors, 'preflight must already have an independent monitor'
        state = json.loads((job/'job-status.json').read_text(encoding='utf-8'))
        assert state['status'] == 'starting'
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(module.subprocess, 'run', preflight)
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k:SimpleNamespace(pid=1234,wait=lambda:0))
    module.worker(job/'job.json')
    assert json.loads((job/'job-status.json').read_text(encoding='utf-8'))['status'] == 'completed'
