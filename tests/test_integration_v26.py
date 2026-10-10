"""Future exporter protocol compatibility with signed, synthetic-only fixtures."""
import json
import importlib.util
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.integration_readiness import check_bundle


class SignedExporterCompatibilityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.bundle = self.root/'signed'
        self.trust = self.root/'trusted-keys.json'
        create_synthetic_fixture(self.bundle, self.trust)

    def test_valid_fixture(self):
        result = check_bundle(self.bundle, self.trust)
        self.assertTrue(result['signature_verified'])
        self.assertEqual(result['status'], 'CONTRACT_CONFORMANT_NOT_EXPORT_APPROVED')
        self.assertFalse(result['current_export_authorization'])
        self.assertFalse(result['scientific_approval'])

    def test_unknown_file_rejected(self):
        (self.bundle/'private-note.txt').write_text('secret')
        with self.assertRaises(EvidenceError): check_bundle(self.bundle, self.trust)

    def test_wrong_signature_rejected(self):
        att = self.bundle/'attestation.json'
        data = json.loads(att.read_text()); data['signature_b64'] = 'A'*88
        att.write_text(json.dumps(data))
        with self.assertRaises(EvidenceError): check_bundle(self.bundle, self.trust)

    def test_revoked_key_rejected(self):
        data = json.loads(self.trust.read_text()); data['keys'][0]['status'] = 'REVOKED'
        self.trust.write_text(json.dumps(data))
        with self.assertRaises(EvidenceError): check_bundle(self.bundle, self.trust)

    def test_unsupported_contract_rejected(self):
        manifest = self.bundle/'manifest.json'
        data = json.loads(manifest.read_text()); data['schema_version'] = 2
        manifest.write_text(json.dumps(data))
        with self.assertRaises(EvidenceError): check_bundle(self.bundle, self.trust)

    def test_symlink_rejected(self):
        att = self.bundle/'attestation.json'; raw = att.read_bytes(); att.unlink()
        (self.root/'alternate.json').write_bytes(raw)
        att.symlink_to(self.root/'alternate.json')
        with self.assertRaises(EvidenceError): check_bundle(self.bundle, self.trust)

    def test_trust_store_inside_bundle_rejected(self):
        (self.bundle/'trusted-keys.json').write_bytes(self.trust.read_bytes())
        with self.assertRaises(EvidenceError): check_bundle(self.bundle,self.bundle/'trusted-keys.json')

    def test_untrusted_signing_key_rejected(self):
        second = self.root/'second'; second_trust = self.root/'other-keys.json'
        create_synthetic_fixture(second, second_trust)
        with self.assertRaises(EvidenceError): check_bundle(self.bundle, second_trust)

    @unittest.skipUnless(importlib.util.find_spec('forexpro_ri.advisor'),
                         'Full Advisor included in the published GitHub v2.4 tree')
    def test_signed_rehearsal_with_advisor(self):
        from forexpro_ri.integration_readiness import rehearsal
        report = rehearsal()
        self.assertEqual(report['status'], 'CONTRACT_REHEARSAL_PASS')
        self.assertTrue(report['signed_only_gate_passed'])
        self.assertFalse(report['export_authorization'])

    @unittest.skipUnless(importlib.util.find_spec('forexpro_ri.advisor'),
                         'Full Advisor included in the published GitHub v2.4 tree')
    def test_quality_benchmark_in_signed_history(self):
        from forexpro_ri.memory import ingest
        from forexpro_ri.quality import benchmark
        memory = self.root / 'history.sqlite'
        ingest(self.bundle, memory, trust_store=self.trust)
        metrics = benchmark(db_path=str(memory))
        self.assertEqual(metrics['status'], 'PASS')
        self.assertEqual(metrics['passed'], metrics['total'])
        self.assertFalse(metrics['model_semantic_truth_verified'])

    def test_manifest_holdout_claim_rejected(self):
        manifest = self.bundle/'manifest.json'; data = json.loads(manifest.read_text())
        data['holdout_access'] = True; manifest.write_text(json.dumps(data))
        with self.assertRaises(EvidenceError): check_bundle(self.bundle, self.trust)


if __name__ == '__main__': unittest.main()
