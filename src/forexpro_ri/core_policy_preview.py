"""Fail-closed, read-only preview of the *proposed* Core v1 recipient policy.

SYNTHETIC signed bundles ONLY. Never produces a release, authorizes a source
record, declassifies text, or imports into Research Memory. The phrase set is
an UNAPPROVED candidate (Core draft #526), not a production DLP control.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

from .attestation import verify_export
from .contracts import EvidenceError

CATALOG_ID = "FRI_SAFE_PHRASES_V1_CANDIDATE_NOT_APPROVED"
REVIEWED_CANDIDATE_SHA256 = "7dbe7ec841bc15262051128d55c2ec4ce2673ce1034d3740d7c0679083eff8d5"
_LABELS = {
    "OUT_OF_SAMPLE": "out-of-sample",
    "COST_STRESS": "cost-stress",
    "PARAMETER_STABILITY": "parameter-stability",
    "MONTE_CARLO": "Monte Carlo",
    "WALK_FORWARD": "walk-forward",
    "REGIME_STABILITY": "regime-stability",
    "DETERMINISTIC_RERUN": "deterministic-rerun",
    "RISK_LIMITS": "risk-limit",
    "SAMPLE_SUFFICIENCY": "sample-sufficiency",
    "MULTIPLE_TESTING": "multiple-testing",
}
_OUTCOMES = {"PASS": "met", "FAIL": "not met"}
_FILES = frozenset({"summary.json", "manifest.json", "attestation.json"})
_MAX_BATCH = 20


def _canonical(data: dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def candidate_catalog_sha256() -> str:
    """Content identity only, never a declassification approval."""
    rows = [
        {
            "procedure": procedure,
            "verdict": verdict,
            "observation": f"The {label} criterion was {word}.",
        }
        for procedure, label in sorted(_LABELS.items())
        for verdict, word in sorted(_OUTCOMES.items())
    ]
    return hashlib.sha256(_canonical({
        "catalog_id": CATALOG_ID, "schema_version": 1, "rows": rows,
        "not_evaluable_supported": False,
    })).hexdigest()


def _layout(root: Path, trust: Path) -> None:
    """Reject unexpected files/links before asking existing Ed25519 verifier."""
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError("synthetic policy bundle directory invalid")
    entries = list(root.iterdir())
    if len(entries) != 3 or {entry.name for entry in entries} != _FILES:
        raise EvidenceError("synthetic policy requires exactly three protocol files")
    for entry in entries:
        if entry.is_symlink() or not entry.is_file():
            raise EvidenceError("synthetic policy rejects symlink or nested input")
        if entry.stat().st_size > (16_384 if entry.name == "attestation.json" else 1_048_576):
            raise EvidenceError("synthetic policy input oversized")
    if trust.is_symlink() or not trust.is_file() or trust.resolve().is_relative_to(root.resolve()):
        raise EvidenceError("synthetic policy trust store must be independent")


def inspect_synthetic_core_v1_batch(
    bundles: Sequence[str | Path], *, trust_store: str | Path
) -> dict[str, Any]:
    """Inspect signed, explicitly synthetic bundles without writing or ingesting.

    A matching synthetic phrase proves neither privacy, complete Core source
    ValidationEvidence, authoritative closure, trusted signer custody nor a
    human release grant. It does NOT enable use with real research data.
    """
    if type(bundles) not in (tuple, list) or not (1 <= len(bundles) <= _MAX_BATCH):
        raise EvidenceError("synthetic recipient batch must contain 1-20 bundles")
    if candidate_catalog_sha256() != REVIEWED_CANDIDATE_SHA256:
        raise EvidenceError("unapproved phrase catalog changed; independent review needed")

    trust = Path(trust_store)
    seen_paths: set[Path] = set()
    seen_ids: set[str] = set()
    criteria_total = 0
    failures = 0
    for bundle in bundles:
        root = Path(bundle)
        _layout(root, trust)
        resolved = root.resolve()
        if resolved in seen_paths:
            raise EvidenceError("duplicate synthetic bundle path")
        seen_paths.add(resolved)
        # Verify signed bytes with the existing FRI protocol *before* examining
        # controlled phrase contents. No second read of the signed documents.
        manifest, summary, receipt = verify_export(root, trust)
        if (not manifest.experiment_id.startswith("SYNTHETIC-") or
                not receipt["signer_key_id"].startswith("SYNTHETIC_")):
            raise EvidenceError("real or ambiguously labeled bundle denied by preview")
        if manifest.experiment_id in seen_ids:
            raise EvidenceError("duplicate synthetic experiment in batch")
        seen_ids.add(manifest.experiment_id)
        if summary["disposition"] != "CLOSED_UNSUCCESSFUL" or summary["not_evaluable"] != []:
            raise EvidenceError("incomplete or not-evaluable scientific claim denied")
        criteria = summary["criteria"]
        if not 10 <= len(criteria) <= 200:
            raise EvidenceError("candidate policy requires full ten-kind preview")
        observed_kinds: set[str] = set()
        fail_count = 0
        for item in criteria:
            procedure, verdict = item["procedure"], item["verdict"]
            if procedure not in _LABELS or verdict not in _OUTCOMES:
                raise EvidenceError("unrecognized candidate phrase category")
            expected = f"The {_LABELS[procedure]} criterion was {_OUTCOMES[verdict]}."
            if item["observation"] != expected:
                raise EvidenceError("observation is not the exact candidate phrase")
            observed_kinds.add(procedure)
            fail_count += int(verdict == "FAIL")
        if observed_kinds != set(_LABELS) or not fail_count:
            raise EvidenceError("missing validation kind or failed criterion")
        criteria_total += len(criteria)
        failures += fail_count

    # No bundle names, IDs, paths, key identifiers, science, or observations.
    return {
        "schema_version": 1,
        "status": "SYNTHETIC_CORE_V1_RECIPIENT_PREVIEW_ONLY",
        "synthetic_only": True,
        "bundle_count": len(bundles),
        "criterion_count": criteria_total,
        "failure_count": failures,
        "procedure_kind_count": len(_LABELS),
        "candidate_phrase_catalog_sha256": REVIEWED_CANDIDATE_SHA256,
        "signed_bundle_checked": True,
        "full_core_validation_evidence_authenticated": False,
        "terminal_closure_authenticated": False,
        "source_registry_authenticated": False,
        "dictionary_approved": False,
        "declassification_approved": False,
        "current_export_authorization": False,
        "real_ingestion_approved": False,
        "scientific_approval": False,
        "holdout_access": False,
        "broker_authority": False,
        "core_feedback_authority": False,
    }
