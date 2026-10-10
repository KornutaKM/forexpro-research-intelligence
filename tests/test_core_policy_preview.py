"""Adversarial signed fixture tests for the *unapproved* Core v1 recipient preview.

Private Ed25519 keys exist only in temporary test-process memory. No Core
science, production signer, real data, broker or online service is used.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from forexpro_ri.attestation import _message
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.core_policy_preview import (
    CATALOG_ID,
    REVIEWED_CANDIDATE_SHA256,
    candidate_catalog_sha256,
    inspect_synthetic_core_v1_batch,
    _LABELS,
    _OUTCOMES,
)


def encoded(x):
    return (json.dumps(x, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


class ConservativeRecipientPreviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="fri-recipient-synthetic-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.private = Ed25519PrivateKey.generate()
        self.key_id = "SYNTHETIC_RECIPIENT_TEST_KEY"
        self.trust = self.root / "external-keys.json"
        self._trust()

    def _trust(self, *, key_id=None, status="ACTIVE", public_key=None):
        pub = public_key or self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.trust.write_bytes(encoded({
            "schema_version": 1,
            "keys": [{
                "key_id": self.key_id if key_id is None else key_id,
                "algorithm": "Ed25519",
                "public_key_b64": base64.b64encode(pub).decode("ascii"),
                "source_system": "forexpro",
                "purpose": "CLOSED_EXPERIMENT_SUMMARY",
                "status": status,
            }],
        }))

    def _summary(self, experiment_id):
        return {
            "experiment_id": experiment_id,
            "disposition": "CLOSED_UNSUCCESSFUL",
            "criteria": [
                {
                    "criterion_id": "synthetic-" + procedure.lower(),
                    "procedure": procedure,
                    "verdict": "FAIL" if procedure == "OUT_OF_SAMPLE" else "PASS",
                    "observation": "The " + label + " criterion was " +
                                   ("not met." if procedure == "OUT_OF_SAMPLE" else "met."),
                }
                for procedure, label in sorted(_LABELS.items())
            ],
            "not_evaluable": [],
        }

    def _bundle(self, name="A", *, experiment_id=None, mutate_summary=None,
                mutate_manifest=None, signer_id=None):
        path = self.root / ("signed-" + name)
        path.mkdir()
        eid = experiment_id if experiment_id is not None else "SYNTHETIC-" + name
        summary = self._summary(eid)
        if mutate_summary is not None:
            mutate_summary(summary)
        summary_bytes = encoded(summary)
        manifest = {
            "schema_version": 1,
            "export_kind": "CLOSED_EXPERIMENT_SUMMARY",
            "source_system": "forexpro",
            "experiment_id": eid,
            "source_revision": "a" * 40,
            "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
            "approved_scope": "READ_ONLY_ADVISORY",
            "holdout_access": False,
            "promotion_authority": False,
            "broker_authority": False,
        }
        if mutate_manifest is not None:
            mutate_manifest(manifest)
        manifest_bytes = encoded(manifest)
        fields = {
            "schema_version": 1,
            "algorithm": "Ed25519",
            "key_id": self.key_id if signer_id is None else signer_id,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
        }
        sig = self.private.sign(_message(fields))
        receipt = {**fields, "signature_b64": base64.b64encode(sig).decode("ascii")}
        for filename, raw in (("summary.json", summary_bytes),
                              ("manifest.json", manifest_bytes),
                              ("attestation.json", encoded(receipt))):
            (path / filename).write_bytes(raw)
        return path

    def check(self, *paths):
        return inspect_synthetic_core_v1_batch(paths, trust_store=self.trust)

    def test_catalog_matches_exact_unapproved_core_candidate(self):
        self.assertEqual(CATALOG_ID, "FRI_SAFE_PHRASES_V1_CANDIDATE_NOT_APPROVED")
        self.assertEqual(candidate_catalog_sha256(), REVIEWED_CANDIDATE_SHA256)
        self.assertEqual(len(_LABELS) * len(_OUTCOMES), 20)

    def test_signed_complete_negative_synthetic_case_is_not_authority(self):
        p = self._bundle()
        output = self.check(p)
        self.assertEqual(output["status"], "SYNTHETIC_CORE_V1_RECIPIENT_PREVIEW_ONLY")
        self.assertEqual(output["bundle_count"], 1)
        self.assertEqual(output["criterion_count"], 10)
        self.assertEqual(output["failure_count"], 1)
        self.assertTrue(output["signed_bundle_checked"])
        self.assertTrue(output["synthetic_only"])
        for name in (
            "full_core_validation_evidence_authenticated", "terminal_closure_authenticated",
            "source_registry_authenticated", "dictionary_approved",
            "declassification_approved", "current_export_authorization",
            "real_ingestion_approved", "scientific_approval", "holdout_access",
            "broker_authority", "core_feedback_authority",
        ):
            self.assertIs(output[name], False)
        view = json.dumps(output)
        self.assertNotIn("SYNTHETIC-A", view)
        self.assertNotIn("signed-A", view)
        self.assertNotIn(self.key_id, view)
        self.assertNotIn("out-of-sample criterion", view)
        self.assertNotIn("private", view.lower())

    def test_batch_composition_and_no_writes(self):
        a, b = self._bundle("A"), self._bundle("B")
        before = set(self.root.rglob("*"))
        result = self.check(a, b)
        self.assertEqual(set(self.root.rglob("*")), before)
        self.assertEqual(result["bundle_count"], 2)
        self.assertEqual(result["criterion_count"], 20)
        self.assertEqual(result["failure_count"], 2)

    def test_reject_empty_long_or_wrong_type_batches(self):
        p = self._bundle()
        for bad in ([], (), (p,) * 21, "signed", None, True):
            with self.subTest(bad=repr(bad)[:24]):
                with self.assertRaises((EvidenceError, TypeError)):
                    inspect_synthetic_core_v1_batch(bad, trust_store=self.trust)

    def test_reject_duplicate_paths_or_experiment_identifiers(self):
        a = self._bundle("A")
        with self.assertRaises(EvidenceError):
            self.check(a, a)
        b = self._bundle("B", experiment_id="SYNTHETIC-A")
        with self.assertRaises(EvidenceError):
            self.check(a, b)

    def test_signed_v01_legacy_bridge_style_is_not_core_v1(self):
        self._bundle(mutate_summary=lambda x: x["not_evaluable"].append({
            "procedure": "MONTE_CARLO", "reason": "SYNTHETIC: incomplete"
        }))
        with self.assertRaises(EvidenceError):
            self.check(self.root / "signed-A")

    def test_signed_incomplete_rejected_with_or_without_not_evaluable(self):
        for n, modifier in enumerate([
            lambda x: x.update(disposition="CLOSED_INCOMPLETE"),
            lambda x: x.update(disposition="CLOSED_INCOMPLETE", not_evaluable=[{
                "procedure": "RISK_LIMITS", "reason": "SYNTHETIC: not evaluated"
            }]),
            lambda x: x.update(not_evaluable=[{
                "procedure": "RISK_LIMITS", "reason": "SYNTHETIC: not evaluated"
            }]),
        ]):
            with self.subTest(n=n):
                p = self._bundle(str(n), mutate_summary=modifier)
                with self.assertRaises(EvidenceError):
                    self.check(p)

    def test_all_pass_and_incomplete_procedure_coverage_rejected(self):
        variations = [
            lambda x: [c.update(verdict="PASS", observation=(
                "The " + _LABELS[c["procedure"]] + " criterion was met."))
                       for c in x["criteria"]],
            lambda x: x["criteria"].pop(),
            lambda x: x["criteria"].append(dict(x["criteria"][0])),
            lambda x: x["criteria"][0].update(procedure="HOLDOUT"),
            lambda x: x["criteria"][0].update(procedure="TRAIN"),
        ]
        for n, mutation in enumerate(variations):
            with self.subTest(n=n):
                p = self._bundle("m" + str(n), mutate_summary=mutation)
                with self.assertRaises(EvidenceError):
                    self.check(p)

    def test_every_candidate_phrase_byte_change_is_rejected(self):
        changes = [
            "The out-of-sample criterion was NOT MET.",
            "The out-of-sample criterion was not met. ",
            "The out-of-sample criterion was not met.\n",
            "Sharpe was -1.0",
            "SYNTHETIC private metric: 123",
            "The holdout criterion was not met.",
            "",
            "The out-of-sample criterion was met.",
        ]
        for n, text in enumerate(changes):
            with self.subTest(n=n):
                def modify(summary):
                    summary["criteria"][0]["observation"] = text
                p = self._bundle("phrase" + str(n), mutate_summary=modify)
                with self.assertRaises(EvidenceError):
                    self.check(p)

    def test_all_ten_procedures_accept_exact_fixed_words_only(self):
        for name in sorted(_LABELS):
            with self.subTest(name=name):
                def modify(summary):
                    for c in summary["criteria"]:
                        if c["procedure"] == name:
                            c["verdict"] = "FAIL"
                            c["observation"] = (
                                "The " + _LABELS[name] + " criterion was not met.")
                p = self._bundle(name, mutate_summary=modify)
                self.assertEqual(self.check(p)["failure_count"], 1 if name == "OUT_OF_SAMPLE" else 2)

    def test_reject_signed_real_claim_and_real_signer_even_with_valid_signature(self):
        real = self._bundle("real", experiment_id="REAL-SCIENCE-01")
        with self.assertRaises(EvidenceError):
            self.check(real)
        self._trust(key_id="non-synthetic-real-key")
        fake = self._bundle("key", signer_id="non-synthetic-real-key")
        with self.assertRaises(EvidenceError):
            self.check(fake)

    def test_signed_extra_science_private_or_authority_fields_rejected(self):
        changes = [
            lambda x: x.update(holdout_access=True),
            lambda x: x.update(promotion_authority=True),
            lambda x: x.update(broker_authority=True),
            lambda x: x.update(source_system="untrusted"),
            lambda x: x.update(approved_scope="LIVE_EXECUTION"),
            lambda x: x.update(private_data="do-not-include"),
        ]
        for n, change in enumerate(changes):
            with self.subTest(n=n):
                p = self._bundle("manifest" + str(n), mutate_manifest=change)
                with self.assertRaises(EvidenceError):
                    self.check(p)

    def test_tamper_and_revoked_signer_rejected(self):
        p = self._bundle()
        summary = p / "summary.json"
        summary.write_bytes(summary.read_bytes() + b" ")
        with self.assertRaises(EvidenceError):
            self.check(p)
        q = self._bundle("B")
        self._trust(status="REVOKED")
        with self.assertRaises(EvidenceError):
            self.check(q)

    def test_wrong_signature_or_substituted_test_key_rejected(self):
        p = self._bundle()
        att = p / "attestation.json"
        data = json.loads(att.read_text())
        data["signature_b64"] = base64.b64encode(b"\x00" * 64).decode("ascii")
        att.write_bytes(encoded(data))
        with self.assertRaises(EvidenceError):
            self.check(p)
        q = self._bundle("B")
        replacement = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self._trust(public_key=replacement)
        with self.assertRaises(EvidenceError):
            self.check(q)

    def test_reject_extra_files_symlinks_and_inner_trust(self):
        p = self._bundle()
        (p / "strategy.json").write_text("PRIVATE")
        with self.assertRaises(EvidenceError):
            self.check(p)
        q = self._bundle("B")
        src = q / "summary.json"
        external = self.root / "shadow.json"
        external.write_bytes(src.read_bytes())
        src.unlink()
        src.symlink_to(external)
        with self.assertRaises(EvidenceError):
            self.check(q)
        s = self._bundle("C")
        with self.assertRaises(EvidenceError):
            inspect_synthetic_core_v1_batch((s,), trust_store=s / "attestation.json")

    def test_cli_success_is_explicitly_synthetic_non_authoritative(self):
        p = self._bundle()
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["core-policy", "--bundle", str(p), "--trust-store", str(self.trust)])
        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        output = json.loads(stdout.getvalue())
        self.assertIs(output["current_export_authorization"], False)
        self.assertEqual(output["status"], "SYNTHETIC_CORE_V1_RECIPIENT_PREVIEW_ONLY")

    def test_cli_denial_does_not_echo_private_paths_or_text(self):
        p = self._bundle(experiment_id="REAL-DONT-EXPORT")
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["core-policy", "--bundle", str(p), "--trust-store", str(self.trust)])
        self.assertEqual(code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue().strip(), "SYNTHETIC_CORE_POLICY_PREVIEW_DENIED")
        self.assertNotIn("REAL-DONT-EXPORT", stderr.getvalue())

    def test_no_runtime_writer_or_core_source_dependency(self):
        import ast
        import forexpro_ri.core_policy_preview as policy
        code = Path(policy.__file__).read_text(encoding="utf-8")
        tree = ast.parse(code)
        forbidden = ("MetaTrader5", "forex_lab", "socket", "subprocess",
                     "requests", "urllib", "sqlite3")
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [x.name for x in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            self.assertFalse(any(n.startswith(forbidden) for n in names))
        self.assertFalse(any(isinstance(n, ast.Call) and
                             isinstance(n.func, ast.Name) and
                             n.func.id in ("open", "exec", "eval")
                             for n in ast.walk(tree)))


if __name__ == "__main__":
    unittest.main()
