"""Operator-question recall and over-suggestion audit from externally supplied labels.

Gold labels must be prepared independently of the Advisor output for real
studies. The bundled example is deliberately SCENARIO_DESIGNED_SYNTHETIC,
not blind/human-validated. This module cannot establish scientific truth.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from .analysis import canonical_json
from .contracts import EvidenceError, _ALLOWED_PROCEDURES
from .review_pack import verify_review_pack

_LABELS = {"SHOULD_REVIEW", "SHOULD_NOT_REVIEW", "CANNOT_DETERMINE"}
_MAX_TOPICS = 12


def _ratio(n: int, d: int) -> dict[str, int | None]:
    return {"numerator": n, "denominator": d, "value": round(n / d, 6) if d else None}


def evaluate_advisor_recall(pack: dict[str, Any], gold: dict[str, Any]) -> dict[str, Any]:
    """Score question coverage vs operator-supplied question-level gold labels.

    Uncertain labels are excluded from TP/FP/FN/TN denominators but counted.
    A positive target with no Advisor question is explicitly a false negative.
    At most one item per procedure is scored as a distinct question for the
    current fixed-vocabulary Advisor; extra items are flagged as duplicates.
    """
    verify_review_pack(pack)
    if pack["status"] not in ("SYNTHETIC_SIGNED_DEMONSTRATION", "SYNTHETIC_DEMONSTRATION"):
        raise EvidenceError("question recall is synthetic-only pending authorized external review")
    if (type(gold) is not dict or set(gold) != {
            "schema_version", "source_class", "label_provenance",
            "eligible_procedures", "targets",
        } or type(gold["schema_version"]) is not int or gold["schema_version"] != 1
            or gold["source_class"] != "CURATED_SYNTHETIC_ONLY"
            or gold["label_provenance"] != "SCENARIO_DESIGNED_NOT_BLINDLY_VALIDATED"):
        raise EvidenceError("gold labels must disclose synthetic non-independent provenance")
    eligible = gold["eligible_procedures"]
    if (type(eligible) is not list or not 1 <= len(eligible) <= len(_ALLOWED_PROCEDURES)
            or any(type(p) is not str or p not in _ALLOWED_PROCEDURES for p in eligible)
            or len(eligible) != len(set(eligible)) or eligible != sorted(eligible)):
        raise EvidenceError("invalid sorted eligible procedures")
    targets = gold["targets"]
    if type(targets) is not list or len(targets) != len(eligible):
        raise EvidenceError("exactly one curator target per eligible procedure is required")
    by_proc = {}
    for target in targets:
        if type(target) is not dict or set(target) != {"procedure", "label"}:
            raise EvidenceError("invalid target shape")
        p, label = target["procedure"], target["label"]
        if (type(p) is not str or p in by_proc or p not in eligible
                or type(label) is not str or label not in _LABELS):
            raise EvidenceError("invalid/duplicate target or unrecognized label")
        by_proc[p] = label
    if set(by_proc) != set(eligible):
        raise EvidenceError("missing target procedures")
    observed: dict[str, list[str]] = {}
    for topic in pack["review_topics"]:
        proc = topic["procedure"]
        observed.setdefault(proc, []).append(topic["item_id"])
    if any(proc not in eligible for proc in observed):
        raise EvidenceError("benchmark scope excludes displayed advisor proposals")
    tp = fp = fn = tn = uncertain = 0
    rows = []
    for p in eligible:
        label = by_proc[p]
        items = sorted(observed.get(p, []))
        has_proposal = bool(items)
        if label == "CANNOT_DETERMINE":
            verdict = "EXCLUDED_FROM_CONFUSION_MATRIX"
            uncertain += 1
        elif label == "SHOULD_REVIEW":
            if has_proposal:
                tp += 1
                verdict = "TRUE_POSITIVE"
            else:
                fn += 1
                verdict = "FALSE_NEGATIVE_MISSED_QUESTION"
        else:
            if has_proposal:
                fp += 1
                verdict = "FALSE_POSITIVE_UNNEEDED_QUESTION"
            else:
                tn += 1
                verdict = "TRUE_NEGATIVE"
        rows.append({
            "procedure": p,
            "human_label": label,
            "observed_advisor_item_ids": items,
            "outcome": verdict,
        })
    duplicate_items = sorted({
        item for ids in observed.values() for item in ids[1:]
    })
    classification_total = tp + fp + fn + tn
    result = {
        "schema_version": 1,
        "report_kind": "SYNTHETIC_ADVISOR_QUESTION_COVERAGE_AUDIT",
        "status": ("NEEDS_REVIEW" if fp or fn or duplicate_items or uncertain
                   else "SCENARIO_LABELS_MATCH"),
        "source_pack_sha256": pack["report_sha256"],
        "gold_label_sha256": hashlib.sha256(canonical_json(gold).encode("utf-8")).hexdigest(),
        "label_provenance": gold["label_provenance"],
        "eligible_procedure_count": len(eligible),
        "observed_topic_count": len(pack["review_topics"]),
        "true_positive_procedures": tp,
        "false_positive_procedures": fp,
        "false_negative_missed_procedures": fn,
        "true_negative_procedures": tn,
        "uncertain_excluded_procedures": uncertain,
        "classification_denominator": classification_total,
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "false_positive_rate": _ratio(fp, fp + tn),
        "duplicate_advisor_item_ids": duplicate_items,
        "procedure_comparisons": rows,
        "external_human_validation_established": False,
        "novelty_or_independence_established": False,
        "scientific_authority": False,
        "broker_authority": False,
        "limitations": [
            "The sample gold labels are designed from synthetic scenarios, not blind external human judgments.",
            "A procedure-level positive match does not validate the usefulness, wording or exact kind of the question.",
            "CANNOT_DETERMINE is excluded from confusion denominators, never counted as agreement.",
            "Precision, recall and false-positive rate have null value when their denominator is zero.",
            "Duplicate items and missing questions must be adjudicated by humans outside the Core system.",
            "No actual Core exports, profits, independent replication or real time improvements are evaluated.",
        ],
    }
    result["report_sha256"] = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()
    return result
