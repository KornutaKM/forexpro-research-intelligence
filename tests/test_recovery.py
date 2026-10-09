"""Offline recovery / disaster rehearsal against synthetic evidence only."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import history, ingest, verify
from forexpro_ri.provenance import audit
from forexpro_ri.recovery import backup, drill, restore_backup, verify_backup


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'live.sqlite'
        self.back = self.root / 'snapshot'
        self.restored = self.root / 'restored.sqlite'
        self.fixture = Path(__file__).resolve().parents[1] / 'examples/closed_synthetic'
        ingest(self.fixture, self.db, allow_unsigned_synthetic=True)

    def _backup(self):
        return backup(self.db, self.back)

    def test_backup_verify_restore_preserve_history_and_receipts(self):
        result = self._backup()
        self.assertEqual(result['status'], 'BACKUP_CREATED')
        self.assertEqual(result['authority'], 'NONE')
        self.assertEqual(verify_backup(self.back)['status'], 'BACKUP_VERIFIED')
        self.assertEqual(restore_backup(self.back, self.restored)['status'], 'RESTORED_TO_NEW_DATABASE')
        self.assertEqual(history(self.db), history(self.restored))
        self.assertEqual(audit(self.db)['report_sha256'], audit(self.restored)['report_sha256'])
        self.assertEqual(verify(self.restored)['experiment_count'], 1)
        self.assertEqual(oct(self.restored.stat().st_mode & 0o777), '0o600')
        self.assertEqual(oct(self.back.stat().st_mode & 0o777), '0o700')

    def test_restore_rejects_existing_database_without_modification(self):
        self._backup()
        with self.assertRaisesRegex(EvidenceError, 'already exists'):
            restore_backup(self.back, self.db)
        self.assertEqual(verify(self.db)['experiment_count'], 1)

    def test_restore_rejects_existing_empty_file(self):
        self._backup()
        self.restored.touch()
        with self.assertRaisesRegex(EvidenceError, 'already exists'):
            restore_backup(self.back, self.restored)
        self.assertEqual(self.restored.read_bytes(), b'')

    def test_backup_refuses_existing_destination(self):
        self._backup()
        with self.assertRaisesRegex(EvidenceError, 'already exists'):
            self._backup()

    def test_backup_refuses_missing_db(self):
        with self.assertRaises(EvidenceError):
            backup(self.root / 'missing.sqlite', self.back)
        self.assertFalse(self.back.exists())

    def test_backup_refuses_symlink_database(self):
        alias = self.root / 'alias.sqlite'
        alias.symlink_to(self.db)
        with self.assertRaises(EvidenceError):
            backup(alias, self.back)

    def test_backup_refuses_parent_symlink(self):
        alias = self.root / 'aliasdir'
        alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(EvidenceError):
            backup(self.db, alias / 'saved')

    def test_backup_refuses_output_with_missing_parent(self):
        with self.assertRaises(EvidenceError):
            backup(self.db, self.root / 'missing' / 'snap')

    def test_backup_refuses_output_in_existing_db_path(self):
        with self.assertRaises(EvidenceError):
            backup(self.db, self.db)

    def test_manifest_declares_no_cryptographic_authentication(self):
        self._backup()
        manifest = json.loads((self.back/'manifest.json').read_text())
        self.assertIn('Local SHA-256 integrity only', manifest['limitations'])
        self.assertFalse(any(manifest['authority'].values()))
        self.assertEqual(manifest['provenance_counts']['unsigned_synthetic'], 1)
        self.assertEqual(verify_backup(self.back)['authentication'], 'NOT_PROVIDED')

    def test_rejects_tampered_sqlite_bytes(self):
        self._backup()
        with (self.back/'memory.sqlite').open('ab') as f:
            f.write(b'malicious-suffix')
        with self.assertRaises(EvidenceError):
            verify_backup(self.back)
        self.assertFalse(self.restored.exists())

    def test_rejects_tampered_manifest_sha(self):
        self._backup()
        p = self.back/'manifest.json'
        m = json.loads(p.read_text())
        m['database_sha256'] = '0' * 64
        p.write_text(json.dumps(m))
        with self.assertRaisesRegex(EvidenceError, 'does not match'):
            restore_backup(self.back, self.restored)
        self.assertFalse(self.restored.exists())

    def test_rejects_tampered_manifest_counts(self):
        self._backup()
        p = self.back/'manifest.json'
        m = json.loads(p.read_text())
        m['provenance_counts']['signature_verified'] = 1000
        p.write_text(json.dumps(m))
        with self.assertRaises(EvidenceError):
            verify_backup(self.back)

    def test_rejects_manifest_extra_fields(self):
        self._backup()
        p = self.back/'manifest.json'
        m = json.loads(p.read_text())
        m['exfiltration_url'] = 'https://invalid.local'
        p.write_text(json.dumps(m))
        with self.assertRaises(EvidenceError):
            verify_backup(self.back)

    def test_rejects_duplicate_manifest_keys(self):
        self._backup()
        m = (self.back/'manifest.json').read_text()
        (self.back/'manifest.json').write_text(m.replace('"format":', '"format":"X", "format":'))
        with self.assertRaisesRegex(EvidenceError, 'duplicate recovery manifest key'):
            verify_backup(self.back)

    def test_rejects_extra_files_and_missing_files(self):
        self._backup()
        junk = self.back/'unexpected'
        junk.write_text('x')
        with self.assertRaisesRegex(EvidenceError, 'exactly'):
            verify_backup(self.back)
        junk.unlink()
        (self.back/'manifest.json').unlink()
        with self.assertRaises(EvidenceError):
            verify_backup(self.back)

    def test_rejects_symlinked_backup_file(self):
        self._backup()
        orig = self.back/'memory.sqlite'
        other = self.root/'copy.sqlite'
        other.write_bytes(orig.read_bytes())
        orig.unlink()
        orig.symlink_to(other)
        with self.assertRaises(EvidenceError):
            verify_backup(self.back)

    def test_rejects_symlinked_manifest(self):
        self._backup()
        orig = self.back/'manifest.json'
        other = self.root/'meta.json'
        other.write_bytes(orig.read_bytes())
        orig.unlink()
        orig.symlink_to(other)
        with self.assertRaises(EvidenceError):
            verify_backup(self.back)

    def test_rejects_symlinked_backup_directory(self):
        self._backup()
        alias = self.root/'alias'
        alias.symlink_to(self.back, target_is_directory=True)
        with self.assertRaises(EvidenceError):
            verify_backup(alias)

    def test_rejects_restore_inside_backup(self):
        self._backup()
        with self.assertRaises(EvidenceError):
            restore_backup(self.back, self.back/'other.sqlite')

    def test_backup_does_not_capture_uncommitted_writes(self):
        # A live writer transaction must not leak its uncommitted records.
        with sqlite3.connect(self.db) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
        writer = sqlite3.connect(self.db, timeout=1)
        try:
            writer.execute('BEGIN IMMEDIATE')
            writer.execute("CREATE TABLE unrelated_uncommitted (secret TEXT)")
            writer.execute("INSERT INTO unrelated_uncommitted VALUES ('UNCOMMITTED')")
            self._backup()
        finally:
            writer.rollback()
            writer.close()
        restore_backup(self.back, self.restored)
        with sqlite3.connect(self.restored) as conn:
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='unrelated_uncommitted'").fetchone())

    def test_backup_wal_contains_committed_updates(self):
        with sqlite3.connect(self.db) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
        # WAL committed bytes may be absent from the main database file.
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE wal_probe (value TEXT)')
            conn.execute("INSERT INTO wal_probe VALUES ('committed')")
        self._backup()
        restore_backup(self.back, self.restored)
        with sqlite3.connect(self.restored) as conn:
            self.assertEqual(conn.execute('SELECT value FROM wal_probe').fetchone()[0], 'committed')

    def test_drill_is_disposable_and_history_unchanged(self):
        original = hashlib.sha256(self.db.read_bytes()).hexdigest()
        result = drill(self.db)
        self.assertEqual(result['status'], 'RECOVERY_DRILL_PASS')
        self.assertTrue(result['source_database_untouched'])
        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), original)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['live.sqlite'])

    def test_cli_lifecycle_and_failure_code(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['recovery', 'backup', '--db', str(self.db), '--out', str(self.back)]), 0)
            self.assertEqual(main(['recovery', 'verify', '--dir', str(self.back)]), 0)
            self.assertEqual(main(['recovery', 'restore', '--dir', str(self.back), '--db', str(self.restored)]), 0)
            self.assertEqual(main(['recovery', 'drill', '--db', str(self.restored)]), 0)
            self.assertEqual(main(['recovery', 'restore', '--dir', str(self.back), '--db', str(self.restored)]), 2)

    def test_source_corruption_refuses_backup(self):
        # Bypass immutable triggers to simulate malicious corruption on disk.
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TRIGGER experiments_no_update')
            conn.execute("UPDATE experiments SET summary_sha256=?", ('0'*64,))
        with self.assertRaises(EvidenceError):
            self._backup()
        self.assertFalse(self.back.exists())

    def test_restore_keeps_unsigned_history_unsigned(self):
        self._backup()
        restore_backup(self.back, self.restored)
        result = audit(self.restored)
        self.assertEqual(result['counts']['unsigned_synthetic'], 1)
        self.assertFalse(result['all_intakes_have_signed_receipts'])

    def test_empty_schema2_db_backup_is_not_evidence_readiness(self):
        empty = self.root/'empty.sqlite'
        from forexpro_ri.memory import _connect
        _connect(empty, creating=True).close()
        b = backup(empty, self.back)
        self.assertEqual(b['experiment_count'], 0)
        restore_backup(self.back, self.restored)
        self.assertEqual(verify(self.restored)['experiment_count'], 0)
        self.assertFalse(audit(self.restored)['all_intakes_have_signed_receipts'])


if __name__ == '__main__':
    unittest.main()
