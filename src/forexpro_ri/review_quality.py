"""Curator-label comparison for FRI Research Review Packs.

A synthetic benchmark checks categorical fidelity and citation identity.
No synthetic run establishes real researcher time saved or scientific validity.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError
from .review_pack import verify_review_pack

_STATES = {"FAIL", "PASS", "NOT_EVALUABLE", "UNOBSERVED"}


def score_review_pack(pack: dict[str, Any], labels: dict[str, Any]) -> dict[str, Any]:
    """Compare a report with an independently authored synthetic truth table.

    Labels are not generated from the pack: they must be curator-reviewed.
    Missing statuses count as errors; evidence references are matched by all
    three identity fields. No raw observations are needed.
    """
    verify_review_pack(pack)
    if (not isinstance(labels, dict) or labels.get("schema_version") != 1
            or labels.get("source_class") != "CURATED_SYNTHETIC_ONLY"
            or not isinstance(labels.get("expected_cases"), dict)
            or not isinstance(labels.get("expected_review_procedures"), list)):
        raise EvidenceError("benchmark needs explicit curated synthetic labels")
    if pack["status"] == "NO_ELIGIBLE_DATA":
        raise EvidenceError("cannot score an empty review pack")
    if pack["status"] not in ("SYNTHETIC_DEMONSTRATION", "HISTORICAL_SIGNED_INTAKES"):
        raise EvidenceError("unknown review state")
    cases = pack.get("cases")
    topics = pack.get("review_topics")
    if not isinstance(cases, list) or not isinstance(topics, list):
        raise EvidenceError("invalid review elements")
    case_map = {}
    for case in cases:
        eid = case["experiment_id"]
        if eid in case_map or not eid.startswith("SYNTHETIC-"):
            raise EvidenceError("benchmark only permits unique synthetic IDs")
        case_map[eid] = case
    if not labels["expected_cases"]:
        raise EvidenceError("benchmark cannot score zero expected cases")
    if set(case_map) != set(labels["expected_cases"]):
        raise EvidenceError("benchmark case IDs do not match independent labels")
    total, correct, wrong = 0, 0, []
    for eid, procedures in sorted(labels["expected_cases"].items()):
        if not isinstance(procedures, dict) or not procedures:
            raise EvidenceError("each benchmark case needs procedure truth")
        recorded = {}
        for row in case_map[eid]["procedure_outcomes"]:
            proc, value = row["procedure"], row["recorded_status"]
            if proc in recorded or value not in _STATES:
                raise EvidenceError("malformed or duplicated procedure outcome")
            recorded[proc] = value
        if set(recorded) != set(procedures):
            raise EvidenceError("benchmark procedure sets differ from labels")
        for proc, expected in sorted(procedures.items()):
            if expected not in _STATES:
                raise EvidenceError("unknown expected categorical status")
            total += 1
            if recorded[proc] == expected:
                correct += 1
            else:
                wrong.append({"experiment_id": eid, "procedure": proc,
                              "expected": expected, "observed": recorded[proc]})

    known = {eid: (case["entry_sha256"], case["receipt_sha256"])
             for eid, case in case_map.items()}
    links, false_refs = 0, 0
    linked_proposals = 0
    for item in topics:
        refs = item["evidence_sample"]
        if not isinstance(refs, list):
            raise EvidenceError("missing evidence sample")
        if refs:
            linked_proposals += 1
        for row in refs:
            links += 1
            if known.get(row.get("experiment_id")) != (
                row.get("entry_sha256"), row.get("receipt_sha256")
            ):
                false_refs += 1
        if item.get("interpretation") != "DESCRIPTIVE_NOT_CAUSAL":
            raise EvidenceError("research interpretation claims causality")
    expected_topics = labels["expected_review_procedures"]
    if any(not isinstance(x, str) or not x for x in expected_topics) or len(set(expected_topics)) != len(expected_topics):
        raise EvidenceError("invalid required review topics")
    proposed_topics = {item["procedure"] for item in topics}
    missing_topics = sorted(set(expected_topics) - proposed_topics)
    unsupported_topics = sorted(proposed_topics - set(expected_topics))
    quality_pass = (
        correct == total and false_refs == 0 and not missing_topics
        and not unsupported_topics
    )
    result = {
        "schema_version": 1,
        "report_kind": "SYNTHETIC_CURATOR_REVIEW_QUALITY",
        "status": "STRUCTURAL_PASS" if quality_pass else "REQUIRES_CURATOR_REVIEW",
        "source_pack_sha256": pack["report_sha256"],
        "source_class": "CURATED_SYNTHETIC_ONLY",
        "procedure_checks": total,
        "correct_procedure_statuses": correct,
        "incorrect_procedure_statuses": wrong,
        "categorical_accuracy": {"numerator": correct, "denominator": total},
        "citation_links_checked": links,
        "false_citation_links": false_refs,
        "proposals_with_sampled_citations": linked_proposals,
        "missing_expected_review_topics": missing_topics,
        "other_observed_review_topics": unsupported_topics,
        "false_independent_replication_claims_allowed": False,
        "causal_or_profitability_validity_established": False,
        "real_operator_time_savings_established": False,
        "scientific_authority": False,
        "broker_authority": False,
        "limits": [
            "Only this human-provided synthetic truth table is assessed, not real research.",
            "Matching citations by ID and digest is structural, not external source authentication.",
            "Advisor semantics, causal reasoning and natural-language claims still require human review.",
            "Independent replication cannot be inferred from distinct experiment IDs.",
            "No timing result or 100x acceleration claim can be established by synthetic labels.",
        ],
    }
    result["report_sha256"] = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()
    return result
