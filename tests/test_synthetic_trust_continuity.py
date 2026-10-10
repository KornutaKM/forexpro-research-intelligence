"""Synthetic-only recipient trust continuity and revocation regression tests."""
from __future__ import annotations

import ast
import base64
import contextlib
import copy
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from forexpro_ri.attestation import _message
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.core_policy_preview import REVIEWED_CANDIDATE_SHA256, _LABELS
from forexpro_ri.synthetic_trust_continuity import (
    inspect_synthetic_recipient_trust_continuity,
    synthetic_operator_keyset_sha256,
    synthetic_recipient_checkpoint_message,
)
from forexpro_ri.synthetic_trust_cli import run


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def wire(obj):
    return json.dumps(obj, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":")).encode("utf-8")


def public(priv):
    return priv.public_key().public_bytes(serialization.Encoding.Raw,
                                         serialization.PublicFormat.Raw)


class SyntheticRecipientTrustTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(prefix="fri-synthetic-recipient-history-")
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.exporter = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
        self.names = ["SYNTHETIC_EXPORTER_A", "SYNTHETIC_EXPORTER_B"]
        self.operator = [Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()]
        self.operator_ids = ["SYNTHETIC_RECEIVER_OWNER_ALPHA", "SYNTHETIC_RECEIVER_OWNER_BETA"]
        self.public_keys = dict(zip(self.operator_ids, map(public, self.operator)))
        self.trust = self.root / "trusted-keys.json"
        self._write_trust(active=self.names[:], revoked=[])
        self.bundle = self._signed_bundle("A")
        self.payloads = []
        self.checkpoints = []
        self._rebuild([{"operator": 0, "epoch": 1, "active": self.names[:], "revoked": []}])

    def _write_trust(self, *, active, revoked):
        data = {"schema_version": 1, "keys": []}
        for name, private in zip(self.names, self.exporter):
            data["keys"].append({
                "key_id": name, "algorithm": "Ed25519",
                "public_key_b64": base64.b64encode(public(private)).decode("ascii"),
                "source_system": "forexpro", "purpose": "CLOSED_EXPERIMENT_SUMMARY",
                "status": "ACTIVE" if name in active else "REVOKED",
            })
        self.trust.write_bytes(wire(data) + b"\n")

    def _signed_bundle(self, name, signer_index=0):
        root = self.root / ("bundle-" + name)
        root.mkdir()
        eid = "SYNTHETIC-RECEIVER-" + name
        summary = {
            "experiment_id": eid, "disposition": "CLOSED_UNSUCCESSFUL",
            "criteria": [{"criterion_id": "synthetic-" + k.lower(), "procedure": k,
                          "verdict": "FAIL" if k == "OUT_OF_SAMPLE" else "PASS",
                          "observation": f"The {word} criterion was " +
                          ("not met." if k == "OUT_OF_SAMPLE" else "met.")}
                         for k, word in sorted(_LABELS.items())],
            "not_evaluable": [],
        }
        summary_raw = wire(summary) + b"\n"
        manifest = {"schema_version": 1, "export_kind": "CLOSED_EXPERIMENT_SUMMARY",
                    "source_system": "forexpro", "experiment_id": eid,
                    "source_revision": "a" * 40, "summary_sha256": digest(summary_raw),
                    "approved_scope": "READ_ONLY_ADVISORY", "holdout_access": False,
                    "promotion_authority": False, "broker_authority": False}
        manifest_raw = wire(manifest) + b"\n"
        fields = {"schema_version": 1, "algorithm": "Ed25519",
                  "key_id": self.names[signer_index],
                  "manifest_sha256": digest(manifest_raw),
                  "summary_sha256": digest(summary_raw)}
        signature = base64.b64encode(self.exporter[signer_index].sign(_message(fields))).decode("ascii")
        for filename, raw in (("summary.json", summary_raw), ("manifest.json", manifest_raw),
                              ("attestation.json", wire({**fields, "signature_b64": signature}) + b"\n")):
            (root / filename).write_bytes(raw)
        return root

    def _payload(self, seq, previous, epoch, active, revoked, retired, minimum=1, trust_sha=None):
        return {"schema_version": 1, "kind": "SYNTHETIC_RECIPIENT_TRUST_NOT_AUTHORITY",
                "classification": "SYNTHETIC_ONLY", "sequence": seq,
                "previous_sha256": previous, "key_epoch": epoch,
                "minimum_accepted_sequence": minimum,
                "trust_store_sha256": trust_sha or digest(self.trust.read_bytes()),
                "catalog_sha256": REVIEWED_CANDIDATE_SHA256,
                "active_exporter_key_ids": sorted(active),
                "revoked_exporter_key_ids": sorted(revoked),
                "retired_operator_key_ids": sorted(retired),
                "source_authority": False, "export_authority": False,
                "holdout_access": False, "broker_authority": False}

    def _sign(self, payload, operator_index):
        key_id = self.operator_ids[operator_index]
        fields = {"schema_version": 1, "algorithm": "Ed25519", "key_id": key_id,
                  "payload": payload}
        signed_bytes = synthetic_recipient_checkpoint_message(key_id=key_id, payload=payload)
        return wire({**fields, "signature_b64": base64.b64encode(
            self.operator[operator_index].sign(signed_bytes)).decode("ascii")})

    def _rebuild(self, phases):
        previous = "0" * 64
        checkpoints = []
        payloads = []
        for i, phase in enumerate(phases, 1):
            payload = self._payload(i, previous, phase["epoch"], phase["active"],
                                    phase["revoked"], phase.get("retired", []),
                                    minimum=phase.get("minimum", 1),
                                    trust_sha=phase.get("trust_sha"))
            raw = self._sign(payload, phase["operator"])
            checkpoints.append(raw)
            payloads.append(payload)
            previous = digest(raw)
        self.payloads = payloads
        self.checkpoints = tuple(checkpoints)
        self._refresh_pins()

    def _refresh_pins(self):
        self.kwargs = {
            "trust_store": self.trust, "signed_checkpoints": self.checkpoints,
            "operator_test_public_keys": self.public_keys,
            "expected_operator_keyset_sha256": synthetic_operator_keyset_sha256(self.public_keys),
            "expected_genesis_sha256": digest(self.checkpoints[0]),
            "expected_latest_sha256": digest(self.checkpoints[-1]),
            "expected_latest_sequence": len(self.checkpoints),
            "independent_minimum_sequence": 1,
        }

    def check(self, bundles=None):
        return inspect_synthetic_recipient_trust_continuity(
            [self.bundle] if bundles is None else bundles, **self.kwargs)

    def test_one_checkpoint_fixed_output_never_has_real_authority(self):
        result = self.check()
        self.assertEqual(result["status"], "SYNTHETIC_RECIPIENT_TRUST_CONTINUITY_ONLY")
        self.assertEqual(result["signed_bundle_count"], 1)
        self.assertEqual(result["complete_negative_candidate_criteria"], 10)
        self.assertTrue(result["checkpoint_history_consistent_against_supplied_pins"])
        self.assertTrue(result["synthetic_only"])
        for name in ("operator_custody_independently_proven", "source_registry_authenticated",
                     "current_source_closure_authenticated", "dictionary_approved",
                     "declassification_approved", "current_export_authorization",
                     "real_ingestion_approved", "scientific_approval", "holdout_access",
                     "broker_authority", "core_feedback_authority"):
            self.assertIs(result[name], False)
        text = json.dumps(result)
        for secret in (str(self.root), self.names[0], "SYNTHETIC-RECEIVER-A", "out-of-sample"):
            self.assertNotIn(secret, text)

    def test_batch_two_complete_negative_synthetic_records(self):
        b = self._signed_bundle("B")
        result = self.check([self.bundle, b])
        self.assertEqual(result["signed_bundle_count"], 2)
        self.assertEqual(result["complete_negative_candidate_criteria"], 20)
        self.assertEqual(list(self.root.rglob("*.sqlite")), [])

    def test_valid_two_step_rotation_with_cumulative_retirement(self):
        phases = [{"operator": 0, "epoch": 1, "active": self.names[:], "revoked": []},
                  {"operator": 1, "epoch": 2, "active": [self.names[0]],
                   "revoked": [self.names[1]], "retired": [self.operator_ids[0]],
                   "minimum": 2}]
        self._write_trust(active=[self.names[0]], revoked=[self.names[1]])
        self._rebuild(phases)
        self.kwargs["independent_minimum_sequence"] = 2
        self.assertIs(self.check()["current_export_authorization"], False)

    def test_revoked_bundle_exporter_fails_even_if_historical_signature_valid(self):
        self._write_trust(active=[self.names[0]], revoked=[self.names[1]])
        self._rebuild([{"operator": 0, "epoch": 1,
                        "active": [self.names[0]], "revoked": [self.names[1]]}])
        b = self._signed_bundle("old", signer_index=1)
        with self.assertRaises(EvidenceError):
            self.check([b])

    def test_revocation_history_cannot_be_erased(self):
        phases = [{"operator": 0, "epoch": 1, "active": [self.names[0]],
                   "revoked": [self.names[1]]},
                  {"operator": 0, "epoch": 1, "active": self.names[:], "revoked": []}]
        self._rebuild(phases)
        with self.assertRaisesRegex(EvidenceError, "revoked exporter revived"):
            self.check()

    def test_rotated_operator_reuse_is_rejected(self):
        phases = [{"operator": 0, "epoch": 1, "active": self.names[:], "revoked": []},
                  {"operator": 1, "epoch": 2, "active": self.names[:], "revoked": [],
                   "retired": [self.operator_ids[0]]},
                  {"operator": 0, "epoch": 3, "active": self.names[:], "revoked": [],
                   "retired": [self.operator_ids[0], self.operator_ids[1]]}]
        self._rebuild(phases)
        with self.assertRaises(EvidenceError):
            self.check()

    def test_stale_head_rejected_with_external_pin(self):
        first = self.checkpoints
        self._rebuild([{"operator": 0, "epoch": 1, "active": self.names[:], "revoked": []},
                       {"operator": 0, "epoch": 1, "active": self.names[:], "revoked": []}])
        self.kwargs["signed_checkpoints"] = first
        with self.assertRaises(EvidenceError):
            self.check()

    def test_changed_current_trust_store_rejected(self):
        self._write_trust(active=[self.names[0]], revoked=[self.names[1]])
        with self.assertRaises(EvidenceError):
            self.check()

    def test_replace_operator_public_key_and_pins_denied(self):
        fake = Ed25519PrivateKey.generate()
        self.kwargs["operator_test_public_keys"] = {
            self.operator_ids[0]: public(fake), self.operator_ids[1]: public(self.operator[1])}
        self.kwargs["expected_operator_keyset_sha256"] = synthetic_operator_keyset_sha256(
            self.kwargs["operator_test_public_keys"])
        with self.assertRaises(EvidenceError):
            self.check()

    def test_fully_forged_consistent_test_claim_has_no_authentication(self):
        out = self.check()
        self.assertIs(out["operator_custody_independently_proven"], False)
        self.assertIs(out["source_registry_authenticated"], False)

    def test_invalid_or_replayed_external_head_and_minimum(self):
        variations = [
            {"expected_genesis_sha256": "f" * 64},
            {"expected_latest_sha256": "f" * 64},
            {"expected_latest_sequence": 2},
            {"expected_latest_sequence": True},
            {"independent_minimum_sequence": 2},
            {"independent_minimum_sequence": True},
            {"expected_operator_keyset_sha256": "a" * 64},
        ]
        for patch in variations:
            with self.subTest(patch=patch):
                self._refresh_pins()
                self.kwargs.update(patch)
                with self.assertRaises(EvidenceError):
                    self.check()

    def test_rehashed_mutations_are_rejected_even_with_fresh_signature(self):
        mutations = [
            ("source_authority", True), ("export_authority", True),
            ("holdout_access", True), ("broker_authority", True),
            ("catalog_sha256", "f" * 64), ("classification", "PRIVATE"),
            ("kind", "PRODUCTION"), ("minimum_accepted_sequence", 2),
            ("key_epoch", 2), ("previous_sha256", "a" * 64),
            ("sequence", 0), ("sequence", True),
            ("active_exporter_key_ids", []),
            ("active_exporter_key_ids", [self.names[0]] * 2),
            ("revoked_exporter_key_ids", [self.names[0]]),
            ("retired_operator_key_ids", [self.operator_ids[0]]),
        ]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                self._rebuild([{"operator": 0, "epoch": 1, "active": self.names[:], "revoked": []}])
                self.payloads[0][field] = value
                try:
                    raw = self._sign(self.payloads[0], 0)
                except EvidenceError:
                    continue  # creation prevented by signed-message validator
                self.checkpoints = (raw,)
                self._refresh_pins()
                with self.assertRaises(EvidenceError):
                    self.check()

    def test_corrupt_signature_duplicate_json_and_unknown_fields(self):
        for variant in ("bad-signature", "duplicate", "private", "noncanonical", "oversize", "invalid-utf8"):
            with self.subTest(variant=variant):
                self._rebuild([{"operator": 0, "epoch": 1, "active": self.names[:], "revoked": []}])
                raw = self.checkpoints[0]
                if variant == "bad-signature":
                    obj = json.loads(raw)
                    obj["signature_b64"] = base64.b64encode(b"\0" * 64).decode()
                    raw = wire(obj)
                elif variant == "duplicate":
                    raw = raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1', 1)
                elif variant == "private":
                    obj = json.loads(raw)
                    obj["payload"]["private_key"] = "SECRET"
                    raw = wire(obj)
                elif variant == "noncanonical":
                    raw = b" " + raw
                elif variant == "oversize":
                    raw = b"x" * 4097
                else:
                    raw = b"\xff"
                self.checkpoints = (raw,)
                self._refresh_pins()
                with self.assertRaises(EvidenceError):
                    self.check()

    def test_missing_generation_link_and_same_epoch_signer_change(self):
        phases = [{"operator": 0, "epoch": 1, "active": self.names[:], "revoked": []},
                  {"operator": 1, "epoch": 1, "active": self.names[:], "revoked": []}]
        self._rebuild(phases)
        with self.assertRaises(EvidenceError):
            self.check()
        phases[1]["epoch"] = 2
        self._rebuild(phases)
        with self.assertRaises(EvidenceError):
            self.check()  # previous operator was not explicitly retired

    def test_operator_epoch_jump_and_floor_rollback(self):
        phases = [{"operator": 0, "epoch": 1, "active": self.names[:],
                   "revoked": [], "minimum": 1},
                  {"operator": 0, "epoch": 1, "active": self.names[:],
                   "revoked": [], "minimum": 2},
                  {"operator": 0, "epoch": 1, "active": self.names[:],
                   "revoked": [], "minimum": 1}]
        self._rebuild(phases)
        with self.assertRaises(EvidenceError):
            self.check()

    def test_wrong_type_empty_unbounded_chain_and_keys(self):
        for patch in (
            {"signed_checkpoints": []}, {"signed_checkpoints": ()},
            {"signed_checkpoints": (b"x",) * 17},
            {"operator_test_public_keys": {}},
            {"operator_test_public_keys": {self.operator_ids[0]: b"\0"}},
        ):
            with self.subTest(patch=str(patch)[:40]):
                self._refresh_pins()
                self.kwargs.update(patch)
                with self.assertRaises(EvidenceError):
                    self.check()

    def test_different_roles_cannot_reuse_same_public_key(self):
        self._trust_same_material_as_operator()
        self._rebuild([{"operator": 0, "epoch": 1, "active": self.names[:], "revoked": []}])
        with self.assertRaises(EvidenceError):
            self.check()

    def _trust_same_material_as_operator(self):
        obj = json.loads(self.trust.read_bytes())
        obj["keys"][0]["public_key_b64"] = base64.b64encode(self.public_keys[self.operator_ids[0]]).decode()
        self.trust.write_bytes(wire(obj) + b"\n")

    def test_cli_success_and_redacted_denial(self):
        operator_file = self.root / "operator-public-test-keys.json"
        operator_file.write_bytes(wire({"schema_version": 1, "operator_keys": [
            {"key_id": kid, "public_key_b64": base64.b64encode(key).decode()}
            for kid, key in self.public_keys.items()]}) + b"\n")
        checkpoint_file = self.root / "checkpoint.json"
        checkpoint_file.write_bytes(self.checkpoints[0])
        options = ["--bundle", str(self.bundle), "--trust-store", str(self.trust),
                   "--checkpoint", str(checkpoint_file),
                   "--operator-test-public-keys", str(operator_file),
                   "--operator-keyset-sha256", self.kwargs["expected_operator_keyset_sha256"],
                   "--expected-genesis-sha256", self.kwargs["expected_genesis_sha256"],
                   "--expected-head-sha256", self.kwargs["expected_latest_sha256"],
                   "--expected-head-sequence", "1", "--minimum-sequence", "1"]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run(options)
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertIs(json.loads(stdout.getvalue())["current_export_authorization"], False)
        options[-1] = "2"
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = run(options)
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue().strip(), "SYNTHETIC_RECIPIENT_TRUST_DENIED")
        self.assertNotIn(str(self.root), stderr.getvalue())

    def test_current_fri_signed_protocol_and_memory_unmodified(self):
        from forexpro_ri.attestation import verify_export
        manifest, _, receipt = verify_export(self.bundle, self.trust)
        self.assertEqual(manifest.export_kind, "CLOSED_EXPERIMENT_SUMMARY")
        self.assertEqual(receipt["status"], "SIGNATURE_VERIFIED")
        self.assertEqual(list(self.root.rglob("*.sqlite")), [])

    def test_no_source_network_or_private_key_writer_imports(self):
        import forexpro_ri.synthetic_trust_continuity as mod
        tree = ast.parse(Path(mod.__file__).read_text(encoding="utf-8"))
        forbidden = ("socket", "urllib", "requests", "sqlite3", "subprocess",
                     "MetaTrader5", "forex_lab")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [x.name for x in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            self.assertFalse(any(x.startswith(forbidden) for x in names))
        self.assertFalse(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                             and n.func.id in {"open", "eval", "exec"}
                             for n in ast.walk(tree)))


if __name__ == "__main__":
    unittest.main()
