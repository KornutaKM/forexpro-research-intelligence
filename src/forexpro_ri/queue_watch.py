"""Read-only operational triage over the durable FRI job queue.

Operational alerts describe local worker health and offline input drift only;
never approve scientific outcomes, broker activity, or authorization.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from .contracts import EvidenceError
from .jobs import _check_inputs, _connect, _hash, _validate_config, verify


def inspect(queue_db: str | Path, *, at: int | None = None, overdue_seconds: int = 3600,
            inspect_sources: bool = False, max_alerts: int = 100) -> dict[str, Any]:
    """Audit immutable event history, report outputs and bounded alert summary.

    Source inspection optionally checks that *current files* match the submitted
    digests; no files are imported, no remote calls made, and no paths are emitted.
    The queue audit and this snapshot are separate reads; no atomicity is claimed.
    """
    if type(overdue_seconds) is not int or not 60 <= overdue_seconds <= 604800:
        raise EvidenceError('overdue_seconds must be 60..604800')
    if type(max_alerts) is not int or not 1 <= max_alerts <= 500:
        raise EvidenceError('max_alerts must be 1..500')
    if type(inspect_sources) is not bool:
        raise EvidenceError('inspect_sources must be bool')
    stamp = int(time.time()) if at is None else int(at)
    chain = verify(queue_db)
    conn = _connect(queue_db, create=False)
    try:
        conn.execute('BEGIN')
        jobs = conn.execute('SELECT * FROM jobs ORDER BY job_id').fetchall()
        if len(jobs) > 5000:
            raise EvidenceError('queue inspection bound exceeded')
        incidents = []
        counts = {code: 0 for code in ('FAILED_JOB', 'EXPIRED_LEASE', 'OVERDUE_QUEUED',
                                       'DUE_RETRY', 'INPUT_CHANGED', 'UNPINNED_LEGACY_TRUST')}
        for row in jobs:
            job = dict(row)
            try:
                import json
                cfg = json.loads(job['request_json'])
                _validate_config(cfg)
                if _hash(cfg) != job['request_sha256']:
                    raise EvidenceError('queue request digest mismatch')
            except (ValueError, TypeError, EvidenceError) as exc:
                raise EvidenceError('queue request integrity failed') from exc
            codes = []
            if job['state'] == 'FAILED':
                codes.append('FAILED_JOB')
            if job['state'] == 'RUNNING' and job['leased_until'] <= stamp:
                codes.append('EXPIRED_LEASE')
            if job['state'] == 'QUEUED' and job['available_at'] + overdue_seconds < stamp:
                codes.append('OVERDUE_QUEUED')
            if job['state'] == 'RETRY' and job['available_at'] <= stamp:
                codes.append('DUE_RETRY')
            if cfg['trust_store'] and 'trust_store_sha256' not in cfg:
                codes.append('UNPINNED_LEGACY_TRUST')
            if inspect_sources and job['state'] not in ('SUCCEEDED', 'FAILED'):
                try:
                    _check_inputs(cfg)
                except (OSError, EvidenceError):
                    codes.append('INPUT_CHANGED')
            for code in codes:
                counts[code] += 1
                incidents.append({'job_id': job['job_id'], 'code': code, 'state': job['state'],
                                  'attempts': job['attempts']})
        severity = ('ATTENTION_REQUIRED' if any(counts[k] for k in ('FAILED_JOB','EXPIRED_LEASE','INPUT_CHANGED'))
                    else 'WATCH' if any(counts[k] for k in ('OVERDUE_QUEUED','DUE_RETRY','UNPINNED_LEGACY_TRUST'))
                    else 'CLEAR')
        report = {
            'schema_version': 1, 'report_kind': 'NON_AUTHORITATIVE_JOB_WATCH',
            'status': severity, 'queue_audit_sha256': chain['report_sha256'],
            'inspected_job_count': len(jobs), 'observed_at_unix': stamp,
            'source_fingerprints_checked': inspect_sources,
            'alert_counts': counts,
            'alerts': incidents[:max_alerts], 'alerts_truncated': len(incidents) > max_alerts,
            'authority': {'scientific': False, 'execution': False, 'broker': False,
                          'holdout': False, 'promotion': False},
            'limitations': [
                'Operational observations only; local timestamps may be skewed.',
                'Queue hashes are not externally authenticated and do not prevent privileged rewrites.',
                'Input inspection detects drift of selected local files but not export permission.',
                'This read-only snapshot does not claim atomic synchronization with a running worker.',
            ],
        }
        report['report_sha256'] = _hash(report)
        return report
    except sqlite3.Error as exc:
        raise EvidenceError('queue watch inspection failed') from exc
    finally:
        conn.close()
