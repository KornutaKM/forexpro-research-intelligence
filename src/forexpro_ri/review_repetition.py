"""Human-facing candidate repetition detector for closed negative observations.

A repeated signature is a recorded pattern, not evidence of independent
replication, shared causes, scientific validity or a trading recommendation.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError

_MAX_MEMBER_SAMPLE = 6


def _clusters_verified(pack: dict[str, Any]) -> dict[str, Any]:
    """Internal helper for caller-validated reports only."""
    groups: dict[tuple[tuple[str, str], ...], list[dict[str, str]]] = defaultdict(list)
    ignored_without_negative = 0
    for case in pack["cases"]:
        signature = tuple(sorted(
            (p["procedure"], p["recorded_status"])
            for p in case["procedure_outcomes"]
            if p["recorded_status"] in ("FAIL", "NOT_EVALUABLE")
        ))
        if not signature:
            ignored_without_negative += 1
            continue
        groups[signature].append({
            "experiment_id": case["experiment_id"],
            "entry_sha256": case["entry_sha256"],
            "receipt_sha256": case["receipt_sha256"],
        })
    clusters = []
    represented = 0
    for signature, cases in groups.items():
        if len(cases) < 2:
            continue
        cases.sort(key=lambda x: x["experiment_id"])
        represented += len(cases)
        sig_doc = [{"procedure": p, "recorded_status": s} for p, s in signature]
        clusters.append({
            "signature_sha256": hashlib.sha256(
                canonical_json({"negative_signature": sig_doc}).encode("utf-8")
            ).hexdigest(),
            "negative_signature": sig_doc,
            "observed_case_count": len(cases),
            "sampled_experiments": cases[:_MAX_MEMBER_SAMPLE],
            "sample_truncated": len(cases) > _MAX_MEMBER_SAMPLE,
            "interpretation": "REPEATED_RECORDED_PATTERN_ONLY",
            "independent_replication_established": False,
            "shared_cause_established": False,
            "recommended_operator_action": "REVIEW_PRIOR_NEGATIVES_BEFORE_PROPOSING_NEW_RESEARCH",
        })
    clusters.sort(key=lambda x: (-x["observed_case_count"], x["signature_sha256"]))
    result = {
        "schema_version": 1,
        "report_kind": "NON_AUTHORITATIVE_REPEAT_RESEARCH_CAUTION",
        "status": "NO_ELIGIBLE_DATA" if not pack["cases"] else "DESCRIPTIVE_PATTERN_REVIEW",
        "source_pack_sha256": pack["report_sha256"],
        "source_class": pack["status"],
        "total_experiments": len(pack["cases"]),
        "cases_without_recorded_negative_signature": ignored_without_negative,
        "repeated_cluster_count": len(clusters),
        "cases_in_repeated_clusters": represented,
        "clusters": clusters,
        "source_independence_established": False,
        "improvement_established": False,
        "scientific_authority": False,
        "broker_authority": False,
        "limitations": [
            "Matching procedure outcomes do not prove identical strategy, sample, protocol or cause.",
            "Different experiment identifiers may share the same data or evaluation lineage.",
            "Clustering does not rank trading opportunities or authorize new experiments.",
            "Only observed FAIL and NOT_EVALUABLE states form a cluster; UNOBSERVED is not a negative result.",
            "All experiment references come from a locally verified pack, not current Core export approval.",
        ],
    }
    result["report_sha256"] = hashlib.sha256(
        canonical_json(result).encode("utf-8")
    ).hexdigest()
    return result


def find_repeated_negatives(pack: dict[str, Any]) -> dict[str, Any]:
    from .review_pack import verify_review_pack

    verify_review_pack(pack)
    return _clusters_verified(pack)
