"""Offline, non-authoritative, self-contained Research Review Pack.

Composes existing verified FRI services; no new history or source data store.
Historical receipts are not source-owner export authorization.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .advisor import build_advisor
from .analysis import canonical_json
from .contracts import EvidenceError
from .dossier import build_dossier
from .failure_intelligence import build_failure_report
from .provenance import audit as provenance_audit
from .quality import assess_advisor

_MAX_CASES = 100
_AUTHORITY = {
    "scientific": False, "holdout": False, "broker": False,
    "promotion": False, "experiment_execution": False, "core_feedback": False,
}


def _digest(data: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def _finalize(data: dict[str, Any]) -> dict[str, Any]:
    data["report_sha256"] = _digest(data)
    return data


def _empty() -> dict[str, Any]:
    return _finalize({
        "schema_version": 1,
        "report_kind": "NON_AUTHORITATIVE_RESEARCH_REVIEW_PACK",
        "status": "NO_ELIGIBLE_DATA",
        "intake_mode": "SIGNED_ONLY",
        "experiment_count": 0,
        "snapshot_sha256": None,
        "provenance_audit_sha256": None,
        "failure_report_sha256": None,
        "advisor_report_sha256": None,
        "procedure_coverage": [],
        "review_topics": [],
        "cases": [],
        "authority": dict(_AUTHORITY),
        "limitations": [
            "No eligible locally stored, authorized closed-research evidence was supplied.",
            "This empty report does not confirm that source export is approved or that experiments passed.",
            "PREVIEW_ONLY and LOCAL_UNVERIFIED data cannot enter Research Memory.",
        ],
    })


def build_review_pack(
    db_path: str | Path, *, expected_procedures: Sequence[str] = (),
    min_support: int = 2, max_items: int = 12,
    allow_unsigned_synthetic: bool = False,
) -> dict[str, Any]:
    """Build a bounded, linked report using existing Research Memory services.

    All historical intake receipts are checked; unsigned is allowed only in
    explicit synthetic rehearsal, never by default. Cross-call snapshot drifts
    are rejected rather than silently mixed.
    """
    if type(allow_unsigned_synthetic) is not bool:
        raise EvidenceError("synthetic gate must be boolean")
    location = Path(db_path)
    if location.is_symlink():
        raise EvidenceError("Research Memory symlink is forbidden")
    if not location.exists():
        if allow_unsigned_synthetic:
            raise EvidenceError("synthetic rehearsal requires an existing fixture database")
        return _empty()
    audit = provenance_audit(location)
    count = audit["experiment_count"]
    if count == 0:
        return _empty()
    if count > _MAX_CASES:
        raise EvidenceError("bounded review pack supports up to 100 closed experiments")
    receipts = audit["receipts"]
    if len(receipts) != count:
        raise EvidenceError("incomplete intake receipt set")
    receipt_by_id = {r["experiment_id"]: r for r in receipts}
    if len(receipt_by_id) != count:
        raise EvidenceError("duplicate intake receipt")
    if any(r["verification_status"] == "LEGACY_UNATTESTED" for r in receipts):
        raise EvidenceError("legacy/unattested research cannot enter a review pack")
    if allow_unsigned_synthetic:
        if any(not eid.startswith("SYNTHETIC-") for eid in receipt_by_id):
            raise EvidenceError("synthetic review mode requires synthetic IDs for all records")
        if any(r["verification_status"] not in ("UNSIGNED_SYNTHETIC", "SIGNATURE_VERIFIED")
               for r in receipts):
            raise EvidenceError("unverifiable synthetic intake")
    elif not audit["all_intakes_have_signed_receipts"]:
        raise EvidenceError("signed-only research pack rejects unsigned evidence")

    source = [{"experiment_id": r["experiment_id"], "entry_sha256": r["entry_sha256"],
               "receipt_sha256": r["receipt_sha256"]}
              for r in sorted(receipts, key=lambda row: row["experiment_id"])]
    synthetic_signed = (not allow_unsigned_synthetic and all(
        ref["experiment_id"].startswith("SYNTHETIC-")
        and receipt_by_id[ref["experiment_id"]]["signer_key_id"] in {
            "SYNTHETIC_EPHEMERAL_BRIDGE_V1",
            "FRI_SYNTHETIC_COHORT_IN_MEMORY_ONLY",
        }
        for ref in source
    ))
    snapshot = _digest({"entries": source})
    failure = build_failure_report(location, min_support=min_support)
    advisor = build_advisor(location, expected_procedures=expected_procedures,
                            min_support=min_support, max_items=max_items,
                            allow_unsigned_synthetic=allow_unsigned_synthetic)
    assess_advisor(advisor, require_signed=not allow_unsigned_synthetic)
    if advisor["memory_snapshot_sha256"] != snapshot:
        raise EvidenceError("advisor snapshot does not match intake receipts")
    if advisor["observed_experiment_count"] != count or failure["observed_experiment_count"] != count:
        raise EvidenceError("inconsistent Research Memory coverage")

    cases = []
    for row in source:
        eid = row["experiment_id"]
        dossier = build_dossier(location, focus_experiment_id=eid,
                                expected_procedures=list(expected_procedures),
                                min_support=min_support)
        if dossier["memory_snapshot_sha256"] != snapshot:
            raise EvidenceError("dossier snapshot changed during compilation")
        if dossier["focus_experiment"]["entry_sha256"] != row["entry_sha256"]:
            raise EvidenceError("dossier entry identity mismatch")
        if dossier["focus_intake_provenance"]["receipt_sha256"] != row["receipt_sha256"]:
            raise EvidenceError("dossier receipt identity mismatch")
        cases.append({
            "experiment_id": eid,
            "entry_sha256": row["entry_sha256"],
            "receipt_sha256": row["receipt_sha256"],
            "evidence_visibility": (
                "SIGNED_SYNTHETIC_TEST_ONLY" if synthetic_signed
                else "HISTORICAL_SIGNED_INTAKE_ONLY"
                if receipt_by_id[eid]["verification_status"] == "SIGNATURE_VERIFIED"
                else "UNSIGNED_SYNTHETIC_DEMO_ONLY"
            ),
            "recorded_disposition": dossier["focus_experiment"]["recorded_disposition"],
            "procedure_outcomes": dossier["procedure_outcomes"],
            "evidence_visibility_gaps": dossier["evidence_visibility_gaps"],
            "similar_observed_cases": dossier["similar_observed_cases"],
            "similar_cases_truncated": dossier["similar_cases_truncated"],
            "dossier_sha256": dossier["report_sha256"],
        })

    # Failure Intelligence covers procedures actually observed anywhere, while
    # Dossier also includes operator-declared procedures that no experiment
    # measured. Do not silently omit these all-UNOBSERVED gaps from the table.
    coverage_by_proc = {row["procedure"]: row for row in failure["procedure_coverage"]}
    dossier_procs = {r["procedure"] for r in cases[0]["procedure_outcomes"]}
    for procedure in sorted(dossier_procs - set(coverage_by_proc)):
        coverage_by_proc[procedure] = {
            "procedure": procedure,
            "failed_experiments": 0,
            "passed_experiments": 0,
            "not_evaluable_experiments": 0,
            "unobserved_experiments": count,
            "failure_evidence": [],
            "not_evaluable_evidence": [],
        }
    if set(coverage_by_proc) != dossier_procs:
        raise EvidenceError("unexpected procedure coverage mismatch")
    merged_coverage = [coverage_by_proc[p] for p in sorted(coverage_by_proc)]

    topics = []
    for proposal in advisor["proposals"]:
        refs = proposal["evidence_sample"]
        for ref in refs:
            known = receipt_by_id.get(ref["experiment_id"])
            if (known is None or known["entry_sha256"] != ref["entry_sha256"]
                    or known["receipt_sha256"] != ref["receipt_sha256"]):
                raise EvidenceError("advisor references unknown or changed evidence")
        topics.append({
            "item_id": proposal["item_id"],
            "kind": proposal["kind"],
            "procedure": proposal["procedure"],
            "reason": proposal["basis"],
            "question_for_new_experiment": proposal["question_for_new_experiment"],
            "evidence_sample": refs,
            "evidence_sample_truncated": proposal["evidence_sample_truncated"],
            "evidence_visibility": (
                "UNSIGNED_SYNTHETIC_DEMO_ONLY" if allow_unsigned_synthetic
                else "SIGNED_SYNTHETIC_TEST_ONLY" if synthetic_signed
                else "HISTORICAL_RECEIPT_NOT_CURRENT_EXPORT_PERMISSION"
            ),
            "interpretation": "DESCRIPTIVE_NOT_CAUSAL",
        })

    # Re-read all provenance after the multi-service composition. A concurrent
    # change cannot quietly combine contradictory views.
    if provenance_audit(location)["report_sha256"] != audit["report_sha256"]:
        raise EvidenceError("Research Memory changed during review compilation")
    return _finalize({
        "schema_version": 1,
        "report_kind": "NON_AUTHORITATIVE_RESEARCH_REVIEW_PACK",
        "status": ("SYNTHETIC_DEMONSTRATION" if allow_unsigned_synthetic
                   else "SYNTHETIC_SIGNED_DEMONSTRATION" if synthetic_signed
                   else "HISTORICAL_SIGNED_INTAKES"),
        "intake_mode": ("SYNTHETIC_EXPLICIT" if allow_unsigned_synthetic
                        else "SIGNED_SYNTHETIC_TEST" if synthetic_signed
                        else "SIGNED_ONLY"),
        "experiment_count": count,
        "snapshot_sha256": snapshot,
        "provenance_audit_sha256": audit["report_sha256"],
        "failure_report_sha256": failure["report_sha256"],
        "advisor_report_sha256": advisor["report_sha256"],
        "procedure_coverage": merged_coverage,
        "review_topics": topics,
        "cases": cases,
        "authority": dict(_AUTHORITY),
        "limitations": [
            "Historical intake verification is not current source-owner export permission.",
            "Outcomes are recorded verdicts, not independently reconstructed scientific conclusions.",
            "UNOBSERVED is neither PASS nor NOT_EVALUABLE.",
            "Cases may share lineage: distinct experiment IDs do not imply independent replication.",
            "Recurring failures and similarities are descriptive, never proof of causality or profitability.",
            "Research questions apply only to NEW preregistered experiments.",
            "No experiment, Core record, scientific authority or broker state is changed.",
        ],
    })


def verify_review_pack(report: dict[str, Any]) -> None:
    """Verify report integrity and non-authority before publishing a document."""
    if (not isinstance(report, dict) or report.get("schema_version") != 1
            or report.get("report_kind") != "NON_AUTHORITATIVE_RESEARCH_REVIEW_PACK"
            or report.get("authority") != _AUTHORITY):
        raise EvidenceError("invalid research review pack or attempted authority escalation")
    if report.get("report_sha256") != _digest({k: v for k, v in report.items() if k != "report_sha256"}):
        raise EvidenceError("review pack digest mismatch")
    if report.get("status") not in ("NO_ELIGIBLE_DATA", "SYNTHETIC_DEMONSTRATION",
                                     "SYNTHETIC_SIGNED_DEMONSTRATION", "HISTORICAL_SIGNED_INTAKES"):
        raise EvidenceError("unknown review state")
    if report["status"] == "NO_ELIGIBLE_DATA" and (
        report.get("experiment_count") != 0 or report.get("cases") or report.get("review_topics")
    ):
        raise EvidenceError("empty state contains research claims")
    # The hash only proves internal byte identity. Reconcile independent
    # procedure outcomes, cohort counts and citation identities as well.
    from .review_integrity import audit_review_structure
    audit_review_structure(report)


def render_review_html(report: dict[str, Any]) -> str:
    """Render a portable, offline, script-free HTML report; escape every field."""
    verify_review_pack(report)
    esc = lambda value: html.escape(str(value), quote=True)
    lines = [
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">",
        "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">",
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">",
        "<title>FRI Research Review Pack</title>",
        "<style>body{font:16px system-ui,sans-serif;max-width:960px;margin:2em auto;padding:0 1em;color:#192b37}"
        "main,section{margin:1.5em 0}article{border:1px solid #bac7d1;border-radius:8px;padding:1em;margin:1em 0}"
        "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #bac7d1;padding:.5em;text-align:left}"
        "code{word-break:break-all;font-size:.83em}small{color:#435463}</style></head><body><main>",
        "<h1>FRI — Research Review Pack</h1>",
        "<p><strong>Non-authoritative research evidence review. No trading or scientific approval.</strong></p>",
        "<p>State: " + esc(report["status"]) + " · Experiments: " + esc(report["experiment_count"]) + "</p>",
    ]
    if report["status"] == "NO_ELIGIBLE_DATA":
        lines.append("<section><h2>No eligible approved research data</h2>"
                     "<p>No eligible closed-research evidence has been supplied. "
                     "Preview outputs cannot be promoted into scientific Research Memory.</p></section>")
    else:
        case_anchors = {c["experiment_id"]: "case-" + str(i + 1)
                        for i, c in enumerate(report["cases"])}
        lines.append("<section><h2>Procedure coverage</h2><table>"
                     "<tr><th>Procedure</th><th>FAIL</th><th>PASS</th>"
                     "<th>NOT_EVALUABLE</th><th>UNOBSERVED</th></tr>")
        for item in report["procedure_coverage"]:
            lines.append("<tr>" + "".join("<td>" + esc(value) + "</td>" for value in (
                item["procedure"], item["failed_experiments"],
                item["passed_experiments"], item["not_evaluable_experiments"],
                item["unobserved_experiments"])) + "</tr>")
        lines.append("</table></section><section><h2>What to investigate next?</h2>")
        if not report["review_topics"]:
            lines.append("<p>No eligible advisory questions in this stored cohort.</p>")
        for item in report["review_topics"]:
            lines.append("<article><h3>" + esc(item["procedure"]) + " — " + esc(item["kind"]) + "</h3>")
            lines.append("<p>" + esc(item["question_for_new_experiment"]) + "</p>")
            lines.append("<p><small>Attention basis: " + esc(item["reason"]) +
                         " · Evidence visibility: " + esc(item["evidence_visibility"]) + "</small></p>")
            lines.append("<p><small>Topic: " + esc(item["item_id"]) +
                         " · Descriptive only; not causal or independent replication.</small></p>")
            if item["evidence_sample_truncated"]:
                lines.append("<p><small>Evidence sample truncated; consult the bound advisor digest.</small></p>")
            for ref in item["evidence_sample"]:
                eid = ref["experiment_id"]
                a = case_anchors.get(eid)
                if a is None:
                    raise EvidenceError("unlinked review evidence")
                lines.append("<p><a href=\"#" + a + "\">" + esc(eid) + "</a>"
                             " · receipt <code>" + esc(ref["receipt_sha256"]) + "</code></p>")
            lines.append("</article>")
        lines.append("</section><section><h2>Evidence-linked experiment dossiers</h2>")
        for c in report["cases"]:
            lines.append("<article id=\"" + case_anchors[c["experiment_id"]] + "\"><h3>" +
                         esc(c["experiment_id"]) + "</h3>")
            lines.append("<p>Recorded disposition: " + esc(c["recorded_disposition"]) +
                         " · " + esc(c["evidence_visibility"]) + "</p>")
            lines.append("<p>Entry <code>" + esc(c["entry_sha256"]) +
                         "</code> · Receipt <code>" + esc(c["receipt_sha256"]) + "</code></p>")
            lines.append("<ul>")
            for outcome in c["procedure_outcomes"]:
                lines.append("<li><details><summary>" + esc(outcome["procedure"]) + ": " +
                             esc(outcome["recorded_status"]) + "</summary>")
                lines.append("<p><small>Expected procedure (operator declaration): " +
                             esc(outcome["expected_by_operator"]) + "</small></p>")
                if outcome["criteria_evidence"]:
                    lines.append("<ul>")
                    for criterion in outcome["criteria_evidence"]:
                        lines.append("<li>Criterion " + esc(criterion["criterion_id"]) +
                                     " · " + esc(criterion["recorded_verdict"]) +
                                     " · observation digest <code>" +
                                     esc(criterion["observation_sha256"]) + "</code></li>")
                    lines.append("</ul>")
                if outcome["not_evaluable_reason_sha256"]:
                    lines.append("<p>Recorded not-evaluable reason digest: <code>" +
                                 esc(outcome["not_evaluable_reason_sha256"]) + "</code></p>")
                if outcome["recorded_status"] == "UNOBSERVED":
                    lines.append("<p>No stored procedure evidence: UNOBSERVED, not PASS.</p>")
                lines.append("</details></li>")
            lines.append("</ul><p>Similar observed cases (not independent replication):</p><ul>")
            for row in c["similar_observed_cases"]:
                eid = row["experiment"]["experiment_id"]
                anchor = case_anchors.get(eid)
                if anchor is None:
                    raise EvidenceError("unlinked similar-case reference")
                lines.append("<li><a href=\"#" + anchor + "\">" +
                             esc(eid) + "</a></li>")
            lines.append("</ul></article>")
        lines.append("</section>")
    lines.append("<section><h2>Limitations</h2><ul>")
    lines.extend("<li>" + esc(note) + "</li>" for note in report["limitations"])
    lines.append("</ul></section><footer><small>Pack SHA-256: <code>" +
                 esc(report["report_sha256"]) + "</code></small></footer></main></body></html>\n")
    return "\n".join(lines)


def publish_review_pack(report: dict[str, Any], output_dir: str | Path) -> dict[str, Any]:
    """Publish a new private HTML+JSON directory; never overwrite prior reports."""
    verify_review_pack(report)
    path = Path(output_dir)
    if path.exists() or path.is_symlink() or not path.parent.is_dir() or path.parent.is_symlink():
        raise EvidenceError("review output must be an unused path beneath a real directory")
    text = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    page = render_review_html(report)
    stage = Path(tempfile.mkdtemp(prefix=".fri-review-stage-", dir=path.parent))
    try:
        stage.chmod(0o700)
        for name, content in (("review.json", text), ("index.html", page)):
            fd = os.open(stage / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        if path.exists() or path.is_symlink():
            raise EvidenceError("review destination appeared during publication")
        stage.rename(path)
        return {"status": "CREATED", "report_sha256": report["report_sha256"],
                "files": ["index.html", "review.json"], "authority": "NONE"}
    finally:
        if stage.exists():
            shutil.rmtree(stage)
