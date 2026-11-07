"""Append-only timings for local execution; no prompts, argv or private model traces."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
from time import perf_counter
import uuid


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def emit(out, event, *, job_id=None, stage=None, operation=None, status=None,
         span_id=None, duration_ms=None, code=None, component=None, target_stage=None,
         wait_type=None):
    # The fixed field list deliberately excludes arbitrary component output and input.
    record = {'schema_version': 1, 'timestamp': timestamp(), 'event': event}
    fields = {'job_id': job_id, 'stage': stage, 'operation': operation, 'status': status,
              'span_id': span_id, 'duration_ms': duration_ms, 'code': code,
              'component': component, 'target_stage': target_stage, 'wait_type': wait_type}
    record.update({key: value for key, value in fields.items() if value is not None})
    path = Path(out)/'logs/events.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, ensure_ascii=True, allow_nan=False)+'\n')


@contextmanager
def span(out, *, stage, operation, job_id=None, component=None):
    prefix = 'component' if component else 'stage'
    fields = {'job_id': job_id, 'stage': stage, 'operation': operation,
              'component': component, 'span_id': uuid.uuid4().hex}
    started = perf_counter()
    emit(out, prefix+'_started', status='started', **fields)
    try:
        yield
    except BaseException as error:
        # A diagnostic write must not replace the original component failure.
        try:
            emit(out, prefix+'_finished', status='failure',
                 duration_ms=round((perf_counter()-started)*1000, 3),
                 code=getattr(error, 'code', type(error).__name__), **fields)
        except OSError:
            pass
        raise
    else:
        emit(out, prefix+'_finished', status='success',
             duration_ms=round((perf_counter()-started)*1000, 3), **fields)
