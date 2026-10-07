import json
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from figfox_plus.native.review_problem_first_v13.transport import _read_stream, send
from figfox_plus.progress import RequestProgress, ProgressTimeoutError


@pytest.mark.parametrize('route', ['direct', 'system'])
def test_network_route_changes_only_the_current_request(tmp_path,monkeypatch,route):
    from figfox_plus.native.review_problem_first_v13 import transport
    seen=[]
    monkeypatch.setenv('FIGFOX_DS_HTTP_ROUTE',route)
    monkeypatch.setenv('HTTPS_PROXY','http://private-proxy.invalid:1234')
    class Opener:
        def open(self,request,timeout):
            seen.append((request,timeout))
            return 'response'
    handlers=[]
    def build(*args):
        handlers.extend(args)
        return Opener()
    monkeypatch.setattr(transport.urllib.request,'build_opener',build)
    selected,opener=transport._network_transport()
    request=transport.urllib.request.Request('https://api.deepseek.com/chat/completions')
    assert selected==route and opener(request,300)=='response'
    proxies=[h for h in handlers if isinstance(h,transport.urllib.request.ProxyHandler)]
    assert (len(proxies)==1 and proxies[0].proxies=={}) if route=='direct' else not proxies
    import os
    assert os.environ['HTTPS_PROXY']=='http://private-proxy.invalid:1234'
    assert seen==[(request,300)]


def test_direct_is_default_and_bad_route_cannot_consume_a_request(tmp_path,monkeypatch):
    from figfox_plus.native.review_problem_first_v13 import transport
    monkeypatch.delenv('FIGFOX_DS_HTTP_ROUTE',raising=False)
    assert transport._network_transport()[0]=='direct'
    monkeypatch.setenv('FIGFOX_DS_HTTP_ROUTE','automatic-retry')
    with pytest.raises(ValueError,match='direct or system'):
        send([{'role':'user','content':'test'}],[],tmp_path/'review',send_http=lambda *a,**k:None)
    assert not (tmp_path/'review').exists()


def chunk(delta, *, finish=None, usage=None):
    return 'data: ' + json.dumps({'id': 'provider-fixture', 'model': 'deepseek-flash',
        'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}], 'usage': usage}) + '\n'


@pytest.mark.parametrize('failure', ['eof', 'timeout', 'bad_json'])
def test_interruption_saves_last_fragments_and_stops_live_refresh(tmp_path, monkeypatch, failure):
    from figfox_plus.native.review_problem_first_v13 import transport
    # Suppress periodic writes so only the final error flush can retain tail data.
    monkeypatch.setattr(transport.time, 'monotonic', lambda: 0)
    def response():
        yield chunk({'reasoning_content': 'partial reasoning'})
        yield chunk({'content': 'partial content', 'tool_calls': [{'index': 0, 'id': 'call-1',
            'function': {'name': 'execute_review_program', 'arguments': '{"issues":'}}]})
        if failure == 'timeout': raise TimeoutError('connection stopped')
        if failure == 'bad_json': yield 'data: malformed\n'
    with pytest.raises((ValueError, TimeoutError)):
        _read_stream(response(), tmp_path)
    state = json.loads((tmp_path / 'stream-state.json').read_text(encoding='utf-8'))
    partial = json.loads((tmp_path / 'response.partial.json').read_text(encoding='utf-8'))
    assert state['status'] == 'interrupted' and not state['done_received']
    assert not state['usage_received'] and state['tool_call_count'] == 1
    assert partial['complete'] is False
    assert partial['choices'][0]['message']['tool_calls'][0]['function']['arguments'] == '{"issues":'
    assert (tmp_path / 'reasoning.txt').read_text() == 'partial reasoning'
    assert (tmp_path / 'content.partial.txt').read_text() == 'partial content'
    assert not (tmp_path / 'response.json').exists()
    page = (tmp_path / 'live.html').read_text(encoding='utf-8')
    assert '接收中断' in page and 'http-equiv="refresh"' not in page


def test_finished_payload_without_done_remains_incomplete_but_keeps_usage(tmp_path):
    usage = {'prompt_tokens': 1200, 'completion_tokens': 600}
    with pytest.raises(ValueError, match='without DONE'):
        _read_stream([chunk({'content': '{}'}, finish='stop', usage=usage)], tmp_path)
    raw = json.loads((tmp_path / 'response.partial.json').read_text())
    assert raw['usage'] == usage
    assert raw['choices'][0]['finish_reason'] == 'stop' and not raw['complete']


def test_completed_stream_preserves_message_and_usage(tmp_path):
    usage = {'prompt_tokens': 1200, 'completion_tokens': 600}
    raw = _read_stream([chunk({'content': '{}'}, finish='stop', usage=usage), 'data: [DONE]\n'], tmp_path)
    assert raw['usage'] == usage and raw['choices'][0]['message']['content'] == '{}'
    assert json.loads((tmp_path / 'stream-state.json').read_text())['status'] == 'stream_complete'
    assert not (tmp_path / 'response.partial.json').exists()


def test_whitespace_deltas_remain_in_the_saved_model_reply(tmp_path):
    from figfox_plus.progress import RequestProgress
    progress = RequestProgress(tmp_path, 'deepseek-flash')
    try:
        raw = _read_stream([chunk({'content': ' \n'}), chunk({'reasoning_content': '\t '}),
            chunk({'content': '{}'}, finish='stop'), 'data: [DONE]\n'], tmp_path, progress)
        assert raw['choices'][0]['message']['content'] == ' \n{}'
        assert raw['choices'][0]['message']['reasoning_content'] == '\t '
        assert progress.state['content_characters'] == 4
        assert progress.state['reasoning_characters'] == 2
        assert progress.state['meaningful_bytes'] == 2
    finally:
        progress.finish()


def test_truncated_finished_turn_is_archived_and_billed_without_becoming_reusable(tmp_path, monkeypatch):
    from figfox_plus.usage_cost import cost_snapshot
    monkeypatch.delenv('FIGFOX_COST_LIMIT_USD', raising=False)
    monkeypatch.delenv('FIGFOX_COST_BUDGET_FILE', raising=False)
    usage = {'prompt_tokens': 1200, 'completion_tokens': 600}
    calls = []
    class Stream:
        headers = {'Content-Type': 'text/event-stream'}
        status = 200
        def __enter__(self):return self
        def __exit__(self, *args):return False
        def __iter__(self):
            return iter([chunk({'content': '{"issues":'}, finish='length', usage=usage), 'data: [DONE]\n'])
    def http(request, timeout):
        calls.append(request)
        return Stream()
    root = tmp_path / 'review'
    messages = [{'role':'user', 'content':'original full inspection task'}]
    with pytest.raises(ValueError, match='finish_reason=length'):
        send(messages, [], root, send_http=http)
    assert not list(root.rglob('response.json'))
    raw = json.loads(next(root.rglob('response.invalid.json')).read_text(encoding='utf-8'))
    assert raw['choices'][0]['message']['content'] == '{"issues":' and raw['usage'] == usage
    assert json.loads(next(root.rglob('usage.json')).read_text(encoding='utf-8')) == usage
    with pytest.raises(ValueError, match='already attempted'):
        send(messages, [], root, send_http=http)
    assert len(calls) == 1
    costs = cost_snapshot(root)
    assert costs['model_requests'] == 1 and costs['cost_complete'] and costs['estimated_usd'] > 0


def test_interrupted_transport_consumes_attempt_and_retains_cost_reservation(tmp_path, monkeypatch):
    budget = tmp_path / 'budget.json'
    monkeypatch.setenv('FIGFOX_COST_LIMIT_USD', '1')
    monkeypatch.setenv('FIGFOX_COST_BUDGET_FILE', str(budget))
    count = []
    class Stream:
        status = 200
        headers = {'Content-Type': 'text/event-stream', 'X-Request-ID': 'test-trace',
                   'Set-Cookie': 'private-cookie', 'Authorization': 'private-credential'}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def __iter__(self): return iter([chunk({'reasoning_content': 'unfinished'})])
    def http(request, timeout):
        count.append(1)
        return Stream()
    root = tmp_path / 'review'
    messages = [{'role': 'user', 'content': 'inspect fixture'}]
    with pytest.raises(ValueError, match='without DONE'):
        send(messages, [], root, send_http=http)
    with pytest.raises(ValueError, match='already attempted'):
        send(messages, [], root, send_http=http)
    assert len(count) == 1
    record = json.loads(budget.read_text())
    assert record['calls'][0]['status'] == 'usage_unknown_reservation_retained'
    assert record['accounted_usd'] > 0 and not record['cost_complete']
    assert 'without DONE' in json.loads(next(root.rglob('error.json')).read_text())['message']
    assert 'http-equiv="refresh"' not in next(root.rglob('live.html')).read_text(encoding='utf-8')
    trace = json.loads(next(root.rglob('http-transport.json')).read_text())
    assert trace['status'] == 200 and trace['headers']['X-Request-ID'] == 'test-trace'
    assert 'private' not in json.dumps(trace) and trace['elapsed_seconds'] >= 0
    state = json.loads(next(root.rglob('stream-state.json')).read_text())
    assert state['event_count'] == 1 and state['wire_bytes_received'] > 0


def test_identical_body_in_explicit_new_task_accounts_both_http_calls(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr('figfox_plus.cost_budget._utcnow', lambda: datetime(2026, 10, 2, 2, tzinfo=timezone.utc))
    budget = tmp_path / 'budget.json'
    monkeypatch.setenv('FIGFOX_COST_LIMIT_USD', '1')
    monkeypatch.setenv('FIGFOX_COST_BUDGET_FILE', str(budget))
    attempts = []
    class Stream:
        headers = {'Content-Type': 'text/event-stream'}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def __iter__(self):
            return iter([chunk({'content': '{}'}, finish='stop', usage={
                'prompt_tokens': 10, 'completion_tokens': 10}), 'data: [DONE]\n'])
    def http(request, timeout):
        attempts.append(request.data)
        return Stream()
    messages = [{'role': 'user', 'content': 'same repair'}]
    for name in ('original', 'authorized-retry'):
        send(messages, [], tmp_path / name, send_http=http, request_limit=1)
    record = json.loads(budget.read_text())
    assert len(attempts) == len(record['calls']) == 2
    assert attempts[0] == attempts[1]
    assert record['accounted_usd'] == pytest.approx(0.00003)
    assert len({call['request_id'] for call in record['calls']}) == 2


def test_connected_gpt_read_outlives_connection_timeout_during_hidden_reasoning(tmp_path, monkeypatch):
    monkeypatch.setenv('FIGFOX_GPT_HIDDEN_IDLE_SECONDS', '2')
    monkeypatch.setenv('FIGFOX_STREAM_IDLE_SECONDS', '0.2')

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            time.sleep(0.25)
            self.wfile.write(b'data: first visible content\n\n')
            self.wfile.flush()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    progress = RequestProgress(tmp_path, 'gpt-5.5')
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}', timeout=0.05) as response:
            progress.attach(response)
            assert response.fp.raw._sock.gettimeout() == pytest.approx(2.5)
            assert next(iter(response)) == b'data: first visible content\n'
            progress.delta(content='first visible content')
            assert response.fp.raw._sock.gettimeout() == pytest.approx(0.7)
            assert not progress.expired.is_set()
    finally:
        progress.finish()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_connected_read_exits_on_meaningful_inactivity_before_socket_timeout(tmp_path, monkeypatch):
    monkeypatch.setenv('FIGFOX_STREAM_IDLE_SECONDS', '0.2')
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            release.wait(2)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    progress = RequestProgress(tmp_path, 'deepseek-flash')
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}', timeout=0.05) as response:
            progress.attach(response)
            started = time.monotonic()
            with pytest.raises(ProgressTimeoutError):
                _read_stream(response, tmp_path, progress)
            assert time.monotonic() - started < 2
    finally:
        progress.finish()
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
