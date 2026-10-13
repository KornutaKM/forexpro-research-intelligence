"""Repeat-research cautions: only actual recorded negatives, not imagined trials."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.review_cohort import make_signed_cohort
from forexpro_ri.review_pack import build_review_pack, publish_review_pack, render_review_html
from forexpro_ri.review_repetition import find_repeated_negatives


class ReviewRepetitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        db = cls.root / "history.sqlite"
        created = make_signed_cohort(cls.root, db)
        cls.pack = build_review_pack(db, expected_procedures=created["expected_procedures"])
        cls.empty = build_review_pack(cls.root / "not-supplied.sqlite")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_identical_negative_patterns_require_human_review(self):
        report = find_repeated_negatives(self.pack)
        self.assertEqual(report["status"], "DESCRIPTIVE_PATTERN_REVIEW")
        self.assertGreaterEqual(report["repeated_cluster_count"], 1)
        self.assertFalse(report["source_independence_established"])
        self.assertFalse(report["improvement_established"])
        self.assertFalse(report["scientific_authority"])
        self.assertFalse(report["broker_authority"])

    def test_pair_identical_states_in_one_cluster(self):
        report = find_repeated_negatives(self.pack)
        matching = [x for x in report["clusters"] if
                    {"SYNTHETIC-COHORT-01", "SYNTHETIC-COHORT-02"} <= {
                        y["experiment_id"] for y in x["sampled_experiments"]
                    }]
        self.assertEqual(len(matching), 1)
        self.assertGreaterEqual(matching[0]["observed_case_count"], 2)
        self.assertFalse(matching[0]["independent_replication_established"])
        self.assertFalse(matching[0]["shared_cause_established"])

    def test_negative_signature_does_not_include_unobserved_or_pass(self):
        report = find_repeated_negatives(self.pack)
        for cluster in report["clusters"]:
            self.assertTrue(cluster["negative_signature"])
            self.assertEqual(cluster["negative_signature"], sorted(
                cluster["negative_signature"], key=lambda r: (r["procedure"], r["recorded_status"])
            ))
            self.assertTrue(all(x["recorded_status"] in ("FAIL", "NOT_EVALUABLE")
                                for x in cluster["negative_signature"]))
            self.assertEqual(len(cluster["signature_sha256"]), 64)
            self.assertLessEqual(len(cluster["sampled_experiments"]), 6)

    def test_all_references_have_matching_case_digests(self):
        known = {c["experiment_id"]: c for c in self.pack["cases"]}
        for cluster in find_repeated_negatives(self.pack)["clusters"]:
            for row in cluster["sampled_experiments"]:
                e = known[row["experiment_id"]]
                self.assertEqual(e["entry_sha256"], row["entry_sha256"])
                self.assertEqual(e["receipt_sha256"], row["receipt_sha256"])

    def test_empty_report_does_not_fabricate_repetition(self):
        out = find_repeated_negatives(self.empty)
        self.assertEqual(out["status"], "NO_ELIGIBLE_DATA")
        self.assertEqual(out["repeated_cluster_count"], 0)
        self.assertEqual(out["clusters"], [])

    def test_full_researcher_html_links_cases(self):
        page = render_review_html(self.pack)
        self.assertIn("Repeated negative-pattern cautions", page)
        self.assertIn("Independent replication: NOT ESTABLISHED", page)
        self.assertIn('href="#case-1"', page)
        self.assertNotIn("<script", page)
        self.assertNotIn(str(self.root), page)

    def test_deterministic_output(self):
        a = find_repeated_negatives(self.pack)
        b = find_repeated_negatives(self.pack)
        self.assertEqual(a, b)
        self.assertEqual(a["source_pack_sha256"], self.pack["report_sha256"])
        self.assertEqual(len(a["report_sha256"]), 64)

    def test_cli_local_only_and_tamper_rejection(self):
        out = self.root / "published"
        publish_review_pack(self.pack, out)
        self.assertEqual(main(["review", "repetition", "--dir", str(out)]), 0)
        json_file = out / "review.json"
        source = json.loads(json_file.read_text("utf-8"))
        source["authority"]["promotion"] = True
        json_file.write_text(json.dumps(source), "utf-8")
        self.assertEqual(main(["review", "repetition", "--dir", str(out)]), 2)

    def test_invalid_pack_rejected_even_if_rehashed_elsewhere(self):
        bad = copy.deepcopy(self.pack)
        bad["cases"][0]["procedure_outcomes"][0]["recorded_status"] = "PASS"
        with self.assertRaises(EvidenceError):
            find_repeated_negatives(bad)


if __name__ == "__main__":
    unittest.main()
