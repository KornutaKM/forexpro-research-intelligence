"""FRI v2.9 hermetic full-recipient qualification and failure containment."""
from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.synthetic_qualification import run_synthetic_recipient_qualification


class SyntheticQualificationEndToEndTests(unittest.TestCase):
    def test_two_bundle_signed_trust_memory_advisor_recovery(self):
        report = run_synthetic_recipient_qualification()
        self.assertEqual(report["status"], "SYNTHETIC_RECIPIENT_QUALIFICATION_PASS_NOT_APPROVAL")
        self.assertEqual(report["rehearsal"], "SYNTHETIC_ONLY")
        self.assertEqual(report["signed_bundle_count"], 2)
        self.assertEqual(report["complete_candidate_criteria"], 20)
        self.assertEqual(report["negative_scenarios_denied"], 6)
        self.assertTrue(report["research_memory_verified"])
        self.assertTrue(report["idempotent_reimport"])
        self.assertTrue(report["recovery_verified"])
        self.assertTrue(report["retired_operator_and_exporter_revocation_rehearsed"])
        self.assertEqual(report["signed_only_advisor_quality"], "PASS")
        for name in (
            "candidate_dictionary_approved", "real_source_closure_authenticated",
            "independent_operator_custody_proven", "real_source_access",
            "current_export_authorization", "real_ingestion_approved",
            "scientific_approval", "holdout_access", "broker_authority",
            "same_campaign_feedback_authority",
        ):
            self.assertIs(report[name], False)
        self.assertNotIn("SYNTHETIC-QUAL-A", json.dumps(report))
        self.assertNotIn("out-of-sample criterion", json.dumps(report))

    def test_operator_command_no_external_input_or_paths(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = main(["integration", "qualification"])
        self.assertEqual(status, 0)
        self.assertEqual(err.getvalue(), "")
        result = json.loads(out.getvalue())
        self.assertFalse(result["real_ingestion_approved"])
        self.assertNotIn("private_key", out.getvalue())
        self.assertNotIn("temporary", out.getvalue().lower())

    def test_cannot_supply_source_bundle_or_production_key_to_command(self):
        for forbidden in (["--bundle", "/private/research"],
                          ["--trust-store", "/private/trusted-keys.json"],
                          ["--real", "1"]):
            with self.subTest(forbidden=forbidden):
                with contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as denied:
                        main(["integration", "qualification", *forbidden])
                self.assertEqual(denied.exception.code, 2)

    def test_disposable_artifact_directory_removed_after_success(self):
        original = tempfile.TemporaryDirectory
        allocated = []
        def record(*args, **kwargs):
            directory = original(*args, **kwargs)
            if kwargs.get("prefix") == "fri-v29-qualification-":
                allocated.append(directory.name)
            return directory
        with patch("forexpro_ri.synthetic_qualification.tempfile.TemporaryDirectory",
                   side_effect=record):
            run_synthetic_recipient_qualification()
        self.assertEqual(len(allocated), 1)
        self.assertFalse(Path(allocated[0]).exists())

    def test_unsigned_or_invalid_receipt_cannot_be_accepted(self):
        with patch("forexpro_ri.synthetic_qualification.ingest",
                   side_effect=EvidenceError("fake source path: /PRIVATE")):
            with self.assertRaises(EvidenceError):
                run_synthetic_recipient_qualification()

    def test_failed_signed_trust_check_prevents_any_ingest(self):
        with patch(
            "forexpro_ri.synthetic_qualification.inspect_synthetic_recipient_trust_continuity",
            side_effect=EvidenceError("invalid synthetic trust"),
        ):
            with patch("forexpro_ri.synthetic_qualification.ingest") as ingest:
                with self.assertRaises(EvidenceError):
                    run_synthetic_recipient_qualification()
                ingest.assert_not_called()

    def test_bad_memory_integrity_is_not_ignored(self):
        with patch("forexpro_ri.synthetic_qualification.verify_memory",
                   return_value={"status": "FAIL", "experiment_count": 2}):
            with self.assertRaises(EvidenceError):
                run_synthetic_recipient_qualification()

    def test_quality_module_cannot_promote_model_claims(self):
        with patch("forexpro_ri.synthetic_qualification.assess_advisor",
                   return_value={"status": "PASS", "model_semantic_truth_verified": True}):
            with self.assertRaises(EvidenceError):
                run_synthetic_recipient_qualification()

    def test_backup_restoration_must_succeed(self):
        with patch("forexpro_ri.synthetic_qualification.restore_backup",
                   side_effect=EvidenceError("restore failed")):
            with self.assertRaises(EvidenceError):
                run_synthetic_recipient_qualification()

    def test_no_private_exception_detail_in_cli_denial(self):
        out, err = io.StringIO(), io.StringIO()
        with patch("forexpro_ri.synthetic_qualification.run_synthetic_recipient_qualification",
                   side_effect=EvidenceError("secret source filename: /PRIVATE/S1")):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                status = main(["integration", "qualification"])
        self.assertEqual(status, 2)
        self.assertEqual(out.getvalue(), "")
        self.assertEqual(err.getvalue().strip(), "INTEGRATION_REJECTED: EvidenceError")
        self.assertNotIn("PRIVATE", err.getvalue())

    def test_recovery_does_not_authorize_a_live_destination(self):
        report = run_synthetic_recipient_qualification()
        self.assertFalse(report["current_export_authorization"])
        self.assertFalse(report["real_source_access"])
        self.assertTrue(report["recovery_verified"])


if __name__ == "__main__":
    unittest.main()
