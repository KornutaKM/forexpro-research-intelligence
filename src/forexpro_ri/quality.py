"""v2.5: deterministic quality checks for a non-authoritative Advisor report.

Structural checks cannot prove semantic truthfulness of LLM prose. The latter
remains unverified and requires explicit human review.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError, _ALLOWED_PROCEDURES

_SHA = re.compile(r"^[0-9a-f]{64}$")
_ITEM = re.compile(r"^[0-9a-f]{24}$")
_KINDS = frozenset({"EVIDENCE_GAP", "REPEATED_NOT_EVALUABLE", "REPEATED_FAILURE", "ISOLATED_NEGATIVE_OR_GAP"})
_ZERO_AUTHORITY = {"scientific", "holdout", "promotion", "broker", "experiment_execution"}


def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and _SHA.fullmatch(value) is not None


def assess_advisor(report: dict[str, Any], *, require_signed: bool = True) -> dict[str, Any]:
    """Fail closed on non-auditable output, unknown evidence and authority claims.

    A valid report is evidence-*referenced*, not independently proof-validated.
    This function deliberately never returns a scientific approval decision.
    """
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise EvidenceError("unsupported advisor report schema")
    if report.get("report_kind") != "NON_AUTHORITATIVE_RESEARCH_ADVISOR":
        raise EvidenceError("report is not advisory")
    if require_signed and report.get("signed_only_gate_passed") is not True:
        raise EvidenceError("signed evidence gate not passed")
    if not isinstance(report.get("authority"), dict) or set(report["authority"]) != _ZERO_AUTHORITY:
        raise EvidenceError("advisor authority structure invalid")
    if any(value is not False for value in report["authority"].values()):
        raise EvidenceError("advisor attempted authority escalation")
    if not _valid_digest(report.get("memory_snapshot_sha256")) or not _valid_digest(report.get("research_program_sha256")):
        raise EvidenceError("missing source evidence digest")
    expected = hashlib.sha256(canonical_json({k: v for k, v in report.items() if k != "report_sha256"}).encode()).hexdigest()
    if report.get("report_sha256") != expected:
        raise EvidenceError("advisor report digest mismatch")
    proposals = report.get("proposals")
    if not isinstance(proposals, list) or len(proposals) > 12 or report.get("proposal_count") != len(proposals):
        raise EvidenceError("proposal count or size invalid")
    if type(report.get("observed_experiment_count")) is not int or report["observed_experiment_count"] < 1:
        raise EvidenceError("invalid study count")
    ids: set[str] = set()
    grounded = 0
    sampled_citations = 0
    for item in proposals:
        if not isinstance(item, dict):
            raise EvidenceError("invalid proposal")
        ident = item.get("item_id")
        if not isinstance(ident, str) or not _ITEM.fullmatch(ident) or ident in ids:
            raise EvidenceError("invalid or repeated proposal id")
        ids.add(ident)
        if item.get("kind") not in _KINDS or item.get("procedure") not in _ALLOWED_PROCEDURES:
            raise EvidenceError("unsupported research topic")
        if item.get("interpretation") != "DESCRIPTIVE_NOT_CAUSAL":
            raise EvidenceError("causal inference is not authorized")
        if item.get("full_evidence_program_sha256") != report["research_program_sha256"]:
            raise EvidenceError("proposal not bound to research program")
        if (type(item.get("recorded_experiment_count")) is not int or
                not 0 <= item["recorded_experiment_count"] <= report["observed_experiment_count"] or
                item.get("cohort_experiment_count") != report["observed_experiment_count"]):
            raise EvidenceError("unsupported experimental count")
        refs = item.get("evidence_sample")
        if not isinstance(refs, list) or len(refs) > 8:
            raise EvidenceError("invalid evidence sample")
        ref_ids = set()
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {"experiment_id", "entry_sha256", "receipt_sha256"}:
                raise EvidenceError("invalid evidence reference")
            if (not isinstance(ref["experiment_id"], str) or not ref["experiment_id"] or
                    len(ref["experiment_id"]) > 128 or
                    not _valid_digest(ref["entry_sha256"]) or not _valid_digest(ref["receipt_sha256"])):
                raise EvidenceError("invalid evidence reference fields")
            if ref["experiment_id"] in ref_ids:
                raise EvidenceError("repeated evidence reference")
            ref_ids.add(ref["experiment_id"])
            sampled_citations += 1
        if not isinstance(item.get("evidence_sample_truncated"), bool):
            raise EvidenceError("invalid citation truncation declaration")
        if not refs and item["kind"] in {"REPEATED_FAILURE", "REPEATED_NOT_EVALUABLE"}:
            raise EvidenceError("negative inference without linked evidence")
        if refs:
            grounded += 1
    inference = report.get("model_inference")
    if inference not in {"NOT_REQUESTED", "LOCAL_MODEL_UNVERIFIED_PROSE"}:
        raise EvidenceError("unrecognized model inference status")
    commentary = report.get("model_commentary", [])
    if not isinstance(commentary, list):
        raise EvidenceError("model commentary must be a list")
    if inference == "NOT_REQUESTED" and commentary:
        raise EvidenceError("unrequested model content")
    if inference == "LOCAL_MODEL_UNVERIFIED_PROSE":
        if not isinstance(commentary, list) or not isinstance(report.get("limitations"), list) or not any(
            isinstance(x, str) and "unverified" in x.lower() for x in report["limitations"]
        ):
            raise EvidenceError("model prose not marked unverified")
        from .local_model import validate_commentary
        if validate_commentary({"items": commentary}, report) != commentary:
            raise EvidenceError("model commentary not normalized")
    return {
        "schema_version": 1,
        "quality_kind": "STRUCTURAL_EVIDENCE_CONSISTENCY_ONLY",
        "status": "PASS",
        "proposal_count": len(proposals),
        "sample_grounded_proposals": grounded,
        "sample_citation_count": sampled_citations,
        "model_items_requiring_human_review": len(commentary),
        "signed_only_gate_passed": report["signed_only_gate_passed"],
        "memory_snapshot_sha256": report["memory_snapshot_sha256"],
        "scientific_approval": False,
        "causal_validity_established": False,
        "model_semantic_truth_verified": False,
        "limits": "Checks binding, shape and authority; not causal validity, source custody or model truthfulness.",
    }


def benchmark(*, db_path: str, allow_unsigned_synthetic: bool = False) -> dict[str, Any]:
    """Reproducible fail-closed regression suite against a real Research Memory."""
    from .advisor import build_advisor

    report = build_advisor(db_path, allow_unsigned_synthetic=allow_unsigned_synthetic)
    cases: list[dict[str, Any]] = []

    def check(name: str, altered: dict[str, Any], expected_pass: bool) -> None:
        try:
            assess_advisor(altered, require_signed=not allow_unsigned_synthetic)
            actual = True
        except EvidenceError:
            actual = False
        cases.append({"case": name, "passed": actual == expected_pass})

    import copy
    check("baseline", report, True)
    broken = copy.deepcopy(report); broken["authority"]["broker"] = True
    check("reject_broker_authority", broken, False)
    broken = copy.deepcopy(report); broken["report_sha256"] = "0" * 64
    check("reject_modified_digest", broken, False)
    broken = copy.deepcopy(report); broken["signed_only_gate_passed"] = False
    broken["report_sha256"] = hashlib.sha256(canonical_json({k: v for k, v in broken.items() if k != "report_sha256"}).encode()).hexdigest()
    # An unsigned report must never pass in the strict/default policy.
    try:
        assess_advisor(broken, require_signed=True)
        unsigned_rejected = False
    except EvidenceError:
        unsigned_rejected = True
    cases.append({"case": "reject_unsigned_in_strict_mode", "passed": unsigned_rejected})
    if report["proposals"]:
        broken = copy.deepcopy(report)
        broken["proposals"][0]["interpretation"] = "PROVEN_CAUSAL"
        check("reject_causal_claim", broken, False)
        broken = copy.deepcopy(report)
        broken["proposals"][0]["evidence_sample"] = [{"experiment_id": "INVENTED", "entry_sha256": "not-a-hash", "receipt_sha256": "0" * 64}]
        check("reject_fabricated_reference", broken, False)
    passed = sum(row["passed"] for row in cases)
    return {
        "schema_version": 1,
        "benchmark_kind": "SYNTHETIC_STRUCTURAL_ADVISOR_REGRESSION",
        "status": "PASS" if passed == len(cases) else "FAIL",
        "passed": passed,
        "total": len(cases),
        "pass_rate": passed / len(cases),
        "cases": cases,
        "quality": assess_advisor(report, require_signed=not allow_unsigned_synthetic),
        "model_semantic_truth_verified": False,
    }
