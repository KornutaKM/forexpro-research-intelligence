"""Synthetic-only recipient trust continuity (v2.8 preview).

This is NOT a production trust store or grant authority. All signed checkpoints,
operator public keys and external head/floor pins are caller supplied. The
module never generates signatures, accesses Core, ingests data or exports.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .contracts import EvidenceError, exact_keys
from .importer import _decode
from .core_policy_preview import (
    REVIEWED_CANDIDATE_SHA256, inspect_synthetic_core_v1_batch,
)

_DOMAIN = b"FRI-SYNTHETIC-RECIPIENT-TRUST-CHECKPOINT-V1\n"
_SHA = re.compile(r"^[a-f0-9]{64}$")
_OPERATOR = re.compile(r"^SYNTHETIC_RECEIVER_OWNER_[A-Z0-9_-]{1,64}$")
_EXPORTER = re.compile(r"^SYNTHETIC_[A-Za-z0-9_-]{1,110}$")
_ZERO = "0" * 64
_FIELDS = frozenset({"schema_version", "algorithm", "key_id", "payload", "signature_b64"})
_PAYLOAD = frozenset({
    "schema_version", "kind", "classification", "sequence", "previous_sha256",
    "key_epoch", "minimum_accepted_sequence", "trust_store_sha256",
    "catalog_sha256", "active_exporter_key_ids", "revoked_exporter_key_ids",
    "retired_operator_key_ids", "source_authority", "export_authority",
    "holdout_access", "broker_authority",
})
_MAX_CHAIN = 16
_MAX_CHECKPOINT = 4096
_MAX_KEYS = 8
_MAX_TRUST_BYTES = 128 * 1024
_MAX_BUNDLES = 20


def _need(condition: bool, reason: str) -> None:
    if not condition:
        raise EvidenceError("synthetic recipient trust denied: " + reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, entry in pairs:
        _need(key not in value, "duplicate JSON field")
        value[key] = entry
    return value


def _sha_text(value: Any) -> bool:
    return type(value) is str and _SHA.fullmatch(value) is not None


def _exporter_name(value: Any) -> bool:
    return (type(value) is str and _EXPORTER.fullmatch(value) is not None and
            not value.startswith("SYNTHETIC_RECEIVER_OWNER_"))


def _sorted_names(value: Any, pattern: re.Pattern[str], max_size: int) -> bool:
    valid = _exporter_name if pattern is _EXPORTER else (
        lambda name: type(name) is str and pattern.fullmatch(name) is not None)
    return (type(value) is list and len(value) <= max_size and
            all(valid(name) for name in value) and
            value == sorted(set(value)))


def synthetic_recipient_checkpoint_message(*, key_id: str, payload: dict[str, Any]) -> bytes:
    """Construct signed bytes only, for tests using externally generated test keys."""
    _need(type(key_id) is str and _OPERATOR.fullmatch(key_id) is not None,
          "operator test key ID invalid")
    _validate_payload(payload)
    return _DOMAIN + _canonical({
        "schema_version": 1, "algorithm": "Ed25519", "key_id": key_id,
        "payload": payload,
    })


def _validate_payload(p: Any) -> None:
    _need(type(p) is dict and p.keys() == _PAYLOAD, "unsupported checkpoint schema")
    _need(type(p["schema_version"]) is int and p["schema_version"] == 1 and
          p["kind"] == "SYNTHETIC_RECIPIENT_TRUST_NOT_AUTHORITY" and
          p["classification"] == "SYNTHETIC_ONLY", "not an isolated synthetic checkpoint")
    for name in ("sequence", "key_epoch", "minimum_accepted_sequence"):
        _need(type(p[name]) is int and 1 <= p[name] < 2**53,
              "invalid checkpoint number")
    _need(p["minimum_accepted_sequence"] <= p["sequence"] and
          p["key_epoch"] <= p["sequence"], "invalid checkpoint sequence floor")
    _need(_sha_text(p["previous_sha256"]) and _sha_text(p["trust_store_sha256"]) and
          p["catalog_sha256"] == REVIEWED_CANDIDATE_SHA256,
          "unreviewed candidate catalog or hash")
    _need((p["sequence"] == 1) == (p["previous_sha256"] == _ZERO),
          "genesis predecessor mismatch")
    for name, pattern, limit in (
        ("active_exporter_key_ids", _EXPORTER, 20),
        ("revoked_exporter_key_ids", _EXPORTER, 20),
        ("retired_operator_key_ids", _OPERATOR, _MAX_CHAIN),
    ):
        _need(_sorted_names(p[name], pattern, limit), "invalid signed key policy")
    _need(set(p["active_exporter_key_ids"]).isdisjoint(p["revoked_exporter_key_ids"]),
          "exporter key both active and revoked")
    _need(bool(p["active_exporter_key_ids"]), "no active synthetic exporter signer")
    _need(all(type(p[name]) is bool and p[name] is False for name in (
        "source_authority", "export_authority", "holdout_access", "broker_authority",
    )), "protected authority claim")


def _parse(raw: bytes) -> tuple[str, dict[str, Any], bytes]:
    _need(type(raw) is bytes and 0 < len(raw) <= _MAX_CHECKPOINT,
          "missing or oversized signed checkpoint")
    try:
        env = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        _need(type(env) is dict and env.keys() == _FIELDS and _canonical(env) == raw,
              "noncanonical checkpoint")
        _need(type(env["schema_version"]) is int and env["schema_version"] == 1 and
              env["algorithm"] == "Ed25519", "wrong checkpoint algorithm")
        name = env["key_id"]
        _need(type(name) is str and _OPERATOR.fullmatch(name) is not None,
              "wrong operator key ID")
        payload = env["payload"]
        _validate_payload(payload)
        b64 = env["signature_b64"]
        _need(type(b64) is str and len(b64) <= 128, "bad checkpoint signature")
        sig = base64.b64decode(b64, validate=True)
        _need(len(sig) == 64 and base64.b64encode(sig).decode("ascii") == b64,
              "bad checkpoint signature encoding")
    except (UnicodeError, ValueError, TypeError, KeyError, OverflowError,
            RecursionError, binascii.Error) as exc:
        raise EvidenceError("synthetic recipient trust denied: malformed checkpoint") from exc
    return name, payload, sig


def _trusted_operator_keys(keys: Mapping[str, bytes]) -> dict[str, bytes]:
    _need(type(keys) is dict and 1 <= len(keys) <= _MAX_KEYS,
          "invalid synthetic operator key set")
    seen: set[bytes] = set()
    result: dict[str, bytes] = {}
    for name, raw in keys.items():
        _need(type(name) is str and _OPERATOR.fullmatch(name) is not None and
              type(raw) is bytes and len(raw) == 32 and raw not in seen,
              "duplicate or invalid operator test key")
        seen.add(raw)
        result[name] = raw
    return result


def synthetic_operator_keyset_sha256(keys: Mapping[str, bytes]) -> str:
    """Deterministic test keyset identity; caller pins remain untrusted."""
    trusted = _trusted_operator_keys(keys)
    return _sha(_canonical([{
        "key_id": name, "public_key_sha256": _sha(raw),
    } for name, raw in sorted(trusted.items())]))


def _trust_snapshot(path: Path) -> tuple[str, dict[str, bytes], set[str], set[str]]:
    _need(not path.is_symlink() and path.is_file(), "missing independent trust file")
    _need(path.stat().st_size <= _MAX_TRUST_BYTES,
          "oversized test trust file")
    raw = path.read_bytes()
    _need(0 < len(raw) <= _MAX_TRUST_BYTES, "invalid trust file")
    decoded = exact_keys(_decode(raw, "trusted-keys.json"),
                         {"schema_version", "keys"}, "trusted public keys")
    _need(type(decoded["schema_version"]) is int and decoded["schema_version"] == 1 and
          type(decoded["keys"]) is list and 1 <= len(decoded["keys"]) <= 20,
          "unsupported public test trust file")
    active: set[str] = set()
    revoked: set[str] = set()
    all_keys: dict[str, bytes] = {}
    for item in decoded["keys"]:
        entry = exact_keys(item, {"key_id", "algorithm", "public_key_b64", "source_system",
                                  "purpose", "status"}, "public trust entry")
        name = entry["key_id"]
        _need(_exporter_name(name) and name not in all_keys and entry["algorithm"] == "Ed25519" and
              entry["source_system"] == "forexpro" and
              entry["purpose"] == "CLOSED_EXPERIMENT_SUMMARY" and
              entry["status"] in ("ACTIVE", "REVOKED"),
              "untrusted synthetic exporter key")
        key_b64 = entry["public_key_b64"]
        _need(type(key_b64) is str and len(key_b64) <= 128,
              "invalid exporter public key")
        try:
            public_key = base64.b64decode(key_b64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise EvidenceError("synthetic recipient trust denied: bad key encoding") from exc
        _need(len(public_key) == 32 and base64.b64encode(public_key).decode("ascii") == key_b64 and
              public_key not in all_keys.values(), "invalid or duplicate test signer material")
        all_keys[name] = public_key
        (active if entry["status"] == "ACTIVE" else revoked).add(name)
    return _sha(raw), all_keys, active, revoked


def inspect_synthetic_recipient_trust_continuity(
    bundles: Sequence[str | Path], *, trust_store: str | Path,
    signed_checkpoints: tuple[bytes, ...],
    operator_test_public_keys: Mapping[str, bytes],
    expected_operator_keyset_sha256: str,
    expected_genesis_sha256: str,
    expected_latest_sha256: str,
    expected_latest_sequence: int,
    independent_minimum_sequence: int,
) -> dict[str, Any]:
    """Compose a signed synthetic trust history with v2.7 recipient preflight.

    All operator keys and 'independent' anchors are supplied by the caller;
    the checker has no real trust-root custody, closure authority or release.
    """
    _need(type(bundles) in (tuple, list) and 1 <= len(bundles) <= _MAX_BUNDLES,
          "invalid synthetic batch")
    _need(type(signed_checkpoints) is tuple and 1 <= len(signed_checkpoints) <= _MAX_CHAIN,
          "invalid synthetic checkpoint chain")
    for value in (expected_operator_keyset_sha256, expected_genesis_sha256,
                  expected_latest_sha256):
        _need(_sha_text(value), "invalid external trust pin")
    for value in (expected_latest_sequence, independent_minimum_sequence):
        _need(type(value) is int and 1 <= value < 2**53,
              "invalid external trust sequence")
    keys = _trusted_operator_keys(operator_test_public_keys)
    _need(hmac.compare_digest(synthetic_operator_keyset_sha256(keys),
                              expected_operator_keyset_sha256),
          "operator test keyset pin mismatch")
    trust = Path(trust_store)
    before_digest, exporter_keys, active, revoked = _trust_snapshot(trust)
    _need(set(exporter_keys.values()).isdisjoint(keys.values()),
          "operator/exporter key roles reused")
    seen: set[str] = set()
    former_key: str | None = None
    former_payload: dict[str, Any] | None = None
    previous_hash: str | None = None
    former_revoked: set[str] = set()
    former_retired: set[str] = set()
    for index, raw in enumerate(signed_checkpoints):
        name, p, sig = _parse(raw)
        _need(name in keys, "unknown synthetic recipient operator")
        sha = _sha(raw)
        if index == 0:
            _need(hmac.compare_digest(sha, expected_genesis_sha256) and
                  p["sequence"] == 1 and p["key_epoch"] == 1 and
                  p["previous_sha256"] == _ZERO and
                  p["retired_operator_key_ids"] == [], "invalid operator chain genesis")
        else:
            assert former_payload is not None and previous_hash is not None and former_key is not None
            _need(p["sequence"] == former_payload["sequence"] + 1 and
                  hmac.compare_digest(p["previous_sha256"], previous_hash),
                  "operator chain gap, replay, rollback or fork")
            _need(former_payload["key_epoch"] <= p["key_epoch"] <=
                  former_payload["key_epoch"] + 1,
                  "operator key epoch rollback or jump")
            changed = name != former_key
            _need(changed == (p["key_epoch"] == former_payload["key_epoch"] + 1),
                  "operator signing key must rotate with epoch")
            _need(not changed or name not in seen,
                  "retired operator reused")
            _need(set(p["revoked_exporter_key_ids"]).issuperset(former_revoked),
                  "revoked exporter revived")
            _need(set(p["retired_operator_key_ids"]).issuperset(former_retired) and
                  set(p["retired_operator_key_ids"]).issubset(seen),
                  "retired operator forgotten or never active")
            _need((not changed or former_key in p["retired_operator_key_ids"]) and
                  (changed or set(p["retired_operator_key_ids"]) == former_retired),
                  "operator rotation missing predecessor retirement")
            _need(p["minimum_accepted_sequence"] >= former_payload["minimum_accepted_sequence"],
                  "signed anti-rollback floor decreased")
        _need(name not in p["retired_operator_key_ids"],
              "current operator is retired")
        signed_fields = {"schema_version": 1, "algorithm": "Ed25519",
                         "key_id": name, "payload": p}
        try:
            Ed25519PublicKey.from_public_bytes(keys[name]).verify(
                sig, _DOMAIN + _canonical(signed_fields))
        except (InvalidSignature, ValueError) as exc:
            raise EvidenceError("synthetic recipient trust denied: invalid operator signature") from exc
        seen.add(name)
        previous_hash = sha
        former_key = name
        former_payload = p
        former_revoked = set(p["revoked_exporter_key_ids"])
        former_retired = set(p["retired_operator_key_ids"])
    latest = former_payload
    assert latest is not None and previous_hash is not None
    _need(hmac.compare_digest(previous_hash, expected_latest_sha256) and
          latest["sequence"] == expected_latest_sequence and
          latest["minimum_accepted_sequence"] >= independent_minimum_sequence and
          latest["sequence"] >= independent_minimum_sequence,
          "old or unpinned current operator checkpoint")
    _need(hmac.compare_digest(latest["trust_store_sha256"], before_digest) and
          set(latest["active_exporter_key_ids"]) == active and
          set(latest["revoked_exporter_key_ids"]) == revoked,
          "current recipient trust store differs from signed policy")
    # Existing preview verifies each source attestation with the local
    # recipient trust store. It never treats a signature as source approval.
    policy = inspect_synthetic_core_v1_batch(bundles, trust_store=trust)
    after_digest, after_keys, after_active, after_revoked = _trust_snapshot(trust)
    _need(before_digest == after_digest and exporter_keys == after_keys and
          active == after_active and revoked == after_revoked,
          "trust file changed while evaluating synthetic bundles")
    _need(policy["status"] == "SYNTHETIC_CORE_V1_RECIPIENT_PREVIEW_ONLY" and
          policy["current_export_authorization"] is False and
          policy["real_ingestion_approved"] is False,
          "underlying synthetic Core policy preview invalid")
    return {
        "schema_version": 1,
        "status": "SYNTHETIC_RECIPIENT_TRUST_CONTINUITY_ONLY",
        "synthetic_only": True,
        "checkpoint_history_consistent_against_supplied_pins": True,
        "signed_bundle_count": policy["bundle_count"],
        "complete_negative_candidate_criteria": policy["criterion_count"],
        "operator_custody_independently_proven": False,
        "source_registry_authenticated": False,
        "current_source_closure_authenticated": False,
        "dictionary_approved": False,
        "declassification_approved": False,
        "current_export_authorization": False,
        "real_ingestion_approved": False,
        "scientific_approval": False,
        "holdout_access": False,
        "broker_authority": False,
        "core_feedback_authority": False,
    }
