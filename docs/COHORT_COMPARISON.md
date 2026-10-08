# FRI v0.6 — Cohort comparison and evidence-visibility contract

## Purpose

Provide an auditable, deterministic **descriptive** comparison of 2–50
previously imported, closed research experiments. This is *not* an optimizer,
protocol validation, trading decision, profitability comparison, or scientific
promotion mechanism.

## CLI

```bash
python -m forexpro_ri.cli memory compare --db local_data/demo.sqlite \
  --experiment SYNTHETIC-001 --experiment SYNTHETIC-002 \
  --expected-procedure REGIME_STABILITY --format markdown
```

The operator must explicitly choose 2–50 distinct experiment IDs. The optional
`--expected-procedure` flag may be repeated and is limited to the established
FRI procedure allowlist. These expectations are local user inputs, *not* evidence
that the procedures were required under an authoritative ForexPro ValidationContract.
This CLI never accesses ForexPro Core or its private repositories.

## Recorded states

- `FAIL`: one or more saved criteria for a procedure failed, even if other
  criteria for that procedure passed.
- `PASS`: one or more saved criteria passed and none of its saved criteria failed.
- `NOT_EVALUABLE`: saved explicit non-evaluability record, with a reason hash.
- `UNOBSERVED`: no saved result for this procedure and experiment. It is
  **not** a failure, success, skipped check or proof the test was required.

A procedure appears in the comparison if it was observed in at least one
selected experiment, or if it was explicitly declared expected by the operator.
`evidence_gaps` list `NOT_EVALUABLE` and `UNOBSERVED` separately and describe
whether the procedure was operator-expected or only encountered in the cohort.
These are *visibility gaps*, not failed scientific acceptance criteria.

## Integrity and evidence linking

The module uses one SQLite read snapshot, checks SQLite integrity and foreign
keys, and verifies every stored immutable entry before generating a report. It
includes `experiment_id`, `source_revision`, `summary_sha256` and
`entry_sha256` for selected experiments. Criterion references contain
`criterion_id` and the observation SHA-256, **not** free-text observations.
The report and selection digest are SHA-256 over canonical JSON and independent
of database file path, experiment input order and ingestion order.

The source exporter's signature status is **not retained** in the current
Research Memory schema. Reports explicitly state
`source_authenticity=NOT_ESTABLISHED_FROM_MEMORY`; neither stored hashes
nor this comparison constitute proof of authorized scientific export.

## Safety boundaries

- Results cannot approve a candidate, promote a state or edit existing science.
- Results cannot read HOLDOUT, raw market data, order state or broker credentials.
- Scientific independence and cross-experiment protocol/data comparability are
  **unknown**. Do not compute pooled success rates from this operator-selected set.
- Similar statuses and missing evidence are not mechanisms or causes.
- Generated JSON/Markdown can reveal source identifiers; save reports only in
  access-restricted locations and never publish real experiment output in CI.
- Only synthetic fixtures run in public GitHub Actions.

## Rollout

Current implementation is intentionally useful **without** any changes to
ForexPro Core while that private system remains under development. A future
integration may enrich the memory contract with independently reviewed lineage
and validation-plan identities, but must not reinterpret the present reports as
scientific evidence.
