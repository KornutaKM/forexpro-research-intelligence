"""Synthetic-only tests of FRI Research Memory invariants."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import history, ingest, patterns, verify


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        self.db = self.root / 'memory.sqlite'
        self.summary = {
            'experiment_id': 'SYNTHETIC-X',
            'disposition': 'CLOSED_UNSUCCESSFUL',
            'criteria': [
                {'criterion_id': 'c1', 'procedure': 'COST_STRESS', 'verdict': 'FAIL', 'observation': 'sensitive-but-synthetic-text'},
                {'criterion_id': 'c2', 'procedure': 'COST_STRESS', 'verdict': 'FAIL', 'observation': 'another synthetic text'},
                {'criterion_id': 'c3', 'procedure': 'MONTE_CARLO', 'verdict': 'PASS', 'observation': 'synthetic pass'},
            ],
            'not_evaluable': [{'procedure': 'REGIME_STABILITY', 'reason': 'synthetic-not-evaluable'}],
        }
        self.manifest = {
            'schema_version': 1, 'export_kind': 'CLOSED_EXPERIMENT_SUMMARY', 'source_system': 'forexpro',
            'experiment_id': self.summary['experiment_id'], 'source_revision': 'a' * 40,
            'summary_sha256': '', 'approved_scope': 'READ_ONLY_ADVISORY',
            'holdout_access': False, 'promotion_authority': False, 'broker_authority': False,
        }
        self.write()

    def write(self):
        raw = (json.dumps(self.summary, sort_keys=True) + '\n').encode()
        self.manifest['summary_sha256'] = hashlib.sha256(raw).hexdigest()
        (self.bundle / 'summary.json').write_bytes(raw)
        (self.bundle / 'manifest.json').write_text(json.dumps(self.manifest), encoding='utf-8')

    def test_ingest_creates_private_db_and_verifies(self):
        x = ingest(self.bundle, self.db)
        self.assertEqual(x['status'], 'IMPORTED')
        self.assertEqual(verify(self.db)['experiment_count'], 1)
        self.assertEqual(self.db.stat().st_mode & 0o777, 0o600)
        self.assertEqual(len(history(self.db)), 1)

    def test_idempotent_reimport(self):
        a = ingest(self.bundle, self.db)
        b = ingest(self.bundle, self.db)
        self.assertEqual(b['status'], 'ALREADY_PRESENT')
        self.assertEqual(a['entry_sha256'], b['entry_sha256'])
        self.assertEqual(len(history(self.db)), 1)

    def test_changed_same_identity_rejected(self):
        ingest(self.bundle, self.db)
        self.summary['criteria'][0]['observation'] = 'different'
        self.write()
        with self.assertRaisesRegex(EvidenceError, 'conflicting immutable export'):
            ingest(self.bundle, self.db)
        self.assertEqual(verify(self.db)['experiment_count'], 1)

    def test_memory_does_not_store_raw_observations(self):
        ingest(self.bundle, self.db)
        data = self.db.read_bytes()
        self.assertNotIn(b'sensitive-but-synthetic-text', data)
        self.assertNotIn(b'synthetic-not-evaluable', data)

    def test_patterns_count_experiments_not_criteria(self):
        ingest(self.bundle, self.db)
        self.assertEqual(patterns(self.db), [
            {'procedure': 'COST_STRESS', 'failed_experiments': 1, 'not_evaluable_experiments': 0},
            {'procedure': 'REGIME_STABILITY', 'failed_experiments': 0, 'not_evaluable_experiments': 1},
        ])
        self.summary['experiment_id'] = 'SYNTHETIC-Y'
        self.manifest['experiment_id'] = 'SYNTHETIC-Y'
        self.write()
        ingest(self.bundle, self.db)
        self.assertEqual(patterns(self.db)[0]['failed_experiments'], 2)
        self.assertEqual(verify(self.db)['experiment_count'], 2)

    def test_import_order_does_not_change_entry_identity(self):
        result = ingest(self.bundle, self.db)
        self.summary['criteria'].reverse()
        self.write()
        with self.assertRaisesRegex(EvidenceError, 'conflicting'):
            ingest(self.bundle, self.db)
        self.assertEqual(history(self.db)[0]['entry_sha256'], result['entry_sha256'])

    def test_cli_ingest_history_patterns_verify(self):
        self.assertEqual(main(['memory', 'ingest', str(self.bundle), '--db', str(self.db)]), 0)
        self.assertEqual(main(['memory', 'history', '--db', str(self.db)]), 0)
        self.assertEqual(main(['memory', 'patterns', '--db', str(self.db)]), 0)
        self.assertEqual(main(['memory', 'verify', '--db', str(self.db)]), 0)

    def test_conflicting_evaluability_rejected(self):
        self.summary['not_evaluable'].append({'procedure': 'COST_STRESS', 'reason': 'contradiction'})
        self.write()
        with self.assertRaisesRegex(EvidenceError, 'same procedure'):
            ingest(self.bundle, self.db)

    def test_protected_input_rejected_and_no_database_created(self):
        self.manifest['holdout_access'] = True
        self.write()
        with self.assertRaises(EvidenceError):
            ingest(self.bundle, self.db)
        self.assertFalse(self.db.exists())

    def test_database_must_not_live_inside_bundle(self):
        with self.assertRaisesRegex(EvidenceError, 'inside input bundle'):
            ingest(self.bundle, self.bundle / 'private.sqlite')

    def test_database_symlink_rejected(self):
        self.db.symlink_to(self.root / 'other.sqlite')
        with self.assertRaisesRegex(EvidenceError, 'symlink'):
            ingest(self.bundle, self.db)

    def test_read_without_existing_memory_rejected(self):
        with self.assertRaisesRegex(EvidenceError, 'missing'):
            history(self.db)
        self.assertFalse(self.db.exists())

    def test_immutable_triggers_block_updates_and_deletes(self):
        ingest(self.bundle, self.db)
        with sqlite3.connect(self.db) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE experiments SET fail_count=0")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("DELETE FROM experiments")
        self.assertEqual(verify(self.db)['status'], 'OK')

    def test_tampering_after_trigger_drop_is_detected(self):
        ingest(self.bundle, self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TRIGGER experiments_no_update')
            conn.execute('UPDATE experiments SET fail_count=23')
        with self.assertRaisesRegex(EvidenceError, 'integrity mismatch'):
            verify(self.db)

    def test_orphan_row_detected(self):
        ingest(self.bundle, self.db)
        with sqlite3.connect(self.db) as conn:
            conn.execute('PRAGMA foreign_keys=OFF')
            conn.execute("INSERT INTO criteria VALUES ('ORPHAN','x','COST_STRESS','FAIL','z')")
        with self.assertRaisesRegex(EvidenceError, 'foreign key'):
            verify(self.db)

    def test_sqlite_malformed_db_rejected(self):
        self.db.write_bytes(b'not-a-sqlite-database')
        with self.assertRaises(EvidenceError):
            ingest(self.bundle, self.db)


if __name__ == '__main__':
    unittest.main()
