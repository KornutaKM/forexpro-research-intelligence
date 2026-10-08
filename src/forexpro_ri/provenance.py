"""Immutable intake receipts and historical authenticity audit for local Research Memory.

A receipt proves that FRI recorded its *past verification decision*. It is not
an export authorization, fresh key-revocation check, or tamper-proof ledger.
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError

_RECEIPT_FIELDS = (
    'experiment_id', 'entry_sha256', 'verification_status', 'manifest_sha256',
    'attestation_sha256', 'signer_key_id', 'signer_public_key_sha256',
)
_STATES = {'SIGNATURE_VERIFIED', 'UNSIGNED_SYNTHETIC', 'LEGACY_UNATTESTED'}
_CREATE = '''CREATE TABLE IF NOT EXISTS intake_receipts (
    experiment_id TEXT PRIMARY KEY REFERENCES experiments(experiment_id),
    entry_sha256 TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK (verification_status IN (
        'SIGNATURE_VERIFIED', 'UNSIGNED_SYNTHETIC', 'LEGACY_UNATTESTED')),
    manifest_sha256 TEXT,
    attestation_sha256 TEXT,
    signer_key_id TEXT,
    signer_public_key_sha256 TEXT,
    receipt_sha256 TEXT NOT NULL
)'''
_TRIGGERS = [
    "CREATE TRIGGER IF NOT EXISTS intake_receipts_no_update BEFORE UPDATE ON intake_receipts BEGIN SELECT RAISE(ABORT, 'immutable'); END",
    "CREATE TRIGGER IF NOT EXISTS intake_receipts_no_delete BEFORE DELETE ON intake_receipts BEGIN SELECT RAISE(ABORT, 'immutable'); END",
]


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def make_receipt(
    experiment_id: str,
    entry_sha256: str,
    verification: dict[str, Any] | None = None,
    *,
    legacy: bool = False,
) -> dict[str, Any]:
    if legacy:
        status = 'LEGACY_UNATTESTED'
    elif verification is None:
        status = 'UNSIGNED_SYNTHETIC'
    else:
        if verification['status'] != 'SIGNATURE_VERIFIED' or verification['experiment_id'] != experiment_id:
            raise EvidenceError('signed receipt identity or status mismatch')
        status = 'SIGNATURE_VERIFIED'
    receipt = {
        'experiment_id': experiment_id,
        'entry_sha256': entry_sha256,
        'verification_status': status,
        'manifest_sha256': verification['manifest_sha256'] if status == 'SIGNATURE_VERIFIED' else None,
        'attestation_sha256': verification['attestation_sha256'] if status == 'SIGNATURE_VERIFIED' else None,
        'signer_key_id': verification['signer_key_id'] if status == 'SIGNATURE_VERIFIED' else None,
        'signer_public_key_sha256': verification['signer_public_key_sha256'] if status == 'SIGNATURE_VERIFIED' else None,
    }
    receipt['receipt_sha256'] = _digest(receipt)
    return receipt


def install_receipts(conn: sqlite3.Connection, *, migrate_existing: bool) -> None:
    """Single-transaction v1 migration. Historical imports are NEVER called signed."""
    try:
        conn.execute('BEGIN IMMEDIATE')
        if migrate_existing:
            # The old rows are checked *before* conversion by the caller.
            conn.execute(_CREATE)
            for row in conn.execute('SELECT experiment_id, entry_sha256 FROM experiments ORDER BY experiment_id'):
                r = make_receipt(row['experiment_id'], row['entry_sha256'], legacy=True)
                conn.execute('INSERT INTO intake_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?)', tuple(r.values()))
        else:
            conn.execute(_CREATE)
        for trig in _TRIGGERS:
            conn.execute(trig)
        conn.execute('PRAGMA user_version=2')
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def read_receipt(conn: sqlite3.Connection, experiment_id: str, entry_sha256: str) -> dict[str, Any]:
    row = conn.execute('SELECT * FROM intake_receipts WHERE experiment_id=?', (experiment_id,)).fetchone()
    if row is None:
        raise EvidenceError(f'missing intake receipt: {experiment_id}')
    receipt = dict(row)
    if receipt['verification_status'] not in _STATES:
        raise EvidenceError(f'invalid intake receipt status: {experiment_id}')
    if receipt['entry_sha256'] != entry_sha256 or receipt['receipt_sha256'] != _digest({k: receipt[k] for k in _RECEIPT_FIELDS}):
        raise EvidenceError(f'intake receipt integrity mismatch: {experiment_id}')
    signed = receipt['verification_status'] == 'SIGNATURE_VERIFIED'
    other = ('manifest_sha256', 'attestation_sha256', 'signer_key_id', 'signer_public_key_sha256')
    if signed:
        if any(not isinstance(receipt[k], str) or not receipt[k] for k in other):
            raise EvidenceError(f'incomplete signed intake receipt: {experiment_id}')
        if any(len(receipt[k]) != 64 or any(c not in '0123456789abcdef' for c in receipt[k]) for k in ('manifest_sha256', 'attestation_sha256', 'signer_public_key_sha256')):
            raise EvidenceError(f'invalid signed intake digest: {experiment_id}')
    elif any(receipt[k] is not None for k in other):
        raise EvidenceError(f'unverified receipt claims signer data: {experiment_id}')
    return receipt


def audit(db_path: str | Path) -> dict[str, Any]:
    """One-snapshot readiness summary, with explicit non-authoritative limits."""
    from .memory import _connect, _load

    conn = _connect(db_path, creating=False)
    try:
        conn.execute('BEGIN')
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise EvidenceError('SQLite integrity check failed')
        if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise EvidenceError('SQLite foreign key check failed')
        ids = [r['experiment_id'] for r in conn.execute('SELECT experiment_id FROM experiments ORDER BY experiment_id')]
        if len(ids) > 5000:
            raise EvidenceError('too many experiments for bounded provenance audit')
        entries = {eid: _load(conn, eid) for eid in ids}
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        receipts = [read_receipt(conn, eid, entries[eid]['entry_sha256']) for eid in ids] if version == 2 else [
            make_receipt(eid, entries[eid]['entry_sha256'], legacy=True) for eid in ids
        ]
        statuses = Counter(r['verification_status'] for r in receipts)
        signed = statuses['SIGNATURE_VERIFIED']
        unsigned = statuses['UNSIGNED_SYNTHETIC']
        legacy = statuses['LEGACY_UNATTESTED']
        # Empty DB is not evidence-ready. An integrity check alone is not admission.
        ready = bool(ids) and signed == len(ids) and version == 2
        public = [{k: r[k] for k in ('experiment_id', 'verification_status', 'entry_sha256',
                                     'receipt_sha256', 'signer_key_id', 'attestation_sha256')} for r in receipts]
        report = {
            'schema_version': version,
            'report_kind': 'NON_AUTHORITATIVE_PROVENANCE_AUDIT',
            'intake_evidence_status': 'ALL_SIGNED_AT_IMPORT' if ready else 'NOT_ALL_SIGNED_AT_IMPORT',
            'all_intakes_have_signed_receipts': ready,
            'experiment_count': len(ids),
            'counts': {'signature_verified': signed, 'unsigned_synthetic': unsigned, 'legacy_unattested': legacy},
            'receipts': public,
            'authority': {'scientific': False, 'promotion': False, 'holdout': False, 'broker': False},
            'limitations': [
                'Signatures were verified on import against the then-configured trust store; this audit does not reverify signatures or check current revocation.',
                'No signature, signing key, raw evidence or exporter authorization is retained in Research Memory.',
                'SQLite hashes and triggers detect ordinary inconsistencies, not a privileged attacker who rewrites the entire database or report.',
                'Signed at import does not imply scientific validity, complete evidence or owner-approved export.',
            ],
        }
        report['report_sha256'] = _digest(report)
        return report
    except sqlite3.Error as exc:
        raise EvidenceError(f'cannot audit Research Memory: {exc}') from exc
    finally:
        conn.close()
