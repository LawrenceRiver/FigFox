"""Recover a batch into a new run, reusing GPT responses and completed results."""
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
    loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded)
    return loaded


def rebase_metadata(folder, old, new):
    """Rebase local operational paths; immutable model requests/responses stay exact."""
    def convert(value):
        if isinstance(value,dict):return {k:convert(v) for k,v in value.items()}
        if isinstance(value,list):return [convert(v) for v in value]
        if isinstance(value,str):
            for before,after in ((str(old),str(new)),(old.as_posix(),new.as_posix())):
                if value.startswith(before):return after+value[len(before):]
        return value
    for path in folder.rglob('*.json'):
        if {'gpt55','model-turns'} & set(path.relative_to(folder).parts):continue
        data=json.loads(path.read_text(encoding='utf-8'))
        changed=convert(data)
        if changed!=data:path.write_text(json.dumps(changed,ensure_ascii=False,indent=2),encoding='utf-8')


def source_cases(source, meta, bench):
    """An interrupted recovery can fall back to its parent for unstarted cases."""
    for case_id in meta['case_map']:
        current=source;seen=set()
        while current not in seen:
            seen.add(current)
            state=bench.read(current/'run.json')
            matches=list((current/state['raw_dir']).glob(case_id+'-*/case.json'))
            if len(matches)==1:
                yield matches[0].parent
                break
            if len(matches)>1:raise ValueError('duplicate case in source run: '+case_id)
            if not state.get('recovery_source'):raise ValueError('missing saved case: '+case_id)
            current=Path(state['recovery_source']).resolve()
        else:raise ValueError('cyclic recovery lineage')


def main():
    batch=module('batch-experiment');bench=module('benchmark')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path)
    parser.add_argument('--run-id',default=datetime.now().strftime('%Y%m%d-%H%M%S')+'-recovery')
    parser.add_argument('--replay-cases',nargs='*',default=[],help='replay specified completed case IDs after host fixes; saved valid model replies are reused')
    parser.add_argument('--offline',action='store_true',help='reuse saved responses only; never send a model request')
    batch.add_cost_arguments(parser,hard_limit=False)
    args=parser.parse_args()
    batch.load_environment()
    from figfox_plus.native.chain import run_chain
    from figfox_plus.native.review_problem_first_v13.transport import send
    from figfox_plus.assets import rmbg_runtime
    rmbg_runtime()  # Fail locally before creating any paid continuation.
    source=args.source.resolve();meta=bench.read(source/'run.json')
    if set(args.replay_cases)-set(meta['case_map']):raise ValueError('unknown case IDs to replay')
    bench.identifier(args.run_id)
    destination=source.parent/args.run_id
    destination.mkdir(exist_ok=False);(destination/'raw').mkdir()
    for name in ('dataset.json','method.json'):shutil.copy2(source/name,destination/name)
    meta.update(run_id=args.run_id,status='running',recovery_source=str(source),
                api_mode='offline' if args.offline else 'online',
                api_cost_target_usd=args.target_usd,
                started_at=datetime.now(timezone.utc).isoformat())
    meta.pop('finished_at',None)
    bench.write(destination/'run.json',meta)
    sources=[p for directory in ('src','prompts','runtime','scripts') for p in (ROOT/directory).rglob('*')
             if p.is_file() and p.suffix in ('.py','.md','.cjs')]
    bench.write(destination/'raw/source-manifest.json',{str(p.relative_to(ROOT)):bench.sha(p) for p in sources})
    failed=False
    for old in source_cases(source,meta,bench):
        previous=bench.read(old/'summary.json') if (old/'summary.json').is_file() else batch.collect_case(old)
        case=destination/'raw'/old.name
        manifest=bench.read(old/'case.json')
        complete=manifest['id'] not in args.replay_cases and previous.get('execution_status') not in ('blocked','failed','running') and previous.get('exit_code')==0 and previous.get('output_stage') in ('review','followup') and previous.get('review_status',previous['status'])!='inspection_incomplete'
        if complete:
            shutil.copytree(old,case)
            # Keep the frozen evidence byte-identical; its source paths remain valid.
        else:
            case.mkdir();(case/'run').mkdir()
            shutil.copy2(old/'original.png',case/'original.png')
            natives=list((old/'run').glob('native-*'))
            if len(natives)!=1:raise ValueError('expected exactly one saved GPT run')
            native=case/'run'/natives[0].name
            shutil.copytree(natives[0],native)
            rebase_metadata(native,old,case)
            # Original API evidence is immutable. Copied GPT is counted once;
            # prior DeepSeek calls remain in an explicit historical ledger.
            if bench.sha(native/'gpt55/response.json')!=bench.sha(natives[0]/'gpt55/response.json'):
                raise ValueError('saved GPT response changed during copying')
            history=bench.read(old/'costs.json')
            history['calls']=[dict(c,reused_from=c.get('reused_from',str(old))) for c in history['calls'] if '/gpt55/' not in c['request'].replace('\\','/')]
            bench.write(case/'prior-costs.json',history)
        manifest.update(exit_code=None,recovery_source=str(old),previous_estimated_usd=previous['estimated_usd'],
                        previous_elapsed_seconds=previous.get('elapsed_seconds',0),
                        recovery_mode='reuse_completed' if complete else 'reuse_saved_gpt',
                        recovery_started_at=datetime.now(timezone.utc).isoformat())
        bench.write(case/'case.json',manifest)
        started=time.monotonic();exit_code=0
        print(json.dumps({'event':'recovery_started','id':manifest['id'],'mode':manifest['recovery_mode']}),flush=True)
        if not complete:
            image_id=manifest['id'];old_review=old/'run/review'/image_id
            from figfox_plus.native.review_problem_first_v13.orchestrator import _plan
            replay=[];not_reused=[]
            for index in (1,2):
                saved=old_review/f'phase-{index}/message.json'
                if not saved.is_file():break
                try:_plan(bench.read(saved),bench.read(old_review/'schedule.json'),review_only=index>1)
                except (ValueError,KeyError,TypeError) as exc:
                    not_reused.append({'path':str(saved),'reason':str(exc)})
                    break
                replay.append(saved)
            if replay or not_reused:
                manifest['recovery_mode']='replay_saved_review'
                bench.write(case/'review-replay.json',{'sources':[{ 'path':str(p),'sha256':bench.sha(p)} for p in replay],
                    'not_reused':not_reused,
                    'note':'Previously returned model decisions re-executed with fixed host; no new model assessment for these phases.'})
            replay_index=0
            def sender(messages,tools,task_dir,*,request_limit):
                nonlocal replay_index
                if replay_index<len(replay):
                    path=replay[replay_index];replay_index+=1
                    return bench.read(path)
                if args.offline:
                    bench.write(case/'blocked-model-stage.json',{'reason':'offline_mode_requires_missing_model_response',
                        'stage':str(task_dir),'model_request_sent':False})
                    raise ValueError('Offline recovery: missing saved model response; no API request sent')
                return send(messages,tools,task_dir,request_limit=request_limit)
            with batch.cost_policy(case,manifest,target_usd=args.target_usd), (case/'console.log').open('w',encoding='utf-8',buffering=1) as log, redirect_stdout(log),redirect_stderr(log):
                bench.write(case/'case.json',manifest)
                try:
                    if args.offline and not replay:
                        sender([],[],case/'run/review'/image_id,request_limit=2)
                    mode={'resume_baseline':native} if (native/'stage-0').is_dir() else {'resume_first':native}
                    run_chain(case/'original.png',case/'run',image_id=image_id,
                              rerun_authorization='saved-response-recovery',review_sender=sender,**mode)
                except Exception:
                    traceback.print_exc();exit_code=1
                except SystemExit as exc:
                    print(str(exc));exit_code=1
        recovery_seconds=round(time.monotonic()-started,3)
        manifest.update(exit_code=exit_code,recovery_elapsed_seconds=recovery_seconds,
                        elapsed_seconds=round(previous.get('elapsed_seconds',0)+recovery_seconds,3),
                        finished_at=datetime.now(timezone.utc).isoformat())
        bench.write(case/'case.json',manifest)
        row=batch.collect_case(case)
        failed|=exit_code!=0
        batch.report_cost_warning(row)
        print(json.dumps({'event':'recovery_finished',**{k:row[k] for k in ('id','status','review_status','additional_estimated_usd','output_stage','recovery_elapsed_seconds')}}),flush=True)
        batch.collect_batch(destination/'raw')
    bench.collect(destination)
    final_meta=bench.read(destination/'run.json')
    final_meta['finished_at']=datetime.now(timezone.utc).isoformat()
    bench.write(destination/'run.json',final_meta)
    print(str(destination),flush=True)
    return int(failed)


if __name__=='__main__':raise SystemExit(main())
