"""Deterministic summaries of recorded observations, not scientific authority."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .contracts import BundleManifest

# These are possible future experiment *design questions*, not strategy repairs.
_QUESTIONS = {
    "OUT_OF_SAMPLE": "For a newly registered experiment, investigate why performance did not persist out of sample.",
    "COST_STRESS": "For a new experiment, preregister realistic transaction-cost and execution-stress assumptions.",
    "PARAMETER_STABILITY": "For a new experiment, examine parameter sensitivity using an independent preregistered protocol.",
    "MONTE_CARLO": "For a new experiment, preregister path-risk and sample-robustness requirements.",
    "WALK_FORWARD": "For a new experiment, review temporal stability with a preregistered fold design.",
    "REGIME_STABILITY": "For a new experiment, preregister a causal warmup/context policy before validation.",
}


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def analyze(manifest: BundleManifest, summary: dict[str, Any]) -> dict[str, Any]:
    failed = sorted((c for c in summary["criteria"] if c["verdict"] == "FAIL"), key=lambda c: c["criterion_id"])
    passed = sorted((c for c in summary["criteria"] if c["verdict"] == "PASS"), key=lambda c: c["criterion_id"])
    uneval = sorted(summary["not_evaluable"], key=lambda c: c["procedure"])

    questions = []
    for proc in sorted({c["procedure"] for c in failed} | {x["procedure"] for x in uneval}):
        if proc in _QUESTIONS:
            questions.append({"procedure": proc, "question": _QUESTIONS[proc]})
    payload = {
        "schema_version": 1,
        "report_kind": "NON_AUTHORITATIVE_ADVISORY",
        "export_authenticity": "NOT_VERIFIED",
        "experiment_id": manifest.experiment_id,
        "source_revision": manifest.source_revision,
        "source_summary_sha256": manifest.summary_sha256,
        "recorded_disposition": summary["disposition"],
        "recorded_failures": failed,
        "recorded_passes": passed,
        "recorded_not_evaluable": uneval,
        "counts": {"fail": len(failed), "pass": len(passed), "not_evaluable": len(uneval)},
        "future_research_questions": questions,
        "authority": {
            "can_register_or_run_experiment": False,
            "can_change_scientific_state": False,
            "can_access_holdout": False,
            "can_place_broker_orders": False,
        },
        "warning": "Observations are taken from the explicitly exported summary; they are not independently reproduced. This report cannot reinterpret a closed experiment or approve a candidate.",
    }
    payload["report_sha256"] = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return payload
