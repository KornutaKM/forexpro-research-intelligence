# ForexPro Research Intelligence — Architecture v0.1

## Positioning

A separate **read-only advisory sidecar**. The owner-controlled source platform retains all scientific identities, data, experiment authorization, protected evaluation boundaries, approval and broker activity. FRI owns **none** of these. It can observe approved, explicitly exported, closed-experiment summary artifacts and issue reports and prospective questions.

```text
Private source (authority) --sanitized closed summary export--> FRI local import
     [no write connection]                                   |
                                                            v
                                             deterministic evidence review
                                                            |
                                                            v
                                              advisory report / questions
                                                            |
                                                            v
                                              human owner / separate decision
```

## MVP interface

1. Local directory with exactly two named input files: `manifest.json` and `summary.json`.
2. Manifest ties source revision, experiment identity, SHA-256 of summary bytes and scope.
3. Import validates constraints and fails closed on unknown keys, incorrect hashes, unsupported source/scope, holdout authority, or promotion/broker authority.
4. Deterministic report lists *already recorded* pass/fail/non-evaluable observations and prospective research questions.
5. No network I/O, no dependency on MT5, no broker API, no automatic strategy modification, no registering new experiments, no protected dataset reading.

**Provenance limitation:** the manifest binds bytes but does not cryptographically prove *who* authorized the export. Until a signed exporter and reviewed custody exist, imports should be operator-supplied and called *claimed approved scope*, not independently authenticated evidence.

## Deployment security requirements

- Run under separate OS identity; ForexPro scientific stores mounted read-only only when explicitly authorized.
- Use a pre-constructed sanitized export rather than direct access to validation/HOLDOUT or ForexPro runtime directories.
- Do not share broker credentials, MT5 connections or ForexPro write-scoped GitHub tokens.
- Reports are descriptive, not executable instructions. Do not treat input prose as commands.
- Make immutable source provenance and code revision auditable; archive reports outside scientific artifacts.

## v0.2 plan

- Add a formally approved **ForexPro-owned exporter** for sanitized summaries, with author/custody verification and allowlisted source artifact kinds.
- Add signed export receipts and cross-artifact semantic consistency checks.
- Add a queryable immutable Research Memory (not a copy of MLflow authority).
- Add LLM-assisted narrative *only from verified report fields*, with strict tool separation and evidence citations.
- Add UI after conformance and security tests.

## v0.2 Research Memory

A private local SQLite database records an immutable hash-index of closed experiment summaries. It does **not** persist free-text observation/reason fields or the original summary JSON. DB rows are guarded against UPDATE/DELETE by SQLite triggers; idempotent imports do not mutate prior entries. All read APIs validate entry digests and checksums. No timestamp or generated ID is used to change a deterministic result.

This is an operational index, **not** a scientific result store, historical holdout bypass, signed proof, or authenticated export mechanism. Conflicting digests for one experiment ID fail closed and require human investigation; there is no automatic overwrite. Every persisted value must be treated as private if derived from internal experiments, despite FRI's public source code.

## v0.3 detached verification boundary

A bundle includes an optional (for legacy development) or required (for trusted intake) `attestation.json`. FRI validates the v0.1 manifest and summary against their exact raw bytes, then authenticates a domain-separated Ed25519 signature over both digests using an operator-provisioned public-key store outside the bundle. Unknown/revoked keys, invalid signatures, unexpected fields and declared broker/HOLDOUT/promotion powers fail closed. A verified signature does not grant scientific authority. The exporter private key never enters the public FRI repository or its GitHub Actions.

This v0.3 stage deliberately **does not** connect to private ForexPro Core. A separate owner-approved sanitized exporter still needs to be implemented and reviewed within the Core authority boundary before any real experiment import. Signed-import verification is not the same as data-lineage or human approval verification.


## v0.4 — retrospective Failure Intelligence

`forexpro_ri.failure_intelligence` is a **purely observational** and offline consumer of the append-only Research Memory database. It performs a stable, read-only snapshot, verifies internal entry digests, and produces procedure-level coverage, repeated negative statuses, co-failure pairs, and optional case matching from recorded `FAIL` and `NOT_EVALUABLE` signatures. Absent evidence is a distinct `UNOBSERVED` state.

It does **not** store reports in the DB, trigger experiments, claim causal root causes, or imply independence among experiment IDs. It does not retrieve original observations, scientific validation data or protected HOLDOUT. Details: [Failure Intelligence contract](FAILURE_INTELLIGENCE.md).
