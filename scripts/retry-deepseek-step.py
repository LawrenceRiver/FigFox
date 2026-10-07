"""Explicitly retry an interrupted repair, reusing immutable GPT/discovery outputs."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from figfox_plus.cost_budget import raise_budget_ceiling
from figfox_plus.providers import load_key
from figfox_plus.native.single_call.transport import _NoRedirect
from figfox_plus.native.review_problem_first_v13 import orchestrator, transport
from figfox_plus.native.review_problem_first_v13.inputs import validate_bundle
from figfox_plus.state import write_json

batch_spec = importlib.util.spec_from_file_location('batch_retry', ROOT/'scripts/batch-experiment.py')
batch = importlib.util.module_from_spec(batch_spec)
batch_spec.loader.exec_module(batch)


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def retry_plan(case):
    """Read-only eligibility check; no request or budget mutation."""
    case = Path(case).resolve()
    manifest = read(case / 'case.json')
    review = case / 'run/review' / manifest['id']
    if (review / 'result.json').exists() or (review / 'phase-2/message.json').exists():
        raise ValueError('repair already returned; this command only retries transport interruptions')
    for name, expected in read(review / 'frozen.json').items():
        if digest(review / name) != expected:
            raise ValueError('frozen input modified: ' + name)
    inputs = validate_bundle(read(review / 'inputs.json'))
    if digest(Path(manifest['original'])) != manifest['source_sha256']:
        raise ValueError('original image changed')
    discovery = read(review / 'phase-1/message.json')
    if orchestrator._plan(discovery, read(review / 'schedule.json'))[0]['programs']:
        raise ValueError('discovery unexpectedly contains programs')
    failed = [p.parent for p in (review / 'model-turns').glob('*/error.json')
              if not (p.parent / 'response.json').exists()]
    if len(failed) != 1 or read(failed[0] / 'stream-state.json')['status'] != 'interrupted':
        raise ValueError('expected one saved interrupted repair stream')
    completed = [p for p in (review / 'model-turns').glob('*/response.json')
                 if transport._message(read(p)) == discovery]
    previous = read(case / 'retry-provenance.json') if (case / 'retry-provenance.json').exists() else {}
    if any(digest(Path(p)) != h for p, h in previous.get('source_hashes', {}).items()):
        raise ValueError('previous source evidence changed')
    if not completed and previous.get('discovery_reused'):
        original_review = Path(previous['source_case']) / 'run/review' / manifest['id']
        completed = [p for p in (original_review / 'model-turns').glob('*/response.json')
                     if transport._message(read(p)) == discovery]
    if len(completed) != 1:
        raise ValueError('discovery must have an unchanged completed provider response')
    body = read(failed[0] / 'request.json')['body']
    if body['thinking'] != {'type': 'enabled'} or body['reasoning_effort'] != 'high':
        raise ValueError('retry requires the standard repair settings')
    protected = [case / 'case.json', case / 'costs.json', review / 'frozen.json',
                 *review.rglob('request.json'), *review.rglob('response.json'),
                 *review.rglob('events.jsonl'), *review.rglob('error.json'),
                 review / 'phase-1/message.json']
    protected.append(Path(manifest['original']))
    for pattern in ('native-*/gpt55/response.txt', 'native-*/gpt55/response.json',
                    'native-*/first-draft.svg', 'native-*/stage-0/scene.svg', 'native-*/stage-0/preview.png'):
        protected.extend((case / 'run').glob(pattern))
    protected.extend(Path(p) for p in previous.get('source_hashes', {}))
    return {'manifest': manifest, 'review': review, 'inputs': inputs, 'body': body,
            'budget': Path(previous.get('budget_file') or case / 'api-budget.json'),
            'failed': failed[0], 'source_hashes': {str(p): digest(p) for p in protected}}


def retry(case, out, *, authorization, budget_usd=None, target_usd=batch.DEFAULT_COST_TARGET_USD, direct=False):
    case, out = Path(case).resolve(), Path(out).resolve()
    plan = retry_plan(case)
    target_usd = batch.positive_usd(target_usd)
    if budget_usd is not None:
        budget_usd = batch.positive_usd(budget_usd)
        if not plan['budget'].is_file():
            raise ValueError('hard retry requires the existing figure ledger; its prior costs cannot be reset')
    out.mkdir(parents=True, exist_ok=False)
    review = out / 'run/review' / plan['manifest']['id']
    review.mkdir(parents=True)
    # Paths in the frozen bundle continue to refer to checked immutable assets.
    for source in plan['review'].glob('*.json'):
        if not source.name.startswith('.'):
            shutil.copyfile(source, review / source.name)
    (review / 'phase-1').mkdir()
    shutil.copyfile(plan['review'] / 'phase-1/message.json', review / 'phase-1/message.json')
    image = plan['inputs']['images'][plan['manifest']['id']]
    baseline = out / 'run/native-reused/stage-0'
    baseline.mkdir(parents=True)
    shutil.copyfile(image['current_svg']['path'], baseline / 'scene.svg')
    shutil.copyfile(image['current_png']['path'], baseline / 'preview.png')
    shutil.copyfile(case / 'costs.json', out / 'prior-costs.json')
    budget = plan['budget']
    if budget.is_file(): shutil.copyfile(budget, out / 'previous-api-budget.json')
    provenance = {'source_case': str(case), 'failed_request': str(plan['failed']),
                  'authorization': authorization, 'source_hashes': plan['source_hashes'],
                  'gpt_reused': True, 'discovery_reused': True, 'automatic_retry': False,
                  'primary_repair_requests_allowed': 1, 'budget_file': str(budget),
                  'api_cost_target_usd': target_usd, 'api_budget_usd': budget_usd,
                  'api_cost_mode': 'hard_limit' if budget_usd is not None else 'target',
                  'http_route': 'direct' if direct else 'configured_proxy'}
    write_json(out / 'retry-provenance.json', provenance)
    # Raising the ceiling is separate from cost_guard; old reservations are retained.
    if budget_usd is not None:
        old_limit = read(budget)['limit_usd']
        if budget_usd > old_limit:
            raise_budget_ceiling(budget, budget_usd, authorization=authorization)
        elif budget_usd != old_limit:
            raise ValueError('retry budget cannot lower or reset the existing figure ledger')
    env = {'FLOW_DS_MODEL': plan['body']['model']}
    previous_env = {key: os.environ.get(key) for key in env}
    os.environ.update(env)
    manifest = {**plan['manifest'], 'started_at': datetime.now(timezone.utc).isoformat(),
                'exit_code': None, 'recovery_source': str(case),
                'previous_estimated_usd': read(case / 'summary.json')['estimated_usd'],
                'previous_elapsed_seconds': plan['manifest']['elapsed_seconds'],
                'elapsed_seconds': 0, 'finished_at': None}
    started = time.monotonic()

    def direct_http(request, timeout):
        # send_http injection normally serves offline tests; real direct calls
        # must explicitly add credentials and retain redirect/TLS protections.
        request.add_header('Authorization', 'Bearer ' + load_key('DEEPSEEK_API_KEY'))
        return urllib.request.build_opener(_NoRedirect(), urllib.request.ProxyHandler({})).open(request, timeout=timeout)

    def sender(messages, tools, task, **unused):
        if Path(task).resolve() == review:
            candidate, _ = transport.budget_request({**plan['body'], 'messages': messages, 'tools': tools})
            if candidate != plan['body']:
                raise ValueError('rebuilt repair differs from the failed request; no request sent')
            print(json.dumps({'event': 'repair_retry_started', 'same_request_body': True}), flush=True)
        return transport.send(messages, tools, task, request_limit=1,
                              **({'send_http': direct_http} if direct else {}))

    try:
        with batch.cost_policy(out, manifest, target_usd=target_usd, budget_usd=budget_usd, budget_file=budget), (out / 'console.log').open('w', encoding='utf-8', buffering=1) as log, redirect_stdout(log), redirect_stderr(log):
            write_json(out / 'case.json', manifest)
            try:
                result = orchestrator.run(review, sender=sender, request_limit=2)
                manifest['exit_code'] = 0
                print(json.dumps({'event': 'review_done', 'status': result['status']}), flush=True)
            except Exception:
                manifest['exit_code'] = 1
                traceback.print_exc()
    finally:
        for key, value in previous_env.items():
            if value is None: os.environ.pop(key, None)
            else: os.environ[key] = value
        manifest.update(elapsed_seconds=round(time.monotonic() - started, 3),
                        finished_at=datetime.now(timezone.utc).isoformat())
        write_json(out / 'case.json', manifest)
        provenance['source_evidence_unchanged'] = all(digest(Path(p)) == h for p, h in plan['source_hashes'].items())
        write_json(out / 'retry-provenance.json', provenance)
        if budget.is_file(): shutil.copyfile(budget, out / 'api-budget.json')
    result = batch.collect_case(out)
    batch.report_cost_warning(result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    batch.add_cost_arguments(parser)
    parser.add_argument('--authorization', required=True)
    parser.add_argument('--direct', action='store_true', help='Bypass the local HTTP proxy for this retry only')
    args = parser.parse_args()
    result = retry(args.case, args.out, budget_usd=args.budget_usd, target_usd=args.target_usd,
                   authorization=args.authorization, direct=args.direct)
    print(json.dumps({key: result.get(key) for key in ('status', 'output_stage', 'review_complete',
          'model_requests', 'estimated_usd', 'cost_complete', 'elapsed_seconds')}), flush=True)
    return result['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
