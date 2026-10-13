"""Human review sidecar: all decisions are private, unverified and non-executable."""
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
from forexpro_ri.review_decisions import decision_template, assess_review_decisions
from forexpro_ri.review_pack import build_review_pack, publish_review_pack


class HumanReviewDecisionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        fixture, trust, db = self.root / "fixture", self.root / "public-keys.json", self.root / "memory.sqlite"
        create_synthetic_fixture(fixture, trust)
        ingest(fixture, db, trust_store=trust)
        self.report = build_review_pack(db, expected_procedures=["MONTE_CARLO"])
        self.directory = self.root / "report"
        publish_review_pack(self.report, self.directory)

    def test_template_and_deferred_decisions(self):
        template = decision_template(self.report)
        self.assertEqual(template["source_pack_sha256"], self.report["report_sha256"])
        self.assertEqual(len(template["decisions"]), len(self.report["review_topics"]))
        self.assertTrue(all(x["choice"] == "DEFER" for x in template["decisions"]))
        assessed = assess_review_decisions(self.report, template)
        self.assertEqual(assessed["topic_count"], len(self.report["review_topics"]))
        self.assertEqual(assessed["decision_counts"]["DEFER"], assessed["topic_count"])
        self.assertFalse(any(assessed["authority"].values()))
        self.assertFalse(assessed["experiment_registered"])
        self.assertFalse(assessed["reviewer_identity_verified"])

    def test_accept_is_for_discussion_only(self):
        template = decision_template(self.report)
        template["decisions"][0]["choice"] = "ACCEPT_FOR_DISCUSSION"
        template["decisions"][0]["reason_code"] = "NEW_EXPERIMENT_QUESTION"
        result = assess_review_decisions(self.report, template)
        self.assertEqual(result["decision_counts"]["ACCEPT_FOR_DISCUSSION"], 1)
        self.assertFalse(any(result["authority"].values()))
        self.assertFalse(result["experiment_registered"])
        self.assertIn("does not preregister", " ".join(result["limitations"]))

    def test_reject_requires_reason_code(self):
        template = decision_template(self.report)
        template["decisions"][0]["choice"] = "REJECT"
        template["decisions"][0]["reason_code"] = "DUPLICATE_PRIOR_WORK"
        self.assertEqual(assess_review_decisions(self.report, template)["decision_counts"]["REJECT"], 1)

    def test_stale_sha_cannot_be_approved(self):
        submission = decision_template(self.report)
        submission["source_pack_sha256"] = "0" * 64
        with self.assertRaises(EvidenceError):
            assess_review_decisions(self.report, submission)

    def test_missing_unknown_repeated_ids_rejected(self):
        template = decision_template(self.report)
        template["decisions"].pop()
        with self.assertRaises(EvidenceError):
            assess_review_decisions(self.report, template)
        template = decision_template(self.report)
        template["decisions"][0]["item_id"] = "forged-topic"
        with self.assertRaises(EvidenceError):
            assess_review_decisions(self.report, template)
        template = decision_template(self.report)
        template["decisions"].append(copy.deepcopy(template["decisions"][0]))
        with self.assertRaises(EvidenceError):
            assess_review_decisions(self.report, template)

    def test_unsupported_metadata_and_executable_choices_rejected(self):
        template = decision_template(self.report)
        for name, val in (("CoreCommand", "RUN"), ("owner_name", "private person"),
                          ("approve_holdout", True)):
            bad = copy.deepcopy(template)
            bad["decisions"][0][name] = val
            with self.subTest(field=name), self.assertRaises(EvidenceError):
                assess_review_decisions(self.report, bad)
        bad = decision_template(self.report)
        bad["decisions"][0]["choice"] = "EXECUTE_EXPERIMENT"
        with self.assertRaises(EvidenceError):
            assess_review_decisions(self.report, bad)

    def test_unsupported_reason_rejected(self):
        bad = decision_template(self.report)
        bad["decisions"][0]["choice"] = "ACCEPT_FOR_DISCUSSION"
        bad["decisions"][0]["reason_code"] = "PENDING_REVIEW"
        with self.assertRaises(EvidenceError):
            assess_review_decisions(self.report, bad)

    def test_cli_template_private_assessment_roundtrip(self):
        template_file = self.root / "template.json"
        answer_file = self.root / "decision-result.json"
        self.assertEqual(main(["review", "decision-template", "--dir", str(self.directory),
                               "--out", str(template_file)]), 0)
        template = json.loads(template_file.read_text("utf-8"))
        template["decisions"][0]["choice"] = "REJECT"
        template["decisions"][0]["reason_code"] = "DUPLICATE_PRIOR_WORK"
        template_file.write_text(json.dumps(template))
        self.assertEqual(main(["review", "decisions", "--dir", str(self.directory),
                               "--input", str(template_file), "--out", str(answer_file)]), 0)
        result = json.loads(answer_file.read_text("utf-8"))
        self.assertEqual(result["decision_counts"]["REJECT"], 1)
        self.assertEqual(result["source_pack_sha256"], self.report["report_sha256"])
        self.assertFalse(result["experiment_registered"])
        self.assertEqual(main(["review", "decisions", "--dir", str(self.directory),
                               "--input", str(template_file), "--out", str(answer_file)]), 2)

    def test_cli_rejects_write_back_into_report_directory(self):
        file = self.directory / "reviewed.json"
        self.assertEqual(main(["review", "decision-template", "--dir", str(self.directory),
                               "--out", str(file)]), 2)
        self.assertFalse(file.exists())
        self.assertEqual(sorted(x.name for x in self.directory.iterdir()), ["index.html", "review.json"])


if __name__ == "__main__":
    unittest.main()
