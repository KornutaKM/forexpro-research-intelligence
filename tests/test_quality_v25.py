"""v2.5 gold-case checks. Synthetic data only; no network/model execution."""
import copy
import hashlib
import unittest

from forexpro_ri.analysis import canonical_json
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.quality import assess_advisor


def report_fixture():
    ref = {"experiment_id": "SYNTHETIC-001", "entry_sha256": "a" * 64, "receipt_sha256": "b" * 64}
    item = {
        "item_id": "a" * 24, "kind": "REPEATED_FAILURE", "procedure": "OUT_OF_SAMPLE",
        "interpretation": "DESCRIPTIVE_NOT_CAUSAL", "recorded_experiment_count": 2,
        "cohort_experiment_count": 2, "evidence_sample": [ref],
        "evidence_sample_truncated": False, "full_evidence_program_sha256": "c" * 64,
    }
    obj = {"schema_version": 1, "report_kind": "NON_AUTHORITATIVE_RESEARCH_ADVISOR",
           "signed_only_gate_passed": True, "research_program_sha256": "c" * 64,
           "memory_snapshot_sha256": "d" * 64, "observed_experiment_count": 2,
           "proposal_count": 1, "proposals": [item], "model_inference": "NOT_REQUESTED",
           "authority": {x: False for x in ("scientific", "holdout", "promotion", "broker", "experiment_execution")},
           "limitations": ["No scientific authority"]}
    return rehash(obj)


def rehash(obj):
    obj.pop("report_sha256", None)
    obj["report_sha256"] = hashlib.sha256(canonical_json(obj).encode()).hexdigest()
    return obj


class QualityGateTests(unittest.TestCase):
    def test_baseline_metric(self):
        result = assess_advisor(report_fixture())
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["sample_grounded_proposals"], 1)
        self.assertEqual(result["sample_citation_count"], 1)
        self.assertFalse(result["model_semantic_truth_verified"])

    def test_reject_signed_gate_failure_even_if_digest_valid(self):
        value = report_fixture(); value["signed_only_gate_passed"] = False
        with self.assertRaises(EvidenceError): assess_advisor(rehash(value))
        self.assertEqual(assess_advisor(value, require_signed=False)["status"], "PASS")

    def test_authority_escalation(self):
        value = report_fixture(); value["authority"]["broker"] = True
        with self.assertRaises(EvidenceError): assess_advisor(rehash(value))

    def test_wrong_hash(self):
        value = report_fixture(); value["proposal_count"] = 9
        with self.assertRaises(EvidenceError): assess_advisor(value)

    def test_reject_fake_evidence_hash_even_if_digest_valid(self):
        value = report_fixture(); value["proposals"][0]["evidence_sample"][0]["entry_sha256"] = "fake"
        with self.assertRaises(EvidenceError): assess_advisor(rehash(value))

    def test_reject_causal_upgrade(self):
        value = report_fixture(); value["proposals"][0]["interpretation"] = "CAUSAL_PROOF"
        with self.assertRaises(EvidenceError): assess_advisor(rehash(value))

    def test_reject_duplicate_reference(self):
        value = report_fixture(); ref = value["proposals"][0]["evidence_sample"][0]
        value["proposals"][0]["evidence_sample"].append(copy.deepcopy(ref))
        with self.assertRaises(EvidenceError): assess_advisor(rehash(value))

    def test_refuse_unverified_model_label(self):
        value = report_fixture(); value["model_inference"] = "APPROVED_AI_PROOF"
        with self.assertRaises(EvidenceError): assess_advisor(rehash(value))

    def test_model_commentary_without_requested_inference(self):
        value = report_fixture(); value["model_commentary"] = [{"item_id": "a"*24,"question":"x","rationale":"y"}]
        with self.assertRaises(EvidenceError): assess_advisor(rehash(value))

    def test_bounded_and_zero_authority(self):
        value = report_fixture(); value["proposals"] = value["proposals"]*13; value["proposal_count"] = 13
        with self.assertRaises(EvidenceError): assess_advisor(rehash(value))


if __name__ == "__main__": unittest.main()
