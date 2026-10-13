"""Operator study CLI qualification with no Core data or claims of 100x causality."""
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


class ReviewStudyProtocolCLITests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        source, trust, db = self.root / "fixture", self.root / "test-keys.json", self.root / "research.sqlite"
        create_synthetic_fixture(source, trust)
        ingest(source, db, trust_store=trust)
        self.pack = self.root / "pack"
        publish_review_pack(build_review_pack(db), self.pack)

    def _plan(self):
        path = self.root / "study-plan.json"
        self.assertEqual(main(["review", "study-plan", "--dir", str(self.pack),
                               "--tasks", "20", "--out", str(path)]), 0)
        return path

    def _measure(self, plan):
        data = {"schema_version": 1, "source_class": "CURATED_SYNTHETIC_ONLY",
                "tasks": [{
                    "task_id": task["task_id"], "order": task["order"],
                    "manual_seconds": 180, "fri_seconds": 45,
                    "manual_correct": True, "fri_correct": True,
                    "manual_citations_correct": True, "fri_citations_correct": True,
                    "manual_independence_error": False, "fri_independence_error": False,
                } for task in plan["assignments"]]}
        path = self.root / "synthetic-measurements.json"
        path.write_text(json.dumps(data), "utf-8")
        return path

    def test_private_plan_and_reconcile_end_to_end(self):
        planpath = self._plan()
        plan = read_private_json(planpath)
        self.assertEqual(plan["task_count"], 20)
        input_path = self._measure(plan)
        out = self.root / "study-result.json"
        argv = ["review", "study-reconcile", "--dir", str(self.pack),
                "--plan", str(planpath), "--input", str(input_path), "--out", str(out)]
        self.assertEqual(main(argv), 0)
        response = read_private_json(out)
        self.assertTrue(response["all_task_orders_match_assignment"])
        self.assertFalse(response["real_world_100x_confirmed"])
        self.assertFalse(response["scientific_authority"])
        self.assertEqual(main(argv), 2)

    def test_posthoc_assignment_edit_rejected(self):
        planpath = self._plan()
        plan = read_private_json(planpath)
        input_path = self._measure(plan)
        amended = read_private_json(input_path)
        original = amended["tasks"][0]["order"]
        amended["tasks"][0]["order"] = "FRI_FIRST" if original == "MANUAL_FIRST" else "MANUAL_FIRST"
        input_path.write_text(json.dumps(amended), "utf-8")
        out = self.root / "result.json"
        self.assertEqual(main(["review", "study-reconcile", "--dir", str(self.pack),
                               "--plan", str(planpath), "--input", str(input_path),
                               "--out", str(out)]), 2)
        self.assertFalse(out.exists())

    def test_output_into_pack_rejected(self):
        output = self.pack / "plan.json"
        self.assertEqual(main(["review", "study-plan", "--dir", str(self.pack),
                               "--out", str(output)]), 2)
        self.assertFalse(output.exists())

    def test_invalid_task_count_rejected_without_file(self):
        output = self.root / "bad-plan.json"
        self.assertEqual(main(["review", "study-plan", "--dir", str(self.pack),
                               "--tasks", "10", "--out", str(output)]), 2)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
