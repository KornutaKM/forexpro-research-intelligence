# ForexPro Research Intelligence (FRI)

Public-source, offline, read-only **advisory** companion for a separately operated research platform.

**Security model:** this repository contains only generic code and explicitly synthetic fixtures. Never commit private research results, dataset files, strategy parameters, API tokens, broker data, or internal export bundles.

**Initial v0.1:** imports explicit closed-experiment summary bundles, checks SHA-256 integrity and strict authority boundaries, classifies recorded outcomes without reinterpreting them, and proposes future research *questions* without changing scientific state.

## Start locally (Python 3.12+)

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python -m forexpro_ri.cli examples/closed_synthetic
python -m forexpro_ri.cli examples/closed_synthetic --out reports/first-report.json
```

To write a file, create `reports/` first (`mkdir reports`). Reports are creation-only and never overwrite an existing file.

The example is **synthetic test evidence**, not a ForexPro production outcome. The tool makes **no** profitability claim.

## Scope and boundaries

- Does **not** fetch private ForexPro datasets, protected PROJECT VALIDATION/HOLDOUT bytes or broker state.
- Does **not** run experimental TRAIN, validation, optimization, holdout or live/demo execution.
- Does **not** create scientific approval or promotional authority.
- Does **not** duplicate MLflow, TrialLedger or ForexPro verification engines.
- Does **not** use an LLM through v0.9: classification is deterministic and based only on already recorded verdicts.
- No GitHub token required, no remote API; v0.3 uses the audited `cryptography` library for Ed25519 verification.

**Important:** v0.1 only checks internal bundle integrity and declared scope. It does not authenticate that ForexPro's scientific owner approved the export. A separately reviewed and signed ForexPro exporter is needed before treating external bundles as trusted evidence.

See [Architecture](docs/ARCHITECTURE.md) and [Integration contract](docs/INTEGRATION_CONTRACT.md).

## Rollout

1. Build/test this package independently; keep core repository unchanged.
2. Agree on a sanitized exporter contract in ForexPro Core, without opening any protected gates.
3. Validate compatibility with an explicitly approved *closed* experiment summary export.
4. Extend deterministic diagnostics and research memory before considering an LLM and UI.

## Publication and licensing

Public visibility does not grant permission to reuse the source. No open-source license has been selected by the repository owner. Choose a license explicitly before describing this repository as open source.

Keep all real data and generated reports in private storage. Run FRI offline, not in public CI, when analyzing any actual research bundle.

## Local Research Memory (v0.2)

FRI can retain a minimal, append-only index of explicitly imported **closed** experiments in a private local SQLite database. It stores only experiment IDs, revision/digest references, procedure names, recorded verdicts, and SHA-256 digests of free-text observations. It **does not store the raw observations, broker data or source bundles**. The SQLite file is local private runtime state and must never be committed or uploaded to public GitHub Actions.

```bash
# Offline example, using only synthetic data:
mkdir -p local_data
python -m forexpro_ri.cli memory ingest examples/closed_synthetic --db local_data/research.sqlite --unsigned-synthetic
python -m forexpro_ri.cli memory history --db local_data/research.sqlite
python -m forexpro_ri.cli memory patterns --db local_data/research.sqlite
python -m forexpro_ri.cli memory verify --db local_data/research.sqlite
```

Re-importing identical bytes is idempotent. Conflicting exports for an existing experiment ID are rejected instead of replacing history. `memory patterns` counts affected **experiments** per recorded procedure, not the number of individual failing criteria; it does not infer causal relationships or prove profitability. `memory verify` checks database consistency and entry digests, **not exporter identity or authenticity**. From v0.9 onward Research Memory stores an immutable digest-linked **historical intake receipt** recording whether a signature was verified. It never retains the signature or raw export; previous v1 records are conservatively marked `LEGACY_UNATTESTED` after migration. SHA-256 alone is not an authentication signature; an adversary with DB write access can bypass local protections. Keep the database on a trusted, access-restricted machine.

## Signed evidence intake (v0.3)

**FRI verifies, but does not create, detached Ed25519 signatures.** Public CI never receives private signing keys, real evidence or a trust store containing production identities. Signing happens exclusively in a separately reviewed private-source exporter, and a trusted public-key store must be provisioned by an operator **outside** the input bundle. A signature proves possession of the matching private key; FRI does not independently prove the scientific approval or quality of the exported findings.

```bash
# The owner provisions approved_public_keys.json privately on the FRI host.
python -m forexpro_ri.cli verify-export /private/approved-closed-bundle --trust-store /private/approved_public_keys.json
python -m forexpro_ri.cli /private/approved-closed-bundle --trust-store /private/approved_public_keys.json --out /private/reports/report.json
python -m forexpro_ri.cli memory ingest /private/approved-closed-bundle --db /private/local_data/research.sqlite --trust-store /private/approved_public_keys.json
```

The first command does not write any file. The actual report and database remain entirely local. FRI never requests ForexPro GitHub access, broker credentials or protected HOLDOUT access. `memory ingest` and the Python `ingest` API **require** a trusted key store by default; explicit `--unsigned-synthetic` / `allow_unsigned_synthetic=True` is allowed only for labeled synthetic fixtures. Text labeling is not a data-loss-prevention guarantee. The v0.1 standalone analysis CLI still supports unsigned analysis with `export_authenticity=NOT_VERIFIED`, so never treat that legacy output as trusted.

The `attestation.json` signature covers exact SHA-256 hashes of both raw manifest and summary bytes. The signing protocol, trust-store schema and key rotation/revocation semantics are specified in [Signed export protocol](docs/SIGNED_EXPORT_PROTOCOL.md). **No real ForexPro exports have yet been authenticated.** No code in the private ForexPro repository has been modified.


## Failure Intelligence (v0.4)

Build a deterministic, read-only diagnostic across **closed experiments already ingested** into local Research Memory. Use the private local database; never run this command on the public GitHub runner using real results.

```bash
# First ingest the synthetic example as in the v0.2 section.
python -m forexpro_ri.cli memory intelligence --db local_data/research.sqlite
python -m forexpro_ri.cli memory intelligence --db local_data/research.sqlite --focus SYNTHETIC-001 --min-support 2
```

The report provides per-procedure coverage (failed, passed, not evaluable, **unobserved**), recurring negative observations, co-failing procedure pairs, immutable evidence references, and optional analogous historical cases for a specific stored experiment. All report JSON is deterministically content-addressed. A procedure fails if **any** of its recorded criteria fails; multiple failed criteria still count as only **one experiment**. A similar case shares recorded negative signatures, not an inferred root cause; similarity is represented as an exact intersection/union fraction.

**Limits:** default recurring-pattern support is **2 distinct experiment IDs**. This is not independence: cases can share data, code or a research lineage. Counts are descriptive for the stored operator-selected set, not probabilities or evidence of future profitability. Co-occurrence is not causality. Textual observations/metrics are not stored in memory, so this module cannot infer why a test failed. The report has no scientific, HOLDOUT or broker authority and only proposes questions for new preregistrations.

See [Failure Intelligence contract](docs/FAILURE_INTELLIGENCE.md).

## Future-integration contract testbench (v0.5)

ForexPro Core is still under development. **FRI v0.5 does not integrate with or modify ForexPro Core.** Instead, it implements an offline signed-export contract testbench that proves the FRI side of the proposed boundary using *synthetic data only*.

```bash
# Complete, temporary synthetic signed-export -> preflight -> memory -> diagnostics test:
python -m forexpro_ri.cli bridge rehearsal

# Optional: keep synthetic protocol files for inspection (not production evidence):
mkdir -p local_data
python -m forexpro_ri.cli bridge fixture --bundle local_data/synthetic-bridge --trust-store local_data/synthetic-keys.json
python -m forexpro_ri.cli bridge preflight local_data/synthetic-bridge --trust-store local_data/synthetic-keys.json
```

The fixture private key is generated in memory and discarded; only a synthetic bundle and its **public** trust-store entry are written. Preflight verifies exact protocol files, SHA-256 bindings, Ed25519 attestation and mutually consistent recorded procedure states. It outputs a **non-authoritative**, bounded summary with no raw observations. `bridge rehearsal` additionally verifies immutable Research Memory and Failure Intelligence end-to-end.

FRI cannot authenticate the source owner's permission merely because a signature validates. A future restricted, reviewed exporter in private ForexPro Core must authorize and sanitize *each* completed experiment before signing. The FRI-side testbench **never** grants scientific approval, HOLDOUT access, trading access, or release authorization. Never use the synthetic public key as an authority for real production exports.

Read [Bridge Contract Testbench](docs/BRIDGE_CONTRACT_TESTBENCH.md) for the exact future Core exporter checklist and limits.

## Research cohort comparison and evidence-visibility gaps (v0.6)

FRI can compare **explicitly selected closed experiments** already in local Research Memory. It reads only their stored verdicts, IDs and digests, **not** their confidential source bundles. Operator-expected procedures are an optional input to the comparison; they are **not** inferred from, or validated against, a ForexPro ValidationContract. The output distinguishes recorded **FAIL**, **PASS**, **NOT_EVALUABLE**, and **UNOBSERVED** (no evidence). Missing or non-evaluable results never become a PASS or FAIL.

Fully synthetic offline demo (does not require signing credentials or private ForexPro files):

```bash
mkdir -p local_data
python -m forexpro_ri.cli memory ingest examples/closed_synthetic --db local_data/demo.sqlite --unsigned-synthetic
python -m forexpro_ri.cli memory ingest examples/closed_synthetic_peer --db local_data/demo.sqlite --unsigned-synthetic
python -m forexpro_ri.cli memory compare --db local_data/demo.sqlite --experiment SYNTHETIC-001 --experiment SYNTHETIC-002 --expected-procedure REGIME_STABILITY
python -m forexpro_ri.cli memory compare --db local_data/demo.sqlite --experiment SYNTHETIC-001 --experiment SYNTHETIC-002 --expected-procedure REGIME_STABILITY --format markdown
```

`--experiment` must be specified for **2–50 distinct stored experiments**; ordering does not affect the report. `--expected-procedure` is optional and repeatable. Reports have a reproducible SHA-256 and include per-criterion digests and selected experiment identities. The Markdown format is a local, human-readable presentation of the same advisory evidence.

**Limits:** This is a comparison of **recorded verdicts**, not evidence that experiments share a valid protocol, comparable datasets, independent validation, or similar performance metrics. A recorded difference does not identify a cause, profit edge, or reason to change a closed experiment. No scientific authority, broker permission or HOLDOUT access is created. Report IDs/digests can themselves be sensitive metadata; do not publish real output in public issues or GitHub Actions.

See [Cohort comparison contract](docs/COHORT_COMPARISON.md).


## Research Dossier (v0.7)

Produce a **single deterministic, read-only** view for one closed experiment: its recorded procedure outcomes, evidence-visibility gaps, up to ten similar recorded negative-signature cases, recurring negative observations and questions for **new** preregistered studies. All sections use one verified SQLite read snapshot; no observation prose, metrics or protected data are imported from the database.

```bash
# Offline, synthetic examples only — never commit a real Research Memory database.
mkdir -p local_data
python -m forexpro_ri.cli memory ingest examples/closed_synthetic --db local_data/demo.sqlite --unsigned-synthetic
python -m forexpro_ri.cli memory ingest examples/closed_synthetic_peer --db local_data/demo.sqlite --unsigned-synthetic
python -m forexpro_ri.cli memory dossier --db local_data/demo.sqlite --focus SYNTHETIC-001 --expected-procedure MONTE_CARLO --format markdown
```

The report is **not** scientific validation, a reason to modify a closed study, or proof of independent replications. `UNOBSERVED` and `NOT_EVALUABLE` remain distinct. Expected procedures are operator declarations, not ForexPro protocol authority; v0.9 adds historical intake-receipt digests, but not retained signatures or fresh revocation checks. See [Research Dossier contract](docs/RESEARCH_DOSSIER.md).


## Historical signed provenance and operational audit (v0.9)

FRI now uses **Research Memory schema v2**. New intakes atomically save an immutable
receipt bound to the stored experiment entry. Receipts record either
`SIGNATURE_VERIFIED`, `UNSIGNED_SYNTHETIC` or `LEGACY_UNATTESTED`, plus
hash-linked historical signer/manifest/attestation references where verified.
There are no private keys, original signatures, free-text observations or
full source bundles in SQLite.

**The secure Python ingest API defaults to signed-only imports**, matching the
CLI. The unsigned mode must be intentionally requested and is restricted to
labeled synthetic fixtures. Never treat the presence of `SYNTHETIC` strings as
an effective privacy filter for actual research data.

```bash
# A private local database, using explicitly synthetic fixtures only:
mkdir -p local_data
python -m forexpro_ri.cli memory ingest examples/closed_synthetic --db local_data/research.sqlite --unsigned-synthetic
python -m forexpro_ri.cli memory audit --db local_data/research.sqlite
# Fails intentionally: synthetic unsigned records are NOT trusted signed history.
python -m forexpro_ri.cli memory audit --db local_data/research.sqlite --require-signed

# Upgrade an existing v1 database in place; BACK UP privately first.
python -m forexpro_ri.cli memory migrate --db local_data/old-research.sqlite

# End-to-end signed ephemeral fixture and audit (no production secrets):
python -m forexpro_ri.cli bridge rehearsal
```

`memory audit --require-signed` is an **operational import gate**, not a gate
for scientific validation or approval. It succeeds only when a nonempty
history contains exclusively historical signed receipts. Rotation/revocation
of a key after an import is **not** revalidated from stored receipts; external
trust management and an approved exporter are still mandatory. Hashes and
SQLite triggers are not tamper-proof against privileged database replacement.
Dossiers now expose the focus experiment's historical signature status and
receipt checksum, and include receipts in the whole-history snapshot digest.

See [Provenance and migration](docs/PROVENANCE_AND_MIGRATION.md) for migration
semantics, threat model and acceptance requirements.
