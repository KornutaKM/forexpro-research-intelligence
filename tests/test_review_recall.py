"""Question-level synthetic recall scoring and false-positive/false-negative controls."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.analysis import canonical_json
from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import ingest
from forexpro_ri.review_cohort import make_signed_cohort
from forexpro_ri.review_pack import build_review_pack
from forexpro_ri.review_recall import evaluate_advisor_recall

GOLD = Path(__file__).resolve().parents[1] / "examples" / "review_question_recall_gold.json"


class QuestionRecallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.temp = temp
        cls.root = Path(temp.name)
        db = cls.root / "cohort.sqlite"
        created = make_signed_cohort(cls.root, db)
        cls.pack = build_review_pack(db, expected_procedures=created["expected_procedures"])
        cls.gold = json.loads(GOLD.read_text("utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_scoped_synthetic_question_coverage(self):
        result = evaluate_advisor_recall(self.pack, self.gold)
        self.assertEqual(result["status"], "SCENARIO_LABELS_MATCH")
        self.assertEqual(result["true_positive_procedures"], 6)
        self.assertEqual(result["false_positive_procedures"], 0)
        self.assertEqual(result["false_negative_missed_procedures"], 0)
        self.assertEqual(result["true_negative_procedures"], 4)
        self.assertEqual(result["classification_denominator"], 10)
        self.assertEqual(result["precision"]["value"], 1)
        self.assertEqual(result["recall"]["value"], 1)
        self.assertFalse(result["external_human_validation_established"])
        self.assertFalse(result["scientific_authority"])

    def test_false_negatives_are_visible_instead_of_changing_gold(self):
        gold = copy.deepcopy(self.gold)
        one = next(x for x in gold["targets"] if x["procedure"] == "RISK_LIMITS")
        one["label"] = "SHOULD_REVIEW"
        result = evaluate_advisor_recall(self.pack, gold)
        self.assertEqual(result["false_negative_missed_procedures"], 1)
        self.assertEqual(result["recall"]["numerator"], 6)
        self.assertEqual(result["recall"]["denominator"], 7)
        self.assertEqual(result["status"], "NEEDS_REVIEW")

    def test_unneeded_questions_count_as_false_positive(self):
        gold = copy.deepcopy(self.gold)
        one = next(x for x in gold["targets"] if x["procedure"] == "COST_STRESS")
        one["label"] = "SHOULD_NOT_REVIEW"
        result = evaluate_advisor_recall(self.pack, gold)
        self.assertEqual(result["false_positive_procedures"], 1)
        self.assertEqual(result["precision"]["denominator"], 6)
        self.assertEqual(result["true_positive_procedures"], 5)
        self.assertEqual(result["status"], "NEEDS_REVIEW")

    def test_unknown_label_excluded_not_marked_pass(self):
        gold = copy.deepcopy(self.gold)
        one = next(x for x in gold["targets"] if x["procedure"] == "RISK_LIMITS")
        one["label"] = "CANNOT_DETERMINE"
        out = evaluate_advisor_recall(self.pack, gold)
        self.assertEqual(out["classification_denominator"], 9)
        self.assertEqual(out["uncertain_excluded_procedures"], 1)
        self.assertEqual(out["status"], "NEEDS_REVIEW")

    def test_zero_denominator_yields_null_not_false_confidence(self):
        gold = copy.deepcopy(self.gold)
        for item in gold["targets"]:
            item["label"] = "SHOULD_NOT_REVIEW"
        result = evaluate_advisor_recall(self.pack, gold)
        self.assertIsNone(result["recall"]["value"])
        self.assertEqual(result["recall"]["denominator"], 0)

    def test_missing_duplicate_unsupported_and_unordered_gold_rejected(self):
        for case in ("missing", "duplicate", "unsorted", "unsupported", "nonblind"):
            gold = copy.deepcopy(self.gold)
            if case == "missing":
                gold["targets"].pop()
            elif case == "duplicate":
                gold["targets"][1]["procedure"] = gold["targets"][0]["procedure"]
            elif case == "unsorted":
                gold["eligible_procedures"].reverse()
            elif case == "unsupported":
                gold["targets"][0]["label"] = "PROVEN_PROFIT"
            else:
                gold["label_provenance"] = "INDEPENDENT_REVIEW_COMPLETED"
            with self.subTest(case=case), self.assertRaises(EvidenceError):
                evaluate_advisor_recall(self.pack, gold)

    def test_extra_top_level_gold_fields_rejected(self):
        gold = copy.deepcopy(self.gold)
        gold["private_evidence"] = "source"
        with self.assertRaises(EvidenceError):
            evaluate_advisor_recall(self.pack, gold)

    def test_non_synthetic_historical_signed_pack_denied(self):
        pack = copy.deepcopy(self.pack)
        pack["status"] = "HISTORICAL_SIGNED_INTAKES"
        pack["intake_mode"] = "SIGNED_ONLY"
        for case in pack["cases"]:
            case["evidence_visibility"] = "HISTORICAL_SIGNED_INTAKE_ONLY"
        for item in pack["review_topics"]:
            item["evidence_visibility"] = "HISTORICAL_RECEIPT_NOT_CURRENT_EXPORT_PERMISSION"
        pack["report_sha256"] = hashlib.sha256(canonical_json({
            k:v for k,v in pack.items() if k!="report_sha256"
        }).encode()).hexdigest()
        with self.assertRaises(EvidenceError):
            evaluate_advisor_recall(pack, self.gold)

    def test_determinism_and_no_core_control(self):
        a = evaluate_advisor_recall(self.pack, self.gold)
        b = evaluate_advisor_recall(self.pack, self.gold)
        self.assertEqual(a, b)
        self.assertFalse(a["novelty_or_independence_established"])
        self.assertFalse(a["broker_authority"])
        self.assertEqual(len(a["report_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
