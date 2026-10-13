"""Twenty-case, synthetic-only signed research cohort for curator review.

No Core access, original observations, stored secret keys or network requests.
The source statuses below are test fixtures, not scientific outcomes. Distinct
synthetic IDs intentionally do NOT establish independent trial lineages.
"""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .attestation import _message
from .bridge import _json_bytes
from .contracts import EvidenceError
from .memory import ingest

_PROCEDURES = (
    "OUT_OF_SAMPLE", "COST_STRESS", "MONTE_CARLO",
    "REGIME_STABILITY", "DETERMINISTIC_RERUN", "SAMPLE_SUFFICIENCY",
)

# F = FAIL, P = PASS, N = NOT_EVALUABLE, U = UNOBSERVED.
# A separate gold-label file (not derived from the generated Review Pack)
# must be checked independently by the benchmark evaluator.
_SCENARIOS = (
    "FFNUPU", "FFNUPU", "PFNUPU", "PFPUNU", "UPFNUU",
    "UNFPUU", "NNPFUU", "NNPFPF", "PPPNUF", "PFPPNU",
    "UNNUPF", "PNNUFP", "FFNUPF", "FPNUPN", "UUFFPN",
    "UPFPFN", "PUUFPF", "PPNFFF", "UPPNNU", "PNPUUF",
)
_TEST_KEY_ID = "FRI_SYNTHETIC_COHORT_IN_MEMORY_ONLY"


def make_signed_cohort(root: Path, db: Path) -> dict:
    """Generate exactly 20 synthetic, signed local bundles and ingest via FRI.

    root must be a newly-created private empty directory. Signing key is never
    serialized or persisted; only ephemeral synthetic test data is written.
    """
    if (root.is_symlink() or not root.is_dir() or any(root.iterdir())
            or db.is_symlink() or db.exists() or db.parent != root):
        raise EvidenceError("synthetic cohort requires an empty private directory and new database")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
    )
    trust = root / "synthetic-public-keys.json"
    trust.write_bytes(_json_bytes({
        "schema_version": 1, "keys": [{
            "key_id": _TEST_KEY_ID, "algorithm": "Ed25519",
            "source_system": "forexpro", "purpose": "CLOSED_EXPERIMENT_SUMMARY",
            "status": "ACTIVE", "public_key_b64": base64.b64encode(public).decode("ascii"),
        }],
    }))
    # A shared, deliberately fake SHA demonstrates that 20 IDs do NOT prove
    # independent replication or separate data lineage.
    fake_source_revision = "a" * 40
    ids = []
    for ordinal, states in enumerate(_SCENARIOS, start=1):
        if len(states) != len(_PROCEDURES) or not set(states) <= {"F", "P", "N", "U"}:
            raise EvidenceError("invalid internal synthetic scenario")
        eid = f"SYNTHETIC-COHORT-{ordinal:02d}"
        bundle = root / eid
        bundle.mkdir(mode=0o700)
        criteria, unavailable = [], []
        for ix, (proc, state) in enumerate(zip(_PROCEDURES, states)):
            if state in {"F", "P"}:
                criteria.append({
                    "criterion_id": f"synthetic-c-{ix:02d}",
                    "procedure": proc,
                    "verdict": "FAIL" if state == "F" else "PASS",
                    "observation": "SYNTHETIC: catalog-only observation",
                })
            elif state == "N":
                unavailable.append({
                    "procedure": proc,
                    "reason": "SYNTHETIC: intentionally not evaluable",
                })
        # Multiple criteria for one procedure must not inflate experiment count
        # or override a FAIL with a PASS.
        if ordinal == 13:
            criteria.append({
                "criterion_id": "synthetic-second-criterion",
                "procedure": "OUT_OF_SAMPLE",
                "verdict": "PASS",
                "observation": "SYNTHETIC: second criterion does not cancel FAIL",
            })
        summary = {
            "experiment_id": eid,
            "disposition": "CLOSED_UNSUCCESSFUL" if "F" in states else "CLOSED_INCOMPLETE",
            "criteria": criteria,
            "not_evaluable": unavailable,
        }
        summary_bytes = _json_bytes(summary)
        manifest = {
            "schema_version": 1,
            "export_kind": "CLOSED_EXPERIMENT_SUMMARY",
            "source_system": "forexpro",
            "experiment_id": eid,
            "source_revision": fake_source_revision,
            "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
            "approved_scope": "READ_ONLY_ADVISORY",
            "holdout_access": False,
            "promotion_authority": False,
            "broker_authority": False,
        }
        manifest_bytes = _json_bytes(manifest)
        signed_fields = {
            "schema_version": 1,
            "algorithm": "Ed25519",
            "key_id": _TEST_KEY_ID,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "summary_sha256": manifest["summary_sha256"],
        }
        signature = base64.b64encode(private.sign(_message(signed_fields))).decode("ascii")
        (bundle / "manifest.json").write_bytes(manifest_bytes)
        (bundle / "summary.json").write_bytes(summary_bytes)
        (bundle / "attestation.json").write_bytes(_json_bytes({
            **signed_fields, "signature_b64": signature,
        }))
        imported = ingest(bundle, db, trust_store=trust)
        if imported["status"] != "IMPORTED" or imported["verification_status"] != "SIGNATURE_VERIFIED":
            raise EvidenceError("synthetic fixture intake failed")
        ids.append(eid)
    return {
        "status": "SYNTHETIC_SIGNED_COHORT_CREATED",
        "experiment_ids": ids,
        "expected_procedures": list(_PROCEDURES),
        "source_class": "SYNTHETIC_ONLY",
        "private_key_persisted": False,
        "independent_replication_established": False,
        "export_authorization": False,
        "scientific_authority": False,
        "broker_authority": False,
    }
