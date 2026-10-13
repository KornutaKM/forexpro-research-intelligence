"""Paired time study: reproducibility, quality and non-authority negatives."""
from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.review_time_study import analyze_paired_study

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "review_time_study_synthetic.json"


class ReviewTimeStudyTests(unittest.TestCase):
    def setUp(self):
        self.example = json.loads(EXAMPLE.read_text("utf-8"))

    def test_synthetic_twenty_task_balanced_results(self):
        result = analyze_paired_study(self.example)
        self.assertEqual(result["status"], "CURATED_SYNTHETIC_ONLY")
        self.assertEqual(result["task_count"], 20)
        self.assertEqual(result["order_counts"], {"FRI_FIRST": 10, "MANUAL_FIRST": 10})
        self.assertTrue(result["minimum_sample_and_order_balance_met"])
        self.assertTrue(result["observed_quality_noninferiority"])
        self.assertGreater(result["median_paired_speedup"], 1)
        self.assertFalse(result["eligible_for_independent_private_review"])
        self.assertFalse(result["real_world_100x_confirmed"])
        self.assertFalse(result["causal_efficiency_gain_established"])
        self.assertFalse(result["scientific_authority"])
        self.assertFalse(result["broker_authority"])

    def test_private_self_report_cannot_be_called_proof(self):
        actual = copy.deepcopy(self.example)
        actual["source_class"] = "SELF_REPORTED_PRIVATE_OPERATOR"
        result = analyze_paired_study(actual)
        self.assertEqual(result["status"], "SELF_REPORTED_PRIVATE_PILOT")
        self.assertTrue(result["eligible_for_independent_private_review"])
        self.assertFalse(result["real_world_100x_confirmed"])
        self.assertFalse(result["causal_efficiency_gain_established"])

    def test_quality_regression_prevents_noninferiority(self):
        x = copy.deepcopy(self.example)
        x["tasks"][0]["fri_correct"] = False
        x["tasks"][1]["fri_citations_correct"] = False
        x["tasks"][2]["fri_independence_error"] = True
        result = analyze_paired_study(x)
        self.assertFalse(result["observed_quality_noninferiority"])
        self.assertEqual(result["fri_worse_on_any_quality_dimension_tasks"], 3)
        self.assertEqual(result["fri_false_independence_claims"], 1)

    def test_bad_elapsed_times_fail(self):
        for seconds in (0, -1, float("nan"), float("inf"), True, "120", 28801):
            x = copy.deepcopy(self.example)
            x["tasks"][0]["fri_seconds"] = seconds
            with self.subTest(seconds=seconds), self.assertRaises(EvidenceError):
                analyze_paired_study(x)

    def test_extra_free_text_or_paths_rejected(self):
        for field in ("operator_name", "source_url", "strategy_params", "secret_path"):
            x = copy.deepcopy(self.example)
            x["tasks"][0][field] = "private"
            with self.subTest(field=field), self.assertRaises(EvidenceError):
                analyze_paired_study(x)

    def test_missing_tasks_invalid_order_duplicate_id(self):
        x = copy.deepcopy(self.example)
        x["tasks"] = []
        with self.assertRaises(EvidenceError):
            analyze_paired_study(x)
        x = copy.deepcopy(self.example)
        x["tasks"][1]["task_id"] = x["tasks"][0]["task_id"]
        with self.assertRaises(EvidenceError):
            analyze_paired_study(x)
        x = copy.deepcopy(self.example)
        x["tasks"][1]["order"] = "UNKNOWN"
        with self.assertRaises(EvidenceError):
            analyze_paired_study(x)

    def test_small_or_unbalanced_sample_not_qualified(self):
        x = copy.deepcopy(self.example)
        x["tasks"] = x["tasks"][:10]
        self.assertFalse(analyze_paired_study(x)["minimum_sample_and_order_balance_met"])
        x = copy.deepcopy(self.example)
        for row in x["tasks"]:
            row["order"] = "MANUAL_FIRST"
        self.assertFalse(analyze_paired_study(x)["minimum_sample_and_order_balance_met"])

    def test_reproducible_digest_and_no_task_identifiers(self):
        a = analyze_paired_study(self.example)
        b = analyze_paired_study(self.example)
        self.assertEqual(a, b)
        self.assertEqual(len(a["report_sha256"]), 64)
        blob = json.dumps(a)
        self.assertNotIn("TASK-001", blob)
        self.assertNotIn(str(EXAMPLE.parent), blob)

    def test_cli_study_and_unknown_schema(self):
        self.assertEqual(main(["review", "study", "--input", str(EXAMPLE)]), 0)
        bad = copy.deepcopy(self.example)
        bad["source_class"] = "VERIFIED_PRODUCTION"
        with self.assertRaises(EvidenceError):
            analyze_paired_study(bad)


if __name__ == "__main__":
    unittest.main()
