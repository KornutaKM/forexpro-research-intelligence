"""Human-only review decision sidecar for a verified Research Review Pack.

Decisions are private annotations bound to one exact report digest. They never
constitute scientific authority, create experiments or send commands to Core.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError
from .review_pack import verify_review_pack

_CHOICES = {
    "DEFER": {"PENDING_REVIEW", "NEEDS_INDEPENDENT_REVIEW"},
    "ACCEPT_FOR_DISCUSSION": {"NEW_EXPERIMENT_QUESTION", "EVIDENCE_GAP_FOR_REVIEW"},
    "REJECT": {"DUPLICATE_PRIOR_WORK", "UNSUPPORTED_OR_UNACTIONABLE", "NEEDS_INDEPENDENT_REVIEW"},
}
_AUTHORITY = {
    "scientific": False, "holdout": False, "broker": False,
    "promotion": False, "experiment_execution": False, "core_feedback": False,
}


def decision_template(pack: dict[str, Any]) -> dict[str, Any]:
    """Create complete operator-editable DEFER defaults without human impersonation."""
    verify_review_pack(pack)
    rows = pack.get("review_topics")
    if not isinstance(rows, list):
        raise EvidenceError("invalid review-topic list")
    return {
        "schema_version": 1,
        "source_pack_sha256": pack["report_sha256"],
        "decisions": [
            {"item_id": item["item_id"], "choice": "DEFER", "reason_code": "PENDING_REVIEW"}
            for item in rows
        ],
    }


def assess_review_decisions(pack: dict[str, Any], submission: dict[str, Any]) -> dict[str, Any]:
    """Bind each human choice to exactly one existing advisory item.

    A reviewed question is for discussion ONLY. This function does not attest
    who performed the review or whether the chosen reason was correct.
    """
    verify_review_pack(pack)
    if (type(submission) is not dict or set(submission) != {
        "schema_version", "source_pack_sha256", "decisions"
    } or submission.get("schema_version") != 1
            or submission.get("source_pack_sha256") != pack["report_sha256"]):
        raise EvidenceError("decisions do not match exact review pack")
    choices = submission["decisions"]
    if type(choices) is not list or len(choices) > 12:
        raise EvidenceError("decision set size out of bounds")
    known = {item["item_id"] for item in pack.get("review_topics", [])}
    if len(known) != len(pack.get("review_topics", [])) or len(choices) != len(known):
        raise EvidenceError("decisions must match all unique advisory topics")
    accepted, names, counters = [], set(), Counter()
    for item in choices:
        if type(item) is not dict or set(item) != {"item_id", "choice", "reason_code"}:
            raise EvidenceError("unknown decision fields")
        ident = item["item_id"]
        if type(ident) is not str or ident not in known or ident in names:
            raise EvidenceError("unknown or repeated decision topic")
        names.add(ident)
        choice, reason = item["choice"], item["reason_code"]
        if type(choice) is not str or type(reason) is not str or (
            choice not in _CHOICES or reason not in _CHOICES[choice]
        ):
            raise EvidenceError("unsupported decision or reason")
        accepted.append({"item_id": ident, "choice": choice, "reason_code": reason})
        counters[choice] += 1
    if names != known:
        raise EvidenceError("missing advisory decisions")
    accepted.sort(key=lambda row: row["item_id"])
    report = {
        "schema_version": 1,
        "report_kind": "PRIVATE_HUMAN_RESEARCH_REVIEW_DECISIONS",
        "source_pack_sha256": pack["report_sha256"],
        "status": "RECORDED_SELF_REPORTED_NOT_SCIENTIFIC_AUTHORITY",
        "topic_count": len(accepted),
        "decision_counts": {key: counters[key] for key in sorted(_CHOICES)},
        "decisions": accepted,
        "authority": dict(_AUTHORITY),
        "reviewer_identity_verified": False,
        "experiment_registered": False,
        "limitations": [
            "Choices are unverified operator annotations, not scientific or source-owner approval.",
            "ACCEPT_FOR_DISCUSSION does not preregister, start, promote or authorize an experiment.",
            "No Core connection, source mutation, HOLDOUT, broker or outgoing feedback is present.",
            "Keep this sidecar in private storage and independently record reviewer identity if required.",
        ],
    }
    report["report_sha256"] = hashlib.sha256(canonical_json(report).encode("utf-8")).hexdigest()
    return report
