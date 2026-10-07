"""Local progress evidence and request inactivity limits, independent of token cost."""
from contextvars import ContextVar
import http.client
import math
import os
from pathlib import Path
import socket
import threading
import time

from .state import write_json

_runtime = ContextVar('figfox_runtime', default=None)


def seconds_setting(name, default):
    value = float(os.environ.get(name, default))
    if not math.isfinite(value) or value <= 0:
        raise ValueError(name + ' must be positive and finite')
    return value


class ProgressTimeoutError(TimeoutError):
    pass


class RunStatus:
    """Heartbeat stays alive during a blocked read; meaningful progress is separate."""
    def __init__(self, folder, image, image_id):
        self.folder = Path(folder)
        self.state = {'schema': 1, 'worker_pid': os.getpid(), 'image': str(image),
                      'image_id': image_id, 'started_at': time.time(), 'status': 'running',
                      'stage': 'preparing', 'stage_at': time.time(), 'current_request': None,
                      'cost_target_usd': float(os.environ.get('FIGFOX_COST_TARGET_USD', 1))}
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.token = _runtime.set(self)
        self.update()
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()

    def update(self, **values):
        with self.lock:
            self.state.update(values, heartbeat_at=time.time())
            _write_snapshot(self.folder / 'runtime-status.json', self.state)

    def stage(self, name, **extra):
        self.update(stage=name, stage_at=time.time(), **extra)

    def _heartbeat(self):
        while not self.stopped.wait(5):
            try:
                self.update()
            except OSError:
                # A full/unavailable drive must not silently terminate a paid request.
                continue

    def finish(self, failure=None):
        self.stopped.set()
        self.thread.join(timeout=6)
        unresolved = self.state.get('review_status') not in (None, 'visual_review_pending') or self.state.get('followup_status') == 'failed'
        status = 'failed' if failure else 'completed_with_issues' if unresolved else 'completed'
        self.update(status=status, error=failure,
                    finished_at=time.time())
        _runtime.reset(self.token)


class RequestProgress:
    """Counts nonblank reasoning/text/tool progress; retains all character counts.

    The watchdog interrupts the socket, so even a read blocked between SSE lines
    can end. A healthy long stream has no total duration or cost-based deadline.
    """
    def __init__(self, folder, model, *, clock=time.monotonic):
        self.folder = Path(folder)
        self.model = model
        self.clock = clock
        self.started = self.last_meaningful = clock()
        self.started_at = time.time()
        self.last_write = -math.inf
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.expired = threading.Event()
        self.response = None
        self.read_socket = None
        self.error = None
        self.runtime = _runtime.get()
        self.warning_seconds = seconds_setting('FIGFOX_GPT_WARN_SECONDS' if model.startswith('gpt')
                                               else 'FIGFOX_DS_WARN_SECONDS', 900 if model.startswith('gpt') else 300)
        self.hidden_limit = seconds_setting('FIGFOX_GPT_HIDDEN_IDLE_SECONDS', 3600)
        self.idle_limit = seconds_setting('FIGFOX_STREAM_IDLE_SECONDS', 1200)
        self.state = {'schema': 1, 'model': model, 'status': 'sending', 'started_at': self.started_at,
                      'meaningful_bytes': 0, 'reasoning_characters': 0, 'content_characters': 0,
                      'tool_argument_characters': 0, 'wire_bytes': 0, 'last_wire_at': None,
                      'last_meaningful_at': None, 'usage': None, 'automatic_retry': False,
                      'warning_seconds': self.warning_seconds,
                      'inactivity_limit_seconds': self.hidden_limit if model.startswith('gpt') else self.idle_limit}
        self.flush(force=True)
        if self.runtime:
            self.runtime.update(current_request=str(self.folder.resolve()))
        self.thread = threading.Thread(target=self._watch, daemon=True)
        self.thread.start()

    @property
    def limit(self):
        return self.hidden_limit if self.model.startswith('gpt') and not self.state.get('meaningful_bytes') else self.idle_limit

    def attach(self, response):
        # urllib's timeout also applies to every later socket read. Once the
        # response is connected, let the progress watchdog decide inactivity;
        # its limit changes after hidden GPT reasoning becomes visible.
        if isinstance(response, http.client.HTTPResponse):
            stream = getattr(response, 'fp', None)
            sock = getattr(getattr(stream, 'raw', None), '_sock', None)
            if sock is None or not hasattr(sock, 'settimeout'):
                raise RuntimeError('cannot configure model response read timeout')
            self.read_socket = sock
            sock.settimeout(self.limit + 0.5)
        self.response = response
        self.state['status'] = 'receiving'
        self.flush(force=True)
        if self.expired.is_set():
            self._shutdown()
            self.check()

    def wire(self, line):
        with self.lock:
            self.state['wire_bytes'] += len(line) if isinstance(line, bytes) else len(line.encode('utf-8'))
            self.state['last_wire_at'] = time.time()
            self.flush()
        self.check()

    def delta(self, *, reasoning='', content='', arguments='', usage=None):
        with self.lock:
            size = len((reasoning + content + arguments).encode('utf-8'))
            for field, value in (('reasoning_characters', reasoning), ('content_characters', content),
                                 ('tool_argument_characters', arguments)):
                self.state[field] += len(value)
            if any(value.strip() for value in (reasoning, content, arguments)):
                self.last_meaningful = self.clock()
                self.state['last_meaningful_at'] = time.time()
                self.state['meaningful_bytes'] += size
                if self.read_socket is not None:
                    self.read_socket.settimeout(self.limit + 0.5)
            if usage:
                self.state['usage'] = usage
            self.flush()
        self.check()

    def flush(self, *, force=False):
        with self.lock:
            now = self.clock()
            if not force and now - self.last_write < 2:
                return
            self.state.update(observed_at=time.time(), elapsed_seconds=round(now-self.started, 3),
                              inactivity_limit_seconds=self.limit,
                              progress_visibility='visible' if self.state['meaningful_bytes'] else
                                  'hidden_reasoning_possible' if self.model.startswith('gpt') else 'awaiting_content')
            _write_snapshot(self.folder / 'progress.json', self.state)
            self.last_write = now

    def expire_if_idle(self):
        with self.lock:
            if self.stop.is_set() or self.expired.is_set() or self.clock()-self.last_meaningful < self.limit:
                return False
            self.error = ProgressTimeoutError(f'No new model content for {self.limit:g}s; request interrupted; no automatic retry')
            self.expired.set()
            self.state.update(status='interrupting', error=str(self.error))
            try:
                self.flush(force=True)
            except OSError:
                # Losing writable evidence storage must not leave the connection running.
                pass
        self._shutdown()
        return True

    def _shutdown(self):
        # urllib HTTPResponse -> BufferedReader -> SocketIO -> SSLSocket.
        stream = getattr(self.response, 'fp', None)
        sock = getattr(getattr(stream, 'raw', None), '_sock', None)
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def _watch(self):
        while not self.stop.wait(1):
            try:
                if self.expire_if_idle():
                    return
            except OSError:
                # Evidence I/O failure does not waive the socket timeout.
                continue

    def check(self):
        if self.expired.is_set():
            raise self.error

    def interrupt_when_stalled(self, error):
        # The socket is a backstop for a blocked read. Classify its timeout by
        # the same meaningful-progress clock used by the watchdog.
        if isinstance(error, TimeoutError):
            self.expire_if_idle()
        return self.error if self.expired.is_set() else error

    def finish(self, *, error=None, usage=None):
        self.stop.set()
        self.thread.join(timeout=2)
        with self.lock:
            self.state.update(status='failed' if error or self.expired.is_set() else 'completed',
                              finished_at=time.time(), error=str(self.error or error) if error or self.error else None)
            if usage:
                self.state['usage'] = usage
            self.flush(force=True)


def _write_snapshot(path, state):
    """Monitoring metadata cannot abort generation; final evidence stays strict."""
    try:
        write_json(path, state)
    except OSError as error:
        state['snapshot_write_errors'] = state.get('snapshot_write_errors', 0) + 1
        state['last_snapshot_write_error'] = {
            'type': type(error).__name__, 'message': str(error), 'at': time.time()}
