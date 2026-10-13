"""Independent semantic consistency audit for offline FRI Research Review Packs.

No Core reads, no network, no raw observations. A self-consistent pack is not
proof of an authorized source exporter, live key status or scientific truth.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError, _ALLOWED_PROCEDURES, _ID

_SHA = re.compile(r"^[0-9a-f]{64}$")
_ITEM = re.compile(r"^[0-9a-f]{24}$")
_STATES = ("FAIL", "PASS", "NOT_EVALUABLE", "UNOBSERVED")
_AUTHORITY = {
    "scientific": False, "holdout": False, "broker": False,
    "promotion": False, "experiment_execution": False, "core_feedback": False,
}
_VIS = {"SIGNED_SYNTHETIC_TEST_ONLY", "HISTORICAL_SIGNED_INTAKE_ONLY",
        "UNSIGNED_SYNTHETIC_DEMO_ONLY"}
_TOPIC_VIS = {"SIGNED_SYNTHETIC_TEST_ONLY", "HISTORICAL_RECEIPT_NOT_CURRENT_EXPORT_PERMISSION",
              "UNSIGNED_SYNTHETIC_DEMO_ONLY"}
_TOPIC_KIND = {"EVIDENCE_GAP", "REPEATED_NOT_EVALUABLE", "REPEATED_FAILURE",
               "ISOLATED_NEGATIVE_OR_GAP"}


def _bad(reason: str) -> None:
    raise EvidenceError("review consistency: " + reason)


def _sha(value: Any) -> bool:
    return type(value) is str and _SHA.fullmatch(value) is not None


def _text(value: Any, *, maxlen: int = 2048) -> bool:
    return type(value) is str and 0 < len(value) <= maxlen


def _identity(obj: Any, *, receipt: bool = True) -> tuple[str, str, str | None]:
    if type(obj) is not dict or not _ID.fullmatch(obj.get("experiment_id", "") if type(obj.get("experiment_id")) is str else ""):
        _bad("invalid experiment identity")
    if not _sha(obj.get("entry_sha256")):
        _bad("invalid entry sha256")
    if receipt and not _sha(obj.get("receipt_sha256")):
        _bad("invalid receipt sha256")
    return (obj["experiment_id"], obj["entry_sha256"],
            obj.get("receipt_sha256") if receipt else None)


def _strict_keys(obj: Any, expected: set[str], context: str) -> None:
    if type(obj) is not dict or set(obj) != expected:
        _bad("unexpected keys in " + context)


def _outcomes(case: dict[str, Any]) -> dict[str, str]:
    rows = case.get("procedure_outcomes")
    if type(rows) is not list or len(rows) > len(_ALLOWED_PROCEDURES):
        _bad("invalid procedure outcomes")
    result = {}
    for row in rows:
        _strict_keys(row, {"procedure", "recorded_status", "expected_by_operator",
                           "criteria_evidence", "not_evaluable_reason_sha256"},
                     "procedure outcome")
        proc = row["procedure"]
        if proc not in _ALLOWED_PROCEDURES or proc in result:
            _bad("duplicate or unsupported procedure")
        status = row["recorded_status"]
        if status not in _STATES or type(row["expected_by_operator"]) is not bool:
            _bad("invalid outcome/expectation")
        criteria = row["criteria_evidence"]
        reason = row["not_evaluable_reason_sha256"]
        if type(criteria) is not list or len(criteria) > 200:
            _bad("invalid criterion evidence")
        ids, verdicts = set(), []
        for c in criteria:
            _strict_keys(c, {"criterion_id", "recorded_verdict", "observation_sha256"},
                         "criterion")
            cid = c["criterion_id"]
            if (type(cid) is not str or not _ID.fullmatch(cid) or cid in ids
                    or c["recorded_verdict"] not in ("PASS", "FAIL")
                    or not _sha(c["observation_sha256"])):
                _bad("invalid/duplicated criterion evidence")
            ids.add(cid)
            verdicts.append(c["recorded_verdict"])
        derived = ("FAIL" if "FAIL" in verdicts else
                   "PASS" if verdicts else
                   "NOT_EVALUABLE" if reason is not None else "UNOBSERVED")
        if status != derived:
            _bad("procedure status conflicts with criterion evidence")
        if (reason is not None and (not _sha(reason) or bool(criteria))):
            _bad("conflicting not-evaluable evidence")
        result[proc] = status
    return result


def _similarity(case: dict[str, Any], identities: dict[str, tuple],
                states: dict[str, dict[str, str]]) -> int:
    sims = case.get("similar_observed_cases")
    if type(sims) is not list or len(sims) > 10 or type(case.get("similar_cases_truncated")) is not bool:
        _bad("invalid similar case set")
    seen = set()
    current_id = case["experiment_id"]
    first = {(p, s) for p, s in states[current_id].items() if s != "PASS" and s != "UNOBSERVED"}
    for other in sims:
        _strict_keys(other, {"experiment", "shared_negative_signatures", "overlap"},
                     "similar case")
        eid, ent, _ = _identity(other["experiment"], receipt=False)
        if (eid == current_id or eid not in identities or eid in seen
                or ent != identities[eid][1]):
            _bad("unbound similar case reference")
        seen.add(eid)
        theirs = {(p, s) for p, s in states[eid].items() if s not in ("PASS", "UNOBSERVED")}
        expected_shared = first & theirs
        expected_union = first | theirs
        provided = other["shared_negative_signatures"]
        if type(provided) is not list:
            _bad("invalid similarity signatures")
        got = set()
        for x in provided:
            _strict_keys(x, {"procedure", "recorded_status"}, "similarity signature")
            key = (x["procedure"], x["recorded_status"])
            if key in got:
                _bad("repeated similarity signature")
            got.add(key)
        if not expected_shared or got != expected_shared:
            _bad("similarity signatures not supported")
        if other["overlap"] != {"shared": len(expected_shared), "union": len(expected_union)}:
            _bad("similarity score inconsistent")
    return len(sims)


def audit_review_structure(report: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on self-contradictory report data; return bounded audit.

    This does NOT verify a raw signed export or authenticate the actual source.
    It only checks that an offline review document is internally consistent.
    """
    required = {
        "schema_version", "report_kind", "status", "intake_mode", "experiment_count",
        "snapshot_sha256", "provenance_audit_sha256", "failure_report_sha256",
        "advisor_report_sha256", "procedure_coverage", "review_topics", "cases",
        "authority", "limitations", "report_sha256",
    }
    _strict_keys(report, required, "report")
    if (type(report["schema_version"]) is not int or report["schema_version"] != 1
            or report["report_kind"] != "NON_AUTHORITATIVE_RESEARCH_REVIEW_PACK"
            or report["authority"] != _AUTHORITY
            or not _sha(report["report_sha256"])):
        _bad("invalid report authority or schema")
    source = {k: v for k, v in report.items() if k != "report_sha256"}
    actual = hashlib.sha256(canonical_json(source).encode()).hexdigest()
    if actual != report["report_sha256"]:
        _bad("report digest mismatch")
    if (type(report["experiment_count"]) is not int or not 0 <= report["experiment_count"] <= 100
            or type(report["cases"]) is not list or type(report["review_topics"]) is not list
            or type(report["procedure_coverage"]) is not list
            or type(report["limitations"]) is not list
            or not 1 <= len(report["limitations"]) <= 50
            or any(not _text(x) for x in report["limitations"])):
        _bad("invalid report bounds")

    status = report["status"]
    if status == "NO_ELIGIBLE_DATA":
        if (report["experiment_count"] != 0 or report["cases"] or report["review_topics"]
                or report["procedure_coverage"] or report["intake_mode"] != "SIGNED_ONLY"
                or any(report[k] is not None for k in ("snapshot_sha256",
                "provenance_audit_sha256", "failure_report_sha256", "advisor_report_sha256"))):
            _bad("false empty report")
        return {"status": "SELF_CONSISTENT_EMPTY_REPORT", "checked_cases": 0,
                "checked_procedures": 0, "checked_criteria": 0, "checked_citations": 0,
                "checked_similar_cases": 0, "source_authenticated": False,
                "scientific_authority": False}
    modes = {
        "SYNTHETIC_DEMONSTRATION": "SYNTHETIC_EXPLICIT",
        "SYNTHETIC_SIGNED_DEMONSTRATION": "SIGNED_SYNTHETIC_TEST",
        "HISTORICAL_SIGNED_INTAKES": "SIGNED_ONLY",
    }
    if status not in modes or report["intake_mode"] != modes[status]:
        _bad("intake mode/status mismatch")
    if any(not _sha(report[k]) for k in ("snapshot_sha256", "provenance_audit_sha256",
                                       "failure_report_sha256", "advisor_report_sha256")):
        _bad("invalid evidence source digest")
    if not 1 <= report["experiment_count"] == len(report["cases"]) <= 100:
        _bad("case count mismatch")

    identities, states = {}, {}
    criteria_count = 0
    gaps_count = 0
    for case in report["cases"]:
        _strict_keys(case, {"experiment_id", "entry_sha256", "receipt_sha256",
                           "evidence_visibility", "recorded_disposition",
                           "procedure_outcomes", "evidence_visibility_gaps",
                           "similar_observed_cases", "similar_cases_truncated",
                           "dossier_sha256"}, "case")
        eid, entry, receipt = _identity(case)
        if eid in identities or not _sha(case["dossier_sha256"]):
            _bad("duplicate case or invalid dossier hash")
        identities[eid] = (eid, entry, receipt)
        if case["recorded_disposition"] not in ("CLOSED_INCOMPLETE", "CLOSED_UNSUCCESSFUL"):
            _bad("unknown recorded disposition")
        expected_vis = ("UNSIGNED_SYNTHETIC_DEMO_ONLY" if status == "SYNTHETIC_DEMONSTRATION"
                        else "SIGNED_SYNTHETIC_TEST_ONLY" if status == "SYNTHETIC_SIGNED_DEMONSTRATION"
                        else "HISTORICAL_SIGNED_INTAKE_ONLY")
        if case["evidence_visibility"] != expected_vis:
            _bad("inconsistent case provenance visibility")
        if status in ("SYNTHETIC_DEMONSTRATION", "SYNTHETIC_SIGNED_DEMONSTRATION") and not eid.startswith("SYNTHETIC-"):
            _bad("synthetic report contains non-synthetic ID")
        states[eid] = _outcomes(case)
        if ("FAIL" in states[eid].values()
                and case["recorded_disposition"] != "CLOSED_UNSUCCESSFUL"):
            _bad("failed procedure cannot claim merely incomplete closure")
        criteria_count += sum(len(x["criteria_evidence"]) for x in case["procedure_outcomes"])
        actual_gaps = case["evidence_visibility_gaps"]
        if type(actual_gaps) is not list:
            _bad("invalid gaps")
        gaps = {x["procedure"]: x for x in actual_gaps
                if type(x) is dict and type(x.get("procedure")) is str}
        if len(gaps) != len(actual_gaps):
            _bad("duplicate/invalid gap")
        expected_gaps = {x["procedure"] for x in case["procedure_outcomes"]
                         if x["recorded_status"] in ("NOT_EVALUABLE", "UNOBSERVED")}
        if set(gaps) != expected_gaps:
            _bad("gap set disagrees with missing outcomes")
        for row in case["procedure_outcomes"]:
            gap = gaps.get(row["procedure"])
            if gap is None:
                continue
            _strict_keys(gap, {"procedure", "recorded_status", "basis",
                               "reason_sha256", "focus_entry_sha256"}, "gap")
            if (gap["recorded_status"] != row["recorded_status"]
                    or gap["focus_entry_sha256"] != entry
                    or gap["basis"] != ("OPERATOR_DECLARED" if row["expected_by_operator"]
                                        else "HISTORY_OBSERVED")
                    or gap["reason_sha256"] != row["not_evaluable_reason_sha256"]):
                _bad("gap evidence contradiction")
        gaps_count += len(gaps)
    if sorted(identities) != [c["experiment_id"] for c in report["cases"]]:
        _bad("nondeterministic case ordering")
    proc_sets = [set(x) for x in states.values()]
    if any(s != proc_sets[0] for s in proc_sets):
        _bad("missing per-case procedure coverage")
    entries = [{"experiment_id": eid, "entry_sha256": ent, "receipt_sha256": rec}
               for eid, ent, rec in (identities[eid] for eid in sorted(identities))]
    digest = hashlib.sha256(canonical_json({"entries": entries}).encode()).hexdigest()
    if report["snapshot_sha256"] != digest:
        _bad("memory identity snapshot mismatch")
    similar_count = 0
    for case in report["cases"]:
        similar_count += _similarity(case, identities, states)

    cov = report["procedure_coverage"]
    if len(cov) != len(proc_sets[0]):
        _bad("incomplete cohort coverage table")
    found = set()
    for row in cov:
        if (type(row) is not dict or row.get("procedure") not in proc_sets[0]
                or row["procedure"] in found):
            _bad("invalid or repeated coverage procedure")
        proc = row["procedure"]
        found.add(proc)
        counts = Counter(states[eid][proc] for eid in identities)
        for key, kind in (("failed_experiments", "FAIL"), ("passed_experiments", "PASS"),
                          ("not_evaluable_experiments", "NOT_EVALUABLE"),
                          ("unobserved_experiments", "UNOBSERVED")):
            if type(row.get(key)) is not int or row[key] != counts[kind]:
                _bad("coverage count disagrees with cases")
        if set(row) != {"procedure", "failed_experiments", "passed_experiments",
                        "not_evaluable_experiments", "unobserved_experiments",
                        "failure_evidence", "not_evaluable_evidence"}:
            _bad("unexpected coverage fields")
        for key, kind in (("failure_evidence", "FAIL"), ("not_evaluable_evidence", "NOT_EVALUABLE")):
            evidence = row[key]
            if type(evidence) is not list:
                _bad("invalid coverage evidence")
            target = sorted(eid for eid in identities if states[eid][proc] == kind)
            actual = []
            for ref in evidence:
                eid, ent, _ = _identity(ref, receipt=False)
                if eid not in identities or identities[eid][1] != ent:
                    _bad("unbound coverage evidence")
                actual.append(eid)
            if sorted(actual) != target or len(actual) != len(set(actual)):
                _bad("coverage evidence disagrees with outcomes")
    if found != proc_sets[0]:
        _bad("coverage omissions")

    topics = report["review_topics"]
    if len(topics) > 12:
        _bad("unbounded advisor topics")
    seen, citations = set(), 0
    for item in topics:
        _strict_keys(item, {"item_id", "kind", "procedure", "reason",
                            "question_for_new_experiment", "evidence_sample",
                            "evidence_sample_truncated", "evidence_visibility",
                            "interpretation"}, "advisory topic")
        iid = item["item_id"]
        if (type(iid) is not str or not _ITEM.fullmatch(iid) or iid in seen
                or item["kind"] not in _TOPIC_KIND
                or item["procedure"] not in proc_sets[0]
                or not _text(item["question_for_new_experiment"])
                or not _text(item["reason"])
                or type(item["evidence_sample_truncated"]) is not bool
                or item["interpretation"] != "DESCRIPTIVE_NOT_CAUSAL"):
            _bad("invalid advisory topic")
        seen.add(iid)
        visibility = ("UNSIGNED_SYNTHETIC_DEMO_ONLY" if status == "SYNTHETIC_DEMONSTRATION"
                      else "SIGNED_SYNTHETIC_TEST_ONLY" if status == "SYNTHETIC_SIGNED_DEMONSTRATION"
                      else "HISTORICAL_RECEIPT_NOT_CURRENT_EXPORT_PERMISSION")
        if item["evidence_visibility"] != visibility:
            _bad("topic provenance visibility mismatch")
        refs = item["evidence_sample"]
        if type(refs) is not list or len(refs) > 8:
            _bad("unbounded topic citations")
        used = set()
        for ref in refs:
            _strict_keys(ref, {"experiment_id", "entry_sha256", "receipt_sha256"},
                         "topic citation")
            eid, ent, rec = _identity(ref)
            if eid in used or identities.get(eid) != (eid, ent, rec):
                _bad("unbound or duplicated topic citation")
            status_at_source = states[eid][item["procedure"]]
            if status_at_source not in ("FAIL", "NOT_EVALUABLE"):
                _bad("topic citation not supported by recorded negative evidence")
            used.add(eid)
            citations += 1
        if item["kind"] in ("REPEATED_FAILURE", "REPEATED_NOT_EVALUABLE") and not refs:
            _bad("repeated negative topic lacks evidence")
    result = {
        "status": "LOCAL_SEMANTIC_CONSISTENCY_PASS",
        "checked_cases": len(identities),
        "checked_procedures": len(proc_sets[0]),
        "checked_criteria": criteria_count,
        "checked_gaps": gaps_count,
        "checked_citations": citations,
        "checked_similar_cases": similar_count,
        "report_sha256": report["report_sha256"],
        "source_authenticated": False,
        "scientific_authority": False,
        "broker_authority": False,
    }
    return result
