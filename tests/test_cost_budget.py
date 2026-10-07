import json

import pytest

from figfox_plus.cost_budget import CostBudgetError, cost_guard, gpt_input_upper_bound, raise_budget_ceiling, reprice_finished_weekend_calls
from figfox_plus.native.review_problem_first_v13.transport import send
from figfox_plus.state import write_json


def configure(monkeypatch, tmp_path, limit='1'):
    from datetime import datetime, timezone
    monkeypatch.setattr('figfox_plus.cost_budget._utcnow', lambda: datetime(2026, 10, 2, 2, tzinfo=timezone.utc))
    ledger = tmp_path / 'api-budget.json'
    monkeypatch.setenv('FIGFOX_COST_LIMIT_USD', limit)
    monkeypatch.setenv('FIGFOX_COST_BUDGET_FILE', str(ledger))
    monkeypatch.setenv('FIGFOX_GPT_MAX_OUTPUT_TOKENS','25000')
    return ledger


def test_completed_weekend_usage_settles_discount_but_pending_and_unknown_keep_peak(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from figfox_plus import cost_budget
    ledger = configure(monkeypatch, tmp_path)
    monkeypatch.setattr(cost_budget, '_utcnow', lambda: datetime(2026, 10, 3, 11, tzinfo=timezone.utc))
    folder = tmp_path / 'weekend'
    with cost_guard('deepseek-flash', 'weekend', folder, 10000, 131072) as ticket:
        assert json.loads(ledger.read_text())['calls'][0]['accounted_usd'] == pytest.approx(0.1602864)
        ticket['sent'] = True
        write_json(folder / 'usage.json', {'prompt_tokens': 10000, 'completion_tokens': 50000})
    record = json.loads(ledger.read_text())
    assert record['accounted_usd'] == pytest.approx(0.0315)
    assert record['calls'][0]['rate_adjustment']['previous_accounted_usd'] == pytest.approx(0.063)
    with cost_guard('deepseek-flash', 'unknown', tmp_path / 'unknown', 10000, 131072) as ticket:
        ticket['sent'] = True
    last = json.loads(ledger.read_text())['calls'][-1]
    assert last['accounted_usd'] == pytest.approx(0.1602864)
    assert 'rate_adjustment' not in last


def test_cross_day_usage_keeps_peak_reservation_price(monkeypatch, tmp_path):
    from datetime import datetime, timezone
    from figfox_plus import cost_budget
    ledger = configure(monkeypatch, tmp_path)
    moments = iter([datetime(2026, 10, 4, 23, 59, tzinfo=timezone.utc), datetime(2026, 10, 5, 0, 1, tzinfo=timezone.utc)])
    monkeypatch.setattr(cost_budget, '_utcnow', lambda: next(moments))
    folder = tmp_path / 'crossing'
    with cost_guard('deepseek-flash', 'crossing', folder, 10000, 131072) as ticket:
        ticket['sent'] = True
        write_json(folder / 'usage.json', {'prompt_tokens': 10000, 'completion_tokens': 50000})
    assert json.loads(ledger.read_text())['accounted_usd'] == pytest.approx(0.063)


def test_deepseek_underfunding_cannot_shrink_reply_and_consume_http(monkeypatch, tmp_path):
    ledger = configure(monkeypatch, tmp_path, '0.05')
    with pytest.raises(CostBudgetError, match='full planned reply'):
        send([{'role': 'user', 'content': 'inspect'}], [], tmp_path / 'review',
             send_http=lambda *a, **k: pytest.fail('must not pay for a reply that was silently shortened'))
    assert not ledger.exists()
    assert not list((tmp_path / 'review').rglob('attempt.json'))


def test_completed_cached_reply_does_not_require_or_consume_more_budget(monkeypatch, tmp_path):
    ledger = configure(monkeypatch, tmp_path, '0.85')
    attempts = []
    class Response:
        headers = {'Content-Type': 'application/json'}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps({'choices': [{'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': '{}'}}],
                                          'usage': {'prompt_tokens': 1000, 'completion_tokens': 1000}}).encode()
    def http(request, timeout):
        attempts.append(request.data)
        return Response()
    message = [{'role': 'user', 'content': 'same input'}]
    first = send(message, [], tmp_path / 'review', send_http=http, request_limit=1)
    with cost_guard('gpt-5.5', 'other', tmp_path / 'other', 0, 25000) as ticket:
        ticket['sent'] = True
        write_json(tmp_path / 'other/usage.json', {'input_tokens': 0, 'output_tokens': 25000})
    assert send(message, [], tmp_path / 'review', send_http=http, request_limit=1) == first
    assert len(attempts) == 1 and len(json.loads(ledger.read_text())['calls']) == 2


@pytest.mark.parametrize('hard_limit', [None, '5'])
def test_deepseek_preserves_upstream_generation_capacity_and_visual_input(monkeypatch, tmp_path, hard_limit):
    from figfox_plus.native.review_problem_first_v13 import transport
    from PIL import Image
    import base64
    if hard_limit is None:
        monkeypatch.delenv('FIGFOX_COST_LIMIT_USD', raising=False)
        monkeypatch.delenv('FIGFOX_COST_BUDGET_FILE', raising=False)
    else:
        configure(monkeypatch, tmp_path, hard_limit)
    monkeypatch.delenv('FLOW_DS_MODEL', raising=False)
    monkeypatch.setenv('FIGFOX_COST_TARGET_USD', '1')
    monkeypatch.setattr(transport, 'load_key', lambda _: 'test-only')
    image = tmp_path/'original.png'; Image.new('RGB', (2,2), 'white').save(image)
    messages = [{'role':'user', 'content':[
        {'type':'text', 'text':'Inspect the original image.'},
        {'type':'image_url', 'image_url':{'url':'data:image/png;base64,' + base64.b64encode(image.read_bytes()).decode(), 'detail':'original'}}]}]
    bodies = []
    class Response:
        headers = {'Content-Type':'application/json'}
        def __enter__(self):return self
        def __exit__(self, *args):return False
        def read(self):return json.dumps({'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'{}'}}],
            'usage':{'prompt_tokens':1000,'completion_tokens':1000}}).encode()
    def http(request, timeout):
        bodies.append(json.loads(request.data));return Response()
    send(messages, [], tmp_path/'review', send_http=http, request_limit=1)
    assert len(bodies) == 1
    assert bodies[0]['max_tokens'] == 393216
    assert bodies[0]['model'] == 'deepseek-flash' and bodies[0]['reasoning_effort'] == 'high'
    assert bodies[0]['thinking'] == {'type':'enabled'} and bodies[0]['messages'] == messages


def test_actual_usage_releases_reservation_across_both_providers(monkeypatch, tmp_path):
    ledger = configure(monkeypatch, tmp_path)
    first = tmp_path / 'first'
    with cost_guard('gpt-5.5', 'first', first, 1000, 25000) as ticket:
        ticket['sent'] = True
        write_json(first / 'response.json', {'usage': {'input_tokens': 100, 'output_tokens': 1000,
            'output_tokens_details': {'reasoning_tokens': 800}}})
    with cost_guard('deepseek-flash', 'review', tmp_path / 'review', 1000, 131072) as ticket:
        assert ticket['max_output_tokens'] == 131072
        ticket['sent'] = True
        write_json(tmp_path / 'review/usage.json', {'prompt_tokens': 1000, 'completion_tokens': 2000})
    record = json.loads(ledger.read_text())
    assert record['accounted_usd'] == pytest.approx(0.0332)
    assert record['cost_complete']
    assert all(not call['bound_violation'] for call in record['calls'])


def test_missing_usage_retains_full_cost_and_prevents_next_request(monkeypatch, tmp_path):
    ledger = configure(monkeypatch, tmp_path)
    with cost_guard('gpt-5.5', 'lost', tmp_path / 'lost', 90000, 18000) as ticket:
        assert ticket['max_output_tokens'] == 18000
        ticket['sent'] = True
    record = json.loads(ledger.read_text())
    assert record['accounted_usd'] == pytest.approx(0.99)
    assert not record['cost_complete']
    with pytest.raises(CostBudgetError, match='cannot fund'):
        with cost_guard('deepseek-flash', 'next', tmp_path / 'next', 0, 131072):
            pytest.fail('must reject before HTTP')
    assert len(json.loads(ledger.read_text())['calls']) == 1


def test_cancelled_before_http_releases_reservation(monkeypatch, tmp_path):
    ledger = configure(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match='duplicate attempt'):
        with cost_guard('gpt-5.5', 'cancelled', tmp_path / 'first', 1000, 25000):
            raise ValueError('duplicate attempt')
    record = json.loads(ledger.read_text())
    assert record['accounted_usd'] == 0
    assert record['cost_complete']


def test_authorized_budget_increase_preserves_unknown_reservation(monkeypatch, tmp_path):
    ledger = configure(monkeypatch, tmp_path)
    with cost_guard('gpt-5.5', 'lost', tmp_path / 'lost', 90000, 18000) as ticket:
        ticket['sent'] = True
    before = json.loads(ledger.read_text())
    raise_budget_ceiling(ledger, 1.5, authorization='User explicitly approved this figure at USD 1.50')
    after = json.loads(ledger.read_text())
    assert after['calls'] == before['calls']
    assert after['accounted_usd'] == before['accounted_usd']
    assert not after['cost_complete'] and after['limit_usd'] == 1.5
    assert after['authorizations'][0]['previous_limit_usd'] == 1


@pytest.mark.parametrize('model,input_bound,output,limit', [
    ('gpt-5.5', 90000, 25000, '1'),
    ('deepseek-flash', 700000, 131072, '0.3'),
])
def test_underfunded_full_request_is_blocked_without_clipping_any_provider(monkeypatch, tmp_path, model, input_bound, output, limit):
    ledger=configure(monkeypatch,tmp_path,limit)
    folder=tmp_path/'blocked'
    with pytest.raises(CostBudgetError,match='output limit unchanged'):
        with cost_guard(model,'blocked',folder,input_bound,output):
            pytest.fail('must not admit an artificially shortened reply')
    assert not ledger.exists()
    blocked=json.loads((folder/'cost-blocked.json').read_text())
    assert blocked['planned_output_tokens']==output
    assert not blocked['output_limit_changed'] and not blocked['model_request_sent']
    assert blocked['required_reservation_usd']>float(limit)


def test_gpt_underfunding_rejects_before_http_or_attempt_record(monkeypatch,tmp_path):
    from PIL import Image
    from figfox_plus import providers
    ledger=configure(monkeypatch,tmp_path,'0.6')
    original=tmp_path/'original.png';Image.new('RGB',(32,32),'white').save(original)
    monkeypatch.setattr(providers,'PLUS_ROOT',tmp_path)
    monkeypatch.setattr(providers,'load_key',lambda _: 'test-only')
    monkeypatch.setattr(providers.urllib.request,'urlopen',lambda *a,**k: pytest.fail('must not send an underfunded GPT request'))
    with pytest.raises(CostBudgetError,match='output limit unchanged'):
        providers.call_gpt55('reproduce',[original],tmp_path/'gpt55','native',rerun_authorization='fixture')
    assert not ledger.exists() and not (tmp_path/'runs/session-ledger.jsonl').exists()
    assert not (tmp_path/'gpt55/request.json').exists()


@pytest.mark.parametrize('hard_limit',[None,'5'])
def test_default_gpt_generation_capacity_does_not_depend_on_cost_mode(monkeypatch,tmp_path,hard_limit):
    from PIL import Image
    from figfox_plus import providers
    if hard_limit is None:
        monkeypatch.delenv('FIGFOX_COST_LIMIT_USD',raising=False)
        monkeypatch.delenv('FIGFOX_COST_BUDGET_FILE',raising=False)
    else:configure(monkeypatch,tmp_path,hard_limit)
    monkeypatch.delenv('FIGFOX_GPT_MAX_OUTPUT_TOKENS',raising=False)
    original=tmp_path/'original.png';Image.new('RGB',(32,32),'white').save(original)
    monkeypatch.setattr(providers,'PLUS_ROOT',tmp_path)
    monkeypatch.setattr(providers,'load_key',lambda _: 'test-only')
    bodies=[]
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def __iter__(self):
            return iter([('data: '+json.dumps({'type':'response.output_text.delta','delta':'<svg/>'})+'\n').encode(),
                ('data: '+json.dumps({'type':'response.completed','response':{'usage':{'input_tokens':100,'output_tokens':100}}})+'\n').encode()])
    def http(request,timeout):
        bodies.append(json.loads(request.data));return Response()
    monkeypatch.setattr(providers.urllib.request,'urlopen',http)
    assert providers.call_gpt55('reproduce',[original],tmp_path/'gpt55','native',rerun_authorization='fixture')=='<svg/>'
    assert bodies[0]['max_output_tokens']==128000
    assert bodies[0]['reasoning']['effort']=='medium'


@pytest.mark.parametrize('limit,authorization', [(1.5, ''), (float('nan'), 'approved'), (0.5, 'approved')])
def test_invalid_budget_changes_leave_the_ledger_unchanged(monkeypatch, tmp_path, limit, authorization):
    ledger = configure(monkeypatch, tmp_path)
    with cost_guard('gpt-5.5', 'lost', tmp_path / 'lost', 1000, 25000):
        pass
    before = ledger.read_bytes()
    with pytest.raises(CostBudgetError):
        raise_budget_ceiling(ledger, limit, authorization=authorization)
    assert ledger.read_bytes() == before


@pytest.mark.parametrize('period', ['weekend', 'weekday', 'crossing'])
def test_finished_weekend_repricing_retains_full_unknown_token_bound(monkeypatch, tmp_path, period):
    from datetime import datetime, timezone
    import os
    ledger = configure(monkeypatch, tmp_path)
    folder = tmp_path / 'failed'
    with cost_guard('deepseek-flash', 'failed', folder, 10000, 10000) as ticket:
        ticket['sent'] = True
        write_json(folder / 'attempt.json', {})
        write_json(folder / 'error.json', {'type': 'TimeoutError'})
    weekend = datetime(2026, 10, 3, 4, tzinfo=timezone.utc).timestamp()
    start = weekend if period == 'weekend' else weekend - 86400
    end = start + 120 if period != 'crossing' else weekend
    os.utime(folder / 'attempt.json', (start, start))
    os.utime(folder / 'error.json', (end, end))
    before = json.loads(ledger.read_text())
    reprice_finished_weekend_calls(ledger)
    after = json.loads(ledger.read_text())
    factor = 0.5 if period == 'weekend' else 1
    assert after['accounted_usd'] == pytest.approx(before['accounted_usd'] * factor)
    assert after['calls'][0]['accounted_usd'] == after['calls'][0]['reserved_usd']
    assert after['calls'][0]['status'] == 'usage_unknown_reservation_retained'
    assert after['calls'][0]['max_output_tokens'] == 10000 and not after['cost_complete']
    reprice_finished_weekend_calls(ledger)
    assert json.loads(ledger.read_text())['accounted_usd'] == after['accounted_usd']


def test_disabled_budget_does_not_change_requests(monkeypatch, tmp_path):
    monkeypatch.delenv('FIGFOX_COST_LIMIT_USD', raising=False)
    monkeypatch.delenv('FIGFOX_COST_BUDGET_FILE', raising=False)
    with cost_guard('unpriced-fixture', 'fixture', tmp_path, 0, 1) as ticket:
        assert ticket is None


def test_long_gpt_context_uses_both_price_multipliers(monkeypatch, tmp_path):
    ledger = configure(monkeypatch, tmp_path, '10')
    with cost_guard('gpt-5.5', 'long', tmp_path / 'first', 300000, 25000) as ticket:
        assert json.loads(ledger.read_text())['calls'][0]['reserved_usd'] == pytest.approx(4.125)
        ticket['sent'] = True
        write_json(tmp_path / 'first/response.json', {'usage': {'input_tokens': 300000, 'output_tokens': 1000}})
    assert json.loads(ledger.read_text())['accounted_usd'] == pytest.approx(3.045)


def test_budget_rejection_cannot_send_http_or_consume_transport_attempt(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path, '0.00001')
    def forbidden(*args, **kwargs):
        pytest.fail('budget rejection must precede network')
    with pytest.raises(CostBudgetError):
        send([{'role': 'user', 'content': 'inspect'}], [], tmp_path / 'review', send_http=forbidden)
    assert not (tmp_path / 'review/api-ledger.jsonl').exists()
    assert not list((tmp_path / 'review').rglob('attempt.json'))


def test_error_still_accounts_usage_received_in_stream(monkeypatch, tmp_path):
    ledger = configure(monkeypatch, tmp_path)
    folder = tmp_path / 'failed'
    folder.mkdir()
    with pytest.raises(TimeoutError):
        with cost_guard('deepseek-flash', 'failed', folder, 2000, 20000) as ticket:
            ticket['sent'] = True
            (folder / 'events.jsonl').write_text(json.dumps({'usage': {'prompt_tokens': 1000,
                'prompt_cache_hit_tokens': 500, 'completion_tokens': 1000}}) + '\n', encoding='utf-8')
            raise TimeoutError('stream lost')
    record = json.loads(ledger.read_text())
    assert record['accounted_usd'] == pytest.approx(0.001353)
    assert record['cost_complete']


def test_original_image_bound_includes_image_tokens_not_base64(tmp_path):
    from PIL import Image
    image = tmp_path / 'image.png'
    Image.new('RGB', (985, 539)).save(image)
    assert gpt_input_upper_bound('abc', [image]) == 3 + 4096 + 129 + 633


def test_incomplete_gpt_preserves_raw_partial_response_and_charged_usage(monkeypatch, tmp_path):
    from PIL import Image
    from figfox_plus import providers
    ledger = configure(monkeypatch, tmp_path)
    image = tmp_path / 'original.png'
    Image.new('RGB', (32, 32)).save(image)
    folder = tmp_path / 'gpt55'
    monkeypatch.setattr(providers, 'PLUS_ROOT', tmp_path)
    monkeypatch.setattr(providers, 'load_key', lambda _: 'test-only')
    events = [{'type': 'response.output_text.delta', 'delta': '<svg>'},
              {'type': 'response.incomplete', 'response': {'status': 'incomplete',
               'usage': {'input_tokens': 100, 'output_tokens': 1000}}}]
    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def __iter__(self):
            return iter(('data: ' + json.dumps(event) + '\n').encode() for event in events)
    def fake_http(request, timeout):
        body = json.loads(request.data)
        assert body['max_output_tokens'] == 25000
        assert body['service_tier'] == 'default'
        return Stream()
    monkeypatch.setattr(providers.urllib.request, 'urlopen', fake_http)
    with pytest.raises(ValueError, match='incomplete'):
        providers.call_gpt55('draw', [image], folder, 'fixture')
    assert (folder / 'response.txt').read_text() == '<svg>'
    assert json.loads((folder / 'response.json').read_text())['status'] == 'incomplete'
    assert json.loads(ledger.read_text())['accounted_usd'] == pytest.approx(0.0305)
