"""Strict bundle contracts: no execution/promotion or holdout access."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_SHA = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
# Conservative export allowlist. Extending this is a reviewed contract change.
_ALLOWED_PROCEDURES = frozenset({
    "OUT_OF_SAMPLE", "COST_STRESS", "PARAMETER_STABILITY", "MONTE_CARLO",
    "WALK_FORWARD", "REGIME_STABILITY", "DETERMINISTIC_RERUN",
    "RISK_LIMITS", "SAMPLE_SUFFICIENCY", "MULTIPLE_TESTING",
})


class EvidenceError(ValueError):
    """Fail-closed evidence import error."""


def exact_keys(obj: Any, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(obj, dict) or set(obj) != expected:
        raise EvidenceError(f"{name} must contain exactly: {', '.join(sorted(expected))}")
    return obj


def str_field(value: Any, name: str, pattern: re.Pattern[str] | None = None) -> str:
    if not isinstance(value, str) or not value or (pattern and not pattern.fullmatch(value)):
        raise EvidenceError(f"invalid {name}")
    return value


@dataclass(frozen=True, slots=True)
class BundleManifest:
    schema_version: int
    export_kind: str
    source_system: str
    experiment_id: str
    source_revision: str
    summary_sha256: str
    approved_scope: str
    holdout_access: bool
    promotion_authority: bool
    broker_authority: bool

    @classmethod
    def parse(cls, value: Any) -> "BundleManifest":
        fields = set(cls.__dataclass_fields__)
        x = exact_keys(value, fields, "manifest")
        if type(x["schema_version"]) is not int or x["schema_version"] != 1:
            raise EvidenceError("unsupported manifest schema_version")
        if x["export_kind"] != "CLOSED_EXPERIMENT_SUMMARY":
            raise EvidenceError("only closed-experiment summaries are allowed")
        if x["source_system"] != "forexpro":
            raise EvidenceError("untrusted source_system")
        if x["approved_scope"] != "READ_ONLY_ADVISORY":
            raise EvidenceError("unsupported approved_scope")
        if any(type(x[k]) is not bool for k in ("holdout_access", "promotion_authority", "broker_authority")):
            raise EvidenceError("authority fields must be booleans")
        if x["holdout_access"] or x["promotion_authority"] or x["broker_authority"]:
            raise EvidenceError("protected capabilities must be false")
        str_field(x["experiment_id"], "experiment_id", _ID)
        str_field(x["source_revision"], "source_revision", _COMMIT)
        str_field(x["summary_sha256"], "summary_sha256", _SHA)
        return cls(**x)


def parse_summary(value: Any, experiment_id: str) -> dict[str, Any]:
    x = exact_keys(value, {"experiment_id", "disposition", "criteria", "not_evaluable"}, "summary")
    if x["experiment_id"] != experiment_id:
        raise EvidenceError("experiment identity mismatch")
    if x["disposition"] not in {"CLOSED_UNSUCCESSFUL", "CLOSED_INCOMPLETE"}:
        raise EvidenceError("input must have an explicitly closed unsuccessful/incomplete disposition")
    if not isinstance(x["criteria"], list) or not isinstance(x["not_evaluable"], list):
        raise EvidenceError("criteria and not_evaluable must be arrays")
    if len(x["criteria"]) > 200 or len(x["not_evaluable"]) > 100:
        raise EvidenceError("summary array too large")
    seen: set[str] = set()
    for i, item in enumerate(x["criteria"]):
        c = exact_keys(item, {"criterion_id", "procedure", "verdict", "observation"}, f"criteria[{i}]")
        cid = str_field(c["criterion_id"], "criterion_id", _ID)
        if cid in seen:
            raise EvidenceError("duplicate criterion_id")
        seen.add(cid)
        proc = str_field(c["procedure"], "procedure", _ID)
        if proc not in _ALLOWED_PROCEDURES:
            raise EvidenceError("procedure not allowed in advisory export")
        if c["verdict"] not in {"PASS", "FAIL"}:
            raise EvidenceError("only recorded PASS/FAIL verdicts are supported")
        if not isinstance(c["observation"], str) or not (0 < len(c["observation"]) <= 1000):
            raise EvidenceError("observation must be bounded nonempty text")
    seen_proc: set[str] = set()
    for i, item in enumerate(x["not_evaluable"]):
        c = exact_keys(item, {"procedure", "reason"}, f"not_evaluable[{i}]")
        proc = str_field(c["procedure"], "procedure", _ID)
        if proc not in _ALLOWED_PROCEDURES:
            raise EvidenceError("procedure not allowed in advisory export")
        if proc in seen_proc:
            raise EvidenceError("duplicate not_evaluable procedure")
        seen_proc.add(proc)
        if not isinstance(c["reason"], str) or not (0 < len(c["reason"]) <= 1000):
            raise EvidenceError("reason must be bounded nonempty text")
    if any(c["verdict"] == "FAIL" for c in x["criteria"]) and x["disposition"] != "CLOSED_UNSUCCESSFUL":
        raise EvidenceError("failed criteria cannot have non-unsuccessful disposition")
    if not x["criteria"] and not x["not_evaluable"]:
        raise EvidenceError("empty evidence summary")
    return x
