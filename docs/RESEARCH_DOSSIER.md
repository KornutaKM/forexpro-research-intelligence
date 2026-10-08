# Research Dossier v0.7: scope, semantics and evidence boundaries

The FRI Research Dossier is a **single-snapshot, deterministic, offline, read-only advisory** assembled from the minimal local Research Memory database. It consolidates a closed experiment's recorded outcomes, evidence-visibility gaps, analogues and prospective research questions. It does **not** load source bundles, raw observations, strategy metrics or broker data.

## Workflow

```bash
mkdir -p local_data
python -m forexpro_ri.cli memory ingest examples/closed_synthetic --db local_data/demo.sqlite --unsigned-synthetic
python -m forexpro_ri.cli memory ingest examples/closed_synthetic_peer --db local_data/demo.sqlite --unsigned-synthetic
python -m forexpro_ri.cli memory dossier --db local_data/demo.sqlite --focus SYNTHETIC-001 --expected-procedure MONTE_CARLO --format markdown
```

For production usage, ingest only separately approved and signed exports into a private Research Memory database. The synthetic-only bypass is **never** permission to import unsigned real research. Never run a private database in public CI or commit reports, even though observation text is absent: experiment IDs and digests can reveal research metadata.

## Data contract

- `schema_version=1`, `report_kind=NON_AUTHORITATIVE_RESEARCH_DOSSIER`.
- `focus_experiment`: entry and summary SHA-256, source revision, recorded disposition and recorded criterion counts.
- `procedure_outcomes`: exactly one row per procedure recorded in history or explicitly supplied by an operator. Precedence: any `FAIL` criterion -> `FAIL`; else any `PASS` -> `PASS`; separate `NOT_EVALUABLE`; missing -> `UNOBSERVED`. Hashes of stored per-criterion observations or non-evaluable reasons are cited, never their original text.
- `evidence_visibility_gaps`: non-evaluable or unobserved procedures for the focus experiment, distinguishing `OPERATOR_DECLARED` from `HISTORY_OBSERVED`. Neither source asserts a scientific ValidationContract.
- `similar_observed_cases`: up to ten other cases sharing negative `(procedure, status)` signatures, ranked by exact Jaccard intersection/union and stable experiment ID tie-breaks. It is *not* evidence of causal or scientific similarity.
- `recurring_negative_observations`: signatures of the focus experiment with at least `min_support` distinct stored experiment IDs; support includes focus and is not a count of criteria or independent replications. `other_experiments` excludes focus.
- `prospective_research_questions`: fixed, code-reviewed questions for **new** preregistered experiments only.
- `memory_snapshot_sha256`: digest over all sorted `(experiment_id, entry_sha256)` references, from one SQLite read transaction. `report_sha256`: canonical JSON content digest excluding the digest field itself.
- All scientific/broker/holdout authority flags are `false` and source authenticity is `NOT_ESTABLISHED_FROM_MEMORY`.

## Security and scientific limits

The implementation verifies SQLite integrity, foreign keys, and **every** stored entry's self-consistency before reporting, within the **same read transaction** used to derive all sections. It caps historical experiment count at 5,000 and analogues at ten. An operator's expected procedures are checked against the reviewed allowlist and are not a validated study battery. The report does not infer missing experimental outcomes, causal explanations, model superiority, trading profits, independence or original exporter authorization. Research Memory v0.2 does not persist the exporter's signature, even if a signed bundle was verified at ingest time.

No ForexPro Core code or private scientific artifacts are needed for this release.
