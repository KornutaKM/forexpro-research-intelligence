"""Adversarial tests for independent Research Review Pack semantic consistency.

All fixtures signed with an ephemeral test key, no ForexPro Core data.
"""
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
from forexpro_ri.review_integrity import audit_review_structure
from forexpro_ri.review_pack import (
    build_review_pack, publish_review_pack, render_review_html, verify_review_pack,
)


def rehash(report):
    report["report_sha256"] = hashlib.sha256(canonical_json({
        k: v for k, v in report.items() if k != "report_sha256"
    }).encode("utf-8")).hexdigest()
    return report


class ReviewIntegrityTests(unittest.TestCase):
    def setUp(self):
        handle = tempfile.TemporaryDirectory()
        self.addCleanup(handle.cleanup)
        self.root = Path(handle.name)
        bundle, keys, db = self.root / "signed-fixture", self.root / "trust.json", self.root / "memory.sqlite"
        create_synthetic_fixture(bundle, keys)
        ingest(bundle, db, trust_store=keys)
        self.report = build_review_pack(db, expected_procedures=["MONTE_CARLO", "REGIME_STABILITY"])

    def check_reject(self, modify):
        altered = copy.deepcopy(self.report)
        modify(altered)
        rehash(altered)
        with self.assertRaises(EvidenceError):
            verify_review_pack(altered)

    def test_valid_report_reconciles_all_procedures_and_sources(self):
        details = audit_review_structure(self.report)
        self.assertEqual(details["status"], "LOCAL_SEMANTIC_CONSISTENCY_PASS")
        self.assertEqual(details["checked_cases"], 1)
        self.assertEqual(details["checked_procedures"], 5)
        self.assertEqual(details["checked_criteria"], 3)
        self.assertEqual(details["checked_gaps"], 2)
        self.assertGreater(details["checked_citations"], 0)
        self.assertFalse(details["source_authenticated"])
        self.assertFalse(details["scientific_authority"])

    def test_all_unobserved_expected_procedure_is_not_omitted(self):
        procedures = {r["procedure"]: r for r in self.report["procedure_coverage"]}
        mc = procedures["MONTE_CARLO"]
        self.assertEqual(mc["unobserved_experiments"], 1)
        self.assertEqual(mc["passed_experiments"], 0)
        self.assertEqual(mc["failed_experiments"], 0)
        self.assertEqual(mc["not_evaluable_experiments"], 0)
        self.assertEqual(mc["failure_evidence"], [])
        self.assertIn("MONTE_CARLO", render_review_html(self.report))

    def test_rehashed_status_change_rejected(self):
        self.check_reject(lambda r: r["cases"][0]["procedure_outcomes"][0].update(
            recorded_status="PASS" if r["cases"][0]["procedure_outcomes"][0]["recorded_status"] != "PASS"
            else "FAIL"))

    def test_rehashed_gap_removed_rejected(self):
        self.check_reject(lambda r: r["cases"][0]["evidence_visibility_gaps"].clear())

    def test_rehashed_case_sha_rejected(self):
        self.check_reject(lambda r: r["cases"][0].update(entry_sha256="a" * 64))

    def test_rehashed_criterion_digest_type_rejected(self):
        self.check_reject(lambda r: r["cases"][0]["procedure_outcomes"][0][
            "criteria_evidence"].append({"criterion_id": "fake", "recorded_verdict": "PASS",
                                         "observation_sha256": "bogus"}))

    def test_rehashed_coverage_count_rejected(self):
        self.check_reject(lambda r: r["procedure_coverage"][0].update(passed_experiments=999))

    def test_rehashed_coverage_evidence_reference_rejected(self):
        def replace(report):
            for row in report["procedure_coverage"]:
                if row["failure_evidence"]:
                    row["failure_evidence"][0]["entry_sha256"] = "f" * 64
                    break
        self.check_reject(replace)

    def test_rehashed_topic_citation_rejected(self):
        def replace(report):
            for topic in report["review_topics"]:
                if topic["evidence_sample"]:
                    topic["evidence_sample"][0]["receipt_sha256"] = "f" * 64
                    break
        self.check_reject(replace)

    def test_rehashed_duplicate_topic_rejected(self):
        self.check_reject(lambda r: r["review_topics"].append(
            copy.deepcopy(r["review_topics"][0])))

    def test_rehashed_provenance_label_rejected(self):
        self.check_reject(lambda r: r["cases"][0].update(
            evidence_visibility="HISTORICAL_SIGNED_INTAKE_ONLY"))

    def test_rehashed_synthetic_identity_rejected(self):
        self.check_reject(lambda r: r["cases"][0].update(experiment_id="REAL-EXPERIMENT-123"))

    def test_rehashed_unsupported_authority_rejected(self):
        self.check_reject(lambda r: r["authority"].update(holdout=True))

    def test_rehashed_unknown_report_keys_rejected(self):
        self.check_reject(lambda r: r.update(strategy_parameters="private"))

    def test_report_ingestion_and_output_remain_immutable(self):
        output = self.root / "report"
        publish_review_pack(self.report, output)
        self.assertEqual(main(["review", "verify", "--dir", str(output)]), 0)
        forged = json.loads((output / "review.json").read_text("utf-8"))
        forged["cases"][0]["procedure_outcomes"][0]["recorded_status"] = "PASS"
        rehash(forged)
        (output / "review.json").write_text(json.dumps(forged))
        self.assertEqual(main(["review", "verify", "--dir", str(output)]), 2)

    def test_empty_state_is_explicit_and_consistent(self):
        missing = build_review_pack(self.root / "missing.sqlite")
        summary = audit_review_structure(missing)
        self.assertEqual(summary["status"], "SELF_CONSISTENT_EMPTY_REPORT")
        missing["experiment_count"] = 1
        rehash(missing)
        with self.assertRaises(EvidenceError):
            verify_review_pack(missing)


if __name__ == "__main__":
    unittest.main()
