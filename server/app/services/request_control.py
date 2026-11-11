"""Request deadline, resource cancellation and a publication fence.

Context-local access keeps direct, synchronous analysis callers compatible.
Diagnostics contain timings and existing sanitized planner outputs, never provider
headers, credentials or full prompts.
"""
import contextvars
import json
import logging
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from app.core.config import settings

current_request = contextvars.ContextVar('analysis_request', default=None)
current_model_metadata = contextvars.ContextVar('model_metadata', default=None)
current_model_call = contextvars.ContextVar('model_call_record', default=None)
TOKEN_FIELDS = ('input_tokens', 'output_tokens', 'total_tokens', 'cached_input_tokens', 'reasoning_tokens')
logger = logging.getLogger(__name__)


class RequestStopped(BaseException):
    """Must pass through legacy broad Exception handlers without retries."""


class RequestControl:
    def __init__(self, seconds):
        self.id = str(uuid.uuid4())
        self.started = time.monotonic()
        self.deadline = self.started + seconds
        self.lock = threading.RLock()
        self.stopped = threading.Event()
        self.reason = None
        self.outcome = None
        self.callbacks = set()
        self.data = {'request_id': self.id, 'started_at': datetime.now(timezone.utc).isoformat(),
                     'budget_seconds': seconds, 'stages': [], 'model_calls': [], 'model_call_count': 0}

    def remaining(self):
        self.check()
        return max(0.001, self.deadline - time.monotonic())

    def check(self):
        if self.stopped.is_set() or time.monotonic() >= self.deadline:
            raise RequestStopped(self.reason or 'timed_out')

    def stage(self, name):
        self.check()
        with self.lock:
            self.data['stages'].append({'stage': name, 'elapsed_ms': self.elapsed(), 'timestamp': datetime.now(timezone.utc).isoformat()})
            self.persist()

    def elapsed(self):
        return round((time.monotonic() - self.started) * 1000)

    def persist(self):
        try:
            directory = Path(settings.WORKSPACE_DIR) / 'evaluations' / 'request-deadlines'
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / (self.id + '.json')
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.data, indent=2))
            temporary.replace(path)
        except OSError:
            logger.warning('Could not persist request timing diagnostics %s', self.id)

    def stop(self, reason):
        with self.lock:
            if self.stopped.is_set():
                return
            self.reason = reason
            self.stopped.set()
            self.data.update(status=reason, elapsed_ms=self.elapsed())
            callbacks = list(self.callbacks)
            self.persist()
        # Resource teardown must never block the async supervisor.
        for callback in callbacks:
            threading.Thread(target=self._close, args=(callback,), daemon=True).start()

    @staticmethod
    def _close(callback):
        try:
            callback()
        except Exception:
            pass

    @contextmanager
    def resource(self, close):
        with self.lock:
            try:
                self.check()
            except RequestStopped:
                threading.Thread(target=self._close, args=(close,), daemon=True).start()
                raise
            self.callbacks.add(close)
        try:
            yield
        finally:
            with self.lock:
                self.callbacks.discard(close)

    @contextmanager
    def publication(self):
        with self.lock:
            self.check()
            yield

    @contextmanager
    def model_call(self):
        with self.lock:
            self.check()
            call = {'number': len(self.data['model_calls']) + 1, 'started_ms': self.elapsed()}
            call.update(current_model_metadata.get() or {})
            call['usage'] = {'source': 'unavailable', **dict.fromkeys(TOKEN_FIELDS)}
            self.data['model_calls'].append(call)
            self.data['model_call_count'] = len(self.data['model_calls'])
            self.summarize_usage()
            self.persist()
        token = current_model_call.set(call)
        try:
            yield call
        finally:
            with self.lock:
                call['ended_ms'] = self.elapsed()
                call['duration_ms'] = call['ended_ms'] - call['started_ms']
                self.persist()
            current_model_call.reset(token)
        self.check()

    def summarize_usage(self):
        """Sum reported counters only; incomplete totals stay explicitly partial."""
        calls = self.data['model_calls']
        summary = {'calls': len(calls)}
        for field in TOKEN_FIELDS:
            values = [c['usage'][field] for c in calls if c['usage'].get(field) is not None]
            summary[field] = {'reported_sum': sum(values) if values else None,
                              'reported_calls': len(values), 'unknown_calls': len(calls) - len(values)}
        self.data['token_usage'] = summary


@contextmanager
def model_metadata(**metadata):
    """Scoped diagnostic labels and character counts; never prompt contents."""
    token = current_model_metadata.set({**(current_model_metadata.get() or {}), **metadata})
    try:
        yield
    finally:
        current_model_metadata.reset(token)


def record_model_usage(usage):
    control, call = current_request.get(), current_model_call.get()
    if control is not None and call is not None:
        with control.lock:
            call['usage'] = usage
            control.summarize_usage()
            control.persist()


def checkpoint():
    control = current_request.get()
    if control:
        control.check()


def report_progress(stage, **payload):
    control = current_request.get()
    if control is not None and getattr(control, 'progress', None):
        control.progress(stage, **payload)


def terminal_stage(result, failed=False):
    if result.get('clarification_required'):return 'clarification'
    status=result.get('analysis_status')
    if status in {'incomplete','unsupported','timed_out','cancelled','failed'}:return status
    return 'failed' if failed else 'completed'


@contextmanager
def phase(name, output_id=None):
    """Measure actual bounded work, including failed phases; never extend budget."""
    checkpoint()
    control=current_request.get();started=time.monotonic()
    record={'phase':name,**({'output_id':output_id} if output_id else {})}
    if control:record['started_ms']=control.elapsed()
    try:
        yield record
    finally:
        record['duration_ms']=round((time.monotonic()-started)*1000,3)
        if control:
            with control.lock:
                control.data.setdefault('phases',[]).append(record)
                control.persist()
    checkpoint()
