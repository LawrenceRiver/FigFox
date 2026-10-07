"""Launch a detached experiment worker and a separate, zero-API-cost monitor."""
import argparse
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from figfox_plus.monitor import detached_options, start_monitor
from figfox_plus.state import write_json


def batch_module():
    spec = importlib.util.spec_from_file_location('figfox_background_batch', ROOT/'scripts/batch-experiment.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def worker(config_path):
    job = config_path.parent
    config = json.loads(config_path.read_text(encoding='utf-8'))
    batch = batch_module(); batch.load_environment()
    record = {'controller_pid':os.getpid(),'started_at':time.time(),'status':'starting'}
    write_json(job/'job-status.json',record)
    environment = os.environ.copy()
    environment['FIGFOX_START_MONITOR'] = '0'
    environment['FIGFOX_COST_TARGET_USD'] = str(config['target_usd'])
    for key in ('FIGFOX_COST_LIMIT_USD','FIGFOX_COST_BUDGET_FILE'):
        environment.pop(key,None)
    if config.get('chain') and config.get('budget_usd'):
        environment.update(FIGFOX_COST_LIMIT_USD=str(config['budget_usd']),FIGFOX_COST_BUDGET_FILE=str(job/'api-budget.json'))
    try:
        start_monitor(job,mode='job')
        with (job/'console.log').open('wb') as log:
            if config.get('chain'):
                preflight = subprocess.run([sys.executable,str(ROOT/'scripts/check-runtime.py'),'--credentials','--sandbox'],
                    cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL)
                if preflight.returncode:
                    raise RuntimeError('local preflight failed; no model request sent')
            process = subprocess.Popen(config['command'],cwd=ROOT,env=environment,stdout=log,
                stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,**detached_options())
            record.update(worker_pid=process.pid,status='running')
            write_json(job/'job-status.json',record)
            start_monitor(job,mode='job')
            code = process.wait()
        record.update(status='completed' if code==0 else 'failed',exit_code=code,finished_at=time.time())
    except BaseException as exc:
        record.update(status='failed',error_type=type(exc).__name__,error=str(exc),finished_at=time.time())
        start_monitor(job,mode='job')
    finally:
        write_json(job/'job-status.json',record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images',nargs='*')
    parser.add_argument('--input-dir',type=Path)
    parser.add_argument('--dataset')
    parser.add_argument('--samples',nargs='*')
    parser.add_argument('--run-id')
    parser.add_argument('--out',type=Path)
    parser.add_argument('--target-usd',type=float,default=1)
    parser.add_argument('--budget-usd',type=float)
    parser.add_argument('--chain',action='store_true')
    parser.add_argument('--id',default='figure')
    parser.add_argument('--authorization')
    parser.add_argument('--worker-config',type=Path,help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker_config:
        worker(args.worker_config.resolve()); return 0
    if any(v is not None and (not math.isfinite(v) or v<=0) for v in (args.target_usd,args.budget_usd)):
        parser.error('amounts must be positive and finite')
    images = [Path(p).resolve() for p in args.images]
    if args.input_dir:
        images += sorted(args.input_dir.resolve().glob('*.png'))
    if args.dataset:
        if images or args.chain or args.out:
            parser.error('dataset mode uses --samples and --run-id; do not combine other inputs')
        dataset = ROOT/'benchmark/datasets'/args.dataset
        if not dataset.is_dir() or not dataset.resolve().is_relative_to((ROOT/'benchmark/datasets').resolve()):
            parser.error('missing dataset')
    elif not images or any(not p.is_file() or p.suffix.lower()!='.png' for p in images):
        parser.error('supply existing PNGs or --input-dir')
    if args.chain and len(images)!=1:
        parser.error('chain mode requires one PNG')
    tag = datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8]
    out = args.out.resolve() if args.out else ROOT/'runs/experiments'/('background-'+tag)
    if not args.dataset and out.exists():
        parser.error('output already exists; choose a new output')
    if args.chain:
        out.parent.mkdir(parents=True,exist_ok=True)
        command = [sys.executable,'-u','-m','figfox_plus','chain','--image',str(images[0]),'--id',args.id,
            '--out',str(out),'--rerun-authorization',args.authorization or uuid4().hex,'--no-monitor']
    elif args.dataset:
        run_id = args.run_id or ('figfox-background-'+tag)
        command = [sys.executable,'-u',str(ROOT/'scripts/benchmark.py'),'run-figfox','--dataset',args.dataset,'--run-id',run_id]
        if args.samples:command += ['--samples']+args.samples
        # Resolve the authoritative output layout without creating a paid run.
        spec = importlib.util.spec_from_file_location('background_benchmark',ROOT/'scripts/benchmark.py')
        benchmark = importlib.util.module_from_spec(spec); spec.loader.exec_module(benchmark)
        benchmark.identifier(args.dataset); benchmark.identifier(run_id)
        registered = benchmark.load_dataset(benchmark.WORKSPACE/'datasets'/args.dataset/'dataset.json')
        if args.samples and set(args.samples)-{s['id'] for s in registered['samples']}:
            parser.error('unknown sample IDs')
        out = benchmark.WORKSPACE/'runs'/args.dataset/'figfox'/run_id/'raw'
        if out.parent.exists():
            parser.error('benchmark run already exists; choose a new run ID')
        if args.target_usd!=1 or args.budget_usd:
            parser.error('dataset launcher currently uses the default target; use PNG inputs for explicit cost options')
    else:
        command = [sys.executable,'-u',str(ROOT/'scripts/batch-experiment.py'),'--out',str(out),'--target-usd',str(args.target_usd)]+[str(p) for p in images]
        if args.budget_usd:command += ['--budget-usd',str(args.budget_usd)]
    job = ROOT/'runs/jobs'/tag; job.mkdir(parents=True)
    config = {'out':str(out),'images':[str(p) for p in images],'command':command,'chain':args.chain,
              'target_usd':args.target_usd,'budget_usd':args.budget_usd,'created_at':time.time()}
    write_json(job/'job.json',config)
    write_json(job/'source-manifest.json',{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for name in ('src','prompts','runtime','scripts') for p in (ROOT/name).rglob('*')
        if p.is_file() and p.suffix in ('.py','.md','.cjs','.ps1','.cs')})
    environment = os.environ.copy(); environment.update(PYTHONPATH=str(ROOT/'src'),PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
    with (job/'launcher.log').open('wb') as log:
        child = subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--worker-config',str(job/'job.json')],
            cwd=ROOT,env=environment,stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,**detached_options(breakaway=True))
    print(json.dumps({'event':'background_started','controller_pid':child.pid,'job':str(job),
        'status_page':str(job/'status.html'),'outputs':str(out),'target_usd':args.target_usd},ensure_ascii=False),flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
