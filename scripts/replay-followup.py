"""Re-execute a saved follow-up after host fixes; model APIs are prohibited."""
import argparse
from contextlib import redirect_stdout,redirect_stderr
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from figfox_plus.native.review_problem_first_v13.followup import run_followup,reconcile_followup
from figfox_plus.state import write_json


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def atomic_write(path,value):
    temp=path.with_suffix('.replay-tmp')
    write_json(temp,value);temp.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case',type=Path)
    args=parser.parse_args();case=args.case.resolve()
    manifest=read(case/'case.json');root=case/'run/review'/manifest['id']
    result=read(root/'result.json')
    if result.get('status')=='visual_review_pending':
        print('Review already completed; no replay needed.');return 0
    source=root.with_name(root.name+'-followup')/'message.json'
    message=read(source)
    from figfox_plus.native.review_problem_first_v13.orchestrator import _plan
    plan,_=_plan(message,read(root/'schedule.json'),review_only=True)
    for program in plan['programs']:
        image=result.get('images',{}).get(program.get('image_id'),{})
        if program.get('base_revision')!=image.get('revision'):
            raise ValueError('Saved response is stale or already applied; no replay performed')
    out=root.with_name(root.name+'-followup-replay-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    write_json(root.parent/'local-replay.json',{'reason':'Replay saved response under updated host; no API requests allowed'})
    calls=0
    def sender(*unused,**kwargs):
        nonlocal calls
        calls+=1
        if calls!=1:raise ValueError('saved replay only permits one model response')
        return message
    started=time.monotonic();status='failed'
    try:
        with (case/'console.log').open('a',encoding='utf-8',buffering=1) as log,redirect_stdout(log),redirect_stderr(log):
            followup=run_followup(root,out,sender=sender)
            state=read(out/'execution/state.json') if (out/'execution/state.json').exists() else {}
            previous=result
            result=reconcile_followup(dict(result,followup=followup),state)
            write_json(out/'previous-result.json',previous)
            atomic_write(root/'result.json',result)
            status='completed'
    finally:
        elapsed=round(time.monotonic()-started,3)
        write_json(out/'replay-provenance.json',{'source_message':str(source),
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'api_requests':0,
            'elapsed_seconds':elapsed,'status':status,
            'host_sources':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (ROOT/'src/figfox_plus').rglob('*.py')}})
        manifest['elapsed_seconds']=round(manifest.get('elapsed_seconds',0)+elapsed,3)
        manifest['recovery_elapsed_seconds']=round(manifest.get('recovery_elapsed_seconds',0)+elapsed,3)
        manifest['local_replay_seconds']=round(manifest.get('local_replay_seconds',0)+elapsed,3)
        manifest['finished_at']=datetime.now(timezone.utc).isoformat()
        atomic_write(case/'case.json',manifest)
    spec=importlib.util.spec_from_file_location('batch',ROOT/'scripts/batch-experiment.py')
    batch=importlib.util.module_from_spec(spec);spec.loader.exec_module(batch)
    summary=batch.collect_case(case)
    print(json.dumps({key:summary.get(key) for key in ('id','status','review_status','output_stage','estimated_usd','model_requests')}))
    return 0


if __name__=='__main__':raise SystemExit(main())
