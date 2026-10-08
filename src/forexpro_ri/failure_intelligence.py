"""Read-only, deterministic cross-experiment diagnostics from Research Memory.

This module observes persisted verdicts only. Co-occurrence is NOT causality,
independent replication, or evidence of a trading edge. No free text is loaded.
"""
from __future__ import annotations

import hashlib
import itertools
import sqlite3
from collections import defaultdict
from fractions import Fraction
from pathlib import Path
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError
from .memory import _connect, _load

_SCHEMA_VERSION = 1
_MAX_EXPERIMENTS = 5000
_MAX_SIMILAR_CASES = 10
_QUESTIONS = {
    "COST_STRESS": "For a NEW preregistered experiment, evaluate sensitivity to realistic transaction costs.",
    "OUT_OF_SAMPLE": "For a NEW preregistered experiment, examine whether the proposed mechanism persists out of sample.",
    "PARAMETER_STABILITY": "For a NEW preregistered experiment, specify a prospective parameter-stability protocol.",
    "MONTE_CARLO": "For a NEW preregistered experiment, specify acceptable trade-path and tail-risk sensitivity.",
    "WALK_FORWARD": "For a NEW preregistered experiment, inspect temporal stability with preselected windows.",
    "REGIME_STABILITY": "For a NEW preregistered experiment, specify causal context and warmup before measuring regime behavior.",
    "DETERMINISTIC_RERUN": "For a NEW preregistered experiment, verify deterministic replay before interpreting outcomes.",
    "MULTIPLE_TESTING": "For a NEW preregistered experiment, control for the search burden and selection bias.",
    "SAMPLE_SUFFICIENCY": "For a NEW preregistered experiment, set minimum sample/trade sufficiency requirements.",
    "RISK_LIMITS": "For a NEW preregistered experiment, define drawdown and tail-risk requirements.",
}


def _reference(row: dict[str, Any]) -> dict[str, str]:
    return {"experiment_id": row["experiment_id"], "entry_sha256": row["entry_sha256"]}


def build_failure_report(
    db_path: str | Path,
    *,
    focus_experiment_id: str | None = None,
    min_support: int = 2,
) -> dict[str, Any]:
    """Build a content-addressed, non-authoritative diagnostic over all stored experiments.

    A procedure is FAILED for an experiment if any registered criterion failed,
    otherwise PASSED if one or more criteria passed; NOT_EVALUABLE is distinct.
    Unobserved procedures are never treated as passed or failed.
    """
    if type(min_support) is not int or not 2 <= min_support <= _MAX_EXPERIMENTS:
        raise EvidenceError("min_support must be an integer from 2 through 5000")
    if focus_experiment_id is not None and (
        not isinstance(focus_experiment_id, str) or not focus_experiment_id
    ):
        raise EvidenceError("focus_experiment_id must be a nonempty experiment ID")

    conn = _connect(db_path, creating=False)
    try:
        conn.execute("BEGIN")  # Stable read snapshot: no mutation to the memory store.
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise EvidenceError("SQLite integrity check failed")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise EvidenceError("SQLite foreign key check failed")
        ids = [r["experiment_id"] for r in conn.execute(
            "SELECT experiment_id FROM experiments ORDER BY experiment_id"
        ).fetchall()]
        if len(ids) > _MAX_EXPERIMENTS:
            raise EvidenceError("too many experiments for bounded intelligence report")
        records = {eid: _load(conn, eid) for eid in ids}
        if focus_experiment_id is not None and focus_experiment_id not in records:
            raise EvidenceError("focus experiment not found")

        # DISTINCT procedures are used, not the raw number of test criteria.
        states: dict[str, dict[str, str]] = {eid: {} for eid in ids}
        for row in conn.execute(
            "SELECT experiment_id, procedure, verdict FROM criteria "
            "ORDER BY experiment_id, procedure, criterion_id"
        ):
            value = states[row["experiment_id"]]
            if row["verdict"] == "FAIL":
                value[row["procedure"]] = "FAIL"
            elif value.get(row["procedure"]) != "FAIL":
                value[row["procedure"]] = "PASS"
        for row in conn.execute(
            "SELECT experiment_id, procedure FROM not_evaluable "
            "ORDER BY experiment_id, procedure"
        ):
            value = states[row["experiment_id"]]
            if row["procedure"] in value:
                raise EvidenceError("contradictory procedure evaluability in memory")
            value[row["procedure"]] = "NOT_EVALUABLE"

        coverage: list[dict[str, Any]] = []
        for proc in sorted({p for value in states.values() for p in value}):
            groups = {kind: [eid for eid in ids if states[eid].get(proc) == kind]
                      for kind in ("FAIL", "PASS", "NOT_EVALUABLE")}
            coverage.append({
                "procedure": proc,
                "failed_experiments": len(groups["FAIL"]),
                "passed_experiments": len(groups["PASS"]),
                "not_evaluable_experiments": len(groups["NOT_EVALUABLE"]),
                "unobserved_experiments": len(ids) - sum(map(len, groups.values())),
                "failure_evidence": [_reference(records[e]) for e in groups["FAIL"]],
                "not_evaluable_evidence": [_reference(records[e]) for e in groups["NOT_EVALUABLE"]],
            })

        pair_members: dict[tuple[str, str], list[str]] = defaultdict(list)
        for eid in ids:
            failed = sorted(p for p, verdict in states[eid].items() if verdict == "FAIL")
            for pair in itertools.combinations(failed, 2):
                pair_members[pair].append(eid)
        cofailures = [
            {"procedures": list(pair), "co_failed_experiments": len(members),
             "evidence": [_reference(records[e]) for e in members]}
            for pair, members in pair_members.items() if len(members) >= min_support
        ]
        cofailures.sort(key=lambda row: (-row["co_failed_experiments"], row["procedures"]))

        recurring = []
        for item in coverage:
            for status, key in (("FAIL", "failed_experiments"),
                                ("NOT_EVALUABLE", "not_evaluable_experiments")):
                if item[key] >= min_support:
                    recurring.append({
                        "procedure": item["procedure"], "recorded_status": status,
                        "affected_experiments": item[key],
                        "evidence": item["failure_evidence"] if status == "FAIL"
                        else item["not_evaluable_evidence"],
                        "future_research_question": _QUESTIONS.get(item["procedure"]),
                    })
        recurring.sort(key=lambda row: (-row["affected_experiments"], row["procedure"], row["recorded_status"]))

        focus = None
        if focus_experiment_id is not None:
            target = states[focus_experiment_id]
            target_signatures = {(p, s) for p, s in target.items() if s != "PASS"}
            matched = []
            for eid in ids:
                if eid == focus_experiment_id:
                    continue
                signatures = {(p, s) for p, s in states[eid].items() if s != "PASS"}
                shared = target_signatures & signatures
                union = target_signatures | signatures
                if not shared:
                    continue
                matched.append((Fraction(len(shared), len(union)), eid, shared, union))
            matched.sort(key=lambda item: (-item[0], item[1]))
            focus = {
                "experiment": _reference(records[focus_experiment_id]),
                "procedure_outcomes": [{"procedure": p, "recorded_status": s}
                                       for p, s in sorted(target.items())],
                "similar_observed_cases": [
                    {"experiment": _reference(records[eid]),
                     "shared_negative_signatures": [{"procedure": p, "recorded_status": s}
                                                    for p, s in sorted(shared)],
                     "overlap": {"shared": len(shared), "union": len(union)}}
                    for _, eid, shared, union in matched[:_MAX_SIMILAR_CASES]
                ],
                "similar_cases_truncated": len(matched) > _MAX_SIMILAR_CASES,
            }

        source_entries = [_reference(records[e]) for e in ids]
        report: dict[str, Any] = {
            "schema_version": _SCHEMA_VERSION,
            "report_kind": "NON_AUTHORITATIVE_FAILURE_INTELLIGENCE",
            "observed_experiment_count": len(ids),
            "min_support": min_support,
            "memory_snapshot_sha256": hashlib.sha256(canonical_json({"entries": source_entries}).encode()).hexdigest(),
            "procedure_coverage": coverage,
            "recurring_observations": recurring,
            "co_failure_patterns": cofailures,
            "focus": focus,
            "scientific_authority": False,
            "holdout_access": False,
            "broker_authority": False,
            "source_authenticity": "NOT_ESTABLISHED_FROM_MEMORY",
            "limitations": [
                "Counts describe stored, operator-selected closed experiments; they are not population rates.",
                "Multiple experiments may share data, code or lineage. Independence is NOT established.",
                "Co-failures, similarity and recurring observations do NOT identify causes.",
                "Free-text details and underlying test metrics are absent from Research Memory.",
                "Stored hashes are self-consistency checks, not cryptographic proof of authorized export.",
                "All questions concern NEW preregistered experiments and do not revise closed ones.",
            ],
        }
        report["report_sha256"] = hashlib.sha256(canonical_json(report).encode("utf-8")).hexdigest()
        return report
    except sqlite3.Error as exc:
        raise EvidenceError(f"cannot analyze Research Memory: {exc}") from exc
    finally:
        conn.close()
