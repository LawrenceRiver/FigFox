import json
from pathlib import Path
from types import SimpleNamespace
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import Image
import pytest

from figfox_plus.progress import RequestProgress, ProgressTimeoutError, RunStatus
from figfox_plus.monitor import Monitor
from figfox_plus.notifications import PROTOCOL, resolve_action, toast_xml
from figfox_plus.state import write_json
from figfox_plus.usage_cost import cost_snapshot, estimate_usage
from figfox_plus.native.review_problem_first_v13.transport import _read_stream


def test_new_reasoning_keeps_arbitrarily_long_stream_alive_and_keepalives_do_not(tmp_path):
    clock = [0]
    progress = RequestProgress(tmp_path,'deepseek-flash',clock=lambda:clock[0])
    try:
        for _ in range(100):
            clock[0] += 1199
            progress.delta(reasoning='正常推理'*1000)
            assert not progress.expire_if_idle()
        assert progress.state['reasoning_characters'] == 400000
        clock[0] += 1201
        progress.wire(': keepalive\n')
        assert progress.expire_if_idle()
        with pytest.raises(ProgressTimeoutError):progress.check()
    finally:progress.finish()


def test_gpt_hidden_reasoning_uses_longer_deadline_then_visible_progress_resets_it(tmp_path):
    clock=[0]
    progress=RequestProgress(tmp_path,'gpt-5.5',clock=lambda:clock[0])
    try:
        clock[0]=1801; progress.wire(': heartbeat\n')
        assert not progress.expire_if_idle()
        assert progress.state['progress_visibility']=='hidden_reasoning_possible'
        progress.delta(content='<svg>')
        clock[0]+=1199
        assert not progress.expire_if_idle()
        clock[0]+=2
        assert progress.expire_if_idle()
    finally:progress.finish()


@pytest.mark.parametrize('field', ['reasoning', 'content', 'arguments'])
def test_whitespace_only_deltas_preserve_counts_without_resetting_inactivity(tmp_path, field):
    clock = [0]
    progress = RequestProgress(tmp_path, 'deepseek-flash', clock=lambda:clock[0])
    try:
        progress.delta(content='<svg>')
        clock[0] = 1199
        progress.delta(**{field: ' \t\n'})
        assert progress.state['meaningful_bytes'] == len('<svg>')
        counter = {'reasoning':'reasoning_characters', 'content':'content_characters',
                   'arguments':'tool_argument_characters'}[field]
        assert progress.state[counter] == (8 if field == 'content' else 3)
        clock[0] = 1201
        assert progress.expire_if_idle()
    finally:
        progress.finish()


def test_idle_connection_is_interrupted_even_when_evidence_write_fails(tmp_path, monkeypatch):
    clock = [0]
    closed = []
    progress = RequestProgress(tmp_path, 'deepseek-flash', clock=lambda:clock[0])
    progress.attach(SimpleNamespace(fp=SimpleNamespace(raw=SimpleNamespace(
        _sock=SimpleNamespace(shutdown=lambda how:closed.append(how))))))
    try:
        with monkeypatch.context() as patch:
            def unavailable(**kwargs):
                raise OSError('fixture evidence storage unavailable')
            patch.setattr(progress, 'flush', unavailable)
            clock[0] = 1201
            assert progress.expire_if_idle()
            assert len(closed) == 1
            with pytest.raises(ProgressTimeoutError):progress.check()
    finally:
        progress.finish()


def test_snapshot_write_failures_do_not_interrupt_complete_stream(tmp_path, monkeypatch):
    clock = [0]
    runtime = RunStatus(tmp_path, tmp_path/'original.png', 'image')
    write = write_json
    failures = []
    def temporary_failure(path, data):
        if Path(path).name in ('progress.json', 'runtime-status.json') and len(failures) < 3:
            failures.append(Path(path).name)
            raise PermissionError('fixture sharing lock')
        return write(path, data)
    monkeypatch.setattr('figfox_plus.progress.write_json', temporary_failure)
    progress = None
    try:
        runtime.stage('review_start')
        (tmp_path/'request').mkdir()
        progress = RequestProgress(tmp_path/'request', 'deepseek-flash', clock=lambda:clock[0])
        chunks = [
            {'choices': [{'index': 0, 'delta': {'reasoning_content': 'whole-image reasoning'}}]},
            {'choices': [{'index': 0, 'delta': {'content': '{"issues":[],"programs":[]}'}, 'finish_reason': 'stop'}],
             'usage': {'prompt_tokens': 100, 'completion_tokens': 20}},
        ]
        def stream():
            for chunk in chunks:
                clock[0] += 3
                yield 'data: ' + json.dumps(chunk) + '\n'
            yield 'data: [DONE]\n'
        raw = _read_stream(stream(), tmp_path/'request', progress)
        progress.finish(usage=raw['usage'])
        assert raw['choices'][0]['message']['content'] == '{"issues":[],"programs":[]}'
        assert raw['choices'][0]['message']['reasoning_content'] == 'whole-image reasoning'
        assert raw['usage'] == {'prompt_tokens': 100, 'completion_tokens': 20}
        saved = json.loads((tmp_path/'request/progress.json').read_text(encoding='utf-8'))
        assert saved['status'] == 'completed' and saved['error'] is None
        assert saved['snapshot_write_errors'] >= 1
        assert not (tmp_path/'request/response.partial.json').exists()
        assert len(failures) == 3 and not progress.expired.is_set()
    finally:
        if progress is not None and not progress.stop.is_set(): progress.finish()
        runtime.finish()


def test_unwritable_progress_still_enforces_actual_inactivity(tmp_path, monkeypatch):
    clock, closed = [0], []
    progress = RequestProgress(tmp_path, 'deepseek-flash', clock=lambda:clock[0])
    progress.attach(SimpleNamespace(fp=SimpleNamespace(raw=SimpleNamespace(
        _sock=SimpleNamespace(shutdown=lambda how:closed.append(how))))))
    try:
        def unavailable(*args): raise OSError('fixture progress drive unavailable')
        monkeypatch.setattr('figfox_plus.progress.write_json', unavailable)
        progress.delta(reasoning='normal continuing reasoning')
        clock[0] = 1201
        assert progress.expire_if_idle()
        assert len(closed) == 1 and progress.state['snapshot_write_errors'] >= 1
        with pytest.raises(ProgressTimeoutError): progress.check()
    finally:
        progress.finish()


def test_watchdog_breaks_real_blocking_http_and_preserves_partial_reply(tmp_path,monkeypatch):
    monkeypatch.setenv('FIGFOX_STREAM_IDLE_SECONDS','0.2')
    done=threading.Event()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header('Content-Type','text/event-stream'); self.end_headers()
            first={'choices':[{'delta':{'reasoning_content':'retained reasoning'},'index':0}]}
            self.wfile.write(('data: '+json.dumps(first)+'\n\n').encode()); self.wfile.flush()
            try:
                while not done.wait(.05):
                    self.wfile.write(b': keepalive\n\n'); self.wfile.flush()
            except (BrokenPipeError,ConnectionResetError):pass
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    progress=RequestProgress(tmp_path,'deepseek-flash')
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{server.server_port}',timeout=5) as response:
            progress.attach(response)
            with pytest.raises(ProgressTimeoutError):_read_stream(response,tmp_path,progress)
        assert (tmp_path/'reasoning.txt').read_text(encoding='utf-8')=='retained reasoning'
        partial=json.loads((tmp_path/'response.partial.json').read_text(encoding='utf-8'))
        assert partial['complete'] is False
        assert not (tmp_path/'response.json').exists()
    finally:
        progress.finish();done.set();server.shutdown();server.server_close();thread.join(2)


def running_fixture(root,now, *, model='deepseek-flash',last=None,hidden=False):
    folder=root/'review/image/model-turns/request'
    write_json(root.parent/'case.json',{'original':'complex.png'})
    write_json(root/'runtime-status.json',{'worker_pid':123,'image':'original.png','image_id':'image',
        'started_at':now-2000,'stage':'review_start','stage_at':now-2000,'heartbeat_at':now,
        'status':'running','current_request':str(folder.resolve()),'cost_target_usd':1})
    write_json(folder/'request.json',{'body':{'model':model}})
    write_json(folder/'progress.json',{'model':model,'started_at':now-2000,'status':'receiving',
        'last_meaningful_at':last,'last_wire_at':now,'warning_seconds':900 if hidden else 300,
        'progress_visibility':'hidden_reasoning_possible' if hidden else 'visible','reasoning_characters':90000})
    return folder


def test_monitor_detects_keepalive_only_once_and_recovers_without_api_calls(tmp_path):
    root=tmp_path/'case/run'; now=time.time();folder=running_fixture(root,now,last=now-301)
    alerts=[]
    monitor=Monitor(root,alive=lambda pid:True,notify=lambda *a,**k:alerts.append(a) or {'status':'submitted'})
    assert not monitor.poll(now=now)
    assert not monitor.poll(now=now+1)
    assert len(alerts)==1 and '疑似停滞' in alerts[0][0]
    record=json.loads((folder/'progress.json').read_text(encoding='utf-8'))
    record['last_meaningful_at']=now+2;write_json(folder/'progress.json',record)
    assert not monitor.poll(now=now+2)
    assert len(alerts)==2 and '输出已恢复' in alerts[-1][0]
    assert not list(root.rglob('api-ledger.jsonl'))
    assert not list(root.rglob('attempt.json'))
    restarted=Monitor(root,alive=lambda pid:True,notify=lambda *a,**k:pytest.fail('duplicate alert'))
    restarted.poll(now=now+3)


def test_hidden_gpt_warning_does_not_assert_stall_or_kill_worker(tmp_path):
    root=tmp_path/'case/run';now=time.time();running_fixture(root,now,model='gpt-5.5',hidden=True)
    alerts=[]
    monitor=Monitor(root,alive=lambda pid:True,notify=lambda *a,**k:alerts.append(a))
    assert not monitor.poll(now=now)
    assert '进度暂不可见' in alerts[0][0] and '可能仍在内部推理' in alerts[0][1]
    assert monitor.record['status']=='running'


def test_live_cost_above_target_does_not_terminate_or_hide_unknown_usage(tmp_path):
    root=tmp_path/'case/run';now=time.time();folder=running_fixture(root,now,last=now)
    gpt=root/'native-fixture/gpt55'
    write_json(gpt/'request.json',{'model':'gpt-5.5'})
    write_json(gpt/'response.json',{'usage':{'input_tokens':100000,'output_tokens':20000}})
    alerts=[];monitor=Monitor(root,alive=lambda pid:True,notify=lambda *a,**k:alerts.append(a))
    assert not monitor.poll(now=now)
    assert monitor.record['costs']['estimated_usd']==1.1
    assert monitor.record['costs']['active_requests']==1 and not monitor.record['costs']['cost_complete']
    assert len(alerts)==1 and '正常生成继续' in alerts[0][1]
    write_json(folder/'progress.json',{'model':'deepseek-flash','status':'failed','started_at':now-100,'error':'disconnect'})
    monitor.poll(now=now+1)
    assert monitor.record['costs']['unknown_cost_requests']==1 and monitor.record['costs']['estimated_usd']==1.1


def test_worker_death_publishes_last_valid_pair_without_paid_retry(tmp_path):
    root=tmp_path/'case/run';now=time.time();running_fixture(root,now,last=now)
    stage=root/'native-fixture/stage-0';stage.mkdir(parents=True)
    svg='<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect id="box" width="2" height="2" fill="red"/></svg>'
    (stage/'scene.svg').write_text(svg,encoding='utf-8');Image.new('RGB',(2,2),'red').save(stage/'preview.png')
    alerts=[];monitor=Monitor(root,alive=lambda pid:False,notify=lambda *a,**k:alerts.append(a))
    assert monitor.poll(now=now)
    assert monitor.record['status']=='failed' and monitor.record['artifacts']['output_stage']=='baseline_only'
    assert (root/'final.svg').read_text(encoding='utf-8')==svg
    with Image.open(root/'final.png') as im:assert im.getpixel((0,0))==(255,0,0)
    assert not list(root.rglob('api-ledger.jsonl'))


@pytest.mark.parametrize('old_record', [False, True])
def test_unresolved_review_is_terminal_but_never_announced_as_full_completion(tmp_path, old_record):
    root = tmp_path/'case/run'
    runtime = RunStatus(root, tmp_path/'complex.png', 'image')
    runtime.update(review_status='emergency_unresolved', followup_status='completed')
    runtime.finish()
    saved = json.loads((root/'runtime-status.json').read_text(encoding='utf-8'))
    assert saved['status'] == 'completed_with_issues'
    if old_record:
        saved['status'] = 'completed'
        saved.pop('review_status')
        write_json(root/'runtime-status.json', saved)
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2" fill="red"/></svg>'
    (root/'final.svg').write_text(svg, encoding='utf-8')
    Image.new('RGB', (2,2), 'red').save(root/'final.png')
    write_json(root/'artifacts.json', {'artifact_status':'available', 'review_status':'emergency_unresolved'})
    before = (root/'runtime-status.json').read_bytes()
    alerts = []
    monitor = Monitor(root, alive=lambda pid:True, notify=lambda *a, **k:alerts.append(a))
    assert monitor.poll()
    assert monitor.record['status'] == 'completed_with_issues'
    assert len(alerts) == 1 and '仍有待处理问题' in alerts[0][0]
    assert '已出图，仍有待处理问题' in (root/'status.html').read_text(encoding='utf-8')
    assert (root/'runtime-status.json').read_bytes() == before
    assert (root/'final.svg').read_text(encoding='utf-8') == svg
    assert not list(root.rglob('api-ledger.jsonl'))


@pytest.mark.parametrize('usage',[{'input_tokens':2},{'output_tokens':2},{'input_tokens':-1,'output_tokens':2},
    {'input_tokens':2,'output_tokens':2,'input_tokens_details':{'cached_tokens':3}}])
def test_partial_or_invalid_usage_is_not_estimated_as_zero(usage):
    assert estimate_usage('gpt-5.5',usage,time.time()) is None


def test_nullable_optional_usage_details_do_not_crash_monitor():
    usage={'input_tokens':100,'output_tokens':100,'input_tokens_details':None,'output_tokens_details':None}
    assert estimate_usage('gpt-5.5',usage,time.time())['estimated_usd']==.0035


def test_live_cost_includes_recovery_history_once_and_is_read_only(tmp_path):
    root=tmp_path/'case/run';folder=root/'native-fixture/gpt55'
    write_json(folder/'request.json',{'model':'gpt-5.5'})
    write_json(folder/'response.json',{'usage':{'input_tokens':100,'output_tokens':100}})
    write_json(root.parent/'prior-costs.json',{'calls':[{'request':'old/unknown','model':'deepseek-flash','usage':None,'cost':None}]})
    before={p:p.read_bytes() for p in root.parent.rglob('*.json')};cache={}
    for _ in range(3):
        cost=cost_snapshot(root,cache=cache)
        assert cost['model_requests']==2 and cost['estimated_usd']==.0035
        assert cost['unknown_cost_requests']==1 and not cost['cost_complete']
    assert before=={p:p.read_bytes() for p in root.parent.rglob('*.json')}


def test_toast_text_is_escaped_and_actions_open_only_registered_files(tmp_path):
    import xml.etree.ElementTree as ET
    token='a'*32
    xml=ET.fromstring(toast_xml('<danger & text>','"quoted" message',token,has_result=True))
    assert xml.find('.//text').text=='<danger & text>'
    assert [a.get('activationType') for a in xml.findall('.//action')]==['protocol','protocol']
    page=tmp_path/'status.html';page.write_text('<h1>status</h1>')
    png=tmp_path/'result.png';Image.new('RGB',(2,2)).save(png)
    write_json(tmp_path/(token+'.json'),{'paths':{'status':str(page),'result':str(png)},'expires_at':100})
    assert resolve_action(f'{PROTOCOL}://open/{token}?kind=status',folder=tmp_path,now=99)==page
    assert resolve_action(f'{PROTOCOL}://open/{token}?kind=result',folder=tmp_path,now=99)==png
    with pytest.raises(ValueError,match='expired'):resolve_action(f'{PROTOCOL}://open/{token}?kind=status',folder=tmp_path,now=101)


@pytest.mark.parametrize('url',['javascript:alert(1)',f'{PROTOCOL}://open/../../x?kind=status',
    f'{PROTOCOL}://other/'+('a'*32)+'?kind=status',f'{PROTOCOL}://open/'+('a'*32)+'?kind=exec'])
def test_notification_action_rejects_commands_remote_hosts_and_traversal(tmp_path,url):
    with pytest.raises(ValueError):resolve_action(url,folder=tmp_path)
