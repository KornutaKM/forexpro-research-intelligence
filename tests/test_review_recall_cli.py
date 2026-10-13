"""Complete private CLI qualification for synthetic omissions and evidence conflict."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.cli import main
from forexpro_ri.memory import ingest
from forexpro_ri.review_cohort import make_signed_cohort
from forexpro_ri.review_pack import build_review_pack, publish_review_pack
from forexpro_ri.review_secureio import read_private_json

GOLD = Path(__file__).resolve().parents[1] / "examples" / "review_question_recall_gold.json"


class ReviewRecallCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        db = cls.root / "cohort.sqlite"
        meta = make_signed_cohort(cls.root, db)
        pack = build_review_pack(db, expected_procedures=meta["expected_procedures"])
        cls.directory = cls.root / "verified"
        publish_review_pack(pack, cls.directory)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_recall_exact_gold_success(self):
        self.assertEqual(main(["review", "recall", "--dir", str(self.directory),
                               "--labels", str(GOLD)]), 0)

    def test_recall_false_negative_needs_review_and_exit_two(self):
        gold = read_private_json(GOLD)
        for row in gold["targets"]:
            if row["procedure"] == "RISK_LIMITS":
                row["label"] = "SHOULD_REVIEW"
        source = self.root / "alternate-gold.json"
        source.write_text(json.dumps(gold), encoding="utf-8")
        self.assertEqual(main(["review", "recall", "--dir", str(self.directory),
                               "--labels", str(source)]), 2)

    def test_mutated_json_cannot_be_scored(self):
        report = self.directory / "review.json"
        valid = report.read_text("utf-8")
        try:
            report.write_text(valid.replace('"schema_version": 1,',
                                            '"schema_version": 1, "schema_version": 1,', 1))
            self.assertEqual(main(["review", "recall", "--dir", str(self.directory),
                                   "--labels", str(GOLD)]), 2)
        finally:
            report.write_text(valid, encoding="utf-8")


class HumanReconciliationCLITests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        fixture, trust, db = self.root / "fixture", self.root / "keys.json", self.root / "memory.sqlite"
        create_synthetic_fixture(fixture, trust)
        ingest(fixture, db, trust_store=trust)
        self.directory = self.root / "pack"
        publish_review_pack(build_review_pack(db), self.directory)

    def test_accepted_unreviewed_is_flagged(self):
        decisions_form = self.root / "decision-form.json"
        rubric_form = self.root / "rubric-form.json"
        self.assertEqual(main(["review", "decision-template", "--dir", str(self.directory),
                               "--out", str(decisions_form)]), 0)
        self.assertEqual(main(["review", "rubric-template", "--dir", str(self.directory),
                               "--out", str(rubric_form)]), 0)
        raw = read_private_json(decisions_form)
        raw["decisions"][0].update(
            choice="ACCEPT_FOR_DISCUSSION", reason_code="NEW_EXPERIMENT_QUESTION"
        )
        decisions_form.write_text(json.dumps(raw), "utf-8")
        choice = self.root / "reviewed-decisions.json"
        rated = self.root / "scored-rubric.json"
        self.assertEqual(main(["review", "decisions", "--dir", str(self.directory),
                               "--input", str(decisions_form), "--out", str(choice)]), 0)
        self.assertEqual(main(["review", "rubric-score", "--dir", str(self.directory),
                               "--input", str(rubric_form), "--out", str(rated)]), 0)
        out = self.root / "reconciliation.json"
        argv = ["review", "reconcile-human", "--dir", str(self.directory),
                "--decisions", str(choice), "--rubric", str(rated), "--out", str(out)]
        self.assertEqual(main(argv), 0)
        result = read_private_json(out)
        self.assertEqual(result["questions_requiring_reconciliation"], 1)
        self.assertEqual(result["status"], "HUMAN_RECONCILIATION_REQUIRED")
        self.assertFalse(result["scientific_authority"])
        self.assertEqual(main(argv), 2)

    def test_unsafe_output_inside_pack_rejected(self):
        form = self.root / "decision-form.json"
        rubric_form = self.root / "rubric-form.json"
        main(["review", "decision-template", "--dir", str(self.directory), "--out", str(form)])
        main(["review", "rubric-template", "--dir", str(self.directory), "--out", str(rubric_form)])
        choice = self.root / "decisions.json"
        rated = self.root / "rubric.json"
        main(["review", "decisions", "--dir", str(self.directory), "--input", str(form), "--out", str(choice)])
        main(["review", "rubric-score", "--dir", str(self.directory), "--input", str(rubric_form), "--out", str(rated)])
        out = self.directory / "forbidden.json"
        self.assertEqual(main(["review", "reconcile-human", "--dir", str(self.directory),
                               "--decisions", str(choice), "--rubric", str(rated),
                               "--out", str(out)]), 2)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
