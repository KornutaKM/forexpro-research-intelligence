"""Deterministic, counterbalanced paired-study registration for FRI operators.

This creates a reproducible assignment scheme, NOT randomized/blinded proof:
researcher/task identity, adherence and scientific quality require external
independent supervision. No tasks or outcome data are sent to Core.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError
from .review_pack import verify_review_pack
from .review_time_study import analyze_paired_study


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def make_study_plan(pack: dict[str, Any], *, task_count: int = 20) -> dict[str, Any]:
    """Balance manual-first and FRI-first orders on bounded anonymous task IDs."""
    verify_review_pack(pack)
    if type(task_count) is not int or not 20 <= task_count <= 100:
        raise EvidenceError("paired study plan requires 20 to 100 tasks")
    ids = [f"TASK-{i:03d}" for i in range(1, task_count + 1)]
    # Explicit reproducible SHA-derived order, not unpredictable randomization.
    priority = sorted(ids, key=lambda x: (
        hashlib.sha256(f"{pack['report_sha256']}:{x}:FRI_STUDY_V1".encode()).hexdigest(), x
    ))
    manual_first = set(priority[:task_count // 2])
    assignments = [
        {"task_id": ident,
         "order": "MANUAL_FIRST" if ident in manual_first else "FRI_FIRST"}
        for ident in ids
    ]
    result = {
        "schema_version": 1,
        "report_kind": "LOCAL_NON_AUTHORITATIVE_STUDY_ASSIGNMENT",
        "source_pack_sha256": pack["report_sha256"],
        "task_count": task_count,
        "assignment_algorithm": "REPRODUCIBLE_SHA256_COUNTERBALANCE_V1",
        "assignments": assignments,
        "source_owner_permission_established": False,
        "researcher_identity_attested": False,
        "blinding_established": False,
        "randomization_independently_verified": False,
        "causal_effect_authorized": False,
        "scientific_authority": False,
        "broker_authority": False,
        "limitations": [
            "Deterministic SHA256 order balances groups but is not randomization or blinding.",
            "Only task IDs and order are registered; task difficulty/identity must be assessed externally.",
            "Operator measurements, accuracy labels and actual adherence remain unverified.",
            "Training effects, task selection, cross-over carryover and missing observations can bias results.",
            "No timing or statistical result can authorize ForexPro Core research or broker actions.",
        ],
    }
    result["report_sha256"] = _digest(result)
    return result


def assess_planned_study(pack: dict[str, Any], plan: dict[str, Any],
                         data: dict[str, Any]) -> dict[str, Any]:
    """Reject post hoc reorder, missing tasks, forged plan, and false 100x claims."""
    verify_review_pack(pack)
    if type(plan) is not dict or type(plan.get("task_count")) is not int:
        raise EvidenceError("invalid paired-study plan")
    if plan != make_study_plan(pack, task_count=plan["task_count"]):
        raise EvidenceError("study assignment plan altered or for another pack")
    if type(data) is not dict or type(data.get("tasks")) is not list:
        raise EvidenceError("invalid planned study measurements")
    expected = {row["task_id"]: row["order"] for row in plan["assignments"]}
    if len(data["tasks"]) != len(expected):
        raise EvidenceError("planned study missing or extra tasks")
    observed = set()
    for row in data["tasks"]:
        if type(row) is not dict:
            raise EvidenceError("invalid task")
        ident = row.get("task_id")
        if type(ident) is not str or ident not in expected or ident in observed:
            raise EvidenceError("unknown or duplicate assigned task")
        observed.add(ident)
        if row.get("order") != expected[ident]:
            raise EvidenceError("paired task order diverges from registered assignment")
    analysis = analyze_paired_study(data)
    output = {
        "schema_version": 1,
        "report_kind": "NON_AUTHORITATIVE_PAIRED_STUDY_PROTOCOL_RECONCILIATION",
        "status": "STRUCTURAL_PROTOCOL_ADHERENCE_ONLY",
        "source_pack_sha256": pack["report_sha256"],
        "assignment_plan_sha256": plan["report_sha256"],
        "measurements_sha256": _digest(data),
        "task_count": len(expected),
        "all_task_orders_match_assignment": True,
        "paired_study": analysis,
        "source_owner_permission_established": False,
        "researcher_identity_verified": False,
        "independent_assessor_verified": False,
        "blinding_established": False,
        "causality_established": False,
        "real_world_100x_confirmed": False,
        "scientific_authority": False,
        "broker_authority": False,
        "limitations": [
            "Registered task ordering alone cannot prove task performance or independence.",
            "The task measurements are synthetic or self-reported, not independently verified.",
            "Quality noninferiority from entered booleans is not a validated external clinical/statistical test.",
            "The output cannot authorize scientific promotion, broker activity or new research execution.",
        ],
    }
    output["report_sha256"] = _digest(output)
    return output
