"""Structured human rubric for FRI Advisor questions in a verified Research Pack.

Two distinct reports can be compared without asserting two authenticated
reviewers. Rubric correctness/independence requires external human protocol.
No free text, identities, data exports, model decisions or Core execution.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError
from .review_pack import verify_review_pack

_DIMENSIONS = {
    "grounding": {"UNREVIEWED", "SUPPORTED_BY_RECORDED_EVIDENCE",
                  "UNSUPPORTED_BY_RECORDED_EVIDENCE", "CANNOT_DETERMINE"},
    "usefulness": {"UNREVIEWED", "USEFUL_RESEARCH_QUESTION", "NOT_USEFUL",
                   "CANNOT_DETERMINE"},
    "duplication": {"UNREVIEWED", "POTENTIALLY_DUPLICATIVE",
                    "NOT_IDENTIFIED_IN_REVIEWED_CORPUS", "CANNOT_DETERMINE"},
    "scientific_language": {"UNREVIEWED", "BOUNDED_ADVISORY_ONLY",
                            "UNSUPPORTED_AUTHORITY_OR_CAUSAL_CLAIM", "CANNOT_DETERMINE"},
}
_BAD = {
    "grounding": "UNSUPPORTED_BY_RECORDED_EVIDENCE",
    "usefulness": "NOT_USEFUL",
    "duplication": "POTENTIALLY_DUPLICATIVE",
    "scientific_language": "UNSUPPORTED_AUTHORITY_OR_CAUSAL_CLAIM",
}
_AUTHORITY = {
    "scientific": False, "holdout": False, "broker": False,
    "promotion": False, "experiment_execution": False, "core_feedback": False,
}


def _digest(row: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()


def curator_template(pack: dict[str, Any]) -> dict[str, Any]:
    """Complete template with no fabricated curator opinions or identity."""
    verify_review_pack(pack)
    return {
        "schema_version": 1,
        "source_pack_sha256": pack["report_sha256"],
        "rubric_version": "FRI_ADVISORY_V1",
        "items": [
            {"item_id": item["item_id"], **{d: "UNREVIEWED" for d in _DIMENSIONS}}
            for item in pack["review_topics"]
        ],
    }


def assess_curator_rubric(pack: dict[str, Any], submission: dict[str, Any]) -> dict[str, Any]:
    """Bind manual categorical judgments to exactly one pack, no fake approval."""
    verify_review_pack(pack)
    if (type(submission) is not dict
            or set(submission) != {"schema_version", "source_pack_sha256", "rubric_version", "items"}
            or type(submission["schema_version"]) is not int or submission["schema_version"] != 1
            or submission["source_pack_sha256"] != pack["report_sha256"]
            or submission["rubric_version"] != "FRI_ADVISORY_V1"):
        raise EvidenceError("unrecognized or stale curator rubric")
    values = submission["items"]
    known = {x["item_id"] for x in pack["review_topics"]}
    if (type(values) is not list or len(values) != len(known)
            or len(values) > 12 or len(known) != len(pack["review_topics"])):
        raise EvidenceError("curator rubric must cover every unique research question")
    seen = set()
    counts = {dim: Counter() for dim in _DIMENSIONS}
    audited = []
    for item in values:
        if type(item) is not dict or set(item) != {"item_id", *_DIMENSIONS}:
            raise EvidenceError("rubric includes unsupported fields")
        ident = item["item_id"]
        if type(ident) is not str or ident not in known or ident in seen:
            raise EvidenceError("duplicated or unknown rubric item")
        seen.add(ident)
        for dim, allowed in _DIMENSIONS.items():
            if type(item[dim]) is not str or item[dim] not in allowed:
                raise EvidenceError("unsupported curator categorical label")
            counts[dim][item[dim]] += 1
        audited.append(dict(item))
    audited.sort(key=lambda x: x["item_id"])
    total = len(audited)
    finished = sum(all(item[d] != "UNREVIEWED" for d in _DIMENSIONS) for item in audited)
    unsupported = sorted(x["item_id"] for x in audited if any(
        x[dim] == bad for dim, bad in _BAD.items()
    ))
    unresolved = sorted(x["item_id"] for x in audited if any(
        x[d] in ("UNREVIEWED", "CANNOT_DETERMINE") for d in _DIMENSIONS
    ))
    response = {
        "schema_version": 1,
        "report_kind": "SELF_REPORTED_HUMAN_RESEARCH_QUESTION_RUBRIC",
        "status": "SELF_REPORTED_REQUIRES_INDEPENDENT_REVIEW",
        "source_pack_sha256": pack["report_sha256"],
        "rubric_version": "FRI_ADVISORY_V1",
        "topic_count": total,
        "fully_labeled_items": finished,
        "dimensions": {
            dim: {value: counts[dim][value] for value in sorted(allowed)}
            for dim, allowed in sorted(_DIMENSIONS.items())
        },
        "items": audited,
        "unsupported_or_problematic_topic_ids": unsupported,
        "unresolved_topic_ids": unresolved,
        "independent_reviewer_authenticated": False,
        "scientific_correctness_established": False,
        "export_authority_established": False,
        "authority": dict(_AUTHORITY),
        "limitations": [
            "These ratings are self-reported human labels, not independently authenticated opinions.",
            "The rubric scores displayed questions, not missing questions never proposed.",
            "NOT_IDENTIFIED_IN_REVIEWED_CORPUS is not global novelty or scientific independence.",
            "All acceptability and usability judgments require external assessor custody.",
            "Even complete favorable ratings cannot authorize experimental registration or Core commands.",
        ],
    }
    response["report_sha256"] = _digest(response)
    return response


def _verified_assessment(pack: dict[str, Any], assessed: dict[str, Any]) -> dict[str, Any]:
    if (type(assessed) is not dict or assessed.get("report_kind")
            != "SELF_REPORTED_HUMAN_RESEARCH_QUESTION_RUBRIC"):
        raise EvidenceError("invalid curator assessment kind")
    data = {
        "schema_version": assessed.get("schema_version"),
        "source_pack_sha256": assessed.get("source_pack_sha256"),
        "rubric_version": assessed.get("rubric_version"),
        "items": assessed.get("items"),
    }
    if assess_curator_rubric(pack, data) != assessed:
        raise EvidenceError("curator assessment altered or inconsistent")
    return assessed


def compare_curator_rubrics(pack: dict[str, Any], left: dict[str, Any],
                           right: dict[str, Any]) -> dict[str, Any]:
    """Display differences, without claiming independent human identities."""
    verify_review_pack(pack)
    a = _verified_assessment(pack, left)
    b = _verified_assessment(pack, right)
    if a["report_sha256"] == b["report_sha256"]:
        raise EvidenceError("identical rubric cannot prove separate assessment")
    by_a = {row["item_id"]: row for row in a["items"]}
    by_b = {row["item_id"]: row for row in b["items"]}
    if set(by_a) != set(by_b):
        raise EvidenceError("curator rubric item mismatch")
    divergences = []
    agreements = Counter()
    for iid in sorted(by_a):
        for dimension in _DIMENSIONS:
            x, y = by_a[iid][dimension], by_b[iid][dimension]
            if x == y and x not in ("UNREVIEWED", "CANNOT_DETERMINE"):
                agreements[dimension] += 1
            elif x != y:
                divergences.append({
                    "item_id": iid,
                    "dimension": dimension,
                    "left": x,
                    "right": y,
                    "requires_human_reconciliation": True,
                })
    result = {
        "schema_version": 1,
        "report_kind": "NON_AUTHORITATIVE_CURATOR_RUBRIC_DISAGREEMENTS",
        "status": "REQUIRES_HUMAN_RECONCILIATION",
        "source_pack_sha256": pack["report_sha256"],
        "left_rubric_sha256": a["report_sha256"],
        "right_rubric_sha256": b["report_sha256"],
        "topic_count": len(by_a),
        "dimension_count": len(_DIMENSIONS),
        "agreement_counts_on_decided_labels": dict(sorted(agreements.items())),
        "disagreements": divergences,
        "independent_reviewers_established": False,
        "human_consensus_attested": False,
        "scientific_authority": False,
        "broker_authority": False,
        "limitations": [
            "Two files are not proof of two real or independent reviewers.",
            "Unreviewed or uncertain labels are never counted as positive agreement.",
            "Even identical judgments do not validate the scientific truth of a proposal.",
            "Independent adjudication and owner sign-off remain outside FRI.",
        ],
    }
    result["report_sha256"] = _digest(result)
    return result
