"""Boundary, deterministic hash and I/O checks; no real research data used."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forexpro_ri.analysis import analyze
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.importer import import_bundle


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        self.addCleanup(self.t.cleanup)
        self.root = Path(self.t.name)
        self.summary = {
            "experiment_id": "SYNTHETIC-001", "disposition": "CLOSED_UNSUCCESSFUL",
            "criteria": [{"criterion_id": "a", "procedure": "COST_STRESS", "verdict": "FAIL", "observation": "synthetic negative net PnL"}],
            "not_evaluable": [{"procedure": "REGIME_STABILITY", "reason": "synthetic missing warmup"}],
        }
        self.manifest = {
            "schema_version": 1, "export_kind": "CLOSED_EXPERIMENT_SUMMARY", "source_system": "forexpro",
            "experiment_id": "SYNTHETIC-001", "source_revision": "a" * 40,
            "summary_sha256": "", "approved_scope": "READ_ONLY_ADVISORY",
            "holdout_access": False, "promotion_authority": False, "broker_authority": False,
        }
        self.write_bundle()

    def write_bundle(self):
        raw = (json.dumps(self.summary, sort_keys=True) + "\n").encode()
        self.manifest["summary_sha256"] = hashlib.sha256(raw).hexdigest()
        (self.root / "summary.json").write_bytes(raw)
        (self.root / "manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")

    def test_report_deterministic_and_advisory(self):
        m, s = import_bundle(self.root)
        a, b = analyze(m, s), analyze(m, s)
        self.assertEqual(a, b)
        self.assertEqual(a["counts"], {"fail": 1, "pass": 0, "not_evaluable": 1})
        self.assertFalse(any(a["authority"].values()))
        self.assertEqual(len(a["future_research_questions"]), 2)

    def test_bad_hash_rejected(self):
        (self.root / "summary.json").write_text("{}")
        with self.assertRaisesRegex(EvidenceError, "SHA-256 mismatch"):
            import_bundle(self.root)

    def test_holdout_access_rejected(self):
        self.manifest["holdout_access"] = True
        self.write_bundle()
        with self.assertRaisesRegex(EvidenceError, "protected capabilities"):
            import_bundle(self.root)

    def test_authority_mutation_rejected(self):
        self.manifest["promotion_authority"] = True
        self.write_bundle()
        with self.assertRaises(EvidenceError):
            import_bundle(self.root)

    def test_wrong_scope_rejected(self):
        self.manifest["approved_scope"] = "HOLDOUT"
        self.write_bundle()
        with self.assertRaises(EvidenceError):
            import_bundle(self.root)

    def test_unknown_field_rejected(self):
        self.summary["secret_field"] = "no"
        self.write_bundle()
        with self.assertRaises(EvidenceError):
            import_bundle(self.root)

    def test_protected_procedure_rejected_even_if_manifest_declares_no_access(self):
        self.summary["criteria"][0]["procedure"] = "HOLDOUT"
        self.write_bundle()
        with self.assertRaisesRegex(EvidenceError, "procedure not allowed"):
            import_bundle(self.root)

    def test_duplicate_json_field_rejected(self):
        raw = b'{"experiment_id":"SYNTHETIC-001","experiment_id":"SYNTHETIC-001"}'
        self.manifest["summary_sha256"] = hashlib.sha256(raw).hexdigest()
        (self.root / "summary.json").write_bytes(raw)
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(EvidenceError, "duplicate JSON key"):
            import_bundle(self.root)

    def test_identity_mismatch_rejected(self):
        self.summary["experiment_id"] = "OTHER"
        self.write_bundle()
        with self.assertRaises(EvidenceError):
            import_bundle(self.root)

    def test_fail_in_incomplete_disposition_rejected(self):
        self.summary["disposition"] = "CLOSED_INCOMPLETE"
        self.write_bundle()
        with self.assertRaises(EvidenceError):
            import_bundle(self.root)

    def test_symlink_file_rejected(self):
        (self.root / "summary.json").unlink()
        other = self.root / "other.json"
        other.write_text("{}")
        (self.root / "summary.json").symlink_to(other)
        with self.assertRaises(EvidenceError):
            import_bundle(self.root)

    def test_cli_writes_once_without_overwrite(self):
        dest = self.root.parent / (self.root.name + "-report.json")
        self.addCleanup(lambda: dest.unlink(missing_ok=True))
        self.assertEqual(main([str(self.root), "--out", str(dest)]), 0)
        self.assertTrue(dest.exists())
        self.assertEqual(main([str(self.root), "--out", str(dest)]), 2)

    def test_cli_cannot_write_into_bundle(self):
        self.assertEqual(main([str(self.root), "--out", str(self.root / "report.json")]), 2)


if __name__ == "__main__":
    unittest.main()
