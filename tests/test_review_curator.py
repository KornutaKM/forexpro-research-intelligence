"""Human-curated rubric smoke tests: missing, tampered, conflicting assessments."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import ingest
from forexpro_ri.review_pack import build_review_pack
from forexpro_ri.review_curator import (
    curator_template, assess_curator_rubric, compare_curator_rubrics,
)


class CuratorRubricTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        bundle, trust, db = root / "synthetic", root / "test-keys.json", root / "memory.sqlite"
        create_synthetic_fixture(bundle, trust)
        ingest(bundle, db, trust_store=trust)
        self.pack = build_review_pack(db, expected_procedures=["MONTE_CARLO", "REGIME_STABILITY"])

    def filled(self):
        row = curator_template(self.pack)
        for item in row["items"]:
            item.update({
                "grounding": "SUPPORTED_BY_RECORDED_EVIDENCE",
                "usefulness": "USEFUL_RESEARCH_QUESTION",
                "duplication": "NOT_IDENTIFIED_IN_REVIEWED_CORPUS",
                "scientific_language": "BOUNDED_ADVISORY_ONLY",
            })
        return row

    def test_template_has_no_fabricated_human_assessment(self):
        a = curator_template(self.pack)
        self.assertEqual(len(a["items"]), len(self.pack["review_topics"]))
        self.assertTrue(all(item["grounding"] == "UNREVIEWED" for item in a["items"]))
        output = assess_curator_rubric(self.pack, a)
        self.assertEqual(output["fully_labeled_items"], 0)
        self.assertEqual(len(output["unresolved_topic_ids"]), output["topic_count"])
        self.assertFalse(output["independent_reviewer_authenticated"])
        self.assertFalse(any(output["authority"].values()))

    def test_all_favorable_self_labels_do_not_approve_science(self):
        result = assess_curator_rubric(self.pack, self.filled())
        self.assertEqual(result["fully_labeled_items"], len(self.pack["review_topics"]))
        self.assertEqual(result["unresolved_topic_ids"], [])
        self.assertEqual(result["unsupported_or_problematic_topic_ids"], [])
        self.assertFalse(result["scientific_correctness_established"])
        self.assertFalse(result["export_authority_established"])
        self.assertFalse(any(result["authority"].values()))

    def test_identify_specific_bad_and_uncertain_questions(self):
        data = self.filled()
        data["items"][0]["grounding"] = "UNSUPPORTED_BY_RECORDED_EVIDENCE"
        data["items"][1]["duplication"] = "POTENTIALLY_DUPLICATIVE"
        data["items"][2]["scientific_language"] = "CANNOT_DETERMINE"
        result = assess_curator_rubric(self.pack, data)
        self.assertEqual(len(result["unsupported_or_problematic_topic_ids"]), 2)
        self.assertEqual(len(result["unresolved_topic_ids"]), 1)
        self.assertEqual(result["dimensions"]["grounding"]["UNSUPPORTED_BY_RECORDED_EVIDENCE"], 1)

    def test_missing_unknown_and_duplicate_topic_rejected(self):
        for mutation in ("missing", "unknown", "duplicate"):
            values = self.filled()
            if mutation == "missing":
                values["items"].pop()
            elif mutation == "unknown":
                values["items"][0]["item_id"] = "unknown"
            else:
                values["items"][1]["item_id"] = values["items"][0]["item_id"]
            with self.subTest(mutation=mutation), self.assertRaises(EvidenceError):
                assess_curator_rubric(self.pack, values)

    def test_unknown_dimension_and_free_text_or_identity_rejected(self):
        for bad in ("GROUNDING_ERROR", "<script>", "BUY"):
            form = self.filled()
            form["items"][0]["grounding"] = bad
            with self.subTest(bad=bad), self.assertRaises(EvidenceError):
                assess_curator_rubric(self.pack, form)
        form = self.filled()
        form["items"][0]["researcher_name"] = "private"
        with self.assertRaises(EvidenceError):
            assess_curator_rubric(self.pack, form)

    def test_stale_source_report_sha_and_schema_rejected(self):
        data = self.filled()
        data["source_pack_sha256"] = "f" * 64
        with self.assertRaises(EvidenceError):
            assess_curator_rubric(self.pack, data)
        data = self.filled()
        data["rubric_version"] = "SCIENTIFIC_ADMISSION"
        with self.assertRaises(EvidenceError):
            assess_curator_rubric(self.pack, data)

    def test_different_rubrics_surface_item_dimension_conflict(self):
        left = assess_curator_rubric(self.pack, self.filled())
        other = self.filled()
        other["items"][0]["usefulness"] = "NOT_USEFUL"
        right = assess_curator_rubric(self.pack, other)
        comparison = compare_curator_rubrics(self.pack, left, right)
        self.assertEqual(len(comparison["disagreements"]), 1)
        self.assertEqual(comparison["disagreements"][0]["dimension"], "usefulness")
        self.assertFalse(comparison["independent_reviewers_established"])
        self.assertFalse(comparison["human_consensus_attested"])
        self.assertFalse(comparison["scientific_authority"])

    def test_identical_documents_never_prove_second_reviewer(self):
        same = assess_curator_rubric(self.pack, self.filled())
        with self.assertRaisesRegex(EvidenceError, "identical"):
            compare_curator_rubrics(self.pack, same, copy.deepcopy(same))

    def test_forged_reviewed_json_even_without_sha_change_rejected(self):
        left = assess_curator_rubric(self.pack, self.filled())
        form = self.filled()
        form["items"][0]["grounding"] = "CANNOT_DETERMINE"
        right = assess_curator_rubric(self.pack, form)
        target_id = form["items"][0]["item_id"]
        next(x for x in right["items"] if x["item_id"] == target_id)[
            "grounding"
        ] = "SUPPORTED_BY_RECORDED_EVIDENCE"
        with self.assertRaises(EvidenceError):
            compare_curator_rubrics(self.pack, left, right)

    def test_forged_authority_or_identity_rejected(self):
        a = assess_curator_rubric(self.pack, self.filled())
        form = self.filled()
        form["items"][0]["grounding"] = "CANNOT_DETERMINE"
        b = assess_curator_rubric(self.pack, form)
        b["independent_reviewer_authenticated"] = True
        with self.assertRaises(EvidenceError):
            compare_curator_rubrics(self.pack, a, b)

    def test_order_independent_determinism(self):
        a = self.filled()
        b = self.filled()
        b["items"] = list(reversed(b["items"]))
        self.assertEqual(assess_curator_rubric(self.pack, a),
                         assess_curator_rubric(self.pack, b))


if __name__ == "__main__":
    unittest.main()
