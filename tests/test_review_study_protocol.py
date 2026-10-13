"""Counterbalanced timing protocol rejects post-hoc and missing-task manipulation."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import ingest
from forexpro_ri.review_pack import build_review_pack
from forexpro_ri.review_study_protocol import make_study_plan, assess_planned_study


class StudyProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.temp = temp
        base = Path(temp.name)
        fixture, trust, db = base / "signed", base / "trust.json", base / "memory.sqlite"
        create_synthetic_fixture(fixture, trust)
        ingest(fixture, db, trust_store=trust)
        cls.pack = build_review_pack(db)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    @staticmethod
    def metrics(plan):
        return {
            "schema_version": 1, "source_class": "CURATED_SYNTHETIC_ONLY",
            "tasks": [
                {
                    "task_id": row["task_id"], "order": row["order"],
                    "manual_seconds": 300 + i,
                    "fri_seconds": 60 + i,
                    "manual_correct": True, "fri_correct": True,
                    "manual_citations_correct": True, "fri_citations_correct": True,
                    "manual_independence_error": False,
                    "fri_independence_error": False,
                }
                for i, row in enumerate(plan["assignments"])
            ],
        }

    def test_balanced_repeatable_plan(self):
        a = make_study_plan(self.pack, task_count=20)
        b = make_study_plan(self.pack, task_count=20)
        self.assertEqual(a, b)
        self.assertEqual({x["order"] for x in a["assignments"]}, {"FRI_FIRST", "MANUAL_FIRST"})
        self.assertEqual(sum(x["order"] == "MANUAL_FIRST" for x in a["assignments"]), 10)
        self.assertFalse(a["blinding_established"])
        self.assertFalse(a["randomization_independently_verified"])
        self.assertFalse(a["scientific_authority"])

    def test_odd_task_count_balanced_with_one_difference(self):
        a = make_study_plan(self.pack, task_count=21)
        counts = {order: sum(x["order"] == order for x in a["assignments"])
                  for order in ("MANUAL_FIRST", "FRI_FIRST")}
        self.assertEqual(sorted(counts.values()), [10, 11])

    def test_synthetic_measurements_match_without_100x_claim(self):
        plan = make_study_plan(self.pack)
        study = self.metrics(plan)
        result = assess_planned_study(self.pack, plan, study)
        self.assertTrue(result["all_task_orders_match_assignment"])
        self.assertEqual(result["paired_study"]["task_count"], 20)
        self.assertGreater(result["paired_study"]["median_paired_speedup"], 1)
        self.assertFalse(result["real_world_100x_confirmed"])
        self.assertFalse(result["independent_assessor_verified"])
        self.assertFalse(result["causality_established"])
        self.assertFalse(result["broker_authority"])

    def test_forged_plan_sha_and_order_rejected(self):
        plan = make_study_plan(self.pack)
        data = self.metrics(plan)
        for key in ("sha", "order", "task", "extra"):
            forged = copy.deepcopy(plan)
            if key == "sha":
                forged["report_sha256"] = "0" * 64
            elif key == "order":
                forged["assignments"][0]["order"] = (
                    "MANUAL_FIRST" if forged["assignments"][0]["order"] == "FRI_FIRST" else "FRI_FIRST"
                )
            elif key == "task":
                forged["assignments"][0]["task_id"] = "TASK-999"
            else:
                forged["scientific_authority"] = True
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                assess_planned_study(self.pack, forged, data)

    def test_changing_task_order_or_duplicate_id_rejected(self):
        plan = make_study_plan(self.pack)
        for mutation in ("order", "duplicate", "missing", "extra"):
            data = self.metrics(plan)
            if mutation == "order":
                original = data["tasks"][0]["order"]
                data["tasks"][0]["order"] = "MANUAL_FIRST" if original == "FRI_FIRST" else "FRI_FIRST"
            elif mutation == "duplicate":
                data["tasks"][1]["task_id"] = data["tasks"][0]["task_id"]
            elif mutation == "missing":
                data["tasks"].pop()
            else:
                data["tasks"].append(copy.deepcopy(data["tasks"][0]))
            with self.subTest(mutation=mutation), self.assertRaises(EvidenceError):
                assess_planned_study(self.pack, plan, data)

    def test_alternative_source_pack_rejected(self):
        plan = make_study_plan(self.pack)
        data = self.metrics(plan)
        another = copy.deepcopy(self.pack)
        another["report_sha256"] = "f" * 64
        with self.assertRaises(EvidenceError):
            assess_planned_study(another, plan, data)

    def test_invalid_task_count_and_bool_rejected(self):
        for value in (0, 19, 101, True, "20"):
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                make_study_plan(self.pack, task_count=value)

    def test_no_synthetic_source_path_in_reports(self):
        plan = make_study_plan(self.pack)
        result = assess_planned_study(self.pack, plan, self.metrics(plan))
        body = json.dumps(result)
        self.assertNotIn("forexpro Core research", body)
        self.assertNotIn("https://", body)


if __name__ == "__main__":
    unittest.main()
