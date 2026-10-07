"""Continue unresolved reviews from committed scenes without rerunning GPT.

Creates a separate recovery batch; extra rounds are explicit experiment deviations.
"""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def main():
    batch=module('batch-experiment');bench=module('benchmark')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--run-id',default=datetime.now().strftime('%Y%m%d-%H%M%S')+'-review-recovery')
    parser.add_argument('--execute',action='store_true',help='allow DS requests; otherwise accounting and status only')
    parser.add_argument('--max-rounds',type=int,default=3)
    parser.add_argument('--max-added-usd',type=batch.positive_usd,
        help='optional explicit hard ceiling for extra recovery costs across this batch')
    batch.add_cost_arguments(parser,hard_limit=False)
    args=parser.parse_args()
    if not 1<=args.max_rounds<=3:raise ValueError('bounded recovery: 1..3 rounds')
    batch.load_environment()
    from figfox_plus.native.review_problem_first_v13.followup import run_followup, reconcile_followup, open_issues
    from figfox_plus.native.review_problem_first_v13.transport import send
    source=args.source.resolve();meta=bench.read(source/'run.json')
    if meta['status']=='running':raise ValueError('source batch must be finished')
    bench.identifier(args.run_id)
    dest=source.parent/args.run_id;dest.mkdir(exist_ok=False)
    for name in ('dataset.json','method.json'):shutil.copy2(source/name,dest/name)
    meta.update(run_id=args.run_id,status='running',recovery_source=str(source),
                started_at=datetime.now(timezone.utc).isoformat(),recovery_policy={
                    'name':'continue committed review','max_rounds':args.max_rounds,
                    'max_added_usd':args.max_added_usd,'api_cost_target_usd':args.target_usd,
                    'gpt_rerun':False,'extra_rounds_are_baseline_deviation':True})
    meta.pop('finished_at',None);bench.write(dest/'run.json',meta)
    (dest/'raw').mkdir()
    total_added=0.0
    paths=[p for folder in ('src','scripts') for p in (ROOT/folder).rglob('*.py')]
    bench.write(dest/'source-manifest.json',{str(p.relative_to(ROOT)):bench.sha(p) for p in paths})
    for old in sorted((source/'raw').glob('case-*')):
        if not (old/'case.json').exists():continue
        case=dest/'raw'/old.name
        shutil.copytree(old,case)
        previous=bench.read(old/'summary.json');manifest=bench.read(case/'case.json')
        ident=manifest['id'];review=case/'run/review'/ident
        baseline_total=previous['estimated_usd']
        manifest.update(recovery_source=str(old),previous_estimated_usd=baseline_total,
            previous_elapsed_seconds=previous['elapsed_seconds'],recovery_mode='continue_committed_review',
            recovery_started_at=datetime.now(timezone.utc).isoformat(),exit_code=0)
        bench.write(case/'case.json',manifest)
        # Original response files, scenes and earlier histories remain unchanged.
        result=bench.read(review/'result.json')
        bench.write(case/'review-before-continuation.json',result)
        follow=Path((result.get('followup') or {}).get('execution_directory') or review.with_name(ident+'-followup')/'execution')
        preflight=batch.read(follow.parent/'program-preflight.json',{})
        if result.get('followup') and preflight:
            result['followup']['rejected_programs']=preflight.get('rejected',[])+preflight.get('shape_rejected',[])
        result=reconcile_followup(result,batch.read(follow/'state.json',{}))
        bench.write(review/'result.json',result)
        started=time.monotonic();rounds=[]
        print(json.dumps({'event':'case_started','id':ident,'open_issues':[i['id'] for i in open_issues(result)]}),flush=True)
        for index in range(1,args.max_rounds+1):
            if not args.execute or not open_issues(result):break
            # Prior review roots can be explicitly offline-only replays. Keep
            # that boundary intact; authorized new calls get a separate root.
            task=case/'run/continuations'/f'{args.run_id}-{ident}-round-{index}'
            def sender(messages,tools,task_dir,*,request_limit):
                current=batch.collect_case(case)
                added=current['estimated_usd']-baseline_total
                if not current['cost_complete']:raise ValueError('unresolved cost uncertainty; no paid continuation')
                if args.max_added_usd is not None and total_added+added+0.5>args.max_added_usd:
                    raise ValueError('recovery budget would be exceeded')
                return send(messages,tools,task_dir,request_limit=request_limit)
            mark=time.monotonic()
            bench.write(case/f'review-before-round-{index}.json',result)
            try:
                with batch.cost_policy(case,manifest,target_usd=args.target_usd), (case/f'continuation-{index}.log').open('w',encoding='utf-8',buffering=1) as log,redirect_stdout(log),redirect_stderr(log):
                    bench.write(case/'case.json',manifest)
                    receipt=run_followup(review,task,sender=sender)
                result.setdefault('followup_history',[]).append(result.get('followup',{}))
                result['followup']=receipt
                state=batch.read(task/'execution/state.json',{})
                result=reconcile_followup(result,state)
                bench.write(review/'result.json',result)
                record={'round':index,'status':result['status'],'elapsed_seconds':round(time.monotonic()-mark,3),
                        'open_issues':[i['id'] for i in open_issues(result)]}
            except Exception as exc:
                record={'round':index,'status':'failed','error':str(exc),'elapsed_seconds':round(time.monotonic()-mark,3)}
                (case/f'continuation-{index}-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
                rounds.append(record);print(json.dumps({'event':'round_finished','id':ident,**record}),flush=True)
                break
            rounds.append(record);print(json.dumps({'event':'round_finished','id':ident,**record}),flush=True)
        elapsed=round(time.monotonic()-started,3)
        manifest.update(elapsed_seconds=round(previous['elapsed_seconds']+elapsed,3),
                        recovery_elapsed_seconds=elapsed,finished_at=datetime.now(timezone.utc).isoformat())
        bench.write(case/'case.json',manifest);bench.write(case/'continuation-rounds.json',rounds)
        row=batch.collect_case(case);total_added+=row['additional_estimated_usd']
        batch.report_cost_warning(row)
        # Every saved GPT response remains identical, and is counted once.
        for p in (case/'run').glob('native-*/gpt55/response.json'):
            assert bench.sha(p)==bench.sha(old/p.relative_to(case))
        print(json.dumps({'event':'case_finished','id':ident,'status':row['status'],'added_usd':row['additional_estimated_usd']}),flush=True)
    batch.collect_batch(dest/'raw');bench.collect(dest)
    meta=bench.read(dest/'run.json');meta.update(finished_at=datetime.now(timezone.utc).isoformat(),additional_estimated_usd=round(total_added,6))
    bench.write(dest/'run.json',meta)
    print(str(dest),flush=True)


if __name__=='__main__':main()
