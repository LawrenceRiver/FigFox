"""Shared token pricing and read-only cost snapshots for live monitoring."""
from datetime import datetime, timezone
import json
from pathlib import Path

# Published Chinese holiday periods; unknown years retain conservative weekday estimates.
CHINESE_PUBLIC_HOLIDAYS = {
    2026: (('01-01', '01-03'), ('02-15', '02-23'), ('04-04', '04-06'),
           ('05-01', '05-05'), ('06-19', '06-21'), ('09-25', '09-27'), ('10-01', '10-07')),
}

PRICES = {
    'checked_on': '2026-10-04', 'currency': 'USD', 'unit': 'per million tokens',
    'gpt-5.5': {'input': 5, 'cached': 0.5, 'output': 30},
    'deepseek-flash-peak': {'input': 0.3, 'cached': 0.006, 'output': 1.2},
    'deepseek-flash-offpeak': {'input': 0.15, 'cached': 0.003, 'output': 0.6},
    'sources': ['https://developers.openai.com/api/docs/models/gpt-5.5',
                'https://api-docs.deepseek.com/quick_start/pricing/'],
    'holiday_calendar': {'years': list(CHINESE_PUBLIC_HOLIDAYS), 'checked_on': '2026-10-06',
        'source': 'https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html'},
    'note': 'Token-based estimate, not a provider invoice. Reasoning is already included in output tokens. Local compute and Codex usage excluded.'}

def estimate_usage(model, usage, timestamp):
    if not isinstance(usage, dict) or not usage: return None
    input_tokens = usage.get('input_tokens', usage.get('prompt_tokens'))
    output_tokens = usage.get('output_tokens', usage.get('completion_tokens'))
    cached = usage.get('prompt_cache_hit_tokens', (usage.get('input_tokens_details') or {}).get('cached_tokens',
                       (usage.get('prompt_tokens_details') or {}).get('cached_tokens', 0)))
    if not all(type(n) is int and n >= 0 for n in (input_tokens, output_tokens, cached)) or cached > input_tokens:
        return None
    if model.startswith('gpt-5.5'):
        rates = dict(PRICES['gpt-5.5'])
        if input_tokens > 272000:
            rates = {k: v*(1.5 if k == 'output' else 2) for k,v in rates.items()}
        period = 'standard'
    elif model.startswith('deepseek-flash') or model.startswith('deepseek-v4-flash'):
        dt = datetime.fromtimestamp(timestamp, timezone.utc)
        # All UTC peak hours fall on the same calendar date in China (UTC+8).
        holiday = any(start <= dt.strftime('%m-%d') <= end
                      for start, end in CHINESE_PUBLIC_HOLIDAYS.get(dt.year, ()))
        peak = not holiday and dt.weekday() < 5 and (1 <= dt.hour < 4 or 6 <= dt.hour < 10)
        period = 'peak' if peak else 'offpeak'
        rates = PRICES['deepseek-flash-'+period]
    else:
        return None
    cost = ((input_tokens-cached)*rates['input']+cached*rates['cached']+output_tokens*rates['output'])/1_000_000
    return {'input_tokens': input_tokens, 'cached_input_tokens': cached, 'output_tokens': output_tokens,
            'estimated_usd': cost, 'price_period': period, 'rates': rates}


def classify_rejected_call(call):
    """Distinguish explicit pre-generation DS rejection from lost usage.

    The zero is an estimation policy based on a rejection, not provider usage
    or an invoice. Keep the raw error and absent usage untouched.
    """
    if call.get('usage') or not call.get('model','').startswith(('deepseek-flash','deepseek-v4-flash')):
        return
    error=call.get('error') or {}
    try:detail=json.loads(error.get('response_body','')).get('error',{})
    except (ValueError,TypeError):return
    message=str(detail.get('message','')).lower()
    rejected=(error.get('status')==402 and 'insufficient balance' in message) or (
        error.get('status')==400 and 'maximum context length' in message and 'please reduce' in message)
    if error.get('type')=='HTTPError' and rejected:
        call['usage_status']='rejected_before_generation'
        call['cost']={'estimated_usd':0,'basis':'explicit pre-generation HTTP rejection; estimated zero, not reported usage',
                      'documentation':'https://api-docs.deepseek.com/quick_start/error_codes/'}


def read_record(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return default


def cost_snapshot(root, *, cache=None, worker_running=True):
    """No publishing, ledger mutations, API calls or rescanning large live SSE logs."""
    root = Path(root)
    cache = cache if cache is not None else {}
    calls = list((read_record(root.parent / 'prior-costs.json', {}) or {}).get('calls', []))
    for path in sorted(root.rglob('request.json')):
        if path.parent.name != 'gpt55' and path.parent.parent.name != 'model-turns':
            continue
        folder = path.parent
        if (folder / 'cost-blocked.json').exists() and not (folder / 'progress.json').exists():
            continue
        progress = read_record(folder / 'progress.json', {}) or {}
        signature = (worker_running,) + tuple((p.stat().st_mtime_ns, p.stat().st_size) if p.is_file() else None
            for p in (path, folder/'progress.json', folder/'usage.json', folder/'response.json',
                      folder/'response.partial.json', folder/'error.json'))
        key = str(path.resolve())
        if key in cache and cache[key][0] == signature:
            calls.append(cache[key][1]); continue
        # New runs expose model/usage in a small record; their request body can
        # contain hundreds of base64 crops and must not be reparsed every poll.
        req = {} if progress.get('model') else read_record(path, {}) or {}
        active = worker_running and progress.get('status') in ('sending', 'receiving', 'interrupting')
        usage = progress.get('usage') or read_record(folder / 'usage.json', {})
        # Reading a full transcript once it ends is fine; avoid it on every delta.
        response = {}
        if not usage and not active:
            response = read_record(folder / 'response.json', {}) or read_record(folder / 'response.partial.json', {}) or {}
            usage = response.get('usage')
        model = progress.get('model') or req.get('model') or req.get('body', {}).get('model', '')
        stamp = response.get('created_at', response.get('created', path.stat().st_mtime))
        call = {'request': key, 'model': model, 'usage': usage, 'active': active,
                'cost': estimate_usage(model, usage, stamp), 'error': read_record(folder/'error.json')}
        classify_rejected_call(call)
        cache[key] = (signature, call)
        calls.append(call)
    pending = sum(bool(c.get('active')) for c in calls)
    unknown = sum(c.get('cost') is None and not c.get('active') for c in calls)
    return {'estimated_usd': round(sum((c.get('cost') or {}).get('estimated_usd', 0) for c in calls), 9),
            'cost_complete': pending == 0 and unknown == 0, 'active_requests': pending,
            'unknown_cost_requests': unknown, 'model_requests': len(calls), 'calls': calls,
            'pricing_checked_on': PRICES['checked_on'], 'not_an_invoice': True}
