"""End-to-end offline operations and fail-closed atomicity tests (synthetic only)."""
from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from forexpro_ri.attestation import _message
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import history, ingest
from forexpro_ri.operations import ingest_batch, readiness, run, verify_report_dir


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'history.sqlite'
        self.out = self.root / 'out'
        self.private = Ed25519PrivateKey.generate()
        public = self.private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        self.trust = self.root / 'trust.json'
        self.trust.write_text(json.dumps({'schema_version': 1, 'keys': [{
            'key_id': 'ephemeral-test-key', 'algorithm': 'Ed25519',
            'source_system': 'forexpro', 'purpose': 'CLOSED_EXPERIMENT_SUMMARY',
            'status': 'ACTIVE', 'public_key_b64': base64.b64encode(public).decode('ascii'),
        }]}), encoding='utf-8')
        self.a = self.fixture('SYNTHETIC-OPS-A', 'OUT_OF_SAMPLE')
        self.b = self.fixture('SYNTHETIC-OPS-B', 'COST_STRESS')

    def fixture(self, eid: str, proc: str, *, signed: bool = True, seed: str = 'failure') -> Path:
        path = self.root / eid
        path.mkdir()
        summary = {
            'experiment_id': eid, 'disposition': 'CLOSED_UNSUCCESSFUL',
            'criteria': [{'criterion_id': 'crit', 'procedure': proc, 'verdict': 'FAIL',
                          'observation': f'SYNTHETIC: {seed}'}],
            'not_evaluable': [{'procedure': 'REGIME_STABILITY', 'reason': 'SYNTHETIC: no warmup'}],
        }
        summary_bytes = (json.dumps(summary, sort_keys=True) + '\n').encode('utf-8')
        manifest = {
            'schema_version': 1, 'export_kind': 'CLOSED_EXPERIMENT_SUMMARY',
            'source_system': 'forexpro', 'experiment_id': eid,
            'source_revision': 'a' * 40, 'summary_sha256': hashlib.sha256(summary_bytes).hexdigest(),
            'approved_scope': 'READ_ONLY_ADVISORY', 'holdout_access': False,
            'promotion_authority': False, 'broker_authority': False,
        }
        manifest_bytes = (json.dumps(manifest, sort_keys=True) + '\n').encode('utf-8')
        (path / 'manifest.json').write_bytes(manifest_bytes)
        (path / 'summary.json').write_bytes(summary_bytes)
        if signed:
            claim = {
                'schema_version': 1, 'algorithm': 'Ed25519', 'key_id': 'ephemeral-test-key',
                'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
                'summary_sha256': hashlib.sha256(summary_bytes).hexdigest(),
            }
            attestation = {**claim, 'signature_b64': base64.b64encode(self.private.sign(_message(claim))).decode('ascii')}
            (path / 'attestation.json').write_text(json.dumps(attestation), encoding='utf-8')
        return path

    def test_signed_batch_is_atomic_and_auditable(self):
        result = ingest_batch([self.b, self.a], self.db, trust_store=self.trust)
        self.assertEqual(result['imported_count'], 2)
        self.assertEqual([x['experiment_id'] for x in result['items']], ['SYNTHETIC-OPS-A', 'SYNTHETIC-OPS-B'])
        self.assertEqual([x['verification_status'] for x in result['items']], ['SIGNATURE_VERIFIED'] * 2)
        self.assertEqual(readiness(self.db)['status'], 'LOCAL_INTAKE_READY')
        self.assertEqual(len(history(self.db)), 2)

    def test_signed_idempotent_repeat_deterministic(self):
        first = ingest_batch([self.a, self.b], self.db, trust_store=self.trust)
        second = ingest_batch([self.b, self.a], self.db, trust_store=self.trust)
        self.assertEqual(second['already_present_count'], 2)
        self.assertEqual(first['items'][0]['entry_sha256'], second['items'][0]['entry_sha256'])
        self.assertEqual(first['items'][0]['receipt_sha256'], second['items'][0]['receipt_sha256'])

    def test_invalid_bundle_fails_before_any_db_creation(self):
        (self.b / 'summary.json').write_text('{}')
        with self.assertRaises(EvidenceError):
            ingest_batch([self.a, self.b], self.db, trust_store=self.trust)
        self.assertFalse(self.db.exists())

    def test_rollback_on_existing_immutable_identity_conflict(self):
        ingest_batch([self.b], self.db, trust_store=self.trust)
        changed = self.root / 'conflict'
        changed.mkdir()
        for name in ('manifest.json', 'summary.json', 'attestation.json'):
            (changed / name).write_bytes((self.b / name).read_bytes())
        # Mutate content while keeping signature valid by re-signing as synthetic test key.
        summary = json.loads((changed / 'summary.json').read_text())
        summary['criteria'][0]['observation'] = 'SYNTHETIC: mutated failure'
        raw = (json.dumps(summary, sort_keys=True) + '\n').encode()
        manifest = json.loads((changed / 'manifest.json').read_text())
        manifest['summary_sha256'] = hashlib.sha256(raw).hexdigest()
        m_raw = (json.dumps(manifest, sort_keys=True) + '\n').encode()
        claim = {'schema_version': 1, 'algorithm': 'Ed25519', 'key_id': 'ephemeral-test-key',
                 'manifest_sha256': hashlib.sha256(m_raw).hexdigest(),
                 'summary_sha256': hashlib.sha256(raw).hexdigest()}
        sig = base64.b64encode(self.private.sign(_message(claim))).decode('ascii')
        (changed / 'summary.json').write_bytes(raw)
        (changed / 'manifest.json').write_bytes(m_raw)
        (changed / 'attestation.json').write_text(json.dumps({**claim, 'signature_b64': sig}))
        # First A inserts, then B conflict -> rollback A.
        with self.assertRaisesRegex(EvidenceError, 'conflicting immutable export'):
            ingest_batch([self.a, changed], self.db, trust_store=self.trust)
        self.assertEqual([x['experiment_id'] for x in history(self.db)], ['SYNTHETIC-OPS-B'])

    def test_rollback_on_provenance_conflict_same_entry(self):
        ingest_batch([self.b], self.db, trust_store=self.trust)
        # Unknown provenance introduced by synthetic-only reimport; cannot silently downgrade.
        unsigned = self.root / 'unsigned-b'
        unsigned.mkdir()
        for name in ('manifest.json', 'summary.json'):
            (unsigned / name).write_bytes((self.b / name).read_bytes())
        unsigned_a = self.root / 'unsigned-a'
        unsigned_a.mkdir()
        for name in ('manifest.json', 'summary.json'):
            (unsigned_a / name).write_bytes((self.a / name).read_bytes())
        with self.assertRaisesRegex(EvidenceError, 'conflicting immutable intake provenance'):
            ingest_batch([unsigned_a, unsigned], self.db, trust_store=None, allow_unsigned_synthetic=True)
        self.assertEqual(len(history(self.db)), 1)

    def test_signed_batch_refuses_existing_unsigned_history(self):
        unsigned = self.fixture('SYNTHETIC-OPS-UNSIGNED', 'MONTE_CARLO', signed=False)
        ingest(unsigned, self.db, allow_unsigned_synthetic=True)
        with self.assertRaisesRegex(EvidenceError, 'existing unsigned or legacy'):
            ingest_batch([self.a], self.db, trust_store=self.trust)
        self.assertEqual(len(history(self.db)), 1)

    def test_signed_rejects_unsigned_input_and_reversed_mode(self):
        unsigned = self.fixture('SYNTHETIC-OPS-UNSIGNED', 'MONTE_CARLO', signed=False)
        with self.assertRaises(EvidenceError):
            ingest_batch([unsigned], self.db, trust_store=self.trust)
        with self.assertRaises(EvidenceError):
            ingest_batch([self.a], self.db, allow_unsigned_synthetic=True)
        self.assertFalse(self.db.exists())

    def test_preflight_rejects_extra_hidden_file(self):
        (self.a / '.secret').write_text('do not ingest')
        with self.assertRaisesRegex(EvidenceError, 'exactly the protocol files'):
            ingest_batch([self.a], self.db, trust_store=self.trust)
        self.assertFalse(self.db.exists())

    def test_preflight_rejects_symlink_file(self):
        path = self.a / 'summary.json'
        content = path.read_bytes()
        path.unlink()
        other = self.root / 'summary-backup'
        other.write_bytes(content)
        path.symlink_to(other)
        with self.assertRaises(EvidenceError):
            ingest_batch([self.a], self.db, trust_store=self.trust)

    def test_rejects_duplicate_paths_and_experiment_ids(self):
        with self.assertRaisesRegex(EvidenceError, 'duplicate bundle path'):
            ingest_batch([self.a, self.a], self.db, trust_store=self.trust)
        second_path = self.root / 'same-id'
        second_path.mkdir()
        for name in ('summary.json', 'manifest.json', 'attestation.json'):
            (second_path / name).write_bytes((self.a / name).read_bytes())
        with self.assertRaisesRegex(EvidenceError, 'duplicate experiment_id'):
            ingest_batch([self.a, second_path], self.db, trust_store=self.trust)
        self.assertFalse(self.db.exists())

    def test_bounds_and_modes(self):
        for bundles in ([], [self.a] * 51):
            with self.assertRaises(EvidenceError):
                ingest_batch(bundles, self.db, trust_store=self.trust)
        with self.assertRaises(EvidenceError):
            ingest_batch([self.a], self.db)
        with self.assertRaises(EvidenceError):
            ingest_batch([self.a], self.db, trust_store=self.trust, allow_unsigned_synthetic=True)

    def test_outside_bundle_database(self):
        with self.assertRaisesRegex(EvidenceError, 'may not reside inside'):
            ingest_batch([self.a], self.a / 'db.sqlite', trust_store=self.trust)

    def test_full_signed_run_publishes_private_reports(self):
        result = run([self.a, self.b], self.db, self.out, trust_store=self.trust,
                     expected_procedures=['MONTE_CARLO'])
        self.assertEqual(result['status'], 'OPERATIONAL_RUN_COMPLETE')
        self.assertEqual(result['report_count'], 8)
        self.assertEqual(verify_report_dir(self.out)['status'], 'LOCAL_FILES_INTACT')
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in self.out.iterdir()))
        self.assertEqual(len(list(self.out.glob('dossier-*.json'))), 2)
        self.assertEqual(len(list(self.out.glob('dossier-*.md'))), 2)
        self.assertEqual(json.loads((self.out / 'run.json').read_text())['scientific_approval'], False)
        self.assertNotIn('SYNTHETIC: failure', b' '.join(f.read_bytes() for f in self.out.iterdir()).decode('utf-8'))

    def test_local_report_fails_on_artifact_tamper(self):
        run([self.a], self.db, self.out, trust_store=self.trust)
        with (self.out / 'run.json').open('a') as f:
            f.write('tampered')
        with self.assertRaisesRegex(EvidenceError, 'size mismatch'):
            verify_report_dir(self.out)

    def test_local_report_fails_on_manifest_tamper(self):
        run([self.a], self.db, self.out, trust_store=self.trust)
        p = self.out / 'artifacts.json'
        data = json.loads(p.read_text())
        data['artifacts'][0]['sha256'] = '0' * 64
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(EvidenceError, 'manifest digest mismatch'):
            verify_report_dir(self.out)

    def test_local_report_fails_on_added_file(self):
        run([self.a], self.db, self.out, trust_store=self.trust)
        (self.out / 'private.txt').write_text('should not be here')
        with self.assertRaisesRegex(EvidenceError, 'unexpected or missing'):
            verify_report_dir(self.out)

    def test_local_report_fails_on_symlink(self):
        run([self.a], self.db, self.out, trust_store=self.trust)
        p = self.out / 'intake.json'
        original = p.read_bytes()
        p.unlink()
        mirror = self.root / 'mirror'
        mirror.write_bytes(original)
        p.symlink_to(mirror)
        with self.assertRaisesRegex(EvidenceError, 'size mismatch'):
            verify_report_dir(self.out)

    def test_verify_report_cli(self):
        run([self.a], self.db, self.out, trust_store=self.trust)
        self.assertEqual(main(['operations', 'verify-report', '--dir', str(self.out)]), 0)

    def test_existing_output_rejected_before_import(self):
        self.out.mkdir()
        with self.assertRaisesRegex(EvidenceError, 'must not exist'):
            run([self.a], self.db, self.out, trust_store=self.trust)
        self.assertFalse(self.db.exists())

    def test_output_inside_bundle_rejected_before_import(self):
        with self.assertRaisesRegex(EvidenceError, 'inside a source bundle'):
            run([self.a], self.db, self.a / 'output', trust_store=self.trust)
        self.assertFalse(self.db.exists())

    def test_bad_expected_procedure_rejected_before_import(self):
        with self.assertRaises(EvidenceError):
            run([self.a], self.db, self.out, trust_store=self.trust,
                expected_procedures=['HOLDOUT'])
        self.assertFalse(self.db.exists())

    def test_signing_not_source_authorization(self):
        ingest_batch([self.a], self.db, trust_store=self.trust)
        r = readiness(self.db)
        self.assertFalse(r['export_authorization_verified'])
        self.assertFalse(r['source_platform_integrated'])
        self.assertFalse(r['scientific_approval'])
        self.assertFalse(r['broker_authority'])
        self.assertFalse(r['holdout_access'])

    def test_unsigned_synthetic_not_signed_readiness(self):
        unsigned = self.fixture('SYNTHETIC-OPS-UNSIGNED', 'MONTE_CARLO', signed=False)
        ingest_batch([unsigned], self.db, allow_unsigned_synthetic=True)
        self.assertEqual(readiness(self.db)['status'], 'NOT_READY')
        self.assertEqual(readiness(self.db, require_signed=False)['status'], 'LOCAL_INTAKE_READY')
        self.assertEqual(main(['operations', 'readiness', '--db', str(self.db)]), 2)
        self.assertEqual(main(['operations', 'readiness', '--db', str(self.db), '--allow-unsigned-synthetic']), 0)

    def test_cli_signed_batch_and_idempotency(self):
        arg = ['operations', 'batch', '--bundle', str(self.a), '--bundle', str(self.b),
               '--db', str(self.db), '--trust-store', str(self.trust)]
        self.assertEqual(main(arg), 0)
        self.assertEqual(main(arg), 0)
        self.assertEqual(main(['operations', 'readiness', '--db', str(self.db)]), 0)

    def test_report_failure_does_not_publish_partial_output(self):
        # One SQLite transaction commits first; simulated renderer failure leaves no published folder.
        with patch('forexpro_ri.operations.render_markdown', side_effect=RuntimeError('synthetic renderer failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic renderer failure'):
                run([self.a], self.db, self.out, trust_store=self.trust)
        self.assertEqual(len(history(self.db)), 1)
        self.assertFalse(self.out.exists())
        retry = run([self.a], self.db, self.out, trust_store=self.trust)
        self.assertEqual(retry['intake']['already_present_count'], 1)


if __name__ == '__main__':
    unittest.main()
