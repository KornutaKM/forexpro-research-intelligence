# Failure Intelligence v0.4 — evidence interpretation contract

## Input boundary

- Accept only the existing *local*, already validated Research Memory v0.2 SQLite store. No direct ForexPro connection or exported data is read by this module.
- The source store contains immutable, hash-indexed records of explicitly *closed* unsuccessful/incomplete research; no free-text observations, metrics, positions or HOLDOUT bytes.
- Every entry is checked against the stored entry SHA-256 before use; SQLite internal consistency and foreign-key checks run before analysis.
- Input is an operator-selected collection. Signed exporter verification at the time of ingest is **not proven by this memory schema**. Stored SHA-256 values support accidental tamper detection, not resistance to an attacker who can rewrite the DB and recompute hashes.

## Deterministic outcome semantics

For every `(experiment_id, procedure)` pair:

1. `FAIL` if at least one recorded criterion for this procedure is `FAIL`, even if another is `PASS`.
2. Otherwise `PASS` if at least one recorded criterion is `PASS`.
3. `NOT_EVALUABLE` if separately listed in the unassessable procedures; overlap with recorded criteria is rejected by the ingest boundary.
4. `UNOBSERVED` if absent from the exported closed-experiment summary. Never count unobserved as PASS, FAIL or NOT_EVALUABLE.

**Unit of counting:** one experiment ID per procedure, not the number of criteria. Do not treat two experiment IDs as statistically independent without separate lineage evidence.

## Reports

`memory intelligence --db <local.sqlite> [--min-support 2] [--focus <experiment_id>]`

The report includes:

- `memory_snapshot_sha256`: stable SHA-256 over sorted source entry identity+digest references;
- `procedure_coverage`: complete counts of FAIL/PASS/NOT_EVALUABLE/UNOBSERVED across stored cases and source evidence for negative statuses;
- `recurring_observations`: procedures with at least `min_support` distinct failed or not-evaluable experiment IDs, plus *prospective* research questions;
- `co_failure_patterns`: pairs of different failed procedures observed in at least `min_support` experiment IDs;
- `focus`: optional list of up to 10 closest other cases with shared negative procedure/status signatures and exact overlap numerator/denominator; ties sort lexicographically by experiment ID;
- `report_sha256`: canonical hash of the report before inserting this property.

The report is read-only, stable across import order and has no dependencies on input wall-clock time. All evidence references are private-local experiment IDs and immutable entry SHA-256 digests; **do not publish the resulting JSON for actual studies**.

## What the report does NOT establish

- Why a failure occurred, or whether an intervention will address it;
- statistical significance, predictive ability, strategy profitability, independent replications or candidate quality;
- scientific authority, permission to rerun a closed experiment, access to PROJECT VALIDATION/HOLDOUT, or authorization to place broker orders;
- provenance authentication: v0.2 memory lacks persisted signature receipts, even though v0.3 verifies signed bundles at intake.

A future exporter/schema migration may permit stricter evidence-chain verification, with explicit owner authorization and privacy controls. That change is outside v0.4.
