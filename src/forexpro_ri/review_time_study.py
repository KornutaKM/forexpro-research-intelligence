"""Offline paired researcher-time study, no raw case text, network or Core access.

Human time records remain SELF_REPORTED until independently reviewed. A fast
synthetic benchmark is never a product performance result or authority grant.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from statistics import median
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError

_TASK_ID = re.compile(r"^TASK-[0-9]{3}$")
_KEYS = {
    "task_id", "order", "manual_seconds", "fri_seconds",
    "manual_correct", "fri_correct", "manual_citations_correct",
    "fri_citations_correct", "manual_independence_error",
    "fri_independence_error",
}
_SOURCE = {"CURATED_SYNTHETIC_ONLY", "SELF_REPORTED_PRIVATE_OPERATOR"}
_ORDERS = {"MANUAL_FIRST", "FRI_FIRST"}


def analyze_paired_study(input_data: dict[str, Any]) -> dict[str, Any]:
    """Report paired descriptive speed/quality without unearned validation.

    Input requires task IDs and numeric measurements only. No free text,
    source URLs, researcher names, protected evidence or strategies are allowed.
    """
    if (type(input_data) is not dict or set(input_data) != {
        "schema_version", "source_class", "tasks"
    } or input_data.get("schema_version") != 1
            or input_data.get("source_class") not in _SOURCE):
        raise EvidenceError("unsupported private paired-study schema")
    tasks = input_data["tasks"]
    if type(tasks) is not list or not 2 <= len(tasks) <= 200:
        raise EvidenceError("paired study must contain 2..200 tasks")
    observed = set()
    ratios, manual_times, fri_times = [], [], []
    orders = Counter()
    manual_wrong = fri_wrong = manual_refs_wrong = fri_refs_wrong = 0
    manual_independence = fri_independence = 0
    fri_worse_tasks = 0
    for row in tasks:
        if type(row) is not dict or set(row) != _KEYS:
            raise EvidenceError("task schema contains unsupported fields")
        task_id = row["task_id"]
        if type(task_id) is not str or not _TASK_ID.fullmatch(task_id) or task_id in observed:
            raise EvidenceError("invalid or repeated task identity")
        observed.add(task_id)
        order = row["order"]
        if order not in _ORDERS:
            raise EvidenceError("invalid task order")
        orders[order] += 1
        manual, fri = row["manual_seconds"], row["fri_seconds"]
        for seconds in (manual, fri):
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or not 0.01 <= seconds <= 28800:
                raise EvidenceError("invalid paired time; requires finite positive seconds")
        for key in (
            "manual_correct", "fri_correct", "manual_citations_correct",
            "fri_citations_correct", "manual_independence_error",
            "fri_independence_error",
        ):
            if type(row[key]) is not bool:
                raise EvidenceError("quality decisions must be booleans")
        manual_times.append(manual)
        fri_times.append(fri)
        ratios.append(manual / fri)
        manual_wrong += not row["manual_correct"]
        fri_wrong += not row["fri_correct"]
        manual_refs_wrong += not row["manual_citations_correct"]
        fri_refs_wrong += not row["fri_citations_correct"]
        manual_independence += row["manual_independence_error"]
        fri_independence += row["fri_independence_error"]
        if ((row["manual_correct"] and not row["fri_correct"])
                or (row["manual_citations_correct"] and not row["fri_citations_correct"])
                or (not row["manual_independence_error"] and row["fri_independence_error"])):
            fri_worse_tasks += 1

    sample_adequate = len(tasks) >= 20 and all(orders[x] >= 5 for x in _ORDERS)
    noninferior = fri_worse_tasks == 0 and fri_wrong <= manual_wrong and (
        fri_refs_wrong <= manual_refs_wrong and fri_independence <= manual_independence
    )
    # No causal inference or external validation even when quality and time
    # look favorable: assignment, learning effects and review are not verified.
    result = {
        "schema_version": 1,
        "report_kind": "NON_AUTHORITATIVE_PAIRED_RESEARCHER_TIME_STUDY",
        "source_class": input_data["source_class"],
        "status": "CURATED_SYNTHETIC_ONLY" if input_data["source_class"] == "CURATED_SYNTHETIC_ONLY"
                  else "SELF_REPORTED_PRIVATE_PILOT",
        "task_count": len(tasks),
        "order_counts": dict(sorted(orders.items())),
        "manual_total_seconds": round(sum(manual_times), 4),
        "fri_total_seconds": round(sum(fri_times), 4),
        "median_paired_speedup": round(median(ratios), 4),
        "geometric_mean_paired_speedup": round(math.exp(sum(math.log(r) for r in ratios) / len(ratios)), 4),
        "manual_incorrect_answers": manual_wrong,
        "fri_incorrect_answers": fri_wrong,
        "manual_incorrect_citations": manual_refs_wrong,
        "fri_incorrect_citations": fri_refs_wrong,
        "manual_false_independence_claims": manual_independence,
        "fri_false_independence_claims": fri_independence,
        "fri_worse_on_any_quality_dimension_tasks": fri_worse_tasks,
        "minimum_sample_and_order_balance_met": sample_adequate,
        "observed_quality_noninferiority": noninferior,
        "eligible_for_independent_private_review": (
            input_data["source_class"] == "SELF_REPORTED_PRIVATE_OPERATOR"
            and sample_adequate and noninferior
        ),
        "real_world_100x_confirmed": False,
        "causal_efficiency_gain_established": False,
        "scientific_authority": False,
        "broker_authority": False,
        "limitations": [
            "Observational paired values are not randomized, independently verified causal effects.",
            "Synthetic speedups are fabricated and do not establish real operator efficiency.",
            "Self-reported real timing requires separate independent review and task validation.",
            "Tasks must match in difficulty, evidence access and accuracy acceptance criteria.",
            "Statistical uncertainty, learning and order effects are not excluded by this report.",
            "No trading, scientific or Core execution authority can arise from these metrics.",
        ],
    }
    result["report_sha256"] = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()
    return result
