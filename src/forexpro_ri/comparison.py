"""Non-authoritative, evidence-linked comparisons of already recorded experiments.

No strategy performance metrics or free-text observations are stored in memory.
Missing status never means PASS. A comparison never asserts scientific independence
or validation/protocol equivalence between its selected experiments.
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError, _ALLOWED_PROCEDURES
from .memory import _connect, _load

_REPORT_SCHEMA_VERSION = 1
_MAX_SELECTED = 50
_MAX_STORED = 5000
_STATUSES = ("FAIL", "PASS", "NOT_EVALUABLE", "UNOBSERVED")


def _validate_ids(experiment_ids: Sequence[str]) -> list[str]:
    if isinstance(experiment_ids, (str, bytes)) or not isinstance(experiment_ids, Sequence):
        raise EvidenceError("experiment_ids must be a sequence of distinct experiment IDs")
    if not 2 <= len(experiment_ids) <= _MAX_SELECTED:
        raise EvidenceError("comparison requires 2..50 distinct experiment IDs")
    if any(not isinstance(e, str) or not e or len(e) > 128 for e in experiment_ids):
        raise EvidenceError("experiment IDs must be nonempty bounded strings")
    if len(set(experiment_ids)) != len(experiment_ids):
        raise EvidenceError("duplicate experiment IDs are forbidden")
    return sorted(experiment_ids)


def _validate_expected(expected: Sequence[str]) -> list[str]:
    if isinstance(expected, (str, bytes)) or not isinstance(expected, Sequence):
        raise EvidenceError("expected_procedures must be a sequence")
    if any(not isinstance(p, str) or p not in _ALLOWED_PROCEDURES for p in expected):
        raise EvidenceError("expected procedures must use the reviewed procedure allowlist")
    if len(set(expected)) != len(expected):
        raise EvidenceError("duplicate expected procedures are forbidden")
    return sorted(expected)


def build_comparison(
    db_path: str | Path,
    *,
    experiment_ids: Sequence[str],
    expected_procedures: Sequence[str] = (),
) -> dict[str, Any]:
    """Compare 2..50 explicitly selected stored experiments in one read snapshot.

    Expected procedures are *operator-provided*, never derived from ForexPro
    scientific authority or asserted to be a complete validation battery.
    """
    ids = _validate_ids(experiment_ids)
    expected = _validate_expected(expected_procedures)
    conn = _connect(db_path, creating=False)
    try:
        conn.execute("BEGIN")
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise EvidenceError("SQLite integrity check failed")
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise EvidenceError("SQLite foreign key check failed")
        stored_ids = [r["experiment_id"] for r in conn.execute(
            "SELECT experiment_id FROM experiments ORDER BY experiment_id"
        ).fetchall()]
        if len(stored_ids) > _MAX_STORED:
            raise EvidenceError("too many stored experiments for bounded comparison")
        # Verify all records, not only the selected cohort, before reporting.
        records = {eid: _load(conn, eid) for eid in stored_ids}
        missing = sorted(set(ids) - set(records))
        if missing:
            raise EvidenceError("unknown experiment IDs: " + ", ".join(missing))

        states: dict[str, dict[str, dict[str, Any]]] = {eid: {} for eid in ids}
        # Select exact IDs with bound parameters; no dynamic SQL identifiers.
        slots = ",".join("?" for _ in ids)
        for row in conn.execute(
            "SELECT experiment_id, procedure, criterion_id, verdict, observation_sha256 "
            f"FROM criteria WHERE experiment_id IN ({slots}) "
            "ORDER BY experiment_id, procedure, criterion_id", ids
        ):
            group = states[row["experiment_id"]].setdefault(row["procedure"], {"criteria": []})
            group["criteria"].append({
                "criterion_id": row["criterion_id"],
                "recorded_verdict": row["verdict"],
                "observation_sha256": row["observation_sha256"],
            })
        for row in conn.execute(
            "SELECT experiment_id, procedure, reason_sha256 "
            f"FROM not_evaluable WHERE experiment_id IN ({slots}) "
            "ORDER BY experiment_id, procedure", ids
        ):
            procedures = states[row["experiment_id"]]
            if row["procedure"] in procedures:
                raise EvidenceError("contradictory procedure evaluability in Research Memory")
            procedures[row["procedure"]] = {"not_evaluable_reason_sha256": row["reason_sha256"]}

        observed = {p for per_exp in states.values() for p in per_exp}
        all_procedures = sorted(observed | set(expected))
        comparisons: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        diverged: list[str] = []
        for procedure in all_procedures:
            outcomes: list[dict[str, Any]] = []
            counts = dict.fromkeys(_STATUSES, 0)
            for eid in ids:
                evidence = states[eid].get(procedure)
                if evidence is None:
                    status = "UNOBSERVED"
                    refs: list[dict[str, str]] = []
                    reason_sha = None
                elif "not_evaluable_reason_sha256" in evidence:
                    status = "NOT_EVALUABLE"
                    refs = []
                    reason_sha = evidence["not_evaluable_reason_sha256"]
                else:
                    refs = evidence["criteria"]
                    status = "FAIL" if any(c["recorded_verdict"] == "FAIL" for c in refs) else "PASS"
                    reason_sha = None
                counts[status] += 1
                outcome = {
                    "experiment_id": eid,
                    "entry_sha256": records[eid]["entry_sha256"],
                    "recorded_status": status,
                    "criteria_evidence": refs,
                    "not_evaluable_reason_sha256": reason_sha,
                }
                outcomes.append(outcome)
                if status in {"NOT_EVALUABLE", "UNOBSERVED"}:
                    gaps.append({
                        "experiment_id": eid,
                        "entry_sha256": records[eid]["entry_sha256"],
                        "procedure": procedure,
                        "recorded_status": status,
                        "basis": "OPERATOR_DECLARED" if procedure in expected else "COHORT_OBSERVED",
                        "reason_sha256": reason_sha,
                    })
            status_divergence = sum(value > 0 for value in counts.values()) > 1
            if status_divergence:
                diverged.append(procedure)
            comparisons.append({
                "procedure": procedure,
                "expected_by_operator": procedure in expected,
                "status_divergence": status_divergence,
                "counts": counts,
                "outcomes": outcomes,
            })

        selected = [
            {
                "experiment_id": eid,
                "entry_sha256": records[eid]["entry_sha256"],
                "source_revision": records[eid]["source_revision"],
                "summary_sha256": records[eid]["summary_sha256"],
                "recorded_disposition": records[eid]["disposition"],
            }
            for eid in ids
        ]
        report: dict[str, Any] = {
            "schema_version": _REPORT_SCHEMA_VERSION,
            "report_kind": "NON_AUTHORITATIVE_COHORT_COMPARISON",
            "selected_experiments": selected,
            "declared_expected_procedures": expected,
            "comparison": comparisons,
            "evidence_gaps": gaps,
            "divergent_procedures": diverged,
            "memory_selection_sha256": hashlib.sha256(canonical_json({"entries": selected}).encode("utf-8")).hexdigest(),
            "source_authenticity": "NOT_ESTABLISHED_FROM_MEMORY",
            "scientific_authority": False,
            "holdout_access": False,
            "broker_authority": False,
            "limitations": [
                "Operator-selected cases are not scientifically proven independent or directly comparable.",
                "Expected procedures are operator declarations, NOT a verified ForexPro ValidationContract.",
                "UNOBSERVED means no saved verdict; it is neither PASS nor FAIL.",
                "NOT_EVALUABLE means no registered evaluable result, not a failed profitability criterion.",
                "Differences in recorded statuses are descriptive, never causation or performance evidence.",
                "Memory stores only digests and verdicts, not original metrics, observations or signed attestations.",
                "This report cannot change closed research, scientific approval or broker state.",
            ],
        }
        report["report_sha256"] = hashlib.sha256(canonical_json(report).encode("utf-8")).hexdigest()
        return report
    except sqlite3.Error as exc:
        raise EvidenceError(f"cannot compare Research Memory: {exc}") from exc
    finally:
        conn.close()


def render_markdown(report: dict[str, Any]) -> str:
    """Render only the strict, locally generated comparison shape (not arbitrary text)."""
    if report.get("report_kind") != "NON_AUTHORITATIVE_COHORT_COMPARISON":
        raise EvidenceError("expected non-authoritative comparison report")
    ids = [e["experiment_id"] for e in report["selected_experiments"]]
    # Allowed experiment IDs exclude pipes, but escape defensively.
    safe = lambda s: str(s).replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    lines = [
        "# FRI research cohort comparison (advisory)",
        "",
        "**Not scientific validation or promotion authority.** Experiments may share datasets or research lineage.",
        "",
        "Experiments: " + ", ".join(f"`{safe(eid)}`" for eid in ids),
        "",
        "| Procedure | " + " | ".join(safe(eid) for eid in ids) + " | Expected by operator |",
        "| --- | " + " | ".join("---" for _ in ids) + " | --- |",
    ]
    for comparison in report["comparison"]:
        statuses = [o["recorded_status"] for o in comparison["outcomes"]]
        lines.append("| " + safe(comparison["procedure"]) + " | " + " | ".join(statuses)
                     + " | " + ("yes" if comparison["expected_by_operator"] else "no") + " |")
    lines.extend(["", "## Evidence visibility gaps", ""])
    if report["evidence_gaps"]:
        for gap in report["evidence_gaps"]:
            lines.append("- `" + safe(gap["experiment_id"]) + "` / `" + safe(gap["procedure"])
                         + "`: **" + gap["recorded_status"] + "** (" + gap["basis"] + ")"
                         + "; entry SHA-256 `" + gap["entry_sha256"] + "`")
    else:
        lines.append("No missing or non-evaluable statuses in the selected procedure comparison.")
    lines.extend(["", "## Provenance", "", "- Memory selection SHA-256: `" + report["memory_selection_sha256"] + "`",
                  "- Report SHA-256: `" + report["report_sha256"] + "`", "- Source authenticity: not established from Research Memory",
                  "", "**Limitations:** " + " ".join(report["limitations"]), ""])
    return "\n".join(lines)
