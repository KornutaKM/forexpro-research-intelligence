"""Local, append-only Research Memory. This store is NOT scientific authority.

Only IDs, hashes, procedure names and verdicts are persisted. The original
free-text observations, report payloads and source bundles are NOT stored.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from .analysis import analyze, canonical_json
from .contracts import EvidenceError
from .importer import import_bundle

_SCHEMA_VERSION = 1

_DDL = """
CREATE TABLE IF NOT EXISTS experiments (
    experiment_id TEXT PRIMARY KEY,
    source_revision TEXT NOT NULL,
    summary_sha256 TEXT NOT NULL,
    report_sha256 TEXT NOT NULL,
    disposition TEXT NOT NULL CHECK (disposition IN ('CLOSED_UNSUCCESSFUL', 'CLOSED_INCOMPLETE')),
    fail_count INTEGER NOT NULL CHECK (fail_count >= 0),
    pass_count INTEGER NOT NULL CHECK (pass_count >= 0),
    not_evaluable_count INTEGER NOT NULL CHECK (not_evaluable_count >= 0),
    entry_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS criteria (
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    criterion_id TEXT NOT NULL,
    procedure TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('PASS', 'FAIL')),
    observation_sha256 TEXT NOT NULL,
    PRIMARY KEY (experiment_id, criterion_id)
);
CREATE TABLE IF NOT EXISTS not_evaluable (
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    procedure TEXT NOT NULL,
    reason_sha256 TEXT NOT NULL,
    PRIMARY KEY (experiment_id, procedure)
);
CREATE TRIGGER IF NOT EXISTS experiments_no_update BEFORE UPDATE ON experiments BEGIN SELECT RAISE(ABORT, 'immutable'); END;
CREATE TRIGGER IF NOT EXISTS experiments_no_delete BEFORE DELETE ON experiments BEGIN SELECT RAISE(ABORT, 'immutable'); END;
CREATE TRIGGER IF NOT EXISTS criteria_no_update BEFORE UPDATE ON criteria BEGIN SELECT RAISE(ABORT, 'immutable'); END;
CREATE TRIGGER IF NOT EXISTS criteria_no_delete BEFORE DELETE ON criteria BEGIN SELECT RAISE(ABORT, 'immutable'); END;
CREATE TRIGGER IF NOT EXISTS not_evaluable_no_update BEFORE UPDATE ON not_evaluable BEGIN SELECT RAISE(ABORT, 'immutable'); END;
CREATE TRIGGER IF NOT EXISTS not_evaluable_no_delete BEFORE DELETE ON not_evaluable BEGIN SELECT RAISE(ABORT, 'immutable'); END;
"""


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _canonical_entry(source: dict[str, Any], criteria: list[dict[str, str]], unevaluable: list[dict[str, str]]) -> dict[str, Any]:
    """No free-text material. Stable across import order, machines and DB paths."""
    return {
        "schema_version": _SCHEMA_VERSION,
        "experiment_id": source["experiment_id"],
        "source_revision": source["source_revision"],
        "summary_sha256": source["summary_sha256"],
        "report_sha256": source["report_sha256"],
        "disposition": source["disposition"],
        "counts": {
            "fail": source["fail_count"],
            "pass": source["pass_count"],
            "not_evaluable": source["not_evaluable_count"],
        },
        "criteria": sorted(criteria, key=lambda item: item["criterion_id"]),
        "not_evaluable": sorted(unevaluable, key=lambda item: item["procedure"]),
    }


def _ensure_location(db: Path, *, creating: bool, bundle: Path | None = None) -> Path:
    if db.is_symlink():
        raise EvidenceError('database path must not be a symlink')
    if not db.parent.is_dir() or db.parent.is_symlink():
        raise EvidenceError('database parent must be an existing, real directory')
    resolved = db.resolve()
    if bundle is not None and resolved.is_relative_to(bundle.resolve()):
        raise EvidenceError('memory database cannot be created inside input bundle')
    if creating and resolved.exists() and not resolved.is_file():
        raise EvidenceError('database path must be a regular file')
    if not creating and not resolved.is_file():
        raise EvidenceError('memory database is missing')
    return resolved


def _connect(db_path: str | Path, *, creating: bool, bundle: Path | None = None) -> sqlite3.Connection:
    target = _ensure_location(Path(db_path), creating=creating, bundle=bundle)
    if creating:
        if not target.exists():
            try:
                with target.open('xb'):
                    pass
                target.chmod(0o600)
            except OSError as exc:
                raise EvidenceError('cannot create local memory database') from exc
    try:
        conn = sqlite3.connect(f'file:{target.as_posix()}?mode={"rw" if creating else "ro"}', uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA busy_timeout=5000')
        if creating:
            conn.execute('PRAGMA synchronous=FULL')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version not in (0, _SCHEMA_VERSION) or (not creating and version != _SCHEMA_VERSION):
            raise EvidenceError('unsupported database schema version')
        if creating and version == 0:
            conn.executescript(_DDL)
            conn.execute(f'PRAGMA user_version={_SCHEMA_VERSION}')
        return conn
    except (sqlite3.Error, EvidenceError) as exc:
        if 'conn' in locals():
            conn.close()
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError(f'cannot open Research Memory: {exc}') from exc


def _load(conn: sqlite3.Connection, experiment_id: str) -> dict[str, Any]:
    row = conn.execute('SELECT * FROM experiments WHERE experiment_id=?', (experiment_id,)).fetchone()
    if row is None:
        raise EvidenceError(f'missing experiment: {experiment_id}')
    source = dict(row)
    criteria = [dict(r) for r in conn.execute('SELECT criterion_id, procedure, verdict, observation_sha256 FROM criteria WHERE experiment_id=? ORDER BY criterion_id', (experiment_id,))]
    unevaluable = [dict(r) for r in conn.execute('SELECT procedure, reason_sha256 FROM not_evaluable WHERE experiment_id=? ORDER BY procedure', (experiment_id,))]
    entry = _canonical_entry(source, criteria, unevaluable)
    actual = _sha(canonical_json(entry))
    if actual != source['entry_sha256']:
        raise EvidenceError(f'memory integrity mismatch for {experiment_id}')
    if source['fail_count'] != sum(c['verdict'] == 'FAIL' for c in criteria) or source['pass_count'] != sum(c['verdict'] == 'PASS' for c in criteria) or source['not_evaluable_count'] != len(unevaluable):
        raise EvidenceError(f'memory count mismatch for {experiment_id}')
    if {c['procedure'] for c in criteria} & {c['procedure'] for c in unevaluable}:
        raise EvidenceError(f'contradictory procedure verdict for {experiment_id}')
    return source


def ingest(bundle_dir: str | Path, db_path: str | Path) -> dict[str, Any]:
    """Atomically save one explicitly exported closed experiment; repeat is a no-op."""
    bundle = Path(bundle_dir)
    manifest, summary = import_bundle(bundle)
    if {c['procedure'] for c in summary['criteria']} & {n['procedure'] for n in summary['not_evaluable']}:
        raise EvidenceError('same procedure cannot be evaluated and not evaluable')
    report = analyze(manifest, summary)
    criteria = [
        {"criterion_id": c['criterion_id'], "procedure": c['procedure'], "verdict": c['verdict'], "observation_sha256": _sha(c['observation'])}
        for c in summary['criteria']
    ]
    unevaluable = [{"procedure": x['procedure'], "reason_sha256": _sha(x['reason'])} for x in summary['not_evaluable']]
    source = {
        'experiment_id': manifest.experiment_id,
        'source_revision': manifest.source_revision,
        'summary_sha256': manifest.summary_sha256,
        'report_sha256': report['report_sha256'],
        'disposition': summary['disposition'],
        'fail_count': report['counts']['fail'],
        'pass_count': report['counts']['pass'],
        'not_evaluable_count': report['counts']['not_evaluable'],
    }
    source['entry_sha256'] = _sha(canonical_json(_canonical_entry(source, criteria, unevaluable)))
    conn = _connect(db_path, creating=True, bundle=bundle)
    try:
        conn.execute('BEGIN IMMEDIATE')
        previous = conn.execute('SELECT entry_sha256 FROM experiments WHERE experiment_id=?', (manifest.experiment_id,)).fetchone()
        if previous is not None:
            if previous['entry_sha256'] != source['entry_sha256']:
                raise EvidenceError('conflicting immutable export for the same experiment_id')
            _load(conn, manifest.experiment_id)
            conn.rollback()
            return {"status": "ALREADY_PRESENT", "experiment_id": manifest.experiment_id, "entry_sha256": source['entry_sha256']}
        conn.execute('INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', tuple(source.values()))
        conn.executemany('INSERT INTO criteria VALUES (?, ?, ?, ?, ?)', [(manifest.experiment_id, c['criterion_id'], c['procedure'], c['verdict'], c['observation_sha256']) for c in criteria])
        conn.executemany('INSERT INTO not_evaluable VALUES (?, ?, ?)', [(manifest.experiment_id, c['procedure'], c['reason_sha256']) for c in unevaluable])
        conn.commit()
        return {"status": "IMPORTED", "experiment_id": manifest.experiment_id, "entry_sha256": source['entry_sha256']}
    except sqlite3.Error as exc:
        conn.rollback()
        raise EvidenceError(f'memory write rejected: {exc}') from exc
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def history(db_path: str | Path) -> list[dict[str, Any]]:
    """Return minimal identity/status metadata, never free-text observations."""
    conn = _connect(db_path, creating=False)
    try:
        return [_load(conn, r['experiment_id']) for r in conn.execute('SELECT experiment_id FROM experiments ORDER BY experiment_id').fetchall()]
    except sqlite3.Error as exc:
        raise EvidenceError(f'cannot read Research Memory: {exc}') from exc
    finally:
        conn.close()


def patterns(db_path: str | Path) -> list[dict[str, Any]]:
    """Count affected experiments, NOT raw criteria, by recorded procedure."""
    conn = _connect(db_path, creating=False)
    try:
        for r in conn.execute('SELECT experiment_id FROM experiments ORDER BY experiment_id').fetchall():
            _load(conn, r['experiment_id'])
        rows = conn.execute('''
            SELECT procedure, SUM(failed) AS failed_experiments, SUM(unavailable) AS not_evaluable_experiments
            FROM (
                SELECT procedure, experiment_id, 1 AS failed, 0 AS unavailable FROM criteria WHERE verdict='FAIL' GROUP BY procedure, experiment_id
                UNION ALL
                SELECT procedure, experiment_id, 0 AS failed, 1 AS unavailable FROM not_evaluable
            ) GROUP BY procedure ORDER BY procedure
        ''').fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as exc:
        raise EvidenceError(f'cannot aggregate Research Memory: {exc}') from exc
    finally:
        conn.close()


def verify(db_path: str | Path) -> dict[str, Any]:
    conn = _connect(db_path, creating=False)
    try:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise EvidenceError('SQLite integrity check failed')
        if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise EvidenceError('SQLite foreign key check failed')
        experiments = conn.execute('SELECT experiment_id FROM experiments ORDER BY experiment_id').fetchall()
        for row in experiments:
            _load(conn, row['experiment_id'])
        return {'status': 'OK', 'schema_version': _SCHEMA_VERSION, 'experiment_count': len(experiments), 'authority': 'NONE', 'export_authenticity': 'NOT_VERIFIED'}
    except sqlite3.Error as exc:
        raise EvidenceError(f'memory verification failed: {exc}') from exc
    finally:
        conn.close()
