"""v2.6 offline compatibility checks for a future PRIVATE approved exporter.

These checks do not create a ForexPro exporter, prove its custody or give any
scientific, holdout or broker authority. No network, source system or secrets.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .bridge import create_synthetic_fixture, preflight
from .contracts import EvidenceError

_PROTOCOL_FILES = frozenset({"manifest.json", "summary.json", "attestation.json"})


def check_bundle(bundle_dir: str | Path, trust_store: str | Path) -> dict[str, Any]:
    """Version-1 protocol preflight + strict no-extra-file disclosure boundary."""
    root = Path(bundle_dir)
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError("bundle must be a local directory")
    contents = list(root.iterdir())
    if len(contents) != 3 or {p.name for p in contents} != _PROTOCOL_FILES:
        raise EvidenceError("unsupported export bundle layout")
    if any(not p.is_file() or p.is_symlink() for p in contents):
        raise EvidenceError("symlink or nested export contents")
    for file in contents:
        if file.stat().st_size > (1_048_576 if file.name != "attestation.json" else 16_384):
            raise EvidenceError("export content exceeds bounds")
    source = Path(trust_store)
    if source.is_symlink() or not source.is_file() or source.resolve().is_relative_to(root.resolve()):
        raise EvidenceError("trust store not independently provisioned")
    validated = preflight(root, source)
    # preflight verifies Ed25519 and agreement between declared and recorded
    # observations; never promote signed provenance into export authorization.
    if validated.get("protocol_version") != 1 or validated.get("status") != "CRYPTOGRAPHIC_PROTOCOL_PASS":
        raise EvidenceError("unsupported bridge protocol")
    return {
        "schema_version": 1,
        "kind": "PRIVATE_EXPORTER_COMPATIBILITY_CHECK",
        "status": "CONTRACT_CONFORMANT_NOT_EXPORT_APPROVED",
        "protocol_version": validated["protocol_version"],
        "experiment_id": validated["experiment_id"],
        "source_revision": validated["source_revision"],
        "disposition": validated["disposition"],
        "counts": validated["counts"],
        "signature_verified": True,
        "trust_store_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "scientific_approval": False,
        "current_export_authorization": False,
        "access_holdout": False,
        "broker_authority": False,
        "warnings": [
            "Signature proves integrity and trust-store membership at check time, not the export policy decision.",
            "A production exporter MUST live privately inside ForexPro and sanitize all free-text fields.",
        ],
    }


def rehearsal() -> dict[str, Any]:
    """Entirely synthetic signed-export rehearsal with disposable ephemeral key."""
    from .advisor import build_advisor
    from .memory import ingest, verify
    from .quality import assess_advisor

    with tempfile.TemporaryDirectory(prefix="fri-v26-contract-") as name:
        root = Path(name)
        bundle = root / "synthetic-bundle"
        trust = root / "trusted-keys.json"
        memory = root / "history.sqlite"
        create_synthetic_fixture(bundle, trust)
        compatibility = check_bundle(bundle, trust)
        ingest(bundle, memory, trust_store=trust)
        verified = verify(memory)
        report = build_advisor(memory)
        quality = assess_advisor(report)
        # Strictly no private key file, no source-system data, no protected bytes.
        if any(p.name.endswith((".pem", ".key")) for p in root.rglob("*")):
            raise EvidenceError("synthetic key material was unexpectedly persisted")
        if not report["signed_only_gate_passed"] or quality["status"] != "PASS":
            raise EvidenceError("signed rehearsal evidence failed")
        return {
            "schema_version": 1,
            "rehearsal": "SYNTHETIC_ONLY",
            "status": "CONTRACT_REHEARSAL_PASS",
            "protocol_version": 1,
            "import_status": "SIGNED_AT_IMPORT",
            "compatibility_status": compatibility["status"],
            "memory_verified": True,
            "advisor_quality": quality["status"],
            "signed_only_gate_passed": report["signed_only_gate_passed"],
            "scientific_approval": False,
            "export_authorization": False,
            "holdout_access": False,
            "broker_authority": False,
            "no_production_exporter": True,
            "warnings": ["Synthetic conformance is not production export approval or an end-to-end ForexPro Core integration."],
        }
