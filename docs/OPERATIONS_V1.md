# FRI v1.0 — offline operational pipeline

## Purpose

Run bounded, operator-selected, signed research exports through one **atomic Research Memory write transaction** followed by integrity, provenance and advisory dossier production. This pipeline is **not** ForexPro exporter authorization, scientific validation, or trading infrastructure.

**Never process real/private exports on GitHub-hosted public CI.** Run locally in a private operating environment. The public workflow uses only synthetic fixtures.

## Commands

```shell
# Synthetic only, no source-platform dependency:
mkdir -p local_data
python -m forexpro_ri.cli operations run \
  --bundle examples/closed_synthetic \
  --bundle examples/closed_synthetic_peer \
  --db local_data/research.sqlite \
  --out local_data/dossier-run \
  --unsigned-synthetic \
  --expected-procedure MONTE_CARLO

python -m forexpro_ri.cli operations readiness \
  --db local_data/research.sqlite --allow-unsigned-synthetic

# In a private operator environment, using source-owner provisioned public keys:
python -m forexpro_ri.cli operations run \
  --bundle /private/exports/closed-001 \
  --bundle /private/exports/closed-002 \
  --trust-store /private/trusted-exporters.json \
  --db /private/state/research.sqlite \
  --out /private/reports/run-001

python -m forexpro_ri.cli operations readiness --db /private/state/research.sqlite
```

`operations batch` performs intake without publishing reports. `operations run` performs intake then readiness and generates `intake.json`, `readiness.json`, `run.json`, and a hashed-name JSON + Markdown dossier for each explicitly submitted experiment, plus an `artifacts.json` SHA-256 inventory.

## Security and consistency contract

- Explicit 1–50 source directories only. No recursive directory scan and no network access.
- Default is **signed-only**, verified against a separately provisioned trust store. `--unsigned-synthetic` is mutually exclusive with `--trust-store`, and accepts only explicitly synthetic bundles.
- Exactly two fixed files for synthetic input or three fixed files for signed input; hidden files and symlinks rejected. Contents validated and bounded by existing v0.9 contracts.
- Prevalidate **every** input before writing; reject repeated input paths and duplicate experiment identities.
- Memory inserts are an SQLite `BEGIN IMMEDIATE` transaction: an immutable/provenance conflict aborts the *whole* batch. Existing Research Memory is checked before inserts. Duplicate identical exports are no-op.
- A signed batch refuses a mixed legacy/unsigned history. Do not mix real signed imports into a synthetic demo database.
- Export and signature approval are distinct. `SIGNATURE_VERIFIED` only records **verification at import**; no independent source-scientific approval is inferred. Trust-store revocation is **not** rechecked during offline history audit.
- Generated reports contain IDs and hashes, not raw observation/reason text. Report directory is created with mode 0700; files mode 0600. It must be new and outside input bundles.
- Rerun after an interruption with the **same bundles**, a fresh output path and the existing DB; identical intakes will be `ALREADY_PRESENT`. Operator must back up any production DB before migrations/major upgrades.
- **Transactional boundary:** atomicity covers Research Memory records, not an external output directory. If report generation fails after commit, memory is still committed; the output directory is not published partially. Re-run with a new output location.
- SQLite append-only triggers and SHA-256 are corruption checks **not tamper-proof custody** against privileged local actors. Place private DB and reports on access-controlled disks.
- `LOCAL_INTAKE_READY` only means FRI's local checks pass. It is **never** authorization to use ForexPro source data, protected holdout, or broker APIs.

## Future ForexPro integration

Source exporter remains *private and ForexPro-owned*. Integration requires owner authorization and explicitly allowed closed summaries, verified data classification, independently provisioned key custody, source revision provenance, and complete negative security tests. None are bypassed by this operational pipeline.

Run `python -m forexpro_ri.cli operations verify-report --dir /private/reports/run-001` to detect accidental changes to the generated files. Its hashes are **not digitally authenticated**: anyone with write access can replace both the content and its inventory.
