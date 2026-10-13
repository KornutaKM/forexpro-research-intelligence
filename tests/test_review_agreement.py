"""Two-reviewer SHA-bound difference reporting; no identity or Core authorization."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import ingest
from forexpro_ri.review_agreement import compare_human_reviews
from forexpro_ri.review_decisions import decision_template, assess_review_decisions
from forexpro_ri.review_pack import build_review_pack, publish_review_pack


class ReviewAgreementTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        fixture, trust, db = self.root / "fixture", self.root / "pubkey.json", self.root / "memory.sqlite"
        create_synthetic_fixture(fixture, trust)
        ingest(fixture, db, trust_store=trust)
        self.pack = build_review_pack(db, expected_procedures=["MONTE_CARLO"])
        self.directory = self.root / "pack"
        publish_review_pack(self.pack, self.directory)

    def make_two(self):
        left = decision_template(self.pack)
        right = decision_template(self.pack)
        right["decisions"][0]["choice"] = "ACCEPT_FOR_DISCUSSION"
        right["decisions"][0]["reason_code"] = "NEW_EXPERIMENT_QUESTION"
        return assess_review_decisions(self.pack, left), assess_review_decisions(self.pack, right)

    def test_disagreement_is_visible_and_non_authoritative(self):
        a, b = self.make_two()
        result = compare_human_reviews(self.pack, a, b)
        self.assertEqual(result["status"], "REQUIRES_HUMAN_RECONCILIATION")
        self.assertEqual(result["topic_count"], len(self.pack["review_topics"]))
        self.assertEqual(len(result["disagreements"]), 1)
        self.assertEqual(result["matching_choice_count"], len(self.pack["review_topics"]) - 1)
        self.assertFalse(result["reviewer_independence_established"])
        self.assertFalse(result["reviewer_identity_authenticated"])
        self.assertFalse(result["scientific_authority"])
        self.assertFalse(result["broker_authority"])
        self.assertFalse(result["experiment_registration_authorized"])

    def test_matching_choice_different_reason_not_full_agreement(self):
        t1 = decision_template(self.pack)
        t2 = decision_template(self.pack)
        t2["decisions"][0]["choice"] = "DEFER"
        t2["decisions"][0]["reason_code"] = "NEEDS_INDEPENDENT_REVIEW"
        a = assess_review_decisions(self.pack, t1)
        b = assess_review_decisions(self.pack, t2)
        result = compare_human_reviews(self.pack, a, b)
        self.assertEqual(result["matching_choice_count"], len(t1["decisions"]))
        self.assertEqual(result["matching_choice_and_reason_count"], len(t1["decisions"]) - 1)
        self.assertFalse(result["full_agreement"])

    def test_identical_records_are_not_two_independent_reviews(self):
        a, _ = self.make_two()
        with self.assertRaisesRegex(EvidenceError, "identical"):
            compare_human_reviews(self.pack, a, copy.deepcopy(a))

    def test_no_mixing_review_packs_or_historical_status(self):
        a, b = self.make_two()
        b["source_pack_sha256"] = "0" * 64
        with self.assertRaises(EvidenceError):
            compare_human_reviews(self.pack, a, b)

    def test_rehashed_forged_outcome_is_not_accepted(self):
        a, b = self.make_two()
        b["decisions"][0]["choice"] = "EXECUTE_EXPERIMENT"
        with self.assertRaises(EvidenceError):
            compare_human_reviews(self.pack, a, b)

    def test_rehashed_forged_sidecar_fields_are_rejected(self):
        a, b = self.make_two()
        b["reviewer_identity_verified"] = True
        with self.assertRaises(EvidenceError):
            compare_human_reviews(self.pack, a, b)
        b["reviewer_identity_verified"] = False
        b["scientific_authority"] = True
        with self.assertRaises(EvidenceError):
            compare_human_reviews(self.pack, a, b)

    def test_unreviewed_templates_cannot_impersonate_checked_decisions(self):
        template = decision_template(self.pack)
        _, checked = self.make_two()
        with self.assertRaises(EvidenceError):
            compare_human_reviews(self.pack, template, checked)

    def test_output_reproducible_and_no_personal_attributes(self):
        left, right = self.make_two()
        a = compare_human_reviews(self.pack, left, right)
        b = compare_human_reviews(self.pack, left, right)
        self.assertEqual(a, b)
        body = json.dumps(a)
        self.assertNotIn(str(self.root), body)
        self.assertNotIn("https://", body)
        self.assertNotIn("RUN_EXPERIMENT", body)

    def test_cli_checked_roundtrip_and_no_overwrites(self):
        left, right = self.make_two()
        a, b, out = self.root / "left.json", self.root / "right.json", self.root / "agreement.json"
        a.write_text(json.dumps(left), "utf-8")
        b.write_text(json.dumps(right), "utf-8")
        argv = ["review", "agreement", "--dir", str(self.directory),
                "--left", str(a), "--right", str(b), "--out", str(out)]
        self.assertEqual(main(argv), 0)
        result = json.loads(out.read_text("utf-8"))
        self.assertEqual(len(result["disagreements"]), 1)
        self.assertEqual(main(argv), 2)

    def test_cli_no_write_inside_original_report(self):
        left, right = self.make_two()
        a, b, out = self.root / "left.json", self.root / "right.json", self.directory / "agreement.json"
        a.write_text(json.dumps(left), "utf-8")
        b.write_text(json.dumps(right), "utf-8")
        self.assertEqual(main(["review", "agreement", "--dir", str(self.directory),
                               "--left", str(a), "--right", str(b), "--out", str(out)]), 2)
        self.assertFalse(out.exists())

    def test_cli_rejects_symlink_review_input(self):
        left, right = self.make_two()
        a, b = self.root / "left.json", self.root / "right.json"
        original = self.root / "original.json"
        original.write_text(json.dumps(left), "utf-8")
        a.symlink_to(original)
        b.write_text(json.dumps(right), "utf-8")
        self.assertEqual(main(["review", "agreement", "--dir", str(self.directory),
                               "--left", str(a), "--right", str(b),
                               "--out", str(self.root / "out.json")]), 2)


if __name__ == "__main__":
    unittest.main()
