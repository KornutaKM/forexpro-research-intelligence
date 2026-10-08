"""Everything is synthetic; never import private source data or secret keys."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.bridge import create_synthetic_fixture, preflight, rehearsal
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.failure_intelligence import build_failure_report
from forexpro_ri.memory import ingest, verify as verify_memory


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="fri-bridge-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        self.trust = self.root / "keys.json"

    def generate(self):
        return create_synthetic_fixture(self.bundle, self.trust)

    def test_full_synthetic_rehearsal(self):
        result = rehearsal()
        self.assertEqual(result["status"], "SYNTHETIC_REHEARSAL_PASS")
        self.assertTrue(result["signed_export_verified"])
        self.assertFalse(result["core_access"])
        self.assertFalse(result["broker_authority"])

    def test_creates_three_files_and_only_public_key(self):
        result = self.generate()
        self.assertEqual(result["fixture"], "SYNTHETIC_ONLY")
        self.assertEqual({p.name for p in self.bundle.iterdir()}, {"manifest.json", "summary.json", "attestation.json"})
        self.assertEqual(self.trust.name, "keys.json")
        self.assertNotIn("private", self.trust.read_text().lower())
        self.assertNotIn(b"PRIVATE KEY", b"".join(p.read_bytes() for p in self.root.rglob("*") if p.is_file()))
        self.assertTrue(all(p.suffix == ".json" for p in self.root.rglob("*") if p.is_file()))

    def test_signed_preflight_has_non_authoritative_scope(self):
        self.generate()
        result = preflight(self.bundle, self.trust)
        self.assertEqual(result["status"], "CRYPTOGRAPHIC_PROTOCOL_PASS")
        self.assertEqual(result["counts"], {"fail": 2, "pass": 1, "not_evaluable": 1})
        self.assertTrue(result["NOT_EXPORT_APPROVAL"])
        self.assertFalse(any(result["authority"].values()))
        self.assertNotIn("negative out-of-sample", json.dumps(result))

    def test_signed_fixture_integrates_with_memory_and_intelligence(self):
        self.generate()
        db = self.root / "memory.sqlite"
        first = ingest(self.bundle, db, trust_store=self.trust)
        second = ingest(self.bundle, db, trust_store=self.trust)
        self.assertEqual(first["status"], "IMPORTED")
        self.assertEqual(second["status"], "ALREADY_PRESENT")
        self.assertEqual(verify_memory(db)["experiment_count"], 1)
        report = build_failure_report(db, focus_experiment_id="SYNTHETIC-BRIDGE-001")
        self.assertEqual(report["observed_experiment_count"], 1)
        self.assertNotIn(b"out-of-sample metric", db.read_bytes())

    def test_tampered_summary_rejected_without_memory(self):
        self.generate()
        p = self.bundle / "summary.json"
        p.write_bytes(p.read_bytes().replace(b"negative", b"positive"))
        with self.assertRaisesRegex(EvidenceError, "SHA-256"):
            preflight(self.bundle, self.trust)
        self.assertFalse((self.root / "memory.sqlite").exists())

    def test_tampered_manifest_rejected(self):
        self.generate()
        p = self.bundle / "manifest.json"
        p.write_bytes(p.read_bytes().replace(b'"source_revision":"', b'"source_revision":"b'))
        with self.assertRaises(EvidenceError):
            preflight(self.bundle, self.trust)

    def test_revoked_key_rejected(self):
        self.generate()
        trust = json.loads(self.trust.read_text())
        trust["keys"][0]["status"] = "REVOKED"
        self.trust.write_text(json.dumps(trust))
        with self.assertRaisesRegex(EvidenceError, "revoked"):
            preflight(self.bundle, self.trust)

    def test_untrusted_public_key_rejected(self):
        self.generate()
        trust = json.loads(self.trust.read_text())
        trust["keys"][0]["key_id"] = "another-key"
        self.trust.write_text(json.dumps(trust))
        with self.assertRaisesRegex(EvidenceError, "not present"):
            preflight(self.bundle, self.trust)

    def test_unexpected_extra_file_rejected(self):
        self.generate()
        (self.bundle / "secrets.txt").write_text("not allowed")
        with self.assertRaisesRegex(EvidenceError, "exactly three"):
            preflight(self.bundle, self.trust)

    def test_missing_attestation_rejected(self):
        self.generate()
        (self.bundle / "attestation.json").unlink()
        with self.assertRaisesRegex(EvidenceError, "exactly three"):
            preflight(self.bundle, self.trust)

    def test_symlink_extra_file_rejected(self):
        self.generate()
        (self.bundle / "extra").symlink_to(self.trust)
        with self.assertRaises(EvidenceError):
            preflight(self.bundle, self.trust)

    def test_bundle_symlink_rejected(self):
        self.generate()
        alias = self.root / "alias"
        alias.symlink_to(self.bundle, target_is_directory=True)
        with self.assertRaises(EvidenceError):
            preflight(alias, self.trust)

    def test_refuse_overwrite_existing_fixture(self):
        self.generate()
        prior = (self.bundle / "summary.json").read_bytes()
        with self.assertRaisesRegex(EvidenceError, "already exists"):
            self.generate()
        self.assertEqual(prior, (self.bundle / "summary.json").read_bytes())

    def test_refuse_overwrite_trust_store(self):
        self.trust.write_text("operator-provisioned")
        with self.assertRaises(EvidenceError):
            self.generate()
        self.assertEqual(self.trust.read_text(), "operator-provisioned")
        self.assertFalse(self.bundle.exists())

    def test_refuse_nonexistent_parent(self):
        with self.assertRaisesRegex(EvidenceError, "parent"):
            create_synthetic_fixture(self.root / "missing" / "bundle", self.trust)
        self.assertFalse(self.trust.exists())

    def test_refuse_trust_path_within_bundle(self):
        with self.assertRaises(EvidenceError):
            create_synthetic_fixture(self.bundle, self.bundle / "keys.json")
        self.assertFalse(self.bundle.exists())

    def test_cli_rehearsal(self):
        self.assertEqual(main(["bridge", "rehearsal"]), 0)

    def test_cli_fixture_and_preflight(self):
        self.assertEqual(main(["bridge", "fixture", "--bundle", str(self.bundle), "--trust-store", str(self.trust)]), 0)
        self.assertEqual(main(["bridge", "preflight", str(self.bundle), "--trust-store", str(self.trust)]), 0)

    def test_cli_preflight_rejects_missing_bundle(self):
        self.assertEqual(main(["bridge", "preflight", str(self.bundle), "--trust-store", str(self.trust)]), 2)


if __name__ == "__main__":
    unittest.main()
