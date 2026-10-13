"""Human discussion decisions cannot conceal unsupported or uncertain rubric ratings."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import ingest
from forexpro_ri.review_adjudication import reconcile_human_evidence
from forexpro_ri.review_curator import curator_template, assess_curator_rubric
from forexpro_ri.review_decisions import decision_template, assess_review_decisions
from forexpro_ri.review_pack import build_review_pack


class HumanEvidenceReconciliationTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        bundle, keys, db = root / "bundle", root / "trust.json", root / "db.sqlite"
        create_synthetic_fixture(bundle, keys)
        ingest(bundle, db, trust_store=keys)
        self.pack = build_review_pack(db, expected_procedures=["MONTE_CARLO"])
        self.choice = decision_template(self.pack)
        self.rubric = curator_template(self.pack)

    def _review(self):
        choices = assess_review_decisions(self.pack, self.choice)
        labels = assess_curator_rubric(self.pack, self.rubric)
        return reconcile_human_evidence(self.pack, choices, labels)

    def test_all_deferred_does_not_claim_approval(self):
        result = self._review()
        self.assertEqual(result["status"], "NO_RECORDED_CONFLICTS_NOT_APPROVAL")
        self.assertEqual(result["accepted_for_discussion_count"], 0)
        self.assertFalse(result["automated_veto_or_approval"])
        self.assertFalse(result["scientific_authority"])

    def test_accept_with_unreviewed_quality_triggers_human_reconciliation(self):
        self.choice["decisions"][0].update(
            choice="ACCEPT_FOR_DISCUSSION", reason_code="NEW_EXPERIMENT_QUESTION")
        result = self._review()
        self.assertEqual(result["questions_requiring_reconciliation"], 1)
        self.assertEqual(result["status"], "HUMAN_RECONCILIATION_REQUIRED")
        self.assertIn("GROUNDING_NOT_REVIEWED", result["conflicts"][0]["reason_codes"])
        self.assertFalse(result["core_feedback"])

    def test_unsupported_grounding_bad_language_duplicate_question_flagged(self):
        ident = self.choice["decisions"][0]["item_id"]
        self.choice["decisions"][0].update(
            choice="ACCEPT_FOR_DISCUSSION", reason_code="EVIDENCE_GAP_FOR_REVIEW")
        candidate = next(item for item in self.rubric["items"] if item["item_id"] == ident)
        candidate.update({
            "grounding": "UNSUPPORTED_BY_RECORDED_EVIDENCE",
            "scientific_language": "UNSUPPORTED_AUTHORITY_OR_CAUSAL_CLAIM",
            "usefulness": "NOT_USEFUL",
            "duplication": "POTENTIALLY_DUPLICATIVE",
        })
        result = self._review()
        self.assertEqual(result["questions_requiring_reconciliation"], 1)
        self.assertEqual(len(result["conflicts"][0]["reason_codes"]), 4)
        self.assertFalse(result["broker_authority"])

    def test_positive_human_labels_still_not_scientific_permission(self):
        ident = self.choice["decisions"][0]["item_id"]
        self.choice["decisions"][0].update(
            choice="ACCEPT_FOR_DISCUSSION", reason_code="NEW_EXPERIMENT_QUESTION")
        found = next(x for x in self.rubric["items"] if x["item_id"] == ident)
        found.update({
            "grounding": "SUPPORTED_BY_RECORDED_EVIDENCE",
            "scientific_language": "BOUNDED_ADVISORY_ONLY",
            "usefulness": "USEFUL_RESEARCH_QUESTION",
            "duplication": "NOT_IDENTIFIED_IN_REVIEWED_CORPUS",
        })
        out = self._review()
        self.assertEqual(out["questions_requiring_reconciliation"], 0)
        self.assertEqual(out["status"], "NO_RECORDED_CONFLICTS_NOT_APPROVAL")
        self.assertFalse(out["scientific_authority"])

    def test_stale_decision_sha_rejected(self):
        decided = assess_review_decisions(self.pack, self.choice)
        decided["source_pack_sha256"] = "0" * 64
        labeled = assess_curator_rubric(self.pack, self.rubric)
        with self.assertRaises(EvidenceError):
            reconcile_human_evidence(self.pack, decided, labeled)

    def test_forged_rubric_is_not_accepted(self):
        decided = assess_review_decisions(self.pack, self.choice)
        labeled = assess_curator_rubric(self.pack, self.rubric)
        labeled["authority"]["scientific"] = True
        with self.assertRaises(EvidenceError):
            reconcile_human_evidence(self.pack, decided, labeled)

    def test_repeatable_no_free_text_or_personal_data(self):
        one = self._review()
        two = self._review()
        self.assertEqual(one, two)
        self.assertFalse(one["human_identity_verified"])
        self.assertEqual(one["total_questions"], len(self.pack["review_topics"]))


if __name__ == "__main__":
    unittest.main()
