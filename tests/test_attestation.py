"""Every test generates ephemeral Ed25519 keys and uses synthetic observations."""
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from forexpro_ri.analysis import canonical_json
from forexpro_ri.attestation import _message, verify_export
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import ingest, verify


class SignedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        self.db = self.root / 'memory.sqlite'
        self.trust_path = self.root / 'approved_public_keys.json'
        self.priv = Ed25519PrivateKey.generate()
        self.other_priv = Ed25519PrivateKey.generate()
        self.summary = {
            'experiment_id': 'SYNTHETIC-SIGNED-1',
            'disposition': 'CLOSED_UNSUCCESSFUL',
            'criteria': [{'criterion_id': 'c1', 'procedure': 'OUT_OF_SAMPLE', 'verdict': 'FAIL', 'observation': 'synthetic negative result'}],
            'not_evaluable': [],
        }
        self.manifest = {
            'schema_version': 1, 'export_kind': 'CLOSED_EXPERIMENT_SUMMARY', 'source_system': 'forexpro',
            'experiment_id': 'SYNTHETIC-SIGNED-1', 'source_revision': 'c' * 40,
            'summary_sha256': '', 'approved_scope': 'READ_ONLY_ADVISORY',
            'holdout_access': False, 'promotion_authority': False, 'broker_authority': False,
        }
        self.key_id = 'test-exporter-2026'
        self.make_trust()
        self.make_bundle()

    def make_trust(self, *, status='ACTIVE', private=None):
        private = private or self.priv
        raw_public = private.public_key().public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
        trust = {'schema_version': 1, 'keys': [{
            'key_id': self.key_id, 'algorithm': 'Ed25519',
            'public_key_b64': base64.b64encode(raw_public).decode('ascii'),
            'source_system': 'forexpro', 'purpose': 'CLOSED_EXPERIMENT_SUMMARY', 'status': status,
        }]}
        self.trust_path.write_text(json.dumps(trust), encoding='utf-8')

    def make_bundle(self, *, sign_by=None):
        sign_by = sign_by or self.priv
        summary = json.dumps(self.summary, sort_keys=True).encode('utf-8')
        self.manifest['summary_sha256'] = hashlib.sha256(summary).hexdigest()
        manifest = json.dumps(self.manifest, sort_keys=True).encode('utf-8')
        (self.bundle / 'summary.json').write_bytes(summary)
        (self.bundle / 'manifest.json').write_bytes(manifest)
        signed = {
            'schema_version': 1, 'algorithm': 'Ed25519', 'key_id': self.key_id,
            'manifest_sha256': hashlib.sha256(manifest).hexdigest(),
            'summary_sha256': hashlib.sha256(summary).hexdigest(),
        }
        signature = sign_by.sign(_message(signed))
        attestation = {**signed, 'signature_b64': base64.b64encode(signature).decode('ascii')}
        (self.bundle / 'attestation.json').write_text(json.dumps(attestation), encoding='utf-8')

    def test_signed_validated_report_and_memory(self):
        _, _, receipt = verify_export(self.bundle, self.trust_path)
        self.assertEqual(receipt['status'], 'SIGNATURE_VERIFIED')
        self.assertEqual(receipt['signer_key_id'], self.key_id)
        self.assertFalse(receipt['scientific_approval'])
        self.assertEqual(main(['verify-export', str(self.bundle), '--trust-store', str(self.trust_path)]), 0)
        self.assertEqual(main([str(self.bundle), '--trust-store', str(self.trust_path)]), 0)
        self.assertEqual(main(['memory', 'ingest', str(self.bundle), '--db', str(self.db), '--trust-store', str(self.trust_path)]), 0)
        self.assertEqual(verify(self.db)['experiment_count'], 1)
        # Research Memory retains no secret keys or original free text.
        self.assertNotIn(b'synthetic negative result', self.db.read_bytes())
        self.assertNotIn(b'PRIVATE KEY', self.db.read_bytes())

    def test_tampered_summary_with_rewritten_manifest_rejected(self):
        # Attacker controls both summary and manifest; no signing key.
        self.summary['criteria'][0]['observation'] = 'synthetic manipulated'
        self.make_bundle()
        (self.bundle / 'summary.json').write_bytes(b'{}')
        with self.assertRaises(EvidenceError):
            verify_export(self.bundle, self.trust_path)

    def test_changed_manifest_without_new_attestation_rejected(self):
        (self.bundle / 'manifest.json').write_text(json.dumps({**self.manifest, 'source_revision': 'd' * 40}))
        with self.assertRaisesRegex(EvidenceError, 'binding mismatch'):
            verify_export(self.bundle, self.trust_path)

    def test_wrong_private_key_rejected(self):
        self.make_bundle(sign_by=self.other_priv)
        with self.assertRaisesRegex(EvidenceError, 'signature'):
            verify_export(self.bundle, self.trust_path)

    def test_unknown_key_rejected(self):
        self.key_id = 'never-approved'
        self.make_bundle()
        with self.assertRaisesRegex(EvidenceError, 'not present'):
            verify_export(self.bundle, self.trust_path)

    def test_revoked_key_rejected(self):
        self.make_trust(status='REVOKED')
        with self.assertRaisesRegex(EvidenceError, 'revoked'):
            verify_export(self.bundle, self.trust_path)

    def test_invalid_attestation_signature_bytes_rejected(self):
        item = json.loads((self.bundle / 'attestation.json').read_text())
        item['signature_b64'] = 'not-base64'
        (self.bundle / 'attestation.json').write_text(json.dumps(item))
        with self.assertRaises(EvidenceError):
            verify_export(self.bundle, self.trust_path)

    def test_trust_store_with_replacement_key_rejected(self):
        self.make_trust(private=self.other_priv)
        with self.assertRaisesRegex(EvidenceError, 'signature'):
            verify_export(self.bundle, self.trust_path)

    def test_untrusted_keys_inside_bundle_rejected(self):
        t = self.bundle / 'keys.json'
        t.write_bytes(self.trust_path.read_bytes())
        with self.assertRaisesRegex(EvidenceError, 'outside evidence bundle'):
            verify_export(self.bundle, t)

    def test_trust_store_symlink_rejected(self):
        alias = self.root / 'alias.json'
        alias.symlink_to(self.trust_path)
        with self.assertRaisesRegex(EvidenceError, 'real local file'):
            verify_export(self.bundle, alias)

    def test_authority_flags_rejected_even_with_valid_signature(self):
        self.manifest['broker_authority'] = True
        self.make_bundle()
        with self.assertRaisesRegex(EvidenceError, 'protected capabilities'):
            verify_export(self.bundle, self.trust_path)
        self.assertFalse(self.db.exists())

    def test_holdout_procedure_rejected_even_with_valid_signature(self):
        self.summary['criteria'][0]['procedure'] = 'HOLDOUT'
        self.make_bundle()
        with self.assertRaisesRegex(EvidenceError, 'not allowed'):
            verify_export(self.bundle, self.trust_path)

    def test_missing_signature_rejected(self):
        (self.bundle / 'attestation.json').unlink()
        self.assertEqual(main(['memory', 'ingest', str(self.bundle), '--db', str(self.db), '--trust-store', str(self.trust_path)]), 2)
        self.assertFalse(self.db.exists())

    def test_cli_implicit_unsigned_rejected(self):
        with self.assertRaises(SystemExit) as exit_info:
            main(['memory', 'ingest', str(self.bundle), '--db', str(self.db)])
        self.assertEqual(exit_info.exception.code, 2)
        self.assertFalse(self.db.exists())

    def test_unsigned_synthetic_explicit_opt_in(self):
        self.assertEqual(main(['memory', 'ingest', str(self.bundle), '--db', str(self.db), '--unsigned-synthetic']), 0)

    def test_unsigned_real_even_explicit_opt_in_rejected(self):
        self.summary['experiment_id'] = 'REAL-PROD-1'
        self.manifest['experiment_id'] = 'REAL-PROD-1'
        self.make_bundle()
        self.assertEqual(main(['memory', 'ingest', str(self.bundle), '--db', str(self.db), '--unsigned-synthetic']), 2)
        self.assertFalse(self.db.exists())

    def test_keyring_duplicate_ids_rejected(self):
        obj = json.loads(self.trust_path.read_text())
        obj['keys'].append(obj['keys'][0])
        self.trust_path.write_text(json.dumps(obj))
        with self.assertRaisesRegex(EvidenceError, 'duplicate trusted'):
            verify_export(self.bundle, self.trust_path)

    def test_attestation_extra_unexpected_key_rejected(self):
        att = json.loads((self.bundle / 'attestation.json').read_text())
        att['unexpected'] = 'something'
        (self.bundle / 'attestation.json').write_text(json.dumps(att))
        with self.assertRaises(EvidenceError):
            verify_export(self.bundle, self.trust_path)

    def test_attestation_symlink_rejected(self):
        src = self.bundle / 'attestation.json'
        copy = self.root / 'copy.json'
        copy.write_bytes(src.read_bytes())
        src.unlink()
        src.symlink_to(copy)
        with self.assertRaisesRegex(EvidenceError, 'symbolic-link'):
            verify_export(self.bundle, self.trust_path)

    def test_memory_conflicting_signed_snapshot_rejected(self):
        ingest(self.bundle, self.db, trust_store=self.trust_path)
        self.summary['criteria'][0]['observation'] = 'synthetic changed'
        self.make_bundle()
        with self.assertRaisesRegex(EvidenceError, 'conflicting immutable'):
            ingest(self.bundle, self.db, trust_store=self.trust_path)


if __name__ == '__main__':
    unittest.main()
