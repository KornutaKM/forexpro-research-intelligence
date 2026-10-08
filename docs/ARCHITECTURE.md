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
