"""Progress between two provenance-class-matched, append-only FRI review packs."""
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
from forexpro_ri.review_diff import compare_review_packs
from forexpro_ri.review_pack import build_review_pack, publish_review_pack

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class ReviewDiffTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.db = self.root / "history.sqlite"

    def synth(self):
        ingest(_EXAMPLES / "closed_synthetic", self.db, allow_unsigned_synthetic=True)
        previous = build_review_pack(self.db, allow_unsigned_synthetic=True,
                                     expected_procedures=["MONTE_CARLO"])
        ingest(_EXAMPLES / "closed_synthetic_peer", self.db, allow_unsigned_synthetic=True)
        current = build_review_pack(self.db, allow_unsigned_synthetic=True,
                                    expected_procedures=["MONTE_CARLO"])
        return previous, current

    def signed(self):
        fixture, trust = self.root / "fixture", self.root / "trust.json"
        create_synthetic_fixture(fixture, trust)
        ingest(fixture, self.db, trust_store=trust)
        return build_review_pack(self.db)

    def test_append_only_new_record_with_supported_links(self):
        a, b = self.synth()
        out = compare_review_packs(a, b)
        self.assertEqual(out["status"], "DESCRIPTIVE_CHANGE_ONLY")
        self.assertEqual(out["previous_case_count"], 1)
        self.assertEqual(out["current_case_count"], 2)
        self.assertEqual(out["new_record_count"], 1)
        self.assertEqual(out["new_closed_records"][0]["experiment_id"], "SYNTHETIC-002")
        self.assertTrue(out["coverage_changes"])
        self.assertFalse(out["improvement_established"])
        self.assertFalse(out["independence_or_causality_established"])
        self.assertFalse(out["source_export_authorization_established"])
        self.assertFalse(out["core_feedback"])

    def test_same_snapshot_no_fabricated_new_experiments(self):
        a, _ = self.synth()
        result = compare_review_packs(a, a)
        self.assertEqual(result["new_record_count"], 0)
        self.assertFalse(result["coverage_changes"])
        self.assertFalse(result["advisory_topics_added"])

    def test_record_removal_rejected(self):
        before, after = self.synth()
        with self.assertRaisesRegex(EvidenceError, "cannot lose"):
            compare_review_packs(after, before)

    def test_cross_signed_unsigned_synthetic_denied(self):
        before, _ = self.synth()
        other = self.root / "other.sqlite"
        fixture, trust = self.root / "signed", self.root / "keys.json"
        create_synthetic_fixture(fixture, trust)
        ingest(fixture, other, trust_store=trust)
        signed = build_review_pack(other)
        with self.assertRaisesRegex(EvidenceError, "provenance"):
            compare_review_packs(before, signed)

    def test_all_unobserved_expected_change_does_not_claim_new_result(self):
        signed = self.signed()
        after = build_review_pack(self.db, expected_procedures=["MONTE_CARLO"])
        result = compare_review_packs(signed, after)
        self.assertEqual(result["new_record_count"], 0)
        changes = {x["procedure"] for x in result["coverage_changes"]}
        self.assertIn("MONTE_CARLO", changes)
        self.assertFalse(result["improvement_established"])

    def test_forged_new_record_identity_denied_even_with_new_digest(self):
        before, after = self.synth()
        changed = copy.deepcopy(after)
        changed["cases"][0]["entry_sha256"] = "f" * 64
        with self.assertRaises(EvidenceError):
            compare_review_packs(before, changed)

    def test_real_core_or_trade_authority_not_conferred(self):
        before, after = self.synth()
        result = compare_review_packs(before, after)
        for key in ("scientific_authority", "holdout_access", "broker_authority",
                    "source_export_authorization_established", "core_feedback"):
            self.assertFalse(result[key])
        dumped = json.dumps(result)
        self.assertNotIn(str(self.root), dumped)
        self.assertNotIn("https://", dumped)

    def test_cli_creation_only_local_compare_and_semantic_audit(self):
        previous, current = self.synth()
        a, b = self.root / "previous", self.root / "current"
        publish_review_pack(previous, a)
        publish_review_pack(current, b)
        result_path = self.root / "progress.json"
        self.assertEqual(main(["review", "audit", "--dir", str(b)]), 0)
        self.assertEqual(main(["review", "compare", "--before", str(a), "--after", str(b),
                               "--out", str(result_path)]), 0)
        result = json.loads(result_path.read_text("utf-8"))
        self.assertEqual(result["new_record_count"], 1)
        self.assertFalse(result["scientific_authority"])
        self.assertEqual(main(["review", "compare", "--before", str(a), "--after", str(b),
                               "--out", str(result_path)]), 2)

    def test_cli_rejects_outfile_inside_pack_and_symlinks(self):
        previous, current = self.synth()
        a, b = self.root / "previous", self.root / "current"
        publish_review_pack(previous, a)
        publish_review_pack(current, b)
        inside = a / "progress.json"
        self.assertEqual(main(["review", "compare", "--before", str(a), "--after", str(b),
                               "--out", str(inside)]), 2)
        self.assertFalse(inside.exists())
        link = self.root / "alias"
        link.symlink_to(a, target_is_directory=True)
        self.assertEqual(main(["review", "audit", "--dir", str(link)]), 2)


if __name__ == "__main__":
    unittest.main()
