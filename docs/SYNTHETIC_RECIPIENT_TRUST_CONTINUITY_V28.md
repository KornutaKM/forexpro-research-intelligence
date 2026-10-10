# FRI v2.8 — synthetic recipient trust continuity and revocation

**Status: DRAFT; SYNTHETIC-ONLY; NOT APPROVED FOR REAL SOURCE DATA OR EXPORT.**

This is a recipient-side extension stacked on [public FRI draft PR #16](https://github.com/KornutaKM/forexpro-research-intelligence/pull/16), which proposes the conservative Core v1 signed-bundle preview. Core [Issue #518](https://github.com/KornutaKM/1111222/issues/518) approved only the engineering design baseline. Real source access, latest closure authority, signer custody, phrase classification and per-record declassification/export permission remain **unapproved**. The phrase candidate in private Core draft #526 is **not** approved merely because its SHA-256 matches.

## Threat model

FRI v1 checks Ed25519 against a local public trust file; this is point-in-time verification, not operator-controlled evidence of historical trust state. An attacker who can replace a trust file, approved-signer list and bundle could fabricate a consistent signed packet. This proposal checks an additional *synthetic operator-signed checkpoint history* for changes, revocation and rollback. All keys and external pins are still caller-supplied and can be jointly forged; no operational independent trust root exists.

## Contract

A checkpoint is bounded canonical compact sorted JSON (max 4096 bytes) with exactly `schema_version`, `algorithm`, `key_id`, `payload`, and `signature_b64`. Ed25519 signs the ASCII domain `FRI-SYNTHETIC-RECIPIENT-TRUST-CHECKPOINT-V1\n` followed by canonical JSON of the four unsigned envelope fields. Only `SYNTHETIC_RECEIVER_OWNER_` operator IDs and `SYNTHETIC_ONLY` claims are accepted; duplicate/extra keys, noncanonical signatures, malformed digests and authority escalation fail closed.

Each payload holds `sequence`, `previous_sha256`, `key_epoch`, `minimum_accepted_sequence`, exact raw `trust_store_sha256`, candidate `catalog_sha256`, sorted active/revoked exporter test-key IDs, sorted retired operator test-key IDs and literal-false `source_authority`, `export_authority`, `holdout_access`, `broker_authority`.

The offline verifier requires:

1. A **complete sequence** of 1–16 signed checkpoints starting at sequence 1 / epoch 1 / zero previous digest. Each later step increments sequence exactly 1 and binds the SHA-256 of the previous signed envelope. A caller-supplied external genesis, final head hash, exact head sequence and minimum accepted sequence must agree. A signed minimum floor may never decrease.
2. **Operator key rotation** only when epoch increases exactly 1 and signer changes. The old signer must be added to the monotonically growing retired set, cannot be reused, and only previously active signer IDs may be retired. Current signer cannot be marked retired. The complete synthetic operator test-keyset has an externally pinned deterministic SHA-256; exporter public keys must not reuse operator key material.
3. **Cumulative exporter revocation:** a revoked exporter key cannot be reactivated by a later checkpoint. Latest active/revoked key sets and exact trust-file raw SHA-256 must match the current local FRI v1 trust store; the trust file is checked again after signed-bundle verification to detect ordinary TOCTOU changes. This is not an atomic filesystem snapshot against malicious administrators.
4. **Conservative FRI v2.7 composition:** existing Ed25519 signature validation on explicitly synthetic packages, exactly the Core v1 candidate vocabulary (20 phrases, SHA-256 `7dbe7ec841bc15262051128d55c2ec4ce2673ce1034d3740d7c0679083eff8d5`), `CLOSED_UNSUCCESSFUL`, no `not_evaluable`, all ten procedure kinds, and at least one FAIL. The bounded batch may contain 1–20 packages; nothing is imported.
5. **No data disclosure or authority:** the response includes only fixed words and aggregate counts. It never returns file paths, strategy parameters, observations, IDs or keys. Every field for real source custody, scientific closure, dictionary approval, export/ingestion, HOLDOUT, trading and same-campaign feedback is literal `false`.

## CLI

`python -m forexpro_ri.cli synthetic-receiver-trust --bundle ./synthetic-bundle --trust-store ./synthetic-trust.json --checkpoint ./genesis.json [--checkpoint ./second.json ...] --operator-test-public-keys ./operator-test-keys.json --operator-keyset-sha256 64hex --expected-genesis-sha256 64hex --expected-head-sha256 64hex --expected-head-sequence 2 --minimum-sequence 2`

The operator test-keyring schema is `{"schema_version":1,"operator_keys":[{"key_id":"SYNTHETIC_RECEIVER_OWNER_ALPHA","public_key_b64":"<canonical 32-byte test key base64>"}]}`. The trust file and checkpoints must be outside the synthetic signed bundle. Keys are test-only; do not supply real production keys or records. No write or export path is exposed.

Run tests:

```sh
python -m unittest discover -s tests -p test_synthetic_trust_continuity.py -v
python -m unittest discover -s tests -v
```

All tests use disposable ephemeral private keys in process memory and synthetic data only. Negative cases cover stale/replaced trust files, signed rollback, epoch and key reactivation, forged signatures, altered source bundles, symlinks and non-disclosing CLI denials.

## Work required before real integration

The source owner still must decide the actual authoritative Core terminal-closure source, immutable consistent snapshot model, real signer/root custody, independent latest-head storage, revocation recovery, minimum read principal, approved exact field/dictionary policy, private recipient and retention, independent privacy/security review and separate per-record release grant (FRI-TRUST-01–10 in private Core draft #530). The source S1 incomplete 9/10 study with missing final `ValidationEvidence` remains ineligible. CI cannot approve any real export, unlock HOLDOUT, alter scientific decisions, or permit trading.
