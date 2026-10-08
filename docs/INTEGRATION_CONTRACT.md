# v0.1 Bundle contract

Only input files: `manifest.json`, `summary.json`. All metadata is declared by the exporter, with raw `summary.json` bytes bound to `manifest.summary_sha256`.

`manifest.json`: `schema_version=1`, `export_kind="CLOSED_EXPERIMENT_SUMMARY"`, `source_system="forexpro"`, `experiment_id`, `source_revision` (40 lowercase hex), `summary_sha256` (64 lowercase hex), `approved_scope="READ_ONLY_ADVISORY"`, `holdout_access=false`, `promotion_authority=false`, `broker_authority=false`.

`summary.json`: `experiment_id`, `disposition` (`CLOSED_UNSUCCESSFUL` or `CLOSED_INCOMPLETE`), `criteria` (each: `criterion_id`, `procedure`, `verdict` PASS/FAIL, `observation`), `not_evaluable` (each: `procedure`, `reason`). Fields are **recorded inputs** and must be reproduced faithfully, not interpreted as independently established scientific evidence.

These simple v0.1 contracts are not substitutes for `ExperimentContract`, `ValidationEvidence`, `TrialLedger`, or any source platform scientific authority artifacts. The sample is **SYNTHETIC** and must never be used for promotion.

The v0.1 procedure allowlist is `OUT_OF_SAMPLE`, `COST_STRESS`, `PARAMETER_STABILITY`, `MONTE_CARLO`, `WALK_FORWARD`, `REGIME_STABILITY`, `DETERMINISTIC_RERUN`, `RISK_LIMITS`, `SAMPLE_SUFFICIENCY`, `MULTIPLE_TESTING`. Unknown names (including HOLDOUT) are rejected until the contract is reviewed. **This is not a content-level DLP control**: operators must sanitize `observation` and `reason` fields before exporting.

## Local memory indexing (v0.2)

The import contract is unchanged from v0.1. The local Research Memory rejects a summary if the same procedure appears both as a recorded verdict and as not evaluable. Successful import produces a stable entry SHA-256 over minimal normalized identity + procedure/verdict + text-hash fields. Text is not stored. Reimport of the same export is a no-op; a different summary digest for the same experiment ID is a conflict. Memory can be destroyed and rebuilt from privately retained, appropriately approved exports. Never assume a locally calculated digest provides export authorization.


## v0.3 authenticated adapter

For signed imports, add `attestation.json` and provide the separate local `trusted-keys.json`. See [Signed export protocol](SIGNED_EXPORT_PROTOCOL.md). The existing source-manifest schema and protected scientific data boundaries remain unchanged. A cryptographically valid signed envelope does not make unsupported claims scientifically correct.
