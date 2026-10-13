"""Operator-first, deterministic gap triage for an authenticated-local Review Pack.

Ordering is about attention to incomplete *recorded evidence*, never strategy
quality, expected return, causal importance, or scientific admission.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError

_BUCKETS = (
    "MISSING_RECORDED_EVIDENCE",
    "RECORDED_NOT_EVALUABLE",
    "RECORDED_FAILURE_REVIEW",
    "NO_RECORDED_NEGATIVE_OR_GAP",
)
_FIELDS = {
    "FAIL": "failed_experiments",
    "PASS": "passed_experiments",
    "NOT_EVALUABLE": "not_evaluable_experiments",
    "UNOBSERVED": "unobserved_experiments",
}
_MAX_SAMPLES = 4


def _summarize_verified(pack: dict[str, Any]) -> dict[str, Any]:
    """Internal helper; caller MUST verify pack structure before invocation."""
    n = pack["experiment_count"]
    case_lookup = {case["experiment_id"]: case for case in pack["cases"]}
    topics_by_proc: dict[str, list[str]] = {}
    for item in pack["review_topics"]:
        topics_by_proc.setdefault(item["procedure"], []).append(item["item_id"])
    rows = []
    for observed in pack["procedure_coverage"]:
        proc = observed["procedure"]
        counts = {
            state: observed[field] for state, field in _FIELDS.items()
        }
        if sum(counts.values()) != n:
            raise EvidenceError("triage coverage count conflict")
        if counts["UNOBSERVED"]:
            bucket = _BUCKETS[0]
            rank = 0
        elif counts["NOT_EVALUABLE"]:
            bucket = _BUCKETS[1]
            rank = 1
        elif counts["FAIL"]:
            bucket = _BUCKETS[2]
            rank = 2
        else:
            bucket = _BUCKETS[3]
            rank = 3
        refs = []
        for eid in sorted(case_lookup):
            case = case_lookup[eid]
            outcome = next(
                (x for x in case["procedure_outcomes"] if x["procedure"] == proc),
                None,
            )
            if outcome is None:
                raise EvidenceError("triage missing per-case procedure")
            if outcome["recorded_status"] in ("UNOBSERVED", "NOT_EVALUABLE", "FAIL"):
                if len(refs) < _MAX_SAMPLES:
                    refs.append({
                        "experiment_id": eid,
                        "entry_sha256": case["entry_sha256"],
                        "receipt_sha256": case["receipt_sha256"],
                        "recorded_status": outcome["recorded_status"],
                    })
        deficit = counts["UNOBSERVED"] + counts["NOT_EVALUABLE"]
        rows.append({
            "procedure": proc,
            "attention_bucket": bucket,
            "recorded_counts": counts,
            "evidence_gaps": deficit,
            "operator_question_ids": sorted(topics_by_proc.get(proc, [])),
            "sampled_case_refs": refs,
            "case_sample_truncated": (
                counts["UNOBSERVED"] + counts["NOT_EVALUABLE"] + counts["FAIL"]
                > len(refs)
            ),
            "interpretation": "DESCRIPTIVE_OPERATOR_ATTENTION_ONLY",
            "_rank": rank,
        })
    rows.sort(key=lambda row: (
        row["_rank"], -row["evidence_gaps"],
        -row["recorded_counts"]["FAIL"], row["procedure"],
    ))
    for row in rows:
        del row["_rank"]
    missing_count = sum(x["recorded_counts"]["UNOBSERVED"] for x in rows)
    unevaluable_count = sum(x["recorded_counts"]["NOT_EVALUABLE"] for x in rows)
    failure_count = sum(x["recorded_counts"]["FAIL"] for x in rows)
    response = {
        "schema_version": 1,
        "report_kind": "NON_AUTHORITATIVE_OPERATOR_EVIDENCE_TRIAGE",
        "status": "NO_ELIGIBLE_DATA" if n == 0 else "LOCAL_REVIEW_ONLY",
        "source_pack_sha256": pack["report_sha256"],
        "source_class": pack["status"],
        "experiment_count": n,
        "procedure_count": len(rows),
        "procedure_state_totals": {
            "FAIL": failure_count,
            "NOT_EVALUABLE": unevaluable_count,
            "UNOBSERVED": missing_count,
            "PASS": sum(x["recorded_counts"]["PASS"] for x in rows),
        },
        "procedures": rows,
        "scientific_authority": False,
        "broker_authority": False,
        "source_export_permission_established": False,
        "causal_rank_established": False,
        "limitations": [
            "Missing procedure states are derived from the operator-declared view, not certified source contracts.",
            "One experiment may count in several procedures; procedure counts are not independent trials.",
            "Attention order prioritizes incomplete evidence and is not a forecast or strategy score.",
            "Signed intake, local hashes and test-key demonstrations do not grant current export permission.",
            "Samples are bounded; read the full verified pack for the complete set of cases.",
        ],
    }
    response["report_sha256"] = hashlib.sha256(
        canonical_json(response).encode("utf-8")
    ).hexdigest()
    return response


def summarize_review(pack: dict[str, Any]) -> dict[str, Any]:
    """Verify the supplied pack, then derive a bounded, linked operator summary."""
    from .review_pack import verify_review_pack

    verify_review_pack(pack)
    return _summarize_verified(pack)
