"""Curated synthetic benchmark: report fidelity is not real research validity."""
from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.analysis import canonical_json
from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import ingest
from forexpro_ri.review_pack import build_review_pack, publish_review_pack
from forexpro_ri.review_quality import score_review_pack

LABELS = Path(__file__).resolve().parents[1] / "examples" / "review_benchmark_labels.json"


class ReviewQualityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        bundle, trust, db = root / "signed", root / "trust.json", root / "memory.sqlite"
        create_synthetic_fixture(bundle, trust)
        ingest(bundle, db, trust_store=trust)
        self.root = root
        self.pack = build_review_pack(db, expected_procedures=["MONTE_CARLO", "REGIME_STABILITY"])
        self.labels = json.loads(LABELS.read_text())

    def _rehash(self, obj):
        obj["report_sha256"] = hashlib.sha256(canonical_json({
            k: v for k, v in obj.items() if k != "report_sha256"
        }).encode()).hexdigest()
        return obj

    def test_curated_labels_match_signed_synthetic_fixture(self):
        result = score_review_pack(self.pack, self.labels)
        self.assertEqual(result["status"], "STRUCTURAL_PASS")
        self.assertEqual(result["procedure_checks"], 5)
        self.assertEqual(result["correct_procedure_statuses"], 5)
        self.assertEqual(result["false_citation_links"], 0)
        self.assertFalse(result["real_operator_time_savings_established"])
        self.assertFalse(result["scientific_authority"])
        self.assertFalse(result["causal_or_profitability_validity_established"])

    def test_wrong_status_is_measured_not_hidden(self):
        falsified = copy.deepcopy(self.pack)
        for row in falsified["cases"][0]["procedure_outcomes"]:
            if row["procedure"] == "REGIME_STABILITY":
                row["recorded_status"] = "PASS"
        self._rehash(falsified)
        result = score_review_pack(falsified, self.labels)
        self.assertEqual(result["status"], "REQUIRES_CURATOR_REVIEW")
        self.assertEqual(len(result["incorrect_procedure_statuses"]), 1)

    def test_forged_citation_fails_quality(self):
        forged = copy.deepcopy(self.pack)
        for item in forged["review_topics"]:
            if item["evidence_sample"]:
                item["evidence_sample"][0]["receipt_sha256"] = "a" * 64
                break
        self._rehash(forged)
        result = score_review_pack(forged, self.labels)
        self.assertGreater(result["false_citation_links"], 0)
        self.assertEqual(result["status"], "REQUIRES_CURATOR_REVIEW")

    def test_missing_review_topic_fails(self):
        altered = copy.deepcopy(self.pack)
        altered["review_topics"].pop()
        self._rehash(altered)
        result = score_review_pack(altered, self.labels)
        self.assertEqual(result["status"], "REQUIRES_CURATOR_REVIEW")
        self.assertTrue(result["missing_expected_review_topics"])

    def test_self_derived_or_non_synthetic_labels_rejected(self):
        invalid = copy.deepcopy(self.labels)
        invalid["source_class"] = "REAL_CORE"
        with self.assertRaises(EvidenceError):
            score_review_pack(self.pack, invalid)
        invalid = copy.deepcopy(self.labels)
        invalid["expected_cases"] = {}
        with self.assertRaises(EvidenceError):
            score_review_pack(self.pack, invalid)

    def test_cli_benchmark_after_verified_publication(self):
        directory = self.root / "private-report"
        publish_review_pack(self.pack, directory)
        self.assertEqual(main(["review", "benchmark", "--dir", str(directory),
                               "--labels", str(LABELS)]), 0)

    def test_causal_escalation_is_not_scored_as_valid(self):
        bad = copy.deepcopy(self.pack)
        bad["review_topics"][0]["interpretation"] = "PROVES_PROFIT"
        self._rehash(bad)
        with self.assertRaises(EvidenceError):
            score_review_pack(bad, self.labels)

    def test_report_digest_required(self):
        bad = copy.deepcopy(self.pack)
        bad["cases"][0]["recorded_disposition"] = "FALSIFIED"
        with self.assertRaises(EvidenceError):
            score_review_pack(bad, self.labels)


if __name__ == "__main__":
    unittest.main()
