"""Rubric CLI E2E qualification: local templates, assessed sheets, discrepancy report."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.cli import main
from forexpro_ri.memory import ingest
from forexpro_ri.review_pack import build_review_pack, publish_review_pack
from forexpro_ri.review_secureio import read_private_json


class CuratorRubricCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        fixture, trust, db = self.root / "fixture", self.root / "trust.json", self.root / "memory.sqlite"
        create_synthetic_fixture(fixture, trust)
        ingest(fixture, db, trust_store=trust)
        pack = build_review_pack(db)
        self.directory = self.root / "report"
        publish_review_pack(pack, self.directory)

    def _fill(self, path):
        report = read_private_json(path)
        for item in report["items"]:
            item.update({
                "grounding": "SUPPORTED_BY_RECORDED_EVIDENCE",
                "usefulness": "USEFUL_RESEARCH_QUESTION",
                "duplication": "NOT_IDENTIFIED_IN_REVIEWED_CORPUS",
                "scientific_language": "BOUNDED_ADVISORY_ONLY",
            })
        path.write_text(json.dumps(report), encoding="utf-8")

    def test_full_template_score_compare_with_human_disagreement(self):
        one, two = self.root / "curator-a.json", self.root / "curator-b.json"
        for target in (one, two):
            self.assertEqual(main(["review", "rubric-template", "--dir", str(self.directory),
                                   "--out", str(target)]), 0)
            self._fill(target)
        changed = read_private_json(two)
        changed["items"][0]["grounding"] = "UNSUPPORTED_BY_RECORDED_EVIDENCE"
        two.write_text(json.dumps(changed), encoding="utf-8")
        scored = self.root / "scored-a.json", self.root / "scored-b.json"
        self.assertEqual(main(["review", "rubric-score", "--dir", str(self.directory),
                               "--input", str(one), "--out", str(scored)]), 0)
        self.assertEqual(main(["review", "rubric-score", "--dir", str(self.directory),
                               "--input", str(two), "--out", str(scored.with_name("scored-b.json"))]), 0)
        out = self.root / "diff.json"
        self.assertEqual(main(["review", "rubric-compare", "--dir", str(self.directory),
                               "--left", str(scored), "--right", str(scored.with_name("scored-b.json")),
                               "--out", str(out)]), 0)
        result = read_private_json(out)
        self.assertEqual(len(result["disagreements"]), 1)
        self.assertFalse(result["independent_reviewers_established"])
        self.assertEqual(main(["review", "rubric-compare", "--dir", str(self.directory),
                               "--left", str(scored), "--right", str(scored.with_name("scored-b.json")),
                               "--out", str(out)]), 2)

    def test_fails_if_attempting_write_inside_review_pack(self):
        out = self.directory / "rubric.json"
        self.assertEqual(main(["review", "rubric-template", "--dir", str(self.directory),
                               "--out", str(out)]), 2)
        self.assertFalse(out.exists())

    def test_hardlinked_sidecar_and_duplicate_labels_fail(self):
        original = self.root / "rubric.json"
        self.assertEqual(main(["review", "rubric-template", "--dir", str(self.directory),
                               "--out", str(original)]), 0)
        source = original.read_text("utf-8").replace('"items":', '"items": [], "items":', 1)
        original.write_text(source, encoding="utf-8")
        out = self.root / "output.json"
        self.assertEqual(main(["review", "rubric-score", "--dir", str(self.directory),
                               "--input", str(original), "--out", str(out)]), 2)
        self.assertFalse(out.exists())

    def test_unedited_template_reports_zero_manual_assessment(self):
        template = self.root / "blank.json"
        checked = self.root / "scored.json"
        self.assertEqual(main(["review", "rubric-template", "--dir", str(self.directory),
                               "--out", str(template)]), 0)
        self.assertEqual(main(["review", "rubric-score", "--dir", str(self.directory),
                               "--input", str(template), "--out", str(checked)]), 0)
        a = read_private_json(checked)
        self.assertEqual(a["fully_labeled_items"], 0)
        self.assertFalse(a["scientific_correctness_established"])


if __name__ == "__main__":
    unittest.main()
