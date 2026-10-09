"""Offline Research Memory snapshot, disaster recovery, and rehearsal.

Backups preserve only what Research Memory already stores: IDs, digests,
verdicts and historical intake receipts. They are confidential operational
artifacts, NOT signed exports, scientific approvals, or tamper-proof archives.
"""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from .contracts import EvidenceError
from .memory import _ensure_location, verify as verify_memory
from .provenance import audit

_FORMAT = 'FRI_RESEARCH_MEMORY_SNAPSHOT'
_VERSION = 1
_SQLITE_FILE = 'memory.sqlite'
_MANIFEST_FILE = 'manifest.json'
_MAX_MANIFEST_BYTES = 16384
_MAX_SNAPSHOT_BYTES = 1024 * 1024 * 1024  # 1 GiB bounded offline snapshots


def _real_parent(path: Path) -> None:
    if (path.is_symlink() or not path.parent.is_dir()
            or any(p.is_symlink() for p in (path.parent, *path.parent.parents))):
        raise EvidenceError('destination and its parent must be real, without symbolic links')
    if path.exists():
        raise EvidenceError('destination already exists; overwrite is forbidden')


def _digest_file(path: Path) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError('snapshot is missing or a symbolic link')
    size = path.stat().st_size
    if size < 1 or size > _MAX_SNAPSHOT_BYTES:
        raise EvidenceError('snapshot file size is outside permitted limits')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest(), size


def _summary(db_path: Path) -> dict[str, Any]:
    integrity = verify_memory(db_path)
    if integrity['schema_version'] != 2:
        raise EvidenceError('recovery snapshots require Research Memory schema v2; migrate explicitly first')
    provenance = audit(db_path)
    if provenance['experiment_count'] != integrity['experiment_count']:
        raise EvidenceError('inconsistent snapshot experiment counts')
    return {
        'memory_schema_version': integrity['schema_version'],
        'experiment_count': integrity['experiment_count'],
        'provenance_counts': provenance['counts'],
        'provenance_report_sha256': provenance['report_sha256'],
    }


def _manifest(db_path: Path) -> dict[str, Any]:
    digest, size = _digest_file(db_path)
    return {
        'format': _FORMAT, 'format_version': _VERSION,
        'database_file': _SQLITE_FILE, 'database_sha256': digest,
        'database_bytes': size,
        **_summary(db_path),
        'authority': {'scientific': False, 'holdout': False, 'promotion': False, 'broker': False},
        'limitations': 'Local SHA-256 integrity only; no cryptographic authenticity or proof of export authorization.',
    }


def _strict_json(raw: bytes) -> dict[str, Any]:
    if len(raw) > _MAX_MANIFEST_BYTES:
        raise EvidenceError('recovery manifest exceeds size limit')
    def pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for k, v in pairs:
            if k in obj:
                raise EvidenceError('duplicate recovery manifest key')
            obj[k] = v
        return obj
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs_no_duplicates)
    except EvidenceError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise EvidenceError('invalid recovery manifest JSON') from exc
    if not isinstance(value, dict):
        raise EvidenceError('recovery manifest must be an object')
    return value


def verify_backup(directory: str | Path) -> dict[str, Any]:
    """Verify bounded snapshot bytes and all semantic/receipt invariants."""
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError('backup must be a real directory')
    if {p.name for p in root.iterdir()} != {_SQLITE_FILE, _MANIFEST_FILE}:
        raise EvidenceError('backup must contain exactly memory.sqlite and manifest.json')
    db = root / _SQLITE_FILE
    metadata = root / _MANIFEST_FILE
    if metadata.is_symlink() or not metadata.is_file():
        raise EvidenceError('invalid recovery manifest file')
    declared = _strict_json(metadata.read_bytes())
    actual = _manifest(db)
    if declared != actual:
        raise EvidenceError('backup manifest does not match recovered database or provenance')
    return {
        'status': 'BACKUP_VERIFIED',
        'database_sha256': actual['database_sha256'],
        'experiment_count': actual['experiment_count'],
        'provenance_counts': actual['provenance_counts'],
        'authority': 'NONE',
        'authentication': 'NOT_PROVIDED',
    }


def backup(db_path: str | Path, destination: str | Path) -> dict[str, Any]:
    """Create a non-overwriting online SQLite snapshot, even with a live WAL."""
    source = _ensure_location(Path(db_path), creating=False)
    target = Path(destination)
    _real_parent(target)
    if target.resolve() == source or source.is_relative_to(target.resolve()):
        raise EvidenceError('backup cannot contain the source database')
    staging = Path(tempfile.mkdtemp(prefix='.fri-backup-', dir=target.parent))
    staging.chmod(0o700)
    try:
        # SQLite online backup produces one consistent committed snapshot,
        # unlike a file copy that can omit uncheckpointed WAL pages.
        source_conn = sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True, timeout=5)
        try:
            with closing(sqlite3.connect(staging / _SQLITE_FILE)) as target_conn:
                source_conn.backup(target_conn, pages=128, sleep=0.05)
        finally:
            source_conn.close()
        # Backed-up DBs can retain the source's WAL journal_mode. Normalize
        # our isolated copy to DELETE before hashing/packaging it, otherwise
        # readers may create transient -shm/-wal companions.
        with closing(sqlite3.connect(staging / _SQLITE_FILE)) as normalized:
            normalized.execute('PRAGMA journal_mode=DELETE')
        (staging / _SQLITE_FILE).chmod(0o600)
        manifest = _manifest(staging / _SQLITE_FILE)
        with (staging / _MANIFEST_FILE).open('x', encoding='utf-8') as stream:
            json.dump(manifest, stream, sort_keys=True, ensure_ascii=True, indent=2)
            stream.write('\n')
        (staging / _MANIFEST_FILE).chmod(0o600)
        result = verify_backup(staging)
        # A concurrent external process can still race rename; reject on best
        # effort here, but do not claim atomic no-clobber on all filesystems.
        if target.exists() or target.is_symlink():
            raise EvidenceError('backup destination appeared during creation')
        staging.rename(target)
        return {'status': 'BACKUP_CREATED', **{k: v for k, v in result.items() if k != 'status'},
                'location': str(target)}
    except (sqlite3.Error, OSError) as exc:
        raise EvidenceError(f'backup failed: {exc}') from exc
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def restore_backup(directory: str | Path, destination: str | Path) -> dict[str, Any]:
    """Restore to a *new* DB only; never overwrite an operational database."""
    source = Path(directory)
    verified = verify_backup(source)
    target = Path(destination)
    _real_parent(target)
    if target.resolve().is_relative_to(source.resolve()):
        raise EvidenceError('restored database cannot be placed inside backup')
    fd, temporary_name = tempfile.mkstemp(prefix='.fri-restore-', suffix='.sqlite', dir=target.parent)
    temp = Path(temporary_name)
    try:
        with os.fdopen(fd, 'wb') as writer, (source / _SQLITE_FILE).open('rb') as reader:
            shutil.copyfileobj(reader, writer, length=1024 * 1024)
            writer.flush()
            os.fsync(writer.fileno())
        temp.chmod(0o600)
        if _manifest(temp) != _strict_json((source / _MANIFEST_FILE).read_bytes()):
            raise EvidenceError('restored database failed post-copy provenance check')
        try:
            # Exclusive hard-link creation prevents overwriting a target that
            # appeared between checks (unlike ordinary rename/replace).
            os.link(temp, target, follow_symlinks=False)
        except FileExistsError as exc:
            raise EvidenceError('restore destination already exists') from exc
        return {'status': 'RESTORED_TO_NEW_DATABASE', 'location': str(target),
                'database_sha256': verified['database_sha256'],
                'experiment_count': verified['experiment_count'],
                'authentication': 'NOT_PROVIDED', 'authority': 'NONE'}
    except (OSError, sqlite3.Error) as exc:
        raise EvidenceError(f'restore failed: {exc}') from exc
    finally:
        temp.unlink(missing_ok=True)


def drill(db_path: str | Path) -> dict[str, Any]:
    """Disposable full recovery rehearsal, never writing over the live DB."""
    source = _ensure_location(Path(db_path), creating=False)
    with tempfile.TemporaryDirectory(prefix='.fri-recovery-drill-', dir=source.parent) as folder:
        directory = Path(folder)
        b = backup(source, directory / 'snapshot')
        v = verify_backup(directory / 'snapshot')
        r = restore_backup(directory / 'snapshot', directory / 'restored.sqlite')
        restored = _summary(directory / 'restored.sqlite')
        original_manifest = _strict_json((directory / 'snapshot' / _MANIFEST_FILE).read_bytes())
        if restored != {k: original_manifest[k] for k in restored}:
            raise EvidenceError('restored snapshot has inconsistent historical provenance')
        return {'status': 'RECOVERY_DRILL_PASS', 'backup': b['database_sha256'],
                'restored': r['database_sha256'], 'experiments': v['experiment_count'],
                'provenance_counts': v['provenance_counts'], 'source_database_untouched': True,
                'authority': 'NONE', 'authentication': 'NOT_PROVIDED'}
