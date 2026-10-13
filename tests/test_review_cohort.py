"""Issue #19 P2: twenty closed synthetic scenarios with independent gold labels."""
from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.analysis import canonical_json
from forexpro_ri.attestation import verify_export
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.review_cohort import make_signed_cohort
from forexpro_ri.review_pack import build_review_pack, publish_review_pack, render_review_html
from forexpro_ri.review_quality import score_review_pack

GOLD = Path(__file__).resolve().parents[1] / "examples" / "review_cohort_gold.json"


class ReviewCohortTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.db = self.root / "research.sqlite"

    def load(self):
        meta = make_signed_cohort(self.root, self.db)
        labels = json.loads(GOLD.read_text(encoding="utf-8"))
        pack = build_review_pack(self.db, expected_procedures=meta["expected_procedures"])
        return meta, labels, pack

    def test_curated_twenty_case_cohort_hundred_twenty_truth_checks(self):
        meta, labels, pack = self.load()
        self.assertEqual(meta["status"], "SYNTHETIC_SIGNED_COHORT_CREATED")
        self.assertEqual(meta["experiment_ids"], sorted(labels["expected_cases"]))
        self.assertFalse(meta["private_key_persisted"])
        self.assertFalse(meta["independent_replication_established"])
        self.assertEqual(pack["status"], "SYNTHETIC_SIGNED_DEMONSTRATION")
        self.assertEqual(pack["experiment_count"], 20)
        self.assertEqual(len(pack["cases"]), 20)
        self.assertFalse(any(pack["authority"].values()))
        score = score_review_pack(pack, labels)
        self.assertEqual(score["status"], "STRUCTURAL_PASS")
        self.assertEqual(score["procedure_checks"], 120)
        self.assertEqual(score["correct_procedure_statuses"], 120)
        self.assertEqual(score["false_citation_links"], 0)
        self.assertFalse(score["real_operator_time_savings_established"])

    def test_repeated_negatives_and_shared_lineage_not_independence(self):
        meta, _, pack = self.load()
        outcomes = {case["experiment_id"]: {
            row["procedure"]: row["recorded_status"]
            for row in case["procedure_outcomes"]
        } for case in pack["cases"]}
        self.assertEqual(outcomes["SYNTHETIC-COHORT-01"], outcomes["SYNTHETIC-COHORT-02"])
        self.assertTrue(pack["cases"][0]["similar_observed_cases"])
        cases_13 = outcomes["SYNTHETIC-COHORT-13"]
        self.assertEqual(cases_13["OUT_OF_SAMPLE"], "FAIL")
        self.assertIn("distinct experiment IDs do not imply independent replication",
                      " ".join(pack["limitations"]))
        self.assertIn("not independent replication", render_review_html(pack))

    def test_six_distinct_scientific_outcome_columns_retained(self):
        _, _, pack = self.load()
        coverage = {row["procedure"]: row for row in pack["procedure_coverage"]}
        self.assertEqual(len(coverage), 6)
        for row in coverage.values():
            self.assertEqual(sum(row[k] for k in (
                "failed_experiments", "passed_experiments",
                "not_evaluable_experiments", "unobserved_experiments",
            )), 20)
        self.assertEqual(coverage["REGIME_STABILITY"]["unobserved_experiments"], 9)
        self.assertEqual(coverage["MONTE_CARLO"]["not_evaluable_experiments"], 8)
        self.assertGreaterEqual(len(pack["review_topics"]), 6)

    def test_identical_report_from_same_memory_bytes(self):
        meta, _, pack = self.load()
        repeat = build_review_pack(self.db, expected_procedures=meta["expected_procedures"])
        self.assertEqual(pack, repeat)
        self.assertEqual(render_review_html(pack).encode("utf-8"),
                         render_review_html(repeat).encode("utf-8"))

    def test_all_signed_bundles_have_synthetic_test_key(self):
        meta, _, _ = self.load()
        trust = self.root / "synthetic-public-keys.json"
        for eid in meta["experiment_ids"]:
            _, _, receipt = verify_export(self.root / eid, trust)
            self.assertEqual(receipt["status"], "SIGNATURE_VERIFIED")

    def test_reject_modified_original_source_bundle(self):
        meta, _, _ = self.load()
        target = self.root / meta["experiment_ids"][0] / "summary.json"
        target.write_bytes(target.read_bytes().replace(b"SYNTHETIC:", b"FALSIFIED:"))
        with self.assertRaises(EvidenceError):
            verify_export(self.root / meta["experiment_ids"][0],
                          self.root / "synthetic-public-keys.json")

    def test_reject_modified_memory(self):
        self.load()
        with sqlite3.connect(self.db) as db:
            db.execute("DROP TRIGGER criteria_no_update")
            db.execute("UPDATE criteria SET verdict='PASS' WHERE verdict='FAIL'")
        with self.assertRaises(EvidenceError):
            build_review_pack(self.db)

    def test_curator_labels_detect_substituted_verdict(self):
        _, labels, pack = self.load()
        fake = copy.deepcopy(pack)
        fake["cases"][0]["procedure_outcomes"][0]["recorded_status"] = "PASS"
        fake["report_sha256"] = hashlib.sha256(canonical_json({
            k: v for k, v in fake.items() if k != "report_sha256"
        }).encode("utf-8")).hexdigest()
        quality = score_review_pack(fake, labels)
        self.assertEqual(quality["status"], "REQUIRES_CURATOR_REVIEW")
        self.assertGreater(len(quality["incorrect_procedure_statuses"]), 0)

    def test_bad_labels_not_scored_as_success(self):
        _, labels, pack = self.load()
        labels["expected_cases"].pop("SYNTHETIC-COHORT-20")
        with self.assertRaises(EvidenceError):
            score_review_pack(pack, labels)

    def test_one_command_cohort_demo_and_benchmark(self):
        dest = self.root / "output"
        self.assertEqual(main(["review", "cohort-demo", "--out", str(dest)]), 0)
        self.assertEqual(main(["review", "verify", "--dir", str(dest)]), 0)
        self.assertEqual(main(["review", "benchmark", "--dir", str(dest),
                               "--labels", str(GOLD)]), 0)
        packed = json.loads((dest / "review.json").read_text(encoding="utf-8"))
        self.assertEqual(packed["experiment_count"], 20)
        self.assertEqual(packed["status"], "SYNTHETIC_SIGNED_DEMONSTRATION")
        self.assertFalse(any(packed["authority"].values()))

    def test_repeated_generation_refused_without_overwrite(self):
        self.load()
        with self.assertRaises(EvidenceError):
            make_signed_cohort(self.root, self.db)

    def test_html_has_only_local_citation_anchors(self):
        _, _, pack = self.load()
        page = render_review_html(pack)
        self.assertEqual(page.count('<article id="case-'), 20)
        self.assertNotIn("https://", page)
        self.assertNotIn("file://", page)
        self.assertNotIn(str(self.root), page)
        self.assertNotIn("<script", page)


if __name__ == "__main__":
    unittest.main()
