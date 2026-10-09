"""FRI v2.0 bounded, offline, durable operator-controlled job processing.

This is an *at-least-once* advisory report queue, NOT ForexPro experiment
execution. No remote fetch, broker, protected data access or automated discovery.
The event hash chain detects accidental edits, not malicious rewriting.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Sequence

from .analysis import canonical_json
from .contracts import EvidenceError
from .operations import _prepare, run as run_pipeline, verify_report_dir

_SCHEMA = """
CREATE TABLE jobs (
  job_id TEXT PRIMARY KEY,
  request_sha256 TEXT NOT NULL UNIQUE,
  request_json TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('QUEUED','RUNNING','RETRY','SUCCEEDED','FAILED')),
  attempts INTEGER NOT NULL CHECK(attempts BETWEEN 0 AND 3),
  max_attempts INTEGER NOT NULL CHECK(max_attempts BETWEEN 1 AND 3),
  available_at INTEGER NOT NULL,
  leased_until INTEGER,
  lease_token TEXT,
  result_sha256 TEXT,
  result_dir TEXT,
  error_code TEXT,
  CHECK ((state='RUNNING') = (lease_token IS NOT NULL)),
  CHECK ((state='RUNNING') = (leased_until IS NOT NULL))
);
CREATE TABLE events (
  event_no INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(job_id),
  event_type TEXT NOT NULL CHECK(event_type IN ('QUEUED','CLAIMED','RETRY','SUCCEEDED','FAILED','REQUEUED')),
  attempt INTEGER NOT NULL,
  event_time INTEGER NOT NULL,
  previous_sha256 TEXT NOT NULL,
  event_sha256 TEXT NOT NULL
);
CREATE TRIGGER immutable_events_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
CREATE TRIGGER immutable_events_delete BEFORE DELETE ON events BEGIN SELECT RAISE(ABORT,'immutable'); END;
PRAGMA user_version=1;
"""
_STATES = {'QUEUED', 'RUNNING', 'RETRY', 'SUCCEEDED', 'FAILED'}


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def _db_path(db_path: str | Path, *, create: bool) -> Path:
    db = Path(db_path)
    if db.is_symlink() or db.parent.is_symlink() or not db.parent.is_dir():
        raise EvidenceError('queue database needs a real existing parent and a non-symlink path')
    target = db.resolve()
    if target.exists() and not target.is_file():
        raise EvidenceError('queue database path is not a file')
    if not create and not target.is_file():
        raise EvidenceError('queue database does not exist')
    return target


def _connect(db_path: str | Path, *, create: bool, writable: bool = False) -> sqlite3.Connection:
    target = _db_path(db_path, create=create)
    fresh = not target.exists()
    if fresh:
        with target.open('xb'):
            pass
        target.chmod(0o600)
    try:
        mode = 'rw' if (create or writable) else 'ro'
        conn = sqlite3.connect(f'file:{target.as_posix()}?mode={mode}', uri=True,
                               isolation_level=None, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if fresh:
            conn.executescript(_SCHEMA)
        elif version != 1:
            raise EvidenceError('unsupported queue schema version')
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise EvidenceError('queue database integrity check failed')
        return conn
    except (sqlite3.Error, EvidenceError) as exc:
        if 'conn' in locals():
            conn.close()
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError(f'cannot open queue database: {type(exc).__name__}') from exc


def _event(conn: sqlite3.Connection, job_id: str, event_type: str, attempt: int, now: int) -> None:
    last = conn.execute('SELECT event_sha256 FROM events ORDER BY event_no DESC LIMIT 1').fetchone()
    previous = last['event_sha256'] if last else '0' * 64
    obj = {'job_id': job_id, 'event_type': event_type, 'attempt': attempt,
           'event_time': now, 'previous_sha256': previous}
    conn.execute('INSERT INTO events(job_id,event_type,attempt,event_time,previous_sha256,event_sha256) '
                 'VALUES(?,?,?,?,?,?)', (job_id, event_type, attempt, now, previous, _hash(obj)))


def _validate_config(cfg: dict[str, Any]) -> None:
    if not isinstance(cfg, dict) or set(cfg) != {
        'bundles', 'bundle_files_sha256', 'memory_db', 'output_root', 'trust_store',
        'unsigned_synthetic', 'expected_procedures', 'min_support'}:
        raise EvidenceError('unsupported queue request shape')
    if type(cfg['unsigned_synthetic']) is not bool:
        raise EvidenceError('invalid trust mode')
    if cfg['unsigned_synthetic'] == (cfg['trust_store'] is not None):
        raise EvidenceError('queue requires exactly one signed or synthetic intake mode')
    if not isinstance(cfg['bundles'], list) or not 1 <= len(cfg['bundles']) <= 50 or not all(isinstance(x, str) for x in cfg['bundles']):
        raise EvidenceError('invalid queue input list')
    if not isinstance(cfg['bundle_files_sha256'], list) or len(cfg['bundles']) != len(cfg['bundle_files_sha256']) or any(
        not isinstance(v, str) or len(v) != 64 or any(c not in '0123456789abcdef' for c in v)
        for v in cfg['bundle_files_sha256']
    ):
        raise EvidenceError('invalid queue input digests')
    if not isinstance(cfg['expected_procedures'], list) or not all(isinstance(x, str) for x in cfg['expected_procedures']):
        raise EvidenceError('invalid expected procedures')
    from .comparison import _validate_expected
    _validate_expected(cfg['expected_procedures'])
    if type(cfg['min_support']) is not int or not 2 <= cfg['min_support'] <= 5000:
        raise EvidenceError('invalid support threshold')
    for name in ('memory_db','output_root'):
        if not isinstance(cfg[name], str) or not cfg[name]:
            raise EvidenceError('invalid queue path')
    if cfg['trust_store'] is not None and not isinstance(cfg['trust_store'], str):
        raise EvidenceError('invalid trust store path')


def _fingerprint(directory: Path, *, signed: bool) -> str:
    expected = ('manifest.json', 'summary.json', 'attestation.json') if signed else ('manifest.json', 'summary.json')
    if directory.is_symlink() or not directory.is_dir() or set(p.name for p in directory.iterdir()) != set(expected):
        raise EvidenceError('queue bundle changed after submission')
    parts = []
    for name in expected:
        file = directory / name
        if file.is_symlink() or not file.is_file() or file.stat().st_size > 1024 * 1024:
            raise EvidenceError('queue source file invalid')
        parts.append({'name': name, 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
    return _hash({'files': parts})


def _check_inputs(cfg: dict[str, Any]) -> None:
    _validate_config(cfg)
    for path, digest in zip(cfg['bundles'], cfg['bundle_files_sha256']):
        if _fingerprint(Path(path), signed=not cfg['unsigned_synthetic']) != digest:
            raise EvidenceError('queue bundle content changed after submission')


def submit(queue_db: str | Path, bundle_dirs: Sequence[str | Path], memory_db: str | Path,
           output_root: str | Path, *, trust_store: str | Path | None = None,
           allow_unsigned_synthetic: bool = False, expected_procedures: Sequence[str] = (),
           min_support: int = 2, max_attempts: int = 3, now: int | None = None) -> dict[str, Any]:
    """Explicitly validate input bundles, then enqueue only paths and fingerprints.

    Report observation text is never saved to the queue.
    """
    if not 1 <= len(bundle_dirs) <= 50 or type(max_attempts) is not int or not 1 <= max_attempts <= 3:
        raise EvidenceError('queue requires 1..50 bundles and 1..3 attempts')
    if (trust_store is None) == (not allow_unsigned_synthetic):
        raise EvidenceError('select signed trust store or unsigned synthetic fixtures')
    paths = [Path(x) for x in bundle_dirs]
    resolved = sorted(x.resolve() for x in paths)
    if len(set(resolved)) != len(resolved):
        raise EvidenceError('duplicate queue input')
    output = Path(output_root)
    if output.is_symlink() or not output.is_dir() or output.resolve() == Path('/'):
        raise EvidenceError('output root must be an existing real local directory')
    db = _db_path(queue_db, create=True)
    memory = Path(memory_db)
    if memory.is_symlink() or not memory.parent.is_dir() or memory.parent.is_symlink():
        raise EvidenceError('invalid Research Memory path')
    protected_paths = [db, memory.resolve(), output.resolve()]
    for bundle in resolved:
        if any(p.is_relative_to(bundle) for p in protected_paths) or output.resolve().is_relative_to(bundle):
            raise EvidenceError('queue database, Research Memory and reports must be outside inputs')
    if db == memory.resolve():
        raise EvidenceError('job queue must be separate from Research Memory')
    for bundle in paths:
        _prepare(bundle, trust_store=Path(trust_store) if trust_store else None,
                 unsigned_synthetic=allow_unsigned_synthetic)
    cfg = {
        'bundles': [str(x) for x in resolved],
        'bundle_files_sha256': [_fingerprint(x, signed=not allow_unsigned_synthetic) for x in resolved],
        'memory_db': str(memory.resolve()), 'output_root': str(output.resolve()),
        'trust_store': str(Path(trust_store).resolve()) if trust_store else None,
        'unsigned_synthetic': allow_unsigned_synthetic,
        'expected_procedures': sorted(expected_procedures), 'min_support': min_support,
    }
    _validate_config(cfg)
    stamp = int(time.time()) if now is None else int(now)
    request_sha = _hash(cfg)
    conn = _connect(db, create=True)
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT COUNT(*) FROM jobs').fetchone()[0] >= 5000:
            raise EvidenceError('queue capacity of 5000 jobs exceeded')
        existing = conn.execute('SELECT job_id,state FROM jobs WHERE request_sha256=?', (request_sha,)).fetchone()
        if existing:
            conn.commit()
            return {'status': 'ALREADY_QUEUED', 'job_id': existing['job_id'], 'state': existing['state']}
        job_id = uuid.uuid4().hex
        conn.execute('INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                     (job_id, request_sha, canonical_json(cfg), 'QUEUED', 0, max_attempts,
                      stamp, None, None, None, None, None))
        _event(conn, job_id, 'QUEUED', 0, stamp)
        conn.commit()
        return {'status': 'QUEUED', 'job_id': job_id, 'state': 'QUEUED'}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def claim(queue_db: str | Path, *, now: int | None = None, lease_seconds: int = 900) -> dict[str, Any] | None:
    if type(lease_seconds) is not int or not 30 <= lease_seconds <= 3600:
        raise EvidenceError('lease_seconds must be 30..3600')
    stamp = int(time.time()) if now is None else int(now)
    conn = _connect(queue_db, create=False, writable=True)
    try:
        conn.execute('BEGIN IMMEDIATE')
        # All expired jobs are eligible. Exhausted leases are marked failed.
        for row in conn.execute('SELECT job_id,attempts,max_attempts FROM jobs WHERE state="RUNNING" AND leased_until<=? ORDER BY job_id', (stamp,)).fetchall():
            if row['attempts'] >= row['max_attempts']:
                conn.execute('UPDATE jobs SET state="FAILED",lease_token=NULL,leased_until=NULL,error_code="LEASE_EXHAUSTED" WHERE job_id=?', (row['job_id'],))
                _event(conn, row['job_id'], 'FAILED', row['attempts'], stamp)
            else:
                conn.execute('UPDATE jobs SET state="RETRY",lease_token=NULL,leased_until=NULL,available_at=? WHERE job_id=?', (stamp, row['job_id']))
                _event(conn, row['job_id'], 'RETRY', row['attempts'], stamp)
        row = conn.execute('SELECT * FROM jobs WHERE state IN ("QUEUED","RETRY") AND available_at<=? ORDER BY available_at,job_id LIMIT 1', (stamp,)).fetchone()
        if row is None:
            conn.commit()
            return None
        token = uuid.uuid4().hex
        attempt = row['attempts'] + 1
        conn.execute('UPDATE jobs SET state="RUNNING",attempts=?,leased_until=?,lease_token=?,error_code=NULL WHERE job_id=?',
                     (attempt, stamp + lease_seconds, token, row['job_id']))
        _event(conn, row['job_id'], 'CLAIMED', attempt, stamp)
        conn.commit()
        return {'job_id': row['job_id'], 'attempt': attempt, 'lease_token': token,
                'request_json': row['request_json'], 'leased_until': stamp+lease_seconds}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finish(queue_db: str | Path, task: dict[str, Any], *, success: bool,
            result: dict[str, Any] | None = None, error: str | None = None,
            transient: bool = False, now: int | None = None) -> dict[str, Any]:
    stamp = int(time.time()) if now is None else int(now)
    conn = _connect(queue_db, create=False, writable=True)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM jobs WHERE job_id=?', (task['job_id'],)).fetchone()
        if row is None or row['state'] != 'RUNNING' or row['lease_token'] != task['lease_token'] or row['attempts'] != task['attempt']:
            raise EvidenceError('stale worker lease rejected')
        if success:
            assert result is not None
            state, code, due = 'SUCCEEDED', None, stamp
            report_dir = str(result['output_directory'])
            report_sha = result['run_report_sha256']
            if verify_report_dir(report_dir)['run_report_sha256'] != report_sha:
                raise EvidenceError('worker report failed post-publication digest verification')
        else:
            code = error if error in {'INVALID_EVIDENCE','TRANSIENT_IO','UNEXPECTED_WORKER_ERROR'} else 'UNEXPECTED_WORKER_ERROR'
            state = 'RETRY' if transient and row['attempts'] < row['max_attempts'] else 'FAILED'
            due = stamp + min(300, 2 ** row['attempts'] * 10) if state == 'RETRY' else stamp
            report_dir, report_sha = None, None
        conn.execute('UPDATE jobs SET state=?,available_at=?,leased_until=NULL,lease_token=NULL,result_dir=?,result_sha256=?,error_code=? WHERE job_id=?',
                     (state, due, report_dir, report_sha, code, task['job_id']))
        _event(conn, task['job_id'], state if state != 'RETRY' else 'RETRY', row['attempts'], stamp)
        conn.commit()
        return {'job_id': task['job_id'], 'state': state, 'attempt': row['attempts'],
                'report_dir': report_dir, 'error_code': code}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def work_once(queue_db: str | Path, *, now: int | None = None) -> dict[str, Any]:
    """Run one due job. Caller schedules repeated invocations; no daemon/network."""
    task = claim(queue_db, now=now)
    if task is None:
        return {'status': 'IDLE'}
    try:
        cfg = json.loads(task['request_json'])
        _check_inputs(cfg)
        out = Path(cfg['output_root']) / f"fri-{task['job_id']}-attempt-{task['attempt']}"
        result = run_pipeline(cfg['bundles'], cfg['memory_db'], out,
                              trust_store=cfg['trust_store'],
                              allow_unsigned_synthetic=cfg['unsigned_synthetic'],
                              expected_procedures=cfg['expected_procedures'],
                              min_support=cfg['min_support'])
        return _finish(queue_db, task, success=True, result=result, now=now)
    except EvidenceError:
        return _finish(queue_db, task, success=False, error='INVALID_EVIDENCE', transient=False, now=now)
    except OSError:
        return _finish(queue_db, task, success=False, error='TRANSIENT_IO', transient=True, now=now)
    except Exception:
        return _finish(queue_db, task, success=False, error='UNEXPECTED_WORKER_ERROR', transient=False, now=now)


def drain(queue_db: str | Path, *, limit: int = 50) -> dict[str, Any]:
    if type(limit) is not int or not 1 <= limit <= 50:
        raise EvidenceError('limit must be 1..50')
    results = []
    for _ in range(limit):
        r = work_once(queue_db)
        if r.get('status') == 'IDLE':
            break
        results.append(r)
    return {'status': 'DRAIN_COMPLETE', 'processed': len(results), 'jobs': results}


def status(queue_db: str | Path) -> dict[str, Any]:
    conn = _connect(queue_db, create=False)
    try:
        rows = conn.execute('SELECT job_id,state,attempts,max_attempts,available_at,result_dir,result_sha256,error_code FROM jobs ORDER BY job_id LIMIT 5000').fetchall()
        return {'schema_version': 1, 'report_kind': 'NON_AUTHORITATIVE_JOB_STATUS',
                'jobs': [dict(row) for row in rows],
                'counts': {key: sum(row['state'] == key for row in rows) for key in sorted(_STATES)},
                'authority': {'scientific': False, 'holdout': False, 'promotion': False, 'broker': False}}
    finally:
        conn.close()


def verify(queue_db: str | Path, *, verify_outputs: bool = True) -> dict[str, Any]:
    conn = _connect(queue_db, create=False)
    try:
        if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise EvidenceError('queue foreign key integrity failed')
        jobs = conn.execute('SELECT * FROM jobs ORDER BY job_id').fetchall()
        events = conn.execute('SELECT * FROM events ORDER BY event_no').fetchall()
        if len(jobs) > 5000 or len(events) > 50000:
            raise EvidenceError('queue verification bounds exceeded')
        reconstructed: dict[str, dict[str, Any]] = {}
        previous = '0' * 64
        for idx, event in enumerate(events, 1):
            e = dict(event)
            if e['event_no'] != idx or e['previous_sha256'] != previous:
                raise EvidenceError('queue event chain continuity failure')
            if _hash({k: e[k] for k in ('job_id','event_type','attempt','event_time','previous_sha256')}) != e['event_sha256']:
                raise EvidenceError('queue event hash mismatch')
            previous = e['event_sha256']
            eid = e['job_id']
            old = reconstructed.get(eid)
            kind = e['event_type']
            if old is None:
                if kind != 'QUEUED' or e['attempt'] != 0:
                    raise EvidenceError('queue event sequence begins incorrectly')
                reconstructed[eid] = {'state': 'QUEUED', 'attempt': 0}
                continue
            if kind == 'REQUEUED':
                if old['state'] != 'FAILED' or e['attempt'] != 0:
                    raise EvidenceError('invalid queue manual requeue')
                old.update(state='QUEUED', attempt=0)
            elif kind == 'CLAIMED':
                if old['state'] not in {'QUEUED','RETRY'} or e['attempt'] != old['attempt'] + 1:
                    raise EvidenceError('invalid queue claim sequence')
                old.update(state='RUNNING', attempt=e['attempt'])
            elif kind == 'RETRY':
                if old['state'] != 'RUNNING' or e['attempt'] != old['attempt']:
                    raise EvidenceError('invalid queue retry sequence')
                old['state'] = 'RETRY'
            elif kind in {'SUCCEEDED','FAILED'}:
                if old['state'] != 'RUNNING' or e['attempt'] != old['attempt']:
                    raise EvidenceError('invalid queue completion sequence')
                old['state'] = kind
            else:
                raise EvidenceError('invalid queue event type')
        for row in jobs:
            j = dict(row)
            if j['job_id'] not in reconstructed:
                raise EvidenceError('queue job missing events')
            record = reconstructed[j['job_id']]
            if record['state'] != j['state'] or record['attempt'] != j['attempts']:
                raise EvidenceError('queue job state diverged from events')
            try:
                cfg = json.loads(j['request_json'])
                _validate_config(cfg)
            except (json.JSONDecodeError, ValueError, TypeError) as exc:
                raise EvidenceError('queue contains invalid request') from exc
            if _hash(cfg) != j['request_sha256'] or not 1 <= j['max_attempts'] <= 3:
                raise EvidenceError('queue request or retry policy changed')
            if j['state'] == 'SUCCEEDED':
                if not j['result_dir'] or not j['result_sha256']:
                    raise EvidenceError('successful queue job lacks report reference')
                if verify_outputs and verify_report_dir(j['result_dir'])['run_report_sha256'] != j['result_sha256']:
                    raise EvidenceError('queue job report hash mismatch')
            elif j['result_sha256'] is not None or j['result_dir'] is not None:
                raise EvidenceError('unsuccessful queue job has report reference')
        if len(reconstructed) != len(jobs):
            raise EvidenceError('orphan queue events')
        result = {'schema_version': 1, 'report_kind': 'NON_AUTHORITATIVE_QUEUE_AUDIT',
                  'status': 'QUEUE_INTACT', 'job_count': len(jobs), 'event_count': len(events),
                  'tip_sha256': previous, 'output_integrity_checked': verify_outputs,
                  'source_platform_integrated': False, 'scientific_approval': False}
        result['report_sha256'] = _hash(result)
        return result
    finally:
        conn.close()


def requeue_failed(queue_db: str | Path, job_id: str, *, now: int | None = None) -> dict[str, Any]:
    """Explicit operator recovery of FAILED tasks, never automatic reauthorization.

    Original bytes/fingerprints must remain intact. This is not a way to override
    rejected evidence: change the input and submit it as a distinct new job.
    """
    stamp = int(time.time()) if now is None else int(now)
    conn = _connect(queue_db, create=False, writable=True)
    try:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute('SELECT * FROM jobs WHERE job_id=?', (job_id,)).fetchone()
        if row is None or row['state'] != 'FAILED':
            raise EvidenceError('only a failed job can be explicitly requeued')
        cfg = json.loads(row['request_json'])
        _check_inputs(cfg)
        conn.execute('UPDATE jobs SET state="QUEUED",attempts=0,available_at=?,lease_token=NULL,leased_until=NULL,error_code=NULL WHERE job_id=?', (stamp, job_id))
        _event(conn, job_id, 'REQUEUED', 0, stamp)
        conn.commit()
        return {'job_id': job_id, 'state': 'QUEUED', 'status': 'EXPLICITLY_REQUEUED'}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def health(queue_db: str | Path, memory_db: str | Path | None = None, *, require_signed: bool = True) -> dict[str, Any]:
    """Local operational health; does not establish scientific validity."""
    audited = verify(queue_db)
    counts = status(queue_db)['counts']
    memory = None
    if memory_db is not None:
        from .operations import readiness
        memory = readiness(memory_db, require_signed=require_signed)
    result = {'schema_version': 1, 'report_kind': 'NON_AUTHORITATIVE_OPERATIONS_HEALTH',
              'queue': {'status': audited['status'], 'audit_sha256': audited['report_sha256'],
                        'counts': counts},
              'research_memory_readiness': memory['status'] if memory else 'NOT_REQUESTED',
              'signed_only_required': bool(require_signed),
              'operational_status': ('ATTENTION_REQUIRED' if counts['FAILED'] or counts['RETRY']
                   or (memory is not None and memory['status'] != 'LOCAL_INTAKE_READY') else 'HEALTHY'),
              'source_platform_integrated': False, 'scientific_approval': False,
              'holdout_access': False, 'broker_authority': False}
    result['report_sha256'] = _hash(result)
    return result
