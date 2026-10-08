# Signed closed-research export verification, v1 (FRI v0.3)

This is an **advisory transport authentication** protocol. It does not authorize experiments, validate science, approve broker actions or grant HOLDOUT access.

## Files

Source owner provisions an **explicitly sanitized, previously closed** report bundle consisting of:

- `summary.json`: schema from `INTEGRATION_CONTRACT.md`; no protected bytes/metrics.
- `manifest.json`: schema from `INTEGRATION_CONTRACT.md`, including SHA-256 of exact raw `summary.json` bytes, a full 40-character source revision, and all authorities set to false.
- `attestation.json`: detached Ed25519 attestation described below.

The caller independently provisions a trusted **public** key registry outside the bundle; FRI does not load keys from its input bundle, remote network, or public repository. The private signing key remains exclusively with an authorized offline source exporter (not supplied by FRI).

## `attestation.json`

Strict JSON object with exactly:

```json
{
  "schema_version": 1,
  "algorithm": "Ed25519",
  "key_id": "owner-approved-exporter-key-v1",
  "manifest_sha256": "<sha256 of exact manifest.json bytes, lowercase hex>",
  "summary_sha256": "<sha256 of exact summary.json bytes, lowercase hex>",
  "signature_b64": "<canonical base64 encoding of 64 Ed25519 signature bytes>"
}
```

Prepare a map containing **only** `schema_version`, `algorithm`, `key_id`, `manifest_sha256`, and `summary_sha256`. Serialize with `json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')`. Sign this precise payload:

```text
ASCII bytes: FRI-CLOSED-EXPORT-ATTESTATION-V1\n
then UTF-8 canonical JSON bytes of the five fields
```

A domain prefix prevents accidental reuse of signatures from unrelated protocols. Unknown fields, duplicate JSON keys, noncanonical base64, oversized files and unrecognized signer keys are rejected. Changes to either manifest or summary require a new signature.

## Trusted public keys

A local `trusted-keys.json` (not committed, outside bundle) has this strict schema. The following value is an **illustrative placeholder**, not an actual key:

```json
{
  "schema_version": 1,
  "keys": [
    {
      "key_id": "owner-approved-exporter-key-v1",
      "algorithm": "Ed25519",
      "public_key_b64": "<canonical base64 encoding of 32 raw public-key bytes>",
      "source_system": "forexpro",
      "purpose": "CLOSED_EXPERIMENT_SUMMARY",
      "status": "ACTIVE"
    }
  ]
}
```

To revoke a key, change its status to `REVOKED`. The verifier refuses signatures from revoked keys. An administrator must control the registry and protect it from substitution or rollbacks; storing public keys is not sufficient if an attacker can alter the trusted list. Verification is against the **current** registry, not historical revocation status.

## Threat model / limitations

- Trust registry provisioning and signing-key custody are external owner-controlled operations. The public code cannot establish that the person controlling a trusted signing key had valid authority to make a specific export.
- SHA-256 and Ed25519 authenticate **bytes**, not scientific truth or procedural authorization.
- FRI does not inspect opaque free-text observations for confidential information. The private source exporter must **strictly sanitize** content before signing; do not use FRI as a data-loss-prevention gateway.
- No HOLDOUT payloads, secrets, strategy parameters, real broker positions or trade activity are allowed. Do not run real exports in public Actions.
- FRI v0.2 Research Memory stores observations as digests and **does not retain signer provenance** as a database record; signed intake verification is a point-in-time admission check. Do not call `memory verify` a historical signature audit.
- The standalone unsigned analysis command remains available as a diagnostic mode but its output is marked `NOT_VERIFIED`.
- No signing private key, complete real report, actual production public-key registry or sanitized export is included in this repository.

## Required work in the private source before actual use

The ForexPro owner must approve the export contract and its allowed data, implement a minimal closed-result exporter and a signed operational receipt, install the signing key under restricted custody, enforce that the export is only from a genuinely closed and authorized result with no protected content, and independently test negative cases. Those modifications require separate review and must not mutate scientific authority, run a holdout or access a broker.
