"""Verify detached Ed25519 attestations for explicitly exported, closed reports.

Public FRI holds ONLY trusted public keys; private signing keys remain exclusively
with the source-system exporter. This module never signs, exports or calls a broker.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import re
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .analysis import canonical_json
from .contracts import BundleManifest, EvidenceError, exact_keys, parse_summary
from .importer import _decode, _read_file

_MAX_TRUST_BYTES = 128 * 1024
_MAX_ATTESTATION_BYTES = 16 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_DOMAIN = b"FRI-CLOSED-EXPORT-ATTESTATION-V1\n"


def _field(value: Any, pattern: re.Pattern[str], name: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise EvidenceError(f"invalid attestation {name}")
    return value


def _base64(value: Any, length: int, name: str) -> bytes:
    if not isinstance(value, str) or len(value) > 256:
        raise EvidenceError(f"invalid {name}")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise EvidenceError(f"invalid {name}") from exc
    if len(decoded) != length or base64.b64encode(decoded).decode("ascii") != value:
        raise EvidenceError(f"noncanonical or invalid {name}")
    return decoded


def _read_trust_store(path: Path, bundle_dir: Path) -> dict[str, bytes]:
    if path.is_symlink() or not path.is_file():
        raise EvidenceError("trusted public key store must be a real local file")
    if path.resolve().is_relative_to(bundle_dir.resolve()):
        raise EvidenceError("trust store must be independently provisioned outside evidence bundle")
    if path.stat().st_size > _MAX_TRUST_BYTES:
        raise EvidenceError("trust store exceeds size limit")
    store = exact_keys(_decode(path.read_bytes(), "trusted-keys.json"), {"schema_version", "keys"}, "trust store")
    if type(store["schema_version"]) is not int or store["schema_version"] != 1:
        raise EvidenceError("unsupported trust store schema")
    keys = store["keys"]
    if not isinstance(keys, list) or not (0 < len(keys) <= 20):
        raise EvidenceError("trust store must contain 1-20 keys")
    result: dict[str, bytes] = {}
    for item in keys:
        key = exact_keys(item, {"key_id", "algorithm", "public_key_b64", "source_system", "purpose", "status"}, "trusted key")
        kid = _field(key["key_id"], _KEY_ID, "key_id")
        if kid in result:
            raise EvidenceError("duplicate trusted key_id")
        if key["algorithm"] != "Ed25519" or key["source_system"] != "forexpro" or key["purpose"] != "CLOSED_EXPERIMENT_SUMMARY":
            raise EvidenceError("unsupported trusted key purpose or algorithm")
        if key["status"] not in ("ACTIVE", "REVOKED"):
            raise EvidenceError("unsupported trusted key status")
        material = _base64(key["public_key_b64"], 32, "public key")
        # Including revoked keys prevents an accidental fallback to an old key.
        result[kid] = material if key["status"] == "ACTIVE" else b""
    return result


def _message(signed_fields: dict[str, Any]) -> bytes:
    """Exact protocol message: unambiguous domain tag + canonical signed fields."""
    return _DOMAIN + canonical_json(signed_fields).encode("utf-8")


def verify_export(bundle_dir: str | Path, trust_store_path: str | Path) -> tuple[BundleManifest, dict[str, Any], dict[str, Any]]:
    """Read bundle exactly once, validate it, then authenticate those bytes.

    Authentication means a valid signature by a key explicitly configured in a
    separate trust store; it does NOT prove scientific merit or legal approval.
    """
    root = Path(bundle_dir)
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError("bundle must be a real local directory")
    manifest_bytes = _read_file(root, "manifest.json")
    summary_bytes = _read_file(root, "summary.json")
    attestation_bytes = _read_file(root, "attestation.json")
    if len(attestation_bytes) > _MAX_ATTESTATION_BYTES:
        raise EvidenceError("attestation exceeds size limit")

    manifest = BundleManifest.parse(_decode(manifest_bytes, "manifest.json"))
    summary_hash = hashlib.sha256(summary_bytes).hexdigest()
    if summary_hash != manifest.summary_sha256:
        raise EvidenceError("summary SHA-256 mismatch")
    summary = parse_summary(_decode(summary_bytes, "summary.json"), manifest.experiment_id)

    a = exact_keys(
        _decode(attestation_bytes, "attestation.json"),
        {"schema_version", "algorithm", "key_id", "manifest_sha256", "summary_sha256", "signature_b64"},
        "attestation",
    )
    if type(a["schema_version"]) is not int or a["schema_version"] != 1 or a["algorithm"] != "Ed25519":
        raise EvidenceError("unsupported attestation schema or algorithm")
    kid = _field(a["key_id"], _KEY_ID, "key_id")
    m_hash = _field(a["manifest_sha256"], _SHA256, "manifest_sha256")
    s_hash = _field(a["summary_sha256"], _SHA256, "summary_sha256")
    if m_hash != hashlib.sha256(manifest_bytes).hexdigest() or s_hash != summary_hash:
        raise EvidenceError("attestation content binding mismatch")
    sig = _base64(a["signature_b64"], 64, "Ed25519 signature")
    trusted = _read_trust_store(Path(trust_store_path), root)
    if kid not in trusted:
        raise EvidenceError("signer key_id is not present in local trust store")
    if not trusted[kid]:
        raise EvidenceError("signer key_id has been revoked")
    signed_fields = {k: a[k] for k in ("schema_version", "algorithm", "key_id", "manifest_sha256", "summary_sha256")}
    try:
        Ed25519PublicKey.from_public_bytes(trusted[kid]).verify(sig, _message(signed_fields))
    except (InvalidSignature, ValueError) as exc:
        raise EvidenceError("invalid export attestation signature") from exc

    return manifest, summary, {
        "status": "SIGNATURE_VERIFIED",
        "scope": "CLOSED_EXPERIMENT_SUMMARY",
        "signer_key_id": kid,
        "signer_public_key_sha256": hashlib.sha256(trusted[kid]).hexdigest(),
        "attestation_sha256": hashlib.sha256(attestation_bytes).hexdigest(),
        "manifest_sha256": m_hash,
        "summary_sha256": s_hash,
        "source_revision": manifest.source_revision,
        "experiment_id": manifest.experiment_id,
        "scientific_approval": False,
        "broker_authority": False,
        "holdout_access": False,
        "warning": "Signature verified against operator-provisioned local public key. This does not validate scientific results or independently prove exporter custody.",
    }
