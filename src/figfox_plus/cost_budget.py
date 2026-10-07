"""Opt-in, shared per-figure API budget, using conservative published rates."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
import json
import math
import os
from pathlib import Path

from . import file_lock
from .state import write_json

MILLION = Decimal(1_000_000)
PRICING_SOURCES = [
    'https://developers.openai.com/api/docs/models/gpt-5.5',
    'https://api-docs.deepseek.com/quick_start/pricing/',
]


class CostBudgetError(ValueError):
    pass


def _utcnow():
    return datetime.now(timezone.utc)


def input_budget_for_full_output(model, output_tokens):
    """Peak-rate input allowance; admission still locks and checks the ledger."""
    filename = os.environ.get('FIGFOX_COST_BUDGET_FILE')
    ceiling = os.environ.get('FIGFOX_COST_LIMIT_USD')
    if not filename and not ceiling:
        return None
    if not filename or not ceiling:
        raise CostBudgetError('both FIGFOX_COST_BUDGET_FILE and FIGFOX_COST_LIMIT_USD are required')
    limit = Decimal(ceiling)
    if not limit.is_finite() or limit <= 0:
        raise CostBudgetError('cost limit must be positive and finite')
    with _ledger(Path(filename)) as record:
        if record and Decimal(str(record['limit_usd'])) != limit:
            raise CostBudgetError('existing figure budget cannot change')
        spent = sum((Decimal(str(c['accounted_usd'])) for c in (record or {}).get('calls', [])), Decimal(0))
    inp_rate, _, out_rate = rates(model, 0)
    available = (limit - spent) * MILLION - Decimal(output_tokens) * out_rate
    return max(0, int((available / inp_rate).to_integral_value(rounding=ROUND_FLOOR)))


def gpt_input_upper_bound(prompt, images):
    from PIL import Image
    # Text tokens cannot exceed UTF-8 bytes. Reserve framing and image headers;
    # original GPT-5.5 images use at most 10,000 patches with multiplier 1.2.
    total = len(prompt.encode('utf-8')) + 4096
    for path in images:
        with Image.open(path) as image:
            patches = min(10_000, math.ceil(image.width / 32) * math.ceil(image.height / 32))
        total += math.ceil(patches * 1.2) + 129
    return total


def rates(model, input_tokens):
    if model == 'gpt-5.5' or model.startswith('gpt-5.5-'):
        return (Decimal('10'), Decimal('1'), Decimal('45')) if input_tokens > 272000 else (
            Decimal('5'), Decimal('0.5'), Decimal('30'))
    if model in ('deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp'):
        # Peak prices remain safe when a call crosses a billing period.
        return Decimal('0.3'), Decimal('0.006'), Decimal('1.2')
    raise CostBudgetError('no verified pricing for budgeted model: ' + model)


def _usage(folder):
    candidates = []
    for name in ('response.json', 'usage.json'):
        path = folder / name
        if path.is_file():
            raw = json.loads(path.read_text(encoding='utf-8'))
            candidates.append(raw.get('usage', raw))
    events = folder / 'events.jsonl'
    if events.is_file():
        for line in events.read_text(encoding='utf-8').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            candidates.append(event.get('response', {}).get('usage') or event.get('usage'))
    for usage in reversed(candidates):
        if not isinstance(usage, dict):
            continue
        inp = usage.get('input_tokens', usage.get('prompt_tokens'))
        out = usage.get('output_tokens', usage.get('completion_tokens'))
        cached = usage.get('prompt_cache_hit_tokens', (usage.get('input_tokens_details') or {}).get('cached_tokens', 0))
        if all(type(v) is int and v >= 0 for v in (inp, out, cached)) and cached <= inp:
            return {'input_tokens': inp, 'output_tokens': out, 'cached_tokens': cached}
    return None


@contextmanager
def _ledger(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + '.lock').open('a+', encoding='utf-8') as handle:
        file_lock.flock(handle, file_lock.LOCK_EX)
        try:
            yield json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None
        finally:
            file_lock.flock(handle, file_lock.LOCK_UN)


def raise_budget_ceiling(path, new_limit, *, authorization):
    """Apply an explicit user-approved increase without releasing any old costs."""
    limit = Decimal(str(new_limit))
    if not limit.is_finite() or limit <= 0 or not isinstance(authorization, str) or not authorization.strip():
        raise CostBudgetError('a finite positive limit and explicit authorization are required')
    path = Path(path).resolve()
    with _ledger(path) as record:
        if not record or limit <= Decimal(str(record['limit_usd'])):
            raise CostBudgetError('new ceiling must exceed the existing figure budget')
        if any(call.get('bound_violation') or call.get('status') == 'reserved' for call in record['calls']):
            raise CostBudgetError('cannot change a budget with an active or out-of-bound request')
        record.setdefault('authorizations', []).append({
            'previous_limit_usd': record['limit_usd'], 'new_limit_usd': float(limit),
            'authorization': authorization, 'at': datetime.now(timezone.utc).isoformat()})
        record['limit_usd'] = float(limit)
        write_json(path, record)


def reprice_finished_weekend_calls(path):
    """Use verified weekend rates only after the entire call has ended.

    An unknown usage still reserves its full input/output upper bound. Pending
    calls retain peak prices, since their eventual billing period is unknown.
    """
    path = Path(path).resolve()
    with _ledger(path) as record:
        if not record:
            raise CostBudgetError('existing budget required')
        for call in record['calls']:
            if not call['model'].startswith('deepseek-') or call.get('rate_adjustment'):
                continue
            if call['status'] not in ('usage_received', 'usage_unknown_reservation_retained'):
                continue
            folder = Path(call['folder'])
            terminal = folder / ('response.json' if (folder / 'response.json').exists() else 'error.json')
            attempt = folder / 'attempt.json'
            if not terminal.is_file() or not attempt.is_file():
                continue
            start = datetime.fromtimestamp(attempt.stat().st_mtime, timezone.utc)
            end = datetime.fromtimestamp(terminal.stat().st_mtime, timezone.utc)
            # Same UTC weekend day proves that no weekday peak was crossed.
            if start.date() != end.date() or start.weekday() < 5 or end < start:
                continue
            call['rate_adjustment'] = {'period': 'offpeak_weekend', 'factor': 0.5,
                'started_at': start.isoformat(), 'finished_at': end.isoformat(),
                'previous_accounted_usd': call['accounted_usd'],
                'previous_reserved_usd': call['reserved_usd'], 'source': PRICING_SOURCES[1]}
            for field in ('reserved_usd', 'accounted_usd'):
                call[field] = float(Decimal(str(call[field])) / 2)
        record['accounted_usd'] = float(sum((Decimal(str(row['accounted_usd'])) for row in record['calls']), Decimal(0)))
        record['note'] = ('Finished calls wholly within a verified weekend use off-peak rates; '
                          'pending calls use peak rates. Missing usage retains the full token-bound '
                          'reservation at the applicable rate. Not a provider invoice.')
        write_json(path, record)


@contextmanager
def cost_guard(model, request_id, folder, input_bound, requested_output):
    """Reserve before the HTTP attempt; missing usage keeps the full reservation.

    The caller marks ticket['sent'] immediately before attempting HTTP. No budget
    means no changed request limits or ledger. A crash leaves its reservation intact.
    A hard ceiling can reject a whole request, never shorten its planned reply.
    """
    filename = os.environ.get('FIGFOX_COST_BUDGET_FILE')
    ceiling = os.environ.get('FIGFOX_COST_LIMIT_USD')
    if not filename and not ceiling:
        yield None
        return
    if not filename or not ceiling:
        raise CostBudgetError('both FIGFOX_COST_BUDGET_FILE and FIGFOX_COST_LIMIT_USD are required')
    limit = Decimal(ceiling)
    if not limit.is_finite() or limit <= 0:
        raise CostBudgetError('cost limit must be positive and finite')
    if type(input_bound) is not int or input_bound < 0:
        raise CostBudgetError('missing conservative input bound')
    if type(requested_output) is not int or requested_output <= 0:
        raise CostBudgetError('planned output tokens must be a positive integer')
    path = Path(filename).resolve()
    inp_rate, _, out_rate = rates(model, input_bound)
    with _ledger(path) as record:
        record = record or {'limit_usd': float(limit), 'currency': 'USD', 'checked_on': '2026-10-03',
                            'pricing_sources': PRICING_SOURCES, 'calls': [],
                            'note': 'Conservative token cost; DeepSeek uses peak rates. Missing usage retains reservation. Not a provider invoice.'}
        if Decimal(str(record['limit_usd'])) != limit:
            raise CostBudgetError('existing figure budget cannot change')
        if any(call.get('bound_violation') for call in record['calls']):
            raise CostBudgetError('previous request exceeded its cost bound; no further requests allowed')
        if any(call['request_id'] == request_id for call in record['calls']):
            raise CostBudgetError('duplicate cost reservation')
        spent = sum((Decimal(str(call['accounted_usd'])) for call in record['calls']), Decimal(0))
        input_cost = Decimal(input_bound) * inp_rate / MILLION
        affordable = int(((limit - spent - input_cost) * MILLION / out_rate).to_integral_value(rounding=ROUND_FLOOR))
        output = requested_output
        required = (Decimal(input_bound) * inp_rate + Decimal(output) * out_rate) / MILLION
        if affordable < output:
            write_json(Path(folder) / 'cost-blocked.json', {'limit_usd': float(limit), 'accounted_usd': float(spent),
                'input_token_upper_bound': input_bound, 'planned_output_tokens': output,
                'required_reservation_usd': float(required), 'remaining_usd': float(limit-spent),
                'affordable_output_tokens': max(0, affordable), 'output_limit_changed': False,
                'model_request_sent': False, 'basis': 'conservative full-request reservation, not actual usage'})
            raise CostBudgetError('figure cost budget cannot fund the full planned request; output limit unchanged; no HTTP request sent')
        reserved = required
        call = {'request_id': request_id, 'model': model, 'folder': str(Path(folder).resolve()),
                'input_token_upper_bound': input_bound, 'max_output_tokens': output,
                'reserved_usd': float(reserved), 'accounted_usd': float(reserved), 'status': 'reserved',
                'reserved_at': _utcnow().isoformat()}
        record['calls'].append(call)
        write_json(path, record)
    ticket = {'max_output_tokens': output, 'sent': False}
    try:
        yield ticket
    finally:
        usage = _usage(Path(folder)) if ticket['sent'] else None
        with _ledger(path) as record:
            call = next(row for row in record['calls'] if row['request_id'] == request_id)
            if not ticket['sent']:
                call.update(status='cancelled_before_http', accounted_usd=0)
            elif usage:
                inp_rate, cached_rate, out_rate = rates(model, usage['input_tokens'])
                actual = ((usage['input_tokens'] - usage['cached_tokens']) * inp_rate +
                          usage['cached_tokens'] * cached_rate + usage['output_tokens'] * out_rate) / MILLION
                call.update(status='usage_received', usage=usage, accounted_usd=float(actual),
                    bound_violation=usage['input_tokens'] > input_bound or usage['output_tokens'] > output or actual > reserved)
                ended = _utcnow()
                started = datetime.fromisoformat(call['reserved_at'])
                # Only a fully ended interval proves the weekend discount. Active
                # and unknown-usage calls keep their entire peak-rate reservation.
                if model.startswith('deepseek-') and started.date() == ended.date() and started.weekday() >= 5 and ended >= started:
                    call['rate_adjustment'] = {'period': 'offpeak_weekend', 'factor': 0.5,
                        'started_at': started.isoformat(), 'finished_at': ended.isoformat(),
                        'previous_accounted_usd': float(actual), 'previous_reserved_usd': float(reserved),
                        'source': PRICING_SOURCES[1]}
                    call['accounted_usd'] = float(actual / 2)
                    call['reserved_usd'] = float(reserved / 2)
            else:
                call['status'] = 'usage_unknown_reservation_retained'
            record['accounted_usd'] = float(sum((Decimal(str(row['accounted_usd'])) for row in record['calls']), Decimal(0)))
            record['cost_complete'] = all(row['status'] in ('usage_received', 'cancelled_before_http') for row in record['calls'])
            write_json(path, record)
