"""Synthetic-only export contract rehearsal; never reads ForexPro Core.

A production exporter belongs to the private source system. No signing private
key, broker credential, private dataset, or source-scientific authority is used
by this module. Synthetic signing keys live only in process memory.
"""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .attestation import _message, verify_export
from .contracts import EvidenceError
from .failure_intelligence import build_failure_report
from .memory import ingest, verify as verify_memory

_KID = "SYNTHETIC_EPHEMERAL_BRIDGE_V1"
_ALLOWED_BUNDLE_NAMES = frozenset({"manifest.json", "summary.json", "attestation.json"})


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _real_parent(path: Path) -> Path:
    parent = path.parent
    if not parent.is_dir() or parent.is_symlink():
        raise EvidenceError("output parent must be an existing, real directory")
    if path.is_symlink() or path.exists():
        raise EvidenceError("output already exists or is a symbolic link")
    return parent.resolve()


def create_synthetic_fixture(bundle_path: str | Path, trust_path: str | Path) -> dict[str, Any]:
    """Create one bounded, explicitly synthetic, signed contract fixture.

    Generates a fresh private signing key IN MEMORY and writes only its public
    counterpart into a separately provisioned local trust-store file. Neither
    the source platform nor private research inputs are read, even optionally.
    """
    bundle = Path(bundle_path)
    trust = Path(trust_path)
    bundle_parent = _real_parent(bundle)
    _real_parent(trust)
    if trust.resolve().is_relative_to((bundle_parent / bundle.name).resolve()):
        raise EvidenceError("trust store must be outside the bundle")
    if bundle.resolve() == trust.resolve():
        raise EvidenceError("bundle and trust store paths must be distinct")

    summary: dict[str, Any] = {
        "experiment_id": "SYNTHETIC-BRIDGE-001",
        "disposition": "CLOSED_UNSUCCESSFUL",
        "criteria": [
            {"criterion_id": "synthetic-oos", "procedure": "OUT_OF_SAMPLE", "verdict": "FAIL",
             "observation": "SYNTHETIC: negative out-of-sample metric"},
            {"criterion_id": "synthetic-cost", "procedure": "COST_STRESS", "verdict": "FAIL",
             "observation": "SYNTHETIC: transaction-cost stress threshold exceeded"},
            {"criterion_id": "synthetic-rerun", "procedure": "DETERMINISTIC_RERUN", "verdict": "PASS",
             "observation": "SYNTHETIC: deterministic replay verified"},
        ],
        "not_evaluable": [{"procedure": "REGIME_STABILITY",
                           "reason": "SYNTHETIC: insufficient preregistered context"}],
    }
    summary_raw = _json_bytes(summary)
    summary_sha = hashlib.sha256(summary_raw).hexdigest()
    manifest = {
        "schema_version": 1,
        "export_kind": "CLOSED_EXPERIMENT_SUMMARY",
        "source_system": "forexpro",
        "experiment_id": "SYNTHETIC-BRIDGE-001",
        "source_revision": "a" * 40,  # deliberately invalid as evidence of a real source commit
        "summary_sha256": summary_sha,
        "approved_scope": "READ_ONLY_ADVISORY",
        "holdout_access": False,
        "promotion_authority": False,
        "broker_authority": False,
    }
    manifest_raw = _json_bytes(manifest)
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    trust_raw = _json_bytes({
        "schema_version": 1,
        "keys": [{"key_id": _KID, "algorithm": "Ed25519", "source_system": "forexpro",
                  "purpose": "CLOSED_EXPERIMENT_SUMMARY", "status": "ACTIVE",
                  "public_key_b64": base64.b64encode(public).decode("ascii")}],
    })
    signed = {"schema_version": 1, "algorithm": "Ed25519", "key_id": _KID,
              "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
              "summary_sha256": summary_sha}
    attestation_raw = _json_bytes({
        **signed, "signature_b64": base64.b64encode(private.sign(_message(signed))).decode("ascii")
    })
    # Use a staging directory, so the bundle is never visible half-written.
    staging = Path(tempfile.mkdtemp(prefix=".fri-synthetic-stage-", dir=bundle_parent))
    trust_created = False
    try:
        for name, raw in (("manifest.json", manifest_raw), ("summary.json", summary_raw),
                          ("attestation.json", attestation_raw)):
            (staging / name).write_bytes(raw)
        with trust.open("xb") as f:
            trust_created = True
            f.write(trust_raw)
        # No overwrite; a caller must allocate an unused path.
        if bundle.exists() or bundle.is_symlink():
            raise EvidenceError("bundle output already exists")
        staging.rename(bundle)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        if trust_created:
            trust.unlink(missing_ok=True)
        raise
    return {"fixture": "SYNTHETIC_ONLY", "experiment_id": manifest["experiment_id"],
            "bundle_path": str(bundle), "trust_store_path": str(trust),
            "private_key_persisted": False, "scientific_authority": False,
            "broker_authority": False, "holdout_access": False}


def preflight(bundle_path: str | Path, trust_store_path: str | Path) -> dict[str, Any]:
    """Check compatibility and cryptographic origin, NOT export authorization.

    Return only concise identifiers and counts: no private observation text.
    """
    bundle = Path(bundle_path)
    if bundle.is_symlink() or not bundle.is_dir():
        raise EvidenceError("bundle must be a real local directory")
    names = {p.name for p in bundle.iterdir()}
    if names != _ALLOWED_BUNDLE_NAMES or any(p.is_symlink() or not p.is_file() for p in bundle.iterdir()):
        raise EvidenceError("bundle must contain exactly three regular protocol files")
    manifest, summary, receipt = verify_export(bundle, trust_store_path)
    evaluated = {c["procedure"] for c in summary["criteria"]}
    unevaluated = {c["procedure"] for c in summary["not_evaluable"]}
    if evaluated & unevaluated:
        raise EvidenceError("same procedure cannot be evaluated and not evaluable")
    return {
        "protocol_version": 1,
        "status": "CRYPTOGRAPHIC_PROTOCOL_PASS",
        "NOT_EXPORT_APPROVAL": True,
        "experiment_id": manifest.experiment_id,
        "source_revision": manifest.source_revision,
        "disposition": summary["disposition"],
        "counts": {
            "fail": sum(c["verdict"] == "FAIL" for c in summary["criteria"]),
            "pass": sum(c["verdict"] == "PASS" for c in summary["criteria"]),
            "not_evaluable": len(summary["not_evaluable"]),
        },
        "signer_key_id": receipt["signer_key_id"],
        "attestation_sha256": receipt["attestation_sha256"],
        "summary_sha256": manifest.summary_sha256,
        "authority": {"scientific": False, "holdout": False, "broker": False},
        "warning": "Cryptographic origin and schema only; exporter custody, data classification and permission require independent owner review.",
    }


def rehearsal() -> dict[str, Any]:
    """Exercise full FRI read-only flow in a temporary synthetic sandbox."""
    with tempfile.TemporaryDirectory(prefix="fri-bridge-synthetic-") as td:
        root = Path(td)
        bundle, trust, db = root / "synthetic-bundle", root / "trust.json", root / "memory.sqlite"
        create_synthetic_fixture(bundle, trust)
        checked = preflight(bundle, trust)
        first = ingest(bundle, db, trust_store=trust)
        second = ingest(bundle, db, trust_store=trust)
        memory_status = verify_memory(db)
        intelligence = build_failure_report(db, focus_experiment_id="SYNTHETIC-BRIDGE-001")
        if first["status"] != "IMPORTED" or second["status"] != "ALREADY_PRESENT":
            raise EvidenceError("rehearsal failed idempotence invariant")
        if checked["counts"] != {"fail": 2, "pass": 1, "not_evaluable": 1}:
            raise EvidenceError("rehearsal failed source-count invariant")
        if memory_status["experiment_count"] != 1 or intelligence["observed_experiment_count"] != 1:
            raise EvidenceError("rehearsal failed consistency invariant")
        return {
            "status": "SYNTHETIC_REHEARSAL_PASS",
            "signed_export_verified": True,
            "memory_integrity_verified": True,
            "idempotent_reimport": True,
            "failure_intelligence_verified": True,
            "fixture_only": True,
            "core_access": False,
            "scientific_authority": False,
            "holdout_access": False,
            "broker_authority": False,
            "source_commit_authenticity": "NOT_ESTABLISHED",
        }
