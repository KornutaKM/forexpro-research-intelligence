"""Compare two separately recorded local human-review sidecars.

Hash-linked decisions are self-reported; this cannot prove reviewers are
independent, competent, or even different people. Agreement authorizes nothing.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError
from .review_decisions import assess_review_decisions
from .review_pack import verify_review_pack


def _verify_reviewed(pack: dict[str, Any], assessed: dict[str, Any]) -> dict[str, Any]:
    if type(assessed) is not dict:
        raise EvidenceError("human review sidecar must be an object")
    if (assessed.get("report_kind") != "PRIVATE_HUMAN_RESEARCH_REVIEW_DECISIONS"
            or type(assessed.get("report_sha256")) is not str
            or type(assessed.get("decisions")) is not list):
        raise EvidenceError("not a reviewed decision sidecar")
    raw = {
        "schema_version": assessed.get("schema_version"),
        "source_pack_sha256": assessed.get("source_pack_sha256"),
        "decisions": assessed["decisions"],
    }
    canonical = assess_review_decisions(pack, raw)
    if canonical != assessed:
        raise EvidenceError("sidecar modified, unsupported or incorrectly hashed")
    return canonical


def compare_human_reviews(pack: dict[str, Any], left: dict[str, Any],
                          right: dict[str, Any]) -> dict[str, Any]:
    """Return choice/reason disagreements, never an automated scientific verdict."""
    verify_review_pack(pack)
    a = _verify_reviewed(pack, left)
    b = _verify_reviewed(pack, right)
    if a["report_sha256"] == b["report_sha256"]:
        raise EvidenceError("identical review content cannot establish separate review")
    choices_a = {x["item_id"]: x for x in a["decisions"]}
    choices_b = {x["item_id"]: x for x in b["decisions"]}
    ids = sorted(choices_a)
    if ids != sorted(choices_b):
        raise EvidenceError("reviewed topic sets differ")
    agreements = reason_agreements = 0
    divergences = []
    for iid in ids:
        x, y = choices_a[iid], choices_b[iid]
        same_choice = x["choice"] == y["choice"]
        same_reason = x["reason_code"] == y["reason_code"]
        agreements += same_choice
        reason_agreements += same_choice and same_reason
        if not same_choice or not same_reason:
            divergences.append({
                "item_id": iid,
                "left_choice": x["choice"],
                "right_choice": y["choice"],
                "left_reason_code": x["reason_code"],
                "right_reason_code": y["reason_code"],
                "requires_human_reconciliation": True,
            })
    output = {
        "schema_version": 1,
        "report_kind": "NON_AUTHORITATIVE_REVIEWER_DISAGREEMENT",
        "source_pack_sha256": pack["report_sha256"],
        "left_sidecar_sha256": a["report_sha256"],
        "right_sidecar_sha256": b["report_sha256"],
        "status": "REQUIRES_HUMAN_RECONCILIATION",
        "topic_count": len(ids),
        "matching_choice_count": agreements,
        "matching_choice_and_reason_count": reason_agreements,
        "choice_agreement": {"numerator": agreements, "denominator": len(ids)},
        "full_agreement": reason_agreements == len(ids),
        "disagreements": divergences,
        "reviewer_identity_authenticated": False,
        "reviewer_independence_established": False,
        "experiment_registration_authorized": False,
        "scientific_authority": False,
        "broker_authority": False,
        "holdout_access": False,
        "core_feedback": False,
        "limitations": [
            "Review sidecars are self-reported; two documents do not prove two independent reviewers.",
            "Identical choices or reasons are not scientific consensus or permission to experiment.",
            "Any conflict requires independent human reconciliation outside FRI.",
            "No automated aggregation can admit science, preregister research or instruct Core.",
        ],
    }
    output["report_sha256"] = hashlib.sha256(
        canonical_json(output).encode("utf-8")
    ).hexdigest()
    return output
