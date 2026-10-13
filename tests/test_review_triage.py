"""Evidence-gap triage qualification, signed synthetic data only."""
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
from forexpro_ri.review_cohort import make_signed_cohort
from forexpro_ri.review_pack import build_review_pack, publish_review_pack, render_review_html
from forexpro_ri.review_triage import summarize_review


class ReviewTriageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        fixture, trust, db = cls.root / "one", cls.root / "test-keys.json", cls.root / "one.sqlite"
        create_synthetic_fixture(fixture, trust)
        ingest(fixture, db, trust_store=trust)
        cls.one = build_review_pack(db, expected_procedures=["MONTE_CARLO", "REGIME_STABILITY"])
        cls.empty = build_review_pack(cls.root / "missing.sqlite")
        cls.group = cls.root / "group"
        cls.group.mkdir()
        cohort_db = cls.group / "twenty.sqlite"
        meta = make_signed_cohort(cls.group, cohort_db)
        cls.twenty = build_review_pack(cohort_db, expected_procedures=meta["expected_procedures"])

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_attention_is_about_evidence_missing_not_success(self):
        report = summarize_review(self.one)
        self.assertEqual(report["status"], "LOCAL_REVIEW_ONLY")
        self.assertEqual(report["experiment_count"], 1)
        self.assertEqual(report["procedure_count"], 5)
        self.assertEqual(report["procedures"][0]["attention_bucket"], "MISSING_RECORDED_EVIDENCE")
        self.assertEqual(report["procedures"][0]["procedure"], "MONTE_CARLO")
        self.assertEqual(report["procedures"][0]["recorded_counts"]["UNOBSERVED"], 1)
        self.assertFalse(report["causal_rank_established"])
        self.assertFalse(report["scientific_authority"])
        self.assertFalse(report["broker_authority"])

    def test_incomplete_precedes_negative_even_when_negative_repeats(self):
        r = summarize_review(self.twenty)
        order = [x["attention_bucket"] for x in r["procedures"]]
        self.assertEqual(order, sorted(order, key={
            "MISSING_RECORDED_EVIDENCE": 0,
            "RECORDED_NOT_EVALUABLE": 1,
            "RECORDED_FAILURE_REVIEW": 2,
            "NO_RECORDED_NEGATIVE_OR_GAP": 3,
        }.get))
        self.assertEqual(r["experiment_count"], 20)
        self.assertEqual(len(r["procedures"]), 6)
        self.assertFalse(r["source_export_permission_established"])

    def test_per_case_samples_bound_and_source_linked(self):
        triage = summarize_review(self.twenty)
        pack = {x["experiment_id"]: x for x in self.twenty["cases"]}
        observed_truncations = 0
        for row in triage["procedures"]:
            self.assertLessEqual(len(row["sampled_case_refs"]), 4)
            observed_truncations += row["case_sample_truncated"]
            for ref in row["sampled_case_refs"]:
                case = pack[ref["experiment_id"]]
                self.assertEqual(ref["entry_sha256"], case["entry_sha256"])
                self.assertEqual(ref["receipt_sha256"], case["receipt_sha256"])
                self.assertIn(ref["recorded_status"], ("FAIL", "NOT_EVALUABLE", "UNOBSERVED"))
        self.assertGreater(observed_truncations, 0)

    def test_total_counts_match_exact_denominator(self):
        summary = summarize_review(self.twenty)
        self.assertEqual(sum(summary["procedure_state_totals"].values()), 120)
        for p in summary["procedures"]:
            self.assertEqual(sum(p["recorded_counts"].values()), 20)
        self.assertEqual(summary["procedure_state_totals"]["PASS"], sum(
            row["recorded_counts"]["PASS"] for row in summary["procedures"]
        ))

    def test_summary_is_deterministic(self):
        a, b = summarize_review(self.twenty), summarize_review(self.twenty)
        self.assertEqual(a, b)
        self.assertEqual(len(a["report_sha256"]), 64)
        self.assertEqual(a["source_pack_sha256"], self.twenty["report_sha256"])

    def test_empty_memory_triage_does_not_invent_science(self):
        result = summarize_review(self.empty)
        self.assertEqual(result["status"], "NO_ELIGIBLE_DATA")
        self.assertEqual(result["experiment_count"], 0)
        self.assertEqual(result["procedures"], [])
        self.assertEqual(result["procedure_state_totals"]["PASS"], 0)

    def test_html_operator_brief_and_linked_dossiers(self):
        page = render_review_html(self.twenty)
        self.assertIn("Operator evidence triage", page)
        self.assertIn("MISSING_RECORDED_EVIDENCE", page)
        self.assertIn('href="#case-1"', page)
        self.assertIn('id="case-1"', page)
        self.assertIn("never scientific rank", page)
        self.assertNotIn("<script", page)
        self.assertNotIn(str(self.root), page)

    def test_cli_triage_only_on_verified_html_and_json(self):
        path = self.root / "published"
        publish_review_pack(self.one, path)
        self.assertEqual(main(["review", "triage", "--dir", str(path)]), 0)
        (path / "index.html").write_text("<h1>forged</h1>", "utf-8")
        self.assertEqual(main(["review", "triage", "--dir", str(path)]), 2)

    def test_fake_claims_and_rehashed_contradiction_rejected(self):
        changed = copy.deepcopy(self.one)
        changed["authority"]["scientific"] = True
        with self.assertRaises(EvidenceError):
            summarize_review(changed)
        changed = copy.deepcopy(self.one)
        changed["procedure_coverage"][0]["failed_experiments"] = 900
        with self.assertRaises(EvidenceError):
            summarize_review(changed)

    def test_all_unobserved_procedure_remains_visible(self):
        result = summarize_review(self.one)
        missing = next(x for x in result["procedures"] if x["procedure"] == "MONTE_CARLO")
        self.assertEqual(missing["recorded_counts"]["UNOBSERVED"], 1)
        self.assertEqual(missing["recorded_counts"]["PASS"], 0)
        self.assertEqual(missing["sampled_case_refs"][0]["recorded_status"], "UNOBSERVED")


if __name__ == "__main__":
    unittest.main()
