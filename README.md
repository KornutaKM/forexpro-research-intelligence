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
- No GitHub token required and no remote API or extra runtime dependencies.

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
