# v0.5 — Contract Testbench for a Future ForexPro Exporter

**Status:** FRI-side synthetic conformance harness. **No ForexPro Core integration exists.**

The objective is to freeze a minimal, reviewable interoperability boundary while the private source platform is still under development. FRI stays separate: it must never read the Core repo, protected HOLDOUT, raw scientific dataset, MT5 terminals, credentials, or unapproved internal artifacts.

## Demonstrated path

```text
synthetic closed summary only
      |
      v
in-memory ephemeral Ed25519 private key (discarded; never serialized)
      |
      +--> summary.json + manifest.json + attestation.json
      +--> independent trust.json (public key only)
      |
      v
FRI bridge preflight -> verify_export -> Research Memory -> Failure Intelligence
      |
      v
advisory-only report; no scientific / broker / HOLDOUT authority
```

Run the whole flow, using only synthetic records:

```sh
python -m forexpro_ri.cli bridge rehearsal
```

To inspect individual protocol files without persisting a private key:

```sh
mkdir -p local_data
python -m forexpro_ri.cli bridge fixture --bundle local_data/synthetic-bridge --trust-store local_data/synthetic-keys.json
python -m forexpro_ri.cli bridge preflight local_data/synthetic-bridge --trust-store local_data/synthetic-keys.json
python -m forexpro_ri.cli memory ingest local_data/synthetic-bridge --db local_data/memory.sqlite --trust-store local_data/synthetic-keys.json
python -m forexpro_ri.cli memory intelligence --db local_data/memory.sqlite --focus SYNTHETIC-BRIDGE-001
```

Do **not** trust this sample key for real research. Every fixture invocation creates a new ephemeral key. The synthetic revision is a placeholder, not proof of a Core commit. This public repo contains **no** signing private keys.

## Future *private* exporter acceptance checklist

An owner-reviewed exporter in ForexPro Core (not implemented in FRI) will have to:

1. Accept a specific human-authorized export scope for a previously closed experiment. **No generic access** to runtime scientific stores or broker state.
2. Resolve the authoritative experiment identity and *actual closed disposition* without inventing final ValidationEvidence where it does not exist. Failed/incomplete stays failed/incomplete.
3. Reproduce only allowlisted `criteria` and `not_evaluable` fields for the v1 schema, with exact recorded PASS/FAIL or not-evaluable states, pre-checked for confidential observations and forbidden names/content.
4. Prohibit HOLDOUT access, open experiments, trial-level strategy parameters, raw trade data, personal data and all broker mutations. If the source does not permit safe release, **do not export**.
5. Bind a real immutable code revision and source artifact IDs through a reviewed private export receipt / provenance. The current v1 manifest provides a source revision but does not independently verify its Git ancestry or the scientific source artifact.
6. Sign the exact canonical detached attestation described in [SIGNED_EXPORT_PROTOCOL.md](SIGNED_EXPORT_PROTOCOL.md), using a restricted private key **outside FRI**. Provision the public key to FRI independently; provide revocation and key-custody controls.
7. Produce a bundle with exactly `summary.json`, `manifest.json`, `attestation.json` and stage it privately. No automatic publication or uploading to public CI.
8. Run `bridge preflight` on the FRI host and confirm a **cryptographic protocol pass**, not scientific approval or data-release authorization.
9. Only then allow explicit operator-initiated ingestion to FRI local memory. Avoid unattended import until release governance is defined.
10. Demonstrate negative conformance tests: tampered summary, tampered manifest, unknown key, revoked key, missing signature, protected procedure, contradictory evaluability and unexpected file all fail closed.

## What the testbench proves — and does not prove

**Proves in synthetic CI:** v1 schema + Ed25519 signature compatibility, local strict file boundary at bridge preflight, authenticated intake behavior, one-time immutable memory persistence, idempotent replay, deterministic Failure Intelligence over the generated record.

**Does not prove:** source-owner authorization, data sanitization, scientific reproducibility, actual ForexPro dataset/validation lineage, key custody, protected-HOLDOUT exclusion inside the future exporter, deployment readiness, live profitability, or broker safety. These are *separate* acceptance criteria requiring independent human approval and source-side evidence.

## API / import rules

- `bridge fixture`: local development only; refuses paths that already exist; emits only synthetic observations and a public trust key.
- `bridge preflight`: read-only, verifies exact three-file structure and detached signature against an independently provisioned trust store, rejects contradictory `criteria` / `not_evaluable` procedure states, returns a non-authoritative receipt **without raw observation text**.
- `bridge rehearsal`: creates isolated temporary files; invokes preflight → signed memory ingestion twice → memory verification → Failure Intelligence; cleans temporary state. No network or Core access.
- `memory ingest`: pre-existing implementation; still requires an explicit `--trust-store` for signed intake. Using unsigned legacy analytics is **not** trusted real-data ingestion.

To add a real exporter, make a *separate reviewed change* in the private Core repository only when its scientific authority and operator permissions allow. Do not paste private Core source or actual export samples into this public repository.
