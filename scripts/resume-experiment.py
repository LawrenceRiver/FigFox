"""Resume a batch case that failed before rendering, reusing its saved GPT response."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('batch_experiment', ROOT/'scripts/batch-experiment.py')
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    batch.add_cost_arguments(parser)
    args = parser.parse_args()
    case = args.case.resolve()
    manifest = batch.read(case/'case.json')
    if not manifest or manifest.get('exit_code') in (None, 0):
        parser.error('case must be a recorded failed experiment')
    runs = list((case/'run').glob('native-*'))
    if len(runs) != 1:
        parser.error('expected exactly one saved native run')
    run = runs[0]
    if (run/'stage-0').exists() or (case/'run/review').exists():
        parser.error('only failures before baseline rendering can be resumed here')
    original = case/'original.png'
    if hashlib.sha256(original.read_bytes()).hexdigest() != manifest['source_sha256']:
        parser.error('original image changed since the experiment')
    response = run/'gpt55/response.json'
    if batch.read(response, {}).get('status') != 'completed':
        parser.error('saved GPT response is not complete')
    if args.budget_usd is not None:
        ledger = batch.read(case/'api-budget.json', {})
        if ledger.get('limit_usd') != args.budget_usd:
            parser.error('explicit hard resume limit must match the existing case ledger; default resume uses a cost target')
    batch.load_environment()
    history = case/'recovery.json'
    if history.exists():
        parser.error('a recovery was already attempted; inspect recovery.json before continuing')
    record = {'previous_case': dict(manifest), 'started_at': datetime.now(timezone.utc).isoformat(),
              'reused_response': str(response),
              'response_sha256': hashlib.sha256(response.read_bytes()).hexdigest(),
              'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                for p in (ROOT/'src').rglob('*.py')}}
    command = [sys.executable, '-u', '-m', 'figfox_plus', 'chain', '--image', str(original),
               '--id', manifest['id'], '--out', str(case/'run'), '--resume-first', str(run),
               '--rerun-authorization', 'reuse-saved-response-only']
    start = time.time()
    with batch.cost_policy(case, manifest, target_usd=args.target_usd, budget_usd=args.budget_usd) as environment:
        record['cost_policy'] = {key: manifest.get(key) for key in
            ('api_cost_mode', 'api_cost_target_usd', 'api_budget_usd')}
        batch.write_json(history, record)
        batch.write_json(case/'case.json', manifest)
        with (case/'console.log').open('a', encoding='utf-8') as log:
            log.write('\n--- Resume using saved GPT response ---\n'); log.flush()
            process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', errors='replace', env=environment)
            try:
                for line in process.stdout:
                    log.write(line); log.flush()
                    if line.startswith('{'): print(line.rstrip(), flush=True)
                exit_code = process.wait()
            except BaseException:
                process.terminate(); process.wait()
                raise
    elapsed = round(time.time()-start, 3)
    record.update(exit_code=exit_code, elapsed_seconds=elapsed,
                  finished_at=datetime.now(timezone.utc).isoformat(),
                  raw_response_unchanged=hashlib.sha256(response.read_bytes()).hexdigest() == record['response_sha256'])
    batch.write_json(history, record)
    manifest.update(exit_code=exit_code, elapsed_seconds=round(manifest.get('elapsed_seconds', 0)+elapsed, 3),
                    finished_at=record['finished_at'], recovery_elapsed_seconds=elapsed)
    batch.write_json(case/'case.json', manifest)
    rows = batch.collect_batch(case.parent)
    batch.report_cost_warning(next(row for row in rows if row['id'] == manifest['id']))
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
