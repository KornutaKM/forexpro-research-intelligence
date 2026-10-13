# Advisor omission benchmark and human-evidence reconciliation

Status: FRI issue #19, Draft PR #20. Public synthetic engineering
qualification ONLY. No independently blind-curated answers, real approved
Core research, export permission or scientific authority are asserted.

## 1. Measure missing questions, not just displayed answers

The previous Advisor rubric evaluates displayed questions for grounding,
usefulness and language. It cannot detect questions Advisor forgot.
The new review recall benchmark evaluates one expected question presence
per procedure against a separately stored scenario-designed label file.

Labels: SHOULD_REVIEW, SHOULD_NOT_REVIEW, CANNOT_DETERMINE.

    python -m forexpro_ri.cli review cohort-demo --out local_data/recall-pack
    python -m forexpro_ri.cli review recall \
      --dir local_data/recall-pack \
      --labels examples/review_question_recall_gold.json

The bundled truth table has six synthetic positive procedures and four
negative procedures. It was designed from the same scenario catalog.
It has NOT been blind-curated or independently validated by humans.

The output enumerates true-positive, false-positive, false-negative,
true-negative and uncertain labels; exact numerators/denominators for
precision, recall and false-positive rate; and possible duplicate question
IDs. With a zero denominator, ratios are null, not a guessed perfect score.
Uncertain labels are excluded from the confusion matrix, not silently
counted as passes. Missing or extra questions require further review.

This is PROCEDURE-LEVEL question coverage only. It does not assess exact
scientific hypothesis wording, multiple distinct questions within a single
procedure, global novelty, causal inference or independent replication.
An external blind benchmark is required for such product-quality claims.

## 2. Compare discussion decisions with evidence-quality concerns

A human can mark a question ACCEPT_FOR_DISCUSSION while their separate
rubric flags weak/unknown grounding, unsafe scientific language, dubious
usefulness or potential duplication. Reconcile the two private, SHA-bound
sidecars against the SAME original report:

    python -m forexpro_ri.cli review reconcile-human \
      --dir local_data/recall-pack \
      --decisions local_data/human-decisions-reviewed.json \
      --rubric local_data/human-rubric-reviewed.json \
      --out local_data/human-evidence-conflicts.json

The output reports exact Advisor item IDs and fixed conflict reason codes.
It does not execute any automatic approval/veto, preregister experiments,
permit scientific promotion, write to ForexPro Core or access broker state.
No recorded conflict is not proof of scientific correctness; self-reported
sidecars are not proof of reviewer identity or independent human oversight.

## 3. Qualification and remaining gates

Adversarial tests cover wrong source provenance, missing questions, extra
questions, uncertain labels, zero denominators, forged source pack,
tampered JSON, stale reviewer digests, unreviewed accepted proposals and
attempted write-back into the protected report directory.

Public-safe CI uses synthetic signed source material only. To establish
product usefulness, preregister real (or approved independent synthetic)
human-defined target questions without seeing Advisor output, use blind
assessors and verify every actual error denominator. Real exports from Core
remain BLOCKED pending the independent source owner decision in issue #19.
