import ctypes
import json
import os
import threading

import pytest

from figfox_plus import state


def sharing_error(code=32):
    error = PermissionError('Windows reader holds the destination')
    error.winerror = code
    return error


def test_transient_sharing_preserves_old_record_until_atomic_commit(tmp_path, monkeypatch):
    path = tmp_path / 'progress.json'
    state.write_json(path, {'old': 1})
    replace = os.replace
    attempts, waits = [], []
    def locked(source, destination):
        attempts.append((source, destination))
        assert json.loads(path.read_text(encoding='utf-8')) == {'old': 1}
        if len(attempts) < 4:
            raise sharing_error()
        return replace(source, destination)
    monkeypatch.setattr(state.os, 'replace', locked)
    monkeypatch.setattr(state.time, 'sleep', waits.append)
    state.write_json(path, {'new': 2})
    assert json.loads(path.read_text(encoding='utf-8')) == {'new': 2}
    assert len(attempts) == 4 and sum(waits) == pytest.approx(0.07)
    assert not list(tmp_path.glob('.progress.json*'))


def test_persistent_denial_is_bounded_and_core_failure_is_not_hidden(tmp_path, monkeypatch):
    path = tmp_path / 'result.json'
    state.write_json(path, {'old': 1})
    attempts, waits = [], []
    def denied(*args):
        attempts.append(args)
        raise sharing_error(5)
    monkeypatch.setattr(state.os, 'replace', denied)
    monkeypatch.setattr(state.time, 'sleep', waits.append)
    with pytest.raises(PermissionError):
        state.write_json(path, {'new': 2})
    assert len(attempts) == 6 and sum(waits) == pytest.approx(0.31)
    assert json.loads(path.read_text(encoding='utf-8')) == {'old': 1}
    assert not list(tmp_path.glob('.result.json*'))


def test_other_io_failures_are_not_retried(tmp_path, monkeypatch):
    def full(*args):
        raise OSError('drive full')
    monkeypatch.setattr(state.os, 'replace', full)
    monkeypatch.setattr(state.time, 'sleep', lambda _: pytest.fail('unexpected retry'))
    with pytest.raises(OSError, match='drive full'):
        state.write_json(tmp_path / 'result.json', {})


@pytest.mark.skipif(os.name != 'nt', reason='real Windows file sharing')
def test_real_windows_reader_lock_recovers_without_losing_record(tmp_path, monkeypatch):
    from ctypes import wintypes
    path = tmp_path / 'progress.json'
    state.write_json(path, {'old': 1})
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value
    blocked, done, failures = threading.Event(), threading.Event(), []
    replace = os.replace
    def observed(source, destination):
        try:
            return replace(source, destination)
        except PermissionError:
            blocked.set()
            raise
    monkeypatch.setattr(state.os, 'replace', observed)
    def writer():
        try:
            state.write_json(path, {'new': 2})
        except Exception as error:
            failures.append(error)
        finally:
            done.set()
    thread = threading.Thread(target=writer)
    thread.start()
    try:
        assert blocked.wait(2)
        assert not done.is_set()
        assert json.loads(path.read_text(encoding='utf-8')) == {'old': 1}
    finally:
        kernel.CloseHandle(wintypes.HANDLE(handle))
        thread.join(2)
    assert done.is_set() and not failures
    assert json.loads(path.read_text(encoding='utf-8')) == {'new': 2}
