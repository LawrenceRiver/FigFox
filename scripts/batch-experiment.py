"""Run the unchanged chain once per PNG; collect outputs, events, timing and usage."""
import argparse
import csv
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from figfox_plus.state import write_json
from figfox_plus.usage_cost import PRICES, estimate_usage, classify_rejected_call

DEFAULT_COST_TARGET_USD = 1.0


def positive_usd(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('amount must be positive and finite')
    return number


def add_cost_arguments(parser, *, hard_limit=True):
    parser.add_argument('--target-usd', type=positive_usd, default=DEFAULT_COST_TARGET_USD,
        help='per-figure cost warning target (default: 1 USD); never shortens output or stops generation')
    if hard_limit:
        parser.add_argument('--budget-usd', type=positive_usd,
            help='explicit hard per-figure ceiling; reject unfunded whole requests without shortening output')


@contextmanager
def cost_policy(case, manifest, *, target_usd=DEFAULT_COST_TARGET_USD, budget_usd=None, budget_file=None):
    """Apply one case's explicit policy, preserving unrelated environment values."""
    manifest.update(api_cost_target_usd=positive_usd(target_usd),
                    api_cost_mode='hard_limit' if budget_usd is not None else 'target')
    if budget_usd is None:
        manifest.pop('api_budget_usd', None)
    else:
        manifest['api_budget_usd'] = positive_usd(budget_usd)
    keys = ('FIGFOX_COST_LIMIT_USD', 'FIGFOX_COST_BUDGET_FILE', 'FIGFOX_COST_TARGET_USD')
    previous = {key: os.environ.get(key) for key in keys}
    try:
        if budget_usd is None:
            for key in keys[:2]: os.environ.pop(key, None)
        else:
            os.environ.update(FIGFOX_COST_LIMIT_USD=str(manifest['api_budget_usd']),
                FIGFOX_COST_BUDGET_FILE=str(budget_file or Path(case)/'api-budget.json'))
        os.environ['FIGFOX_COST_TARGET_USD'] = str(manifest['api_cost_target_usd'])
        yield os.environ.copy()
    finally:
        for key, value in previous.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value


def report_cost_warning(row):
    if row.get('cost_target_status') == 'exceeded' or row.get('unknown_cost_requests', 0):
        print(json.dumps({'event': 'cost_warning', **{key: row.get(key) for key in
            ('id', 'api_cost_target_usd', 'cost_target_status', 'estimated_usd', 'cost_complete', 'unknown_cost_requests')},
            'generation_stopped_by_target': False}), flush=True)




def read(path, default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else default


def load_environment():
    for name in ('.env.local', '.env'):
        path = ROOT/name
        if not path.is_file(): continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip().removeprefix('export ')
            if not line or line.startswith('#') or '=' not in line: continue
            key, value = line.split('=', 1)
            if not os.environ.get(key.strip()):
                os.environ[key.strip()] = value.strip().strip('"').strip("'")
    os.environ['PYTHONPATH'] = str(ROOT/'src')
    os.environ['PYTHONUTF8'] = '1'
    os.environ['PYTHONIOENCODING'] = 'utf-8'




def token_summary(calls):
    fields=('input_tokens','cached_input_tokens','output_tokens','reasoning_tokens','total_tokens')
    totals=dict.fromkeys(fields,0);complete=True
    for call in calls:
        if call.get('usage_status')=='rejected_before_generation':continue
        usage=call.get('usage') or {}
        incoming=usage.get('input_tokens',usage.get('prompt_tokens'))
        outgoing=usage.get('output_tokens',usage.get('completion_tokens'))
        if not all(type(n) is int and n >= 0 for n in (incoming, outgoing)):
            complete=False;continue
        totals['input_tokens']+=incoming;totals['output_tokens']+=outgoing
        totals['total_tokens']+=incoming+outgoing
        cached=usage.get('prompt_cache_hit_tokens',(usage.get('input_tokens_details') or {}).get('cached_tokens',(usage.get('prompt_tokens_details') or {}).get('cached_tokens',0)))
        if type(cached) is int and 0 <= cached <= incoming:totals['cached_input_tokens']+=cached
        else:complete=False
        totals['reasoning_tokens']+=(usage.get('output_tokens_details') or usage.get('completion_tokens_details') or {}).get('reasoning_tokens') or 0
    return {**{k:v if complete else None for k,v in totals.items()},'known_tokens':totals,'token_usage_complete':complete}


def collect_case(case):
    case = Path(case)
    manifest = read(case/'case.json', {})
    run = case/'run'
    calls = []
    for request in sorted(run.rglob('request.json')):
        if request.parent.name != 'gpt55' and request.parent.parent.name != 'model-turns': continue
        req = read(request, {})
        response = read(request.parent/'response.json', {})
        usage = response.get('usage') or read(request.parent/'usage.json', {})
        # Incomplete OpenAI streams may still contain reported usage; never treat missing usage as zero.
        if not usage and (request.parent/'events.jsonl').exists():
            with (request.parent/'events.jsonl').open(encoding='utf-8') as events:
                for line in events:
                    try: event = json.loads(line)
                    except json.JSONDecodeError: continue
                    usage = event.get('response', {}).get('usage') or event.get('usage') or usage
        model = response.get('model') or req.get('model') or req.get('body', {}).get('model', '')
        stamp = response.get('created_at', response.get('created', request.stat().st_mtime))
        calls.append({'request': str(request.relative_to(case)), 'model': model, 'usage': usage,
                      'request_saved_at': datetime.fromtimestamp(request.stat().st_mtime, timezone.utc).isoformat(),
                      'response_elapsed_seconds': round((request.parent/'response.json').stat().st_mtime-request.stat().st_mtime, 3) if response else None,
                      'cost': estimate_usage(model, usage, stamp),
                      'error': read(request.parent/'error.json')})
    # Recovery history contains only calls not copied into the active run tree.
    prior_calls=read(case/'prior-costs.json',{}).get('calls',[])
    calls=prior_calls+calls
    for call in calls:classify_rejected_call(call)
    tokens=token_summary(calls)
    write_json(case/'costs.json', {'calls': calls, 'pricing': PRICES, **tokens})
    image_id = manifest.get('id')
    review = run/'review'/str(image_id)
    result = read(review/'result.json', {})
    raw_model = next(iter(sorted(run.glob('native-*/gpt55/response.txt'))), None)
    raw_svg = None
    if raw_model:
        from figfox_plus.native.document import extract_svg
        try:
            source = extract_svg(raw_model.read_text(encoding='utf-8'))
        except ValueError:
            source = None
        if source:
            raw_svg = case/'raw-model.svg'
            raw_svg.write_text(source, encoding='utf-8')
    error = None
    if manifest.get('exit_code') and (case/'console.log').is_file():
        lines = (case/'console.log').read_text(encoding='utf-8').strip().splitlines()
        error = lines[-1] if lines else None
    # Prefer the last committed follow-up checkpoint, including on partial failure.
    follow_dir=Path((result.get('followup') or {}).get('execution_directory') or review.with_name(review.name+'-followup')/'execution')
    follow = read(follow_dir/'state.json', {})
    preflight=read(follow_dir.parent/'program-preflight.json',{})
    if result.get('followup') and preflight:
        result['followup']['rejected_programs']=preflight.get('rejected',[])+preflight.get('shape_rejected',[])
    from figfox_plus.native.review_problem_first_v13.followup import reconcile_followup
    result=reconcile_followup(result,follow)
    from figfox_plus.native.artifacts import publish_latest
    artifacts = publish_latest(run, str(image_id), error=(
        {'type':'PipelineFailure','message':error or 'pipeline returned a nonzero exit code'}
        if manifest.get('exit_code') else None))
    final = artifacts['outputs'] if artifacts['artifact_status']=='available' else None
    selected = artifacts['output_stage']
    baseline = next(iter(sorted(run.glob('native-*/stage-0/scene.svg'))), None)
    exports = {}
    if final:
        for suffix in ('svg', 'png'):
            source = Path(final[suffix])
            if source.is_file():
                target = case/('final.'+suffix)
                shutil.copyfile(source, target)
                exports[suffix] = str(target.resolve())
    if baseline:
        for source, name in ((baseline, 'baseline.svg'), (baseline.with_name('preview.png'), 'baseline.png')):
            if source.is_file(): shutil.copyfile(source, case/name)
    known = sum(c['cost']['estimated_usd'] for c in calls if c['cost'])
    receipts = result.get('rcd', []) + (result.get('followup') or {}).get('rcd', [])
    effective_receipts = result.get('effective_rcd', result.get('rcd', [])) or []
    main_rejected = len(result.get('rejected_programs', []))
    followup_rejected = len((result.get('followup') or {}).get('rejected_programs', []))
    summary = {**manifest, **tokens, 'elapsed_time_complete':manifest.get('elapsed_time_complete',True), 'status': result.get('status', 'failed' if manifest.get('exit_code') else 'running'),
               'output_stage': selected if final else 'none', 'outputs': exports,
               'artifact_status': 'available' if set(exports)=={'svg','png'} else 'unavailable',
               'review_complete': bool(selected!='baseline_only' and result.get('status')=='visual_review_pending'
                                       and manifest.get('exit_code')==0 and (result.get('followup') or {}).get('status')!='failed'),
               'raw_model_svg': str(raw_svg.resolve()) if raw_svg else None, 'error': error,
               'model_requests': len(calls), 'estimated_usd': round(known, 6),
               'cost_complete': all(c['cost'] is not None for c in calls),
               'unknown_cost_requests': sum(c['cost'] is None for c in calls),
               'changed_programs': sum(r.get('status') == 'changed_unverified' for r in receipts),
               'failed_or_blocked_programs': sum(r.get('status') in ('failed','blocked') for r in receipts),
               'effective_failed_or_blocked_programs': sum(r.get('status') in ('failed','blocked') for r in effective_receipts),
               'preflight_rejected_programs': main_rejected + followup_rejected,
               'main_preflight_rejected_programs': main_rejected,
               'followup_preflight_rejected_programs': followup_rejected,
               'followup': result.get('followup'), 'visual_passed': False}
    summary['historical_failed_or_blocked_programs'] = summary['failed_or_blocked_programs']
    if manifest.get('api_cost_target_usd') is not None:
        target = manifest['api_cost_target_usd']
        summary['cost_target_status'] = ('exceeded' if known > target else 'within_target'
            if summary['cost_complete'] and manifest.get('exit_code') is not None else 'unknown')
    summary['review_status']=summary['status']
    summary['execution_status']=('running' if manifest.get('exit_code') is None else
        'failed' if manifest.get('exit_code') or set(exports)!={'svg','png'} else
        'completed' if selected!='baseline_only' and result.get('status')=='visual_review_pending' and (result.get('followup') or {}).get('status')!='failed' else
        'completed_with_issues' if manifest.get('exit_code')==0 else 'running')
    summary['status']=summary['execution_status']
    blocked=read(case/'blocked-model-stage.json')
    if blocked:
        summary.update(status='blocked',execution_status='blocked',model_stage_blocked=blocked)
    if manifest.get('recovery_source'):
        previous=manifest.get('previous_estimated_usd',0)
        summary['additional_estimated_usd']=round(max(0,summary['estimated_usd']-previous),6)
    write_json(case/'summary.json', summary)
    return summary


def collect_batch(out):
    rows = [collect_case(p.parent) for p in sorted(out.glob('*/case.json'))]
    write_json(out/'summary.json', {'cases': rows, 'known_estimated_usd': sum(r['estimated_usd'] for r in rows),
                                  'cost_complete': all(r['cost_complete'] for r in rows), 'pricing': PRICES})
    fields = ['id','original','status','execution_status','review_status','artifact_status','review_complete','exit_code','elapsed_seconds','model_requests','input_tokens','cached_input_tokens','output_tokens','reasoning_tokens','total_tokens','token_usage_complete','estimated_usd','cost_complete','additional_estimated_usd','output_stage',
               'api_budget_usd','api_cost_target_usd','cost_target_status',
               'changed_programs','failed_or_blocked_programs','historical_failed_or_blocked_programs',
               'effective_failed_or_blocked_programs','preflight_rejected_programs',
               'main_preflight_rejected_programs','followup_preflight_rejected_programs']
    with (out/'summary.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader(); writer.writerows(rows)
    cards = []
    for p in sorted(out.glob('*/summary.json')):
        row = read(p)
        folder = p.parent.name
        target_note = ('<p>'+html.escape('费用目标 $'+str(row['api_cost_target_usd'])+'：'+
            {'exceeded':'已超过目标，生成额度保持原配置','within_target':'在目标内','unknown':'用量尚不完整'}[row['cost_target_status']])+'</p>'
            if row.get('api_cost_target_usd') is not None else '')
        cards.append('<section><h2>'+html.escape(Path(row['original']).name)+'</h2><p>'+html.escape(
            f"{row['status']} | {row.get('elapsed_seconds', 0):.1f}s | estimated ${row['estimated_usd']:.4f} | stage: {row['output_stage']}")+'</p>'+
            target_note+
            (f'<a href="{folder}/final.svg">SVG</a> · <a href="{folder}/final.png">PNG</a><br><img src="{folder}/final.png">' if row['outputs'] else f'<p>Only the GPT baseline is available: <a href="{folder}/baseline.svg">baseline SVG</a> · <a href="{folder}/baseline.png">baseline PNG</a>. Review has not finished.</p>' if row['output_stage']=='baseline_only' else '<p>No valid rendered output.</p>')+
            (f'<p><a href="{folder}/raw-model.svg">Raw model SVG (may be invalid; not repaired)</a></p>' if row.get('raw_model_svg') else '')+
            ('<pre>'+html.escape(row['error'])+'</pre>' if row.get('error') else '')+'</section>')
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>FigFox experiments</title><style>body{font:16px system-ui;max-width:1400px;margin:32px auto}img{max-width:100%}section{margin-bottom:48px}</style><h1>FigFox experiments</h1><p>Unmodified pipeline outputs. Execution is not visual acceptance. Costs are estimates from reported usage.</p>'+''.join(cards), encoding='utf-8')
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('images', nargs='*')
    parser.add_argument('--input-dir', type=Path, help='run every PNG in this folder, non-recursively')
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--collect-only', action='store_true', help='refresh reports without any model calls')
    add_cost_arguments(parser)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.collect_only:
        if not out.is_dir(): parser.error('output directory does not exist')
        collect_batch(out); return 0
    images = [Path(p).resolve() for p in args.images]
    if args.input_dir: images += sorted(args.input_dir.resolve().glob('*.png'))
    images = list(dict.fromkeys(images))
    if not images or any(not p.is_file() or p.suffix.lower() != '.png' for p in images):
        parser.error('supply existing PNG files or --input-dir')
    if out.exists(): parser.error('output already exists; choose a new batch directory')
    load_environment()
    # One local preflight per batch, no model inference.
    check = subprocess.run([sys.executable, str(ROOT/'scripts/check-runtime.py'), '--credentials', '--sandbox'])
    if check.returncode: return check.returncode
    out.mkdir(parents=True)
    write_json(out/'pricing.json', PRICES)
    sources = [p for folder in ('src', 'prompts', 'runtime') for p in (ROOT/folder).rglob('*')
               if p.is_file() and p.suffix in ('.py', '.md', '.cjs')]
    write_json(out/'source-manifest.json', {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources})
    failed = False
    for index, image in enumerate(images, 1):
        image_id = f'case-{index:03d}'
        case = out/(image_id+'-'+image.stem)
        case.mkdir()
        shutil.copyfile(image, case/'original.png')
        start = time.time()
        manifest = {'id': image_id, 'original': str(image), 'source_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                    'started_at': datetime.now(timezone.utc).isoformat(), 'exit_code': None}
        command = [sys.executable, '-u', '-m', 'figfox_plus', 'chain', '--image', str(case/'original.png'),
                   '--id', image_id, '--out', str(case/'run'), '--rerun-authorization', uuid4().hex]
        with cost_policy(case, manifest, target_usd=args.target_usd, budget_usd=args.budget_usd) as environment:
            write_json(case/'case.json', manifest)
            print(json.dumps({'event': 'case_started', 'id': image_id, 'file': image.name,
                'api_cost_target_usd': args.target_usd, 'api_budget_usd': args.budget_usd}), flush=True)
            with (case/'console.log').open('w', encoding='utf-8') as log:
                process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding='utf-8', errors='replace', env=environment)
                try:
                    for line in process.stdout:
                        log.write(line); log.flush()
                        # Chain events are concise; tracebacks stay in the case log.
                        if line.startswith('{'): print(line.rstrip(), flush=True)
                    exit_code = process.wait()
                except BaseException:
                    process.terminate(); process.wait()
                    raise
        manifest.update(exit_code=exit_code, elapsed_seconds=round(time.time()-start, 3),
                        finished_at=datetime.now(timezone.utc).isoformat())
        write_json(case/'case.json', manifest)
        rows = collect_batch(out)
        row = next(r for r in rows if r['id'] == image_id)
        failed |= exit_code != 0
        report_cost_warning(row)
        print(json.dumps({'event': 'case_finished', **{k:row[k] for k in ('id','status','exit_code','elapsed_seconds','estimated_usd','cost_complete','output_stage','api_cost_target_usd','cost_target_status')}}), flush=True)
    print(str(out), flush=True)
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
