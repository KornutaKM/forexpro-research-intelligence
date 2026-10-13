"""Human-only reconciliation of proposed actions and evidence-quality ratings.

A discussion approval in one sidecar can conflict with weak/unknown grounding
or unsafe scientific language in another. This report creates *warnings*, not
automatic vetoes, approvals or Core task registration.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .analysis import canonical_json
from .review_agreement import _verify_reviewed
from .review_curator import _verified_assessment
from .review_pack import verify_review_pack

_REASONS = {
    "UNSUPPORTED_BY_RECORDED_EVIDENCE": "GROUNDING_NOT_SUPPORTED",
    "CANNOT_DETERMINE": "GROUNDING_UNCERTAIN",
    "UNREVIEWED": "GROUNDING_NOT_REVIEWED",
}
_RISK = ("grounding", "scientific_language", "usefulness", "duplication")


def reconcile_human_evidence(
    pack: dict[str, Any],
    decisions: dict[str, Any],
    rubric: dict[str, Any],
) -> dict[str, Any]:
    """Cross-check exactly two pack-bound, internally verified human documents."""
    verify_review_pack(pack)
    chosen = _verify_reviewed(pack, decisions)
    scored = _verified_assessment(pack, rubric)
    decisions_by = {row["item_id"]: row for row in chosen["decisions"]}
    graded_by = {row["item_id"]: row for row in scored["items"]}
    issues = []
    for iid in sorted(decisions_by):
        decision, grade = decisions_by[iid], graded_by[iid]
        if decision["choice"] != "ACCEPT_FOR_DISCUSSION":
            continue
        codes = []
        grounding = grade["grounding"]
        if grounding in _REASONS:
            codes.append(_REASONS[grounding])
        language = grade["scientific_language"]
        if language in ("UNSUPPORTED_AUTHORITY_OR_CAUSAL_CLAIM", "CANNOT_DETERMINE", "UNREVIEWED"):
            codes.append("SCIENTIFIC_LANGUAGE_" + language)
        usefulness = grade["usefulness"]
        if usefulness in ("NOT_USEFUL", "CANNOT_DETERMINE", "UNREVIEWED"):
            codes.append("QUESTION_USEFULNESS_" + usefulness)
        dup = grade["duplication"]
        if dup in ("POTENTIALLY_DUPLICATIVE", "CANNOT_DETERMINE", "UNREVIEWED"):
            codes.append("DUPLICATION_" + dup)
        if codes:
            issues.append({
                "item_id": iid,
                "operator_choice": decision["choice"],
                "reason_codes": codes,
                "requires_independent_human_reconciliation": True,
            })
    result = {
        "schema_version": 1,
        "report_kind": "NON_AUTHORITATIVE_ADVISORY_HUMAN_EVIDENCE_RECONCILIATION",
        "status": ("HUMAN_RECONCILIATION_REQUIRED" if issues
                   else "NO_RECORDED_CONFLICTS_NOT_APPROVAL"),
        "source_pack_sha256": pack["report_sha256"],
        "decisions_sha256": chosen["report_sha256"],
        "rubric_sha256": scored["report_sha256"],
        "total_questions": len(decisions_by),
        "accepted_for_discussion_count": sum(
            x["choice"] == "ACCEPT_FOR_DISCUSSION" for x in chosen["decisions"]
        ),
        "questions_requiring_reconciliation": len(issues),
        "conflicts": issues,
        "automated_veto_or_approval": False,
        "human_identity_verified": False,
        "scientific_authority": False,
        "broker_authority": False,
        "core_feedback": False,
        "limitations": [
            "A discussion decision is not scientific admission or permission to run an experiment.",
            "A conflict is a human review prompt, not an automatically overturned decision.",
            "No recorded conflict does not validate the truth of a question or identity of reviewers.",
            "The rubric and decision files are self-reported, even when SHA-bound to the same pack.",
            "Missing Advisor questions are not represented; a separate recall audit is required.",
        ],
    }
    result["report_sha256"] = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()
    return result
