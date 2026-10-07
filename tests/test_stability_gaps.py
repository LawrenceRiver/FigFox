"""Fault injection at existing checkpoint, publication and monitoring boundaries."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time
import zlib

from PIL import Image
import pytest

from figfox_plus import monitor as monitoring, state
from figfox_plus.native.artifacts import publish_latest
from figfox_plus.native.review_problem_first_v13.programs import _atomic_json
from figfox_plus.usage_cost import estimate_usage


def sharing_error():
    error = PermissionError('fixture Windows reader holds destination')
    error.winerror = 32
    return error


def pair(folder, color='red'):
    folder.mkdir(parents=True, exist_ok=True)
    svg, png = folder/'scene.svg', folder/'preview.png'
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2">'
                   f'<rect id="box" width="2" height="2" fill="{color}"/></svg>', encoding='utf-8')
    Image.new('RGB', (2, 2), color).save(png)
    return {'svg': str(svg), 'png': str(png), 'revision': hashlib.sha256(svg.read_bytes()).hexdigest()}


def test_execution_record_recovers_from_transient_reader_lock(tmp_path, monkeypatch):
    path = tmp_path/'execution/state.json'
    state.write_json(path, {'images': {'image': {'revision': 'old'}}})
    replace, attempts, waits = os.replace, [], []
    def locked(source, destination):
        assert Path(destination) == path
        attempts.append(source)
        assert json.loads(path.read_text(encoding='utf-8'))['images']['image']['revision'] == 'old'
        if len(attempts) < 3:
            raise sharing_error()
        return replace(source, destination)
    monkeypatch.setattr(state.os, 'replace', locked)
    monkeypatch.setattr(state.time, 'sleep', waits.append)
    _atomic_json(path, {'images': {'image': {'revision': 'committed'}}})
    assert json.loads(path.read_text(encoding='utf-8'))['images']['image']['revision'] == 'committed'
    assert len(attempts) == 3 and sum(waits) == pytest.approx(.03)
    assert list(path.parent.iterdir()) == [path]


@pytest.mark.parametrize('suffix', ['svg', 'png'])
def test_publication_recovers_from_transient_output_lock(tmp_path, monkeypatch, suffix):
    baseline = pair(tmp_path/'native-fixture/stage-0')
    source = {key: Path(baseline[key]).read_bytes() for key in ('svg', 'png')}
    target = tmp_path/('final.' + suffix)
    target.write_bytes(b'previous complete output')
    replace, attempts = os.replace, []
    def locked(temporary, destination):
        if Path(destination) == target:
            attempts.append(temporary)
            assert target.read_bytes() == b'previous complete output'
            if len(attempts) < 3:
                raise sharing_error()
        return replace(temporary, destination)
    monkeypatch.setattr(state.os, 'replace', locked)
    monkeypatch.setattr(state.time, 'sleep', lambda _: None)
    published = publish_latest(tmp_path, 'image')
    assert published['artifact_status'] == 'available' and len(attempts) == 3
    for key in ('svg', 'png'):
        assert (tmp_path/('final.' + key)).read_bytes() == source[key]
        assert Path(baseline[key]).read_bytes() == source[key]
    assert not list(tmp_path.glob('.final.*'))


def test_undecodable_png_is_rejected_even_when_all_chunk_checksums_pass(tmp_path):
    baseline = pair(tmp_path/'native-fixture/stage-0')
    latest = pair(tmp_path/'accepted', 'blue')
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    corrupted = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 2, 2, 8, 2, 0, 0, 0))
                 + chunk(b'IDAT', zlib.compress(b'\x00')) + chunk(b'IEND', b''))
    Path(latest['png']).write_bytes(corrupted)
    with Image.open(latest['png']) as image:
        image.verify()  # Container and CRC validation alone accepts this fixture.
    with Image.open(latest['png']) as image:
        with pytest.raises(OSError):
            image.load()
    state.write_json(tmp_path/'review/image/phase-2/execution/state.json', {'images': {'image': latest}})
    published = publish_latest(tmp_path, 'image', error={'type': 'RenderError'})
    assert published['output_stage'] == 'baseline_only' and len(published['rejected_candidates']) == 1
    assert (tmp_path/'final.png').read_bytes() == Path(baseline['png']).read_bytes()
    assert Path(latest['png']).read_bytes() == corrupted


def running(root, now):
    request = root/'review/image/model-turns/request'
    state.write_json(root/'runtime-status.json', {'worker_pid': 123, 'image': 'complex.png', 'image_id': 'image',
        'started_at': now-2000, 'stage': 'review_start', 'stage_at': now-2000, 'heartbeat_at': now,
        'status': 'running', 'current_request': str(request.resolve()), 'cost_target_usd': 1})
    state.write_json(request/'request.json', {'body': {'model': 'deepseek-flash'}})
    state.write_json(request/'progress.json', {'model': 'deepseek-flash', 'status': 'receiving',
        'started_at': now-2000, 'last_meaningful_at': now-301, 'warning_seconds': 300,
        'progress_visibility': 'visible', 'reasoning_characters': 90000})
    return request


def heartbeat(root, now):
    runtime = json.loads((root/'runtime-status.json').read_text(encoding='utf-8'))
    runtime['heartbeat_at'] = now
    state.write_json(root/'runtime-status.json', runtime)


def test_each_stall_episode_is_reported_once_across_monitor_restart(tmp_path):
    now = time.time()
    request = running(tmp_path, now)
    alerts = []
    def start():
        return monitoring.Monitor(tmp_path, alive=lambda _: True,
            notify=lambda *a, **k: alerts.append(a) or {'status': 'submitted'})
    monitor = start()
    monitor.poll(now=now)
    monitor = start()  # Restart while still stalled: neither lose recovery nor repeat the warning.
    monitor.poll(now=now+1)
    progress = json.loads((request/'progress.json').read_text(encoding='utf-8'))
    progress['last_meaningful_at'] = now+2
    state.write_json(request/'progress.json', progress)
    monitor.poll(now=now+2)
    assert ['疑似停滞' in a[0] for a in alerts] == [True, False]
    assert '输出已恢复' in alerts[-1][0]
    heartbeat(tmp_path, now+303)
    monitor.poll(now=now+303)
    monitor.poll(now=now+304)
    assert len(alerts) == 3 and '疑似停滞' in alerts[-1][0]
    monitor = start()
    progress['last_meaningful_at'] = now+305
    state.write_json(request/'progress.json', progress)
    monitor.poll(now=now+305)
    monitor.poll(now=now+306)
    assert len(alerts) == 4 and '输出已恢复' in alerts[-1][0]
    assert not list(tmp_path.rglob('attempt.json')) and not list(tmp_path.rglob('api-ledger.jsonl'))


@pytest.mark.parametrize('execution', ['review/image/phase-2/execution', 'review/image-followup/execution'])
def test_local_commits_are_progress_but_worker_heartbeat_alone_is_not(tmp_path, execution):
    now = time.time()
    request = running(tmp_path, now)
    state.write_json(request/'progress.json', {'model': 'deepseek-flash', 'status': 'completed',
        'started_at': now-2000, 'finished_at': now-1000})
    checkpoint = tmp_path/execution/'state.json'
    state.write_json(checkpoint, {'images': {'image': {'revision': 'committed'}}})
    os.utime(checkpoint, (now-5, now-5))
    alerts = []
    monitor = monitoring.Monitor(tmp_path, alive=lambda _: True, notify=lambda *a, **k: alerts.append(a))
    monitor.poll(now=now)
    assert alerts == []
    heartbeat(tmp_path, now+301)
    monitor.poll(now=now+301)
    assert len(alerts) == 1 and '本地处理耗时较长' in alerts[0][0]
    assert monitor.record['status'] == 'running'


def test_secondary_event_log_failure_does_not_suppress_system_notification(tmp_path, monkeypatch):
    alerts = []
    monitor = monitoring.Monitor(tmp_path, notify=lambda *a, **k: alerts.append(a) or {'status': 'submitted'})
    original = Path.open
    def locked(path, *args, **kwargs):
        if path.name == 'monitor-events.jsonl':
            raise sharing_error()
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', locked)
    monitor.alert('fixture', 'Fixture stall', 'Existing request is stalled.')
    monitor.alert('fixture', 'Fixture stall', 'Duplicate poll.')
    assert len(alerts) == 1
    saved = json.loads((tmp_path/'monitor-state.json').read_text(encoding='utf-8'))
    assert saved['alerts'][0]['notification']['status'] == 'submitted'
    assert saved['alerts'][0]['event_log_error']


@pytest.mark.parametrize('mode', ['chain', 'job'])
def test_monitor_entrypoint_recovers_io_failure_without_restarting_generation(tmp_path, monkeypatch, mode):
    calls, waits = [], []
    def poll(*args):
        calls.append('local monitor poll')
        if len(calls) == 1:
            raise sharing_error()
        return True
    class LocalMonitor:
        def __init__(self, root):
            assert root == tmp_path.resolve()
        def poll(self):
            return poll()
    monkeypatch.setattr(monitoring, 'Monitor', LocalMonitor)
    monkeypatch.setattr(monitoring, 'monitor_job', poll)
    monkeypatch.setattr(monitoring.time, 'sleep', waits.append)
    monkeypatch.setattr(sys, 'argv', ['monitor', '--root', str(tmp_path), '--mode', mode])
    monitoring.main()
    assert len(calls) == 2 and waits == [5]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('date', ['2026-01-01', '2026-02-23', '2026-04-06', '2026-05-05',
                                  '2026-06-19', '2026-09-25', '2026-10-06'])
def test_chinese_public_holiday_uses_deepseek_offpeak_pricing(date):
    timestamp = datetime.fromisoformat(date+'T02:00:00+00:00').timestamp()
    result = estimate_usage('deepseek-flash', {'prompt_tokens': 2000, 'prompt_cache_hit_tokens': 1000,
        'completion_tokens': 1000, 'completion_tokens_details': {'reasoning_tokens': 600}}, timestamp)
    assert result['price_period'] == 'offpeak' and result['estimated_usd'] == .000753


@pytest.mark.parametrize('date', ['2026-01-05', '2026-02-24', '2026-04-07', '2026-05-06',
                                  '2026-06-22', '2026-09-28', '2026-10-08', '2027-01-05'])
def test_regular_weekday_peak_is_preserved_including_unverified_future_calendar(date):
    timestamp = datetime.fromisoformat(date+'T02:00:00+00:00').timestamp()
    result = estimate_usage('deepseek-flash', {'prompt_tokens': 1000, 'completion_tokens': 1000}, timestamp)
    assert result['price_period'] == 'peak' and result['estimated_usd'] == .0015


def test_chinese_makeup_saturday_keeps_deepseek_weekend_discount():
    timestamp = datetime(2026, 10, 10, 2, tzinfo=timezone.utc).timestamp()
    result = estimate_usage('deepseek-v4-flash', {'prompt_tokens': 1000, 'completion_tokens': 1000}, timestamp)
    assert result['price_period'] == 'offpeak' and result['estimated_usd'] == .00075
