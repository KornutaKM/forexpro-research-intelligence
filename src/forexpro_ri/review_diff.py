"""Review progression between two offline evidence-linked FRI packs.

The Research Memory is append-only: changing or deleting a previously
recorded experiment is rejected. Newly added observations do not establish
experimental independence, trial causality or improved trading performance.
"""
from __future__ import annotations

import hashlib
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError
from .review_pack import verify_review_pack

_COUNTS = ("failed_experiments", "passed_experiments",
           "not_evaluable_experiments", "unobserved_experiments")
_CLASS = {
    "SYNTHETIC_DEMONSTRATION": "synthetic",
    "SYNTHETIC_SIGNED_DEMONSTRATION": "synthetic",
    "HISTORICAL_SIGNED_INTAKES": "historical",
    "NO_ELIGIBLE_DATA": "empty",
}


def compare_review_packs(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Compare two integrity-checked reports with strict append-only identity.

    The comparison is descriptive. Different operator-expected procedure
    declarations may change UNOBSERVED coverage without any new research.
    """
    verify_review_pack(before)
    verify_review_pack(after)
    a, b = _CLASS[before["status"]], _CLASS[after["status"]]
    if a != "empty" and b != "empty" and a != b:
        raise EvidenceError("cannot conflate synthetic and non-synthetic research")
    left = {x["experiment_id"]: x for x in before["cases"]}
    right = {x["experiment_id"]: x for x in after["cases"]}
    if not set(left) <= set(right):
        raise EvidenceError("append-only Research Memory cannot lose historical cases")
    for eid in left:
        if (left[eid]["entry_sha256"], left[eid]["receipt_sha256"]) != (
            right[eid]["entry_sha256"], right[eid]["receipt_sha256"]
        ):
            raise EvidenceError("previous closed experiment evidence identity changed")
    added = sorted(set(right) - set(left))
    prior_topics = {x["item_id"]: x for x in before["review_topics"]}
    later_topics = {x["item_id"]: x for x in after["review_topics"]}
    coverage_a = {x["procedure"]: x for x in before["procedure_coverage"]}
    coverage_b = {x["procedure"]: x for x in after["procedure_coverage"]}
    coverage_changes = []
    for procedure in sorted(set(coverage_a) | set(coverage_b)):
        old, new = coverage_a.get(procedure), coverage_b.get(procedure)
        prev = {key: old[key] if old else None for key in _COUNTS}
        current = {key: new[key] if new else None for key in _COUNTS}
        if prev != current:
            coverage_changes.append({
                "procedure": procedure, "previous_counts": prev, "current_counts": current,
                "interpretation": "COHORT_OR_OPERATOR_EXPECTATION_CHANGED_NOT_CAUSAL",
            })
    # An untrusted report can add/remove a topic because of operator-declared
    # expected procedures or ranking limits. Never describe it as proof of
    # improved scientific quality.
    result = {
        "schema_version": 1,
        "report_kind": "NON_AUTHORITATIVE_RESEARCH_REVIEW_PROGRESS",
        "status": "DESCRIPTIVE_CHANGE_ONLY",
        "previous_pack_sha256": before["report_sha256"],
        "current_pack_sha256": after["report_sha256"],
        "previous_case_count": len(left),
        "current_case_count": len(right),
        "new_closed_records": [
            {"experiment_id": eid, "entry_sha256": right[eid]["entry_sha256"],
             "receipt_sha256": right[eid]["receipt_sha256"]}
            for eid in added
        ],
        "new_record_count": len(added),
        "coverage_changes": coverage_changes,
        "advisory_topics_added": sorted(set(later_topics) - set(prior_topics)),
        "advisory_topics_no_longer_displayed": sorted(set(prior_topics) - set(later_topics)),
        "scientific_results_overwritten": False,
        "independence_or_causality_established": False,
        "improvement_established": False,
        "source_export_authorization_established": False,
        "core_feedback": False,
        "scientific_authority": False,
        "holdout_access": False,
        "broker_authority": False,
        "limitations": [
            "Comparing two historical reports does not prove identical operator expectations, "
            "underlying data/lineage independence or causal experiment improvement.",
            "Displayed research topics may change solely due to operator-declared procedure "
            "expectations, a top-N limit or newly ingested historical evidence.",
            "Append-only record identity is a local consistency rule, not cryptographic "
            "source/export authorization or current signer status.",
            "A new record can be another observation of the same data/lineage, not replication.",
            "No FRI report can overwrite closed research or submit a question to Core.",
        ],
    }
    result["report_sha256"] = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()
    return result
