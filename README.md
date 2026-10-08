# ForexPro Research Intelligence (FRI)

Public-source, offline, read-only **advisory** companion for a separately operated research platform.

**Security model:** this repository contains only generic code and explicitly synthetic fixtures. Never commit private research results, dataset files, strategy parameters, API tokens, broker data, or internal export bundles.

**MVP v0.1:** imports explicit closed-experiment summary bundles, checks SHA-256 integrity and strict authority boundaries, classifies recorded outcomes without reinterpreting them, and proposes future research *questions* without changing scientific state.

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
- Does **not** use an LLM in v0.1: classification is deterministic and based only on already recorded verdicts.
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

Re-importing identical bytes is idempotent. Conflicting exports for an existing experiment ID are rejected instead of replacing history. `memory patterns` counts affected **experiments** per recorded procedure, not the number of individual failing criteria; it does not infer causal relationships or prove profitability. `memory verify` checks database consistency and entry digests, **not exporter identity or authenticity**. The v0.3 signed importer authenticates a bundle at ingestion but v0.2 Research Memory schema does not permanently store the signer attestation; signed provenance persistence is a separate future migration. SHA-256 alone is not an authentication signature; an adversary with DB write access can bypass local protections. Keep the database on a trusted, access-restricted machine.

## Signed evidence intake (v0.3)

**FRI verifies, but does not create, detached Ed25519 signatures.** Public CI never receives private signing keys, real evidence or a trust store containing production identities. Signing happens exclusively in a separately reviewed private-source exporter, and a trusted public-key store must be provisioned by an operator **outside** the input bundle. A signature proves possession of the matching private key; FRI does not independently prove the scientific approval or quality of the exported findings.

```bash
# The owner provisions approved_public_keys.json privately on the FRI host.
python -m forexpro_ri.cli verify-export /private/approved-closed-bundle --trust-store /private/approved_public_keys.json
python -m forexpro_ri.cli /private/approved-closed-bundle --trust-store /private/approved_public_keys.json --out /private/reports/report.json
python -m forexpro_ri.cli memory ingest /private/approved-closed-bundle --db /private/local_data/research.sqlite --trust-store /private/approved_public_keys.json
```

The first command does not write any file. The actual report and database remain entirely local. FRI never requests ForexPro GitHub access, broker credentials or protected HOLDOUT access. `memory ingest` now **requires** `--trust-store` unless `--unsigned-synthetic` is explicitly supplied for a synthetic-only test fixture; generic unsigned imports are rejected by the CLI. The v0.1 standalone analysis CLI still supports unsigned analysis with `export_authenticity=NOT_VERIFIED`, so never treat that legacy output as trusted.

The `attestation.json` signature covers exact SHA-256 hashes of both raw manifest and summary bytes. The signing protocol, trust-store schema and key rotation/revocation semantics are specified in [Signed export protocol](docs/SIGNED_EXPORT_PROTOCOL.md). **No real ForexPro exports have yet been authenticated.** No code in the private ForexPro repository has been modified.
