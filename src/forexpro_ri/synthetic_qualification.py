"""Hermetic FRI recipient qualification: synthetic-only, no real input interface.

Generates ephemeral test signers IN MEMORY and creates solely disposable
synthetic evidence in a new temporary directory. The rehearsal composes the
conservative candidate policy, signed trust history, Research Memory, Advisor,
quality checks, backup/restore and negative source-tampering cases.
It never verifies a real Core source, grants an export or runs a broker.
"""
from __future__ import annotations

import base64
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .attestation import _message
from .advisor import build_advisor
from .contracts import EvidenceError
from .core_policy_preview import REVIEWED_CANDIDATE_SHA256, _LABELS
from .memory import ingest, verify as verify_memory
from .quality import assess_advisor
from .recovery import backup, restore_backup, verify_backup
from .synthetic_trust_continuity import (
    inspect_synthetic_recipient_trust_continuity,
    synthetic_operator_keyset_sha256,
    synthetic_recipient_checkpoint_message,
)

_ZERO = "0" * 64
_OPERATOR_IDS = ("SYNTHETIC_RECEIVER_OWNER_QUAL_A",
                 "SYNTHETIC_RECEIVER_OWNER_QUAL_B")
_EXPORTER_IDS = ("SYNTHETIC_QUAL_EXPORTER_A", "SYNTHETIC_QUAL_EXPORTER_B")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _wire(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _public(private: Ed25519PrivateKey) -> bytes:
    return private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )


def _new_file(path: Path, raw: bytes) -> None:
    # Creation-only, scoped to the TemporaryDirectory allocated by the drill.
    with path.open("xb") as stream:
        stream.write(raw)


def _test_bundle(root: Path, name: str, signer: Ed25519PrivateKey) -> Path:
    directory = root / ("synthetic-" + name)
    directory.mkdir(mode=0o700)
    exp = "SYNTHETIC-QUAL-" + name
    criteria = [
        {
            "criterion_id": "synthetic-" + procedure.lower(),
            "procedure": procedure,
            "verdict": "FAIL" if procedure == "OUT_OF_SAMPLE" else "PASS",
            "observation": f"The {label} criterion was " +
                           ("not met." if procedure == "OUT_OF_SAMPLE" else "met."),
        }
        for procedure, label in sorted(_LABELS.items())
    ]
    summary = {"experiment_id": exp, "disposition": "CLOSED_UNSUCCESSFUL",
               "criteria": criteria, "not_evaluable": []}
    summary_bytes = _wire(summary)
    manifest = {
        "schema_version": 1, "export_kind": "CLOSED_EXPERIMENT_SUMMARY",
        "source_system": "forexpro", "experiment_id": exp,
        "source_revision": "a" * 40,
        "summary_sha256": _sha(summary_bytes),
        "approved_scope": "READ_ONLY_ADVISORY",
        "holdout_access": False, "promotion_authority": False,
        "broker_authority": False,
    }
    manifest_bytes = _wire(manifest)
    signed = {
        "schema_version": 1, "algorithm": "Ed25519",
        "key_id": _EXPORTER_IDS[0], "manifest_sha256": _sha(manifest_bytes),
        "summary_sha256": _sha(summary_bytes),
    }
    attestation = {
        **signed,
        "signature_b64": base64.b64encode(signer.sign(_message(signed))).decode("ascii"),
    }
    for name, raw in (("manifest.json", manifest_bytes),
                      ("summary.json", summary_bytes),
                      ("attestation.json", _wire(attestation))):
        _new_file(directory / name, raw)
    return directory


def _test_checkpoint(
    *, sequence: int, epoch: int, previous: str, trust_hash: str,
    active: list[str], revoked: list[str], retired: list[str],
    private: Ed25519PrivateKey, owner_id: str,
) -> bytes:
    payload = {
        "schema_version": 1,
        "kind": "SYNTHETIC_RECIPIENT_TRUST_NOT_AUTHORITY",
        "classification": "SYNTHETIC_ONLY", "sequence": sequence,
        "previous_sha256": previous, "key_epoch": epoch,
        "minimum_accepted_sequence": sequence,
        "trust_store_sha256": trust_hash,
        "catalog_sha256": REVIEWED_CANDIDATE_SHA256,
        "active_exporter_key_ids": sorted(active),
        "revoked_exporter_key_ids": sorted(revoked),
        "retired_operator_key_ids": sorted(retired),
        "source_authority": False, "export_authority": False,
        "holdout_access": False, "broker_authority": False,
    }
    signed = {
        "schema_version": 1, "algorithm": "Ed25519",
        "key_id": owner_id, "payload": payload,
    }
    message = synthetic_recipient_checkpoint_message(key_id=owner_id,
                                                       payload=payload)
    return _canonical({
        **signed,
        "signature_b64": base64.b64encode(private.sign(message)).decode("ascii"),
    })


def _expect_denied(check: Any, label: str) -> None:
    try:
        check()
    except (EvidenceError, OSError, ValueError, TypeError):
        return
    raise EvidenceError("synthetic qualification unexpectedly accepted " + label)


def run_synthetic_recipient_qualification() -> dict[str, Any]:
    """No caller data, no paths/keys arguments, no durable outputs.

    A green drill tests *synthetic behavior* of the currently proposed FRI
    recipient stack; it cannot authorize import/export of any real source.
    """
    if REVIEWED_CANDIDATE_SHA256 != (
        "7dbe7ec841bc15262051128d55c2ec4ce2673ce1034d3740d7c0679083eff8d5"
    ):
        raise EvidenceError("candidate phrase identity unexpectedly changed")
    # Every resource, including SQLite, checkpoint and public trust fixture,
    # disappears when the context exits (also on rejection).
    with tempfile.TemporaryDirectory(prefix="fri-v29-qualification-") as td:
        root = Path(td)
        exporter = (Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate())
        operator = (Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate())
        operator_keys = dict(zip(_OPERATOR_IDS, map(_public, operator)))
        trust_file = root / "synthetic-public-keys.json"
        trust_policy = {
            "schema_version": 1,
            "keys": [
                {
                    "key_id": name, "algorithm": "Ed25519",
                    "public_key_b64": base64.b64encode(_public(key)).decode("ascii"),
                    "source_system": "forexpro", "purpose": "CLOSED_EXPERIMENT_SUMMARY",
                    "status": "ACTIVE" if i == 0 else "REVOKED",
                }
                for i, (name, key) in enumerate(zip(_EXPORTER_IDS, exporter))
            ],
        }
        trusted_bytes = _wire(trust_policy)
        _new_file(trust_file, trusted_bytes)
        bundles = (_test_bundle(root, "A", exporter[0]),
                   _test_bundle(root, "B", exporter[0]))
        genesis = _test_checkpoint(
            sequence=1, epoch=1, previous=_ZERO, trust_hash=_sha(b"synthetic-previous-trust"),
            active=list(_EXPORTER_IDS), revoked=[], retired=[],
            private=operator[0], owner_id=_OPERATOR_IDS[0],
        )
        latest = _test_checkpoint(
            sequence=2, epoch=2, previous=_sha(genesis),
            trust_hash=_sha(trusted_bytes), active=[_EXPORTER_IDS[0]],
            revoked=[_EXPORTER_IDS[1]], retired=[_OPERATOR_IDS[0]],
            private=operator[1], owner_id=_OPERATOR_IDS[1],
        )
        args = {
            "trust_store": trust_file, "signed_checkpoints": (genesis, latest),
            "operator_test_public_keys": operator_keys,
            "expected_operator_keyset_sha256": (
                synthetic_operator_keyset_sha256(operator_keys)),
            "expected_genesis_sha256": _sha(genesis),
            "expected_latest_sha256": _sha(latest),
            "expected_latest_sequence": 2,
            "independent_minimum_sequence": 2,
        }

        def gate(selected: tuple[Path, ...] = bundles) -> dict[str, Any]:
            return inspect_synthetic_recipient_trust_continuity(selected, **args)

        verified = gate()
        if (verified["signed_bundle_count"] != 2 or
                verified["complete_negative_candidate_criteria"] != 20 or
                verified["source_registry_authenticated"] is not False or
                verified["current_export_authorization"] is not False or
                verified["real_ingestion_approved"] is not False):
            raise EvidenceError("synthetic recipient policy invariant failed")

        database = root / "ephemeral-research.sqlite"
        receipts = [ingest(bundle, database, trust_store=trust_file)
                    for bundle in bundles]
        if any(row["status"] != "IMPORTED" for row in receipts):
            raise EvidenceError("synthetic ingestion incomplete")
        duplicate = ingest(bundles[0], database, trust_store=trust_file)
        if duplicate["status"] != "ALREADY_PRESENT":
            raise EvidenceError("idempotent synthetic replay failed")

        memory = verify_memory(database)
        advisor = build_advisor(database, min_support=2)
        quality = assess_advisor(advisor)
        if (memory["status"] != "OK" or memory["experiment_count"] != 2 or
                advisor["signed_only_gate_passed"] is not True or
                advisor["observed_experiment_count"] != 2 or
                quality["status"] != "PASS" or
                quality["model_semantic_truth_verified"] is not False or
                any(advisor["authority"].values()) or
                not any(item["kind"] == "REPEATED_FAILURE" and
                        item["procedure"] == "OUT_OF_SAMPLE"
                        for item in advisor["proposals"])):
            raise EvidenceError("signed synthetic Research Advisor qualification failed")

        backup_dir = root / "backup"
        backup_result = backup(database, backup_dir)
        backup_check = verify_backup(backup_dir)
        restored_db = root / "restored.sqlite"
        restore_result = restore_backup(backup_dir, restored_db)
        restored = verify_memory(restored_db)
        restored_advisor = build_advisor(restored_db, min_support=2)
        if (backup_result["status"] != "BACKUP_CREATED" or
                backup_check["status"] != "BACKUP_VERIFIED" or
                restore_result["status"] != "RESTORED_TO_NEW_DATABASE" or
                restored["experiment_count"] != 2 or
                restored_advisor["report_sha256"] != advisor["report_sha256"]):
            raise EvidenceError("synthetic recovery continuity broken")
        _expect_denied(lambda: restore_backup(backup_dir, database),
                       "live database overwrite")

        # Deliberate adversarial failures happen only AFTER the good evidence
        # was ingested and backed up, so a denial must not modify the memory.
        args["signed_checkpoints"] = (genesis,)
        _expect_denied(gate, "old signed checkpoint")
        args["signed_checkpoints"] = (genesis, latest)
        args["independent_minimum_sequence"] = 3
        _expect_denied(gate, "raised independent minimum sequence")
        args["independent_minimum_sequence"] = 2

        trust_file.write_bytes(_wire({
            **trust_policy,
            "keys": [
                {**row, "status": "ACTIVE"} for row in trust_policy["keys"]
            ],
        }))
        _expect_denied(gate, "revoked exporter revival and trust rollback")
        trust_file.write_bytes(trusted_bytes)
        altered = bundles[1] / "summary.json"
        original = altered.read_bytes()
        altered.write_bytes(original + b" ")
        _expect_denied(gate, "tampered signed observation bytes")
        altered.write_bytes(original)
        _expect_denied(lambda: gate((bundles[0], bundles[0])),
                       "duplicate synthetic experiment")
        if (verify_memory(database)["experiment_count"] != 2 or
                build_advisor(database, min_support=2)["report_sha256"] !=
                advisor["report_sha256"] or
                gate()["signed_bundle_count"] != 2):
            raise EvidenceError("negative checks modified verified synthetic state")
        if list(root.rglob("*.pem")) or list(root.rglob("*.key")):
            raise EvidenceError("synthetic private key was persisted")
        return {
            "schema_version": 1,
            "status": "SYNTHETIC_RECIPIENT_QUALIFICATION_PASS_NOT_APPROVAL",
            "rehearsal": "SYNTHETIC_ONLY",
            "signed_bundle_count": 2,
            "complete_candidate_criteria": 20,
            "research_memory_verified": True,
            "signed_only_advisor_quality": "PASS",
            "idempotent_reimport": True,
            "recovery_verified": True,
            "negative_scenarios_denied": 6,
            "retired_operator_and_exporter_revocation_rehearsed": True,
            "candidate_dictionary_approved": False,
            "real_source_closure_authenticated": False,
            "independent_operator_custody_proven": False,
            "real_source_access": False,
            "current_export_authorization": False,
            "real_ingestion_approved": False,
            "scientific_approval": False,
            "holdout_access": False,
            "broker_authority": False,
            "same_campaign_feedback_authority": False,
        }
