"""Issue #19 P0: operator Research Review Pack; synthetic-only and fail-closed tests."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forexpro_ri.analysis import canonical_json
from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import ingest
from forexpro_ri.review_pack import (
    build_review_pack, publish_review_pack, render_review_html, verify_review_pack,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class ReviewPackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "memory.sqlite"

    def signed_fixture(self):
        bundle = self.root / "signed-synthetic"
        keys = self.root / "trusted-test-keys.json"
        create_synthetic_fixture(bundle, keys)
        ingest(bundle, self.db, trust_store=keys)

    def unsigned_fixture(self):
        ingest(EXAMPLES / "closed_synthetic", self.db, allow_unsigned_synthetic=True)
        ingest(EXAMPLES / "closed_synthetic_peer", self.db, allow_unsigned_synthetic=True)

    def test_signed_pack_is_deterministic_and_non_authoritative(self):
        self.signed_fixture()
        a = build_review_pack(self.db, expected_procedures=["MONTE_CARLO"])
        b = build_review_pack(self.db, expected_procedures=["MONTE_CARLO"])
        self.assertEqual(a, b)
        self.assertEqual(a["status"], "HISTORICAL_SIGNED_INTAKES")
        self.assertEqual(a["experiment_count"], 1)
        self.assertFalse(any(a["authority"].values()))
        self.assertGreater(len(a["review_topics"]), 0)
        self.assertEqual(a["cases"][0]["experiment_id"], "SYNTHETIC-BRIDGE-001")
        self.assertEqual(a["cases"][0]["evidence_visibility"], "HISTORICAL_SIGNED_INTAKE_ONLY")
        states = {row["procedure"]: row["recorded_status"]
                  for row in a["cases"][0]["procedure_outcomes"]}
        self.assertEqual(states["REGIME_STABILITY"], "NOT_EVALUABLE")
        self.assertEqual(states["MONTE_CARLO"], "UNOBSERVED")
        self.assertEqual(states["OUT_OF_SAMPLE"], "FAIL")

    def test_full_html_links_and_digest(self):
        self.signed_fixture()
        report = build_review_pack(self.db)
        html = render_review_html(report)
        self.assertIn("href=\"#case-1\"", html)
        self.assertIn("NOT_EVALUABLE", html)
        self.assertIn("UNOBSERVED", html)
        self.assertIn("No trading or scientific approval", html)
        self.assertIn(report["report_sha256"], html)
        self.assertNotIn(str(self.root), html)
        self.assertNotIn("<script", html)

    def test_missing_db_is_not_evidence_of_success(self):
        missing = self.root / "no.sqlite"
        a = build_review_pack(missing)
        self.assertFalse(missing.exists())
        self.assertEqual(a["status"], "NO_ELIGIBLE_DATA")
        self.assertEqual(a["cases"], [])
        self.assertIn("No eligible", render_review_html(a))
        with self.assertRaises(EvidenceError):
            build_review_pack(missing, allow_unsigned_synthetic=True)

    def test_default_rejects_unsigned_memory(self):
        self.unsigned_fixture()
        with self.assertRaises(EvidenceError):
            build_review_pack(self.db)
        demo = build_review_pack(self.db, allow_unsigned_synthetic=True,
                                 expected_procedures=["MONTE_CARLO"])
        self.assertEqual(demo["status"], "SYNTHETIC_DEMONSTRATION")
        self.assertEqual(demo["experiment_count"], 2)
        self.assertTrue(all(not case["similar_cases_truncated"] for case in demo["cases"]))
        self.assertFalse(any(demo["authority"].values()))

    def test_legacy_receipts_are_never_allowed(self):
        self.unsigned_fixture()
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP TRIGGER intake_receipts_no_update")
            conn.execute("UPDATE intake_receipts SET verification_status='LEGACY_UNATTESTED'")
        with self.assertRaises(EvidenceError):
            build_review_pack(self.db, allow_unsigned_synthetic=True)

    def test_malformed_or_tampered_memory_fails_closed(self):
        self.unsigned_fixture()
        with sqlite3.connect(self.db) as conn:
            conn.execute("DROP TRIGGER criteria_no_update")
            conn.execute("UPDATE criteria SET verdict='PASS' WHERE verdict='FAIL'")
        with self.assertRaises(EvidenceError):
            build_review_pack(self.db, allow_unsigned_synthetic=True)

    def test_snapshot_drift_is_rejected(self):
        self.signed_fixture()
        from forexpro_ri import review_pack
        actual = review_pack.provenance_audit
        calls = []

        def drifting(path):
            result = actual(path)
            calls.append(1)
            if len(calls) == 2:
                result["report_sha256"] = "f" * 64
            return result

        with patch.object(review_pack, "provenance_audit", side_effect=drifting):
            with self.assertRaisesRegex(EvidenceError, "changed during"):
                build_review_pack(self.db)

    def test_publication_creation_only_and_verify(self):
        self.signed_fixture()
        r = build_review_pack(self.db)
        destination = self.root / "private-report"
        result = publish_review_pack(r, destination)
        self.assertEqual(result["status"], "CREATED")
        self.assertEqual(sorted(p.name for p in destination.iterdir()), ["index.html", "review.json"])
        self.assertEqual((destination / "index.html").read_text(), render_review_html(r))
        self.assertEqual(main(["review", "verify", "--dir", str(destination)]), 0)
        with self.assertRaises(EvidenceError):
            publish_review_pack(r, destination)

    def test_cli_signed_demo_end_to_end(self):
        out = self.root / "new-demo-output"
        self.assertEqual(main(["review", "demo", "--out", str(out)]), 0)
        self.assertEqual(main(["review", "verify", "--dir", str(out)]), 0)
        report = json.loads((out / "review.json").read_text())
        self.assertEqual(report["status"], "HISTORICAL_SIGNED_INTAKES")
        self.assertFalse(any(report["authority"].values()))

    def test_html_and_json_tampering_detected(self):
        self.signed_fixture()
        report = build_review_pack(self.db)
        out = self.root / "review"
        publish_review_pack(report, out)
        html_file = out / "index.html"
        html_file.write_text(html_file.read_text().replace("FRI —", "Changed —"))
        self.assertEqual(main(["review", "verify", "--dir", str(out)]), 2)
        html_file.write_text(render_review_html(report))
        json_file = out / "review.json"
        data = json.loads(json_file.read_text())
        data["cases"][0]["recorded_disposition"] = "CLOSED_SUCCESSFUL"
        json_file.write_text(json.dumps(data))
        self.assertEqual(main(["review", "verify", "--dir", str(out)]), 2)

    def test_html_escaping_even_when_report_contains_untrusted_string(self):
        self.signed_fixture()
        report = build_review_pack(self.db)
        report["review_topics"][0]["question_for_new_experiment"] = "<img src=x onerror=alert(1)>"
        report["report_sha256"] = hashlib.sha256(canonical_json(
            {k: v for k, v in report.items() if k != "report_sha256"}).encode()).hexdigest()
        page = render_review_html(report)
        self.assertNotIn("<img ", page)
        self.assertIn("&lt;img", page)

    def test_audited_reference_identity_cannot_be_substituted(self):
        self.signed_fixture()
        from forexpro_ri import review_pack
        original = review_pack.build_advisor

        def forged(*args, **kwargs):
            data = original(*args, **kwargs)
            data["proposals"][0]["evidence_sample"][0]["entry_sha256"] = "f" * 64
            data["report_sha256"] = hashlib.sha256(canonical_json(
                {k: v for k, v in data.items() if k != "report_sha256"}).encode()).hexdigest()
            return data

        with patch.object(review_pack, "build_advisor", side_effect=forged):
            with self.assertRaises(EvidenceError):
                build_review_pack(self.db)

    def test_no_private_paths_or_file_url_emitted(self):
        self.signed_fixture()
        report = build_review_pack(self.db)
        blob = json.dumps(report) + render_review_html(report)
        self.assertNotIn(str(self.root), blob)
        self.assertNotIn("file://", blob)
        self.assertNotIn("http://", blob)
        self.assertNotIn("https://", blob)

    def test_invalid_pack_or_authority_escalation_rejected(self):
        self.signed_fixture()
        r = build_review_pack(self.db)
        r["authority"]["broker"] = True
        with self.assertRaises(EvidenceError):
            verify_review_pack(r)
        with self.assertRaises(EvidenceError):
            render_review_html(r)

    def test_symlink_output_denied(self):
        self.signed_fixture()
        report = build_review_pack(self.db)
        (self.root / "link").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(EvidenceError):
            publish_review_pack(report, self.root / "link" / "report")

    def test_unsigned_synthetic_rejects_non_synthetic_identifier(self):
        self.unsigned_fixture()
        from forexpro_ri import review_pack
        original = review_pack.provenance_audit

        def renamed(path):
            a = original(path)
            for row in a["receipts"]:
                row["experiment_id"] = row["experiment_id"].replace("SYNTHETIC-", "REAL-")
            return a

        with patch.object(review_pack, "provenance_audit", side_effect=renamed):
            with self.assertRaises(EvidenceError):
                build_review_pack(self.db, allow_unsigned_synthetic=True)


if __name__ == "__main__":
    unittest.main()
