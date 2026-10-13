# FRI — Human-curated Advisor rubric and planned paired study

Status: Issue #19 P2, implemented with synthetic-only CI in Draft PR #20.
No owner-approved Core export, independent human curator validation or real
operator time improvement is established by these tools.

## 1. Local privacy and file integrity

Research Review CLI now uses bounded, no-follow reads for pack JSON/HTML,
reviewer labels and timing inputs. It rejects symbolic links, hardlinks,
nonregular files, empty/oversized inputs, duplicated JSON object keys,
non-finite JSON constants, invalid UTF-8 and files changing mid-read.
JSON limit is 16 MiB, HTML limit is 32 MiB. New output artifacts are
creation-only with restricted file permissions.

This is not a sandbox against privileged replacement of parent directories.
Use trusted restricted local folders. A valid content hash does not establish
an authorized source export, live key status or scientific truth.

## 2. Expert rubric for displayed Advisor questions

The existing human decision tool records discussion acceptance, deferral or
rejection. The new rubric evaluates four different dimensions separately:

| Dimension | Allowed judgments |
| --- | --- |
| grounding | SUPPORTED_BY_RECORDED_EVIDENCE, UNSUPPORTED_BY_RECORDED_EVIDENCE, CANNOT_DETERMINE |
| usefulness | USEFUL_RESEARCH_QUESTION, NOT_USEFUL, CANNOT_DETERMINE |
| duplication | POTENTIALLY_DUPLICATIVE, NOT_IDENTIFIED_IN_REVIEWED_CORPUS, CANNOT_DETERMINE |
| scientific_language | BOUNDED_ADVISORY_ONLY, UNSUPPORTED_AUTHORITY_OR_CAUSAL_CLAIM, CANNOT_DETERMINE |

Every field starts at UNREVIEWED; no generated model opinion is allowed to
fill human labels. Non-duplication in the reviewed corpus is not proof of
global novelty or independent scientific replication.

Prepare one signed synthetic pack and two separate private templates:

    python -m forexpro_ri.cli review cohort-demo --out local_data/pack-for-study
    python -m forexpro_ri.cli review rubric-template \
      --dir local_data/pack-for-study --out local_data/reviewer-a-input.json
    python -m forexpro_ri.cli review rubric-template \
      --dir local_data/pack-for-study --out local_data/reviewer-b-input.json

After actual human editing of all enumerated categories, validate both:

    python -m forexpro_ri.cli review rubric-score \
      --dir local_data/pack-for-study \
      --input local_data/reviewer-a-input.json \
      --out local_data/reviewer-a-assessed.json
    python -m forexpro_ri.cli review rubric-score \
      --dir local_data/pack-for-study \
      --input local_data/reviewer-b-input.json \
      --out local_data/reviewer-b-assessed.json
    python -m forexpro_ri.cli review rubric-compare \
      --dir local_data/pack-for-study \
      --left local_data/reviewer-a-assessed.json \
      --right local_data/reviewer-b-assessed.json \
      --out local_data/reviewer-differences.json

All question IDs must match the source report exactly. The assessment counts
labeled and unresolved questions, potentially unsupported evidence,
duplication concerns and unsupported scientific language. Comparison exposes
categorical disagreements but DOES NOT verify reviewer identity or whether
two humans are independently involved. Identical assessment documents are
rejected as proof of two separate reviews. Human adjudication remains required.

This checks displayed Advisor suggestions, not useful questions missed
entirely by the Advisor. Full recall still requires an independent human
benchmark. Even favorable labels do not authorize Core operations.

## 3. Reproducible paired time-study allocation

A task plan uses an exact report SHA-256 plus 20–100 pseudonymous task IDs to
counterbalance MANUAL_FIRST and FRI_FIRST orders. This deterministic algorithm
is NOT unpredictable randomization or blinding.

    python -m forexpro_ri.cli review study-plan \
      --dir local_data/pack-for-study --tasks 20 \
      --out local_data/study-locked-plan.json

Privately preregister task difficulty, accuracy rubric, evidence access,
reviewer instructions, and order BEFORE any measurement. Do not store task
text, personal information, source data or strategies in machine inputs.

Measurements use the existing bounded paired study schema: task_id, order,
positive manual_seconds and fri_seconds, correctness booleans for answers and
citations, and independent-replication-error booleans. Only CURATED_SYNTHETIC_ONLY
or SELF_REPORTED_PRIVATE_OPERATOR source classes are supported.

    python -m forexpro_ri.cli review study-reconcile \
      --dir local_data/pack-for-study \
      --plan local_data/study-locked-plan.json \
      --input local_data/private-study-times.json \
      --out local_data/private-study-reconciliation.json

The scorer rejects changed registered task order, missing/extra IDs,
duplicate tasks, invalid measurements, altered plan SHA, and any other
unregistered task assignment. It reports descriptive paired time ratios
with correctness checks. It DOES NOT independently establish causal benefit,
researcher identity, scientific approval, quality noninferiority or 100x
real-world acceleration.

## 4. Limits and next review

CI uses ONLY signed synthetic test fixtures. Separate externally supervised
expert evaluation is needed to validate human assessments; users must also
show question recall, independent curator custody, task equivalence and
honest reporting of every error and denominator. Cross-project Core exporter
authorization remains blocked pending the source-owner governance in #19.
