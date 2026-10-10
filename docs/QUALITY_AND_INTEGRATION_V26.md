# FRI v2.5–v2.6: independent quality and integration readiness

This release **does not integrate with ForexPro Core**. It delivers an offline
regression gate and versioned conformance checks for a *future, private,
source-owned* exporter. Both tools are non-authoritative and use only synthetic
fixtures in public CI.

## Quality v2.5

`quality benchmark` reads a locally provisioned Research Memory database and
constructs the published deterministic Research Advisor pack. The default
requires *historically verified signatures* for all ingested records; a
`--unsigned-synthetic` override is provided exclusively for demonstration.

It verifies the Advisor's schema, digest, count bounds, listed reference
integrity, immutable program/snapshot digests, no causal upgrade and zero
scientific/holdout/promotion/broker/experiment-execution authority. The
reproducible negative regression cases test authority escalation, modified
digests, untrusted history, unsupported causal interpretation and fabricated
references. A machine-readable summary reports `passed`, `total`, and
`pass_rate` on a **fixed synthetic regression suite**, not an estimate of real
AI truthfulness, predictive efficacy or production reliability.

`validate_commentary` from v2.4 restricts optional local-model items to exact
known IDs, types and bounds. Quality v2.5 also verifies the inferred material
is labelled unverified. **This cannot guarantee semantic truthfulness or
prevent every persuasive hallucination in free text.** Human review remains
mandatory. No live Ollama call is performed in public CI.

```bash
python -m forexpro_ri.cli quality benchmark \
  --db local_data/research.sqlite
```

## Integration readiness v2.6

`integration check` verifies the **existing v1** signed-export protocol:
exactly `manifest.json`, `summary.json`, `attestation.json`, with an
independently provisioned local trust store, Ed25519, SHA-256, the supported
allowlisted procedures, no holdout/promotion/broker authority and an explicitly
closed unsuccessful/incomplete disposition.

It rejects extra files, nested directories, symlinks, oversize entries,
unsupported versions, revoked/unknown signer keys and malformed evidence.
There is **no v2 export protocol introduced in this release**: adopting a new
wire version requires an explicit contract review and conformance fixture.

```bash
python -m forexpro_ri.cli integration check \
  --bundle /path/to/approved-export \
  --trust-store /path/outside/bundle/trusted-keys.json
python -m forexpro_ri.cli integration rehearsal
```

`integration rehearsal` creates a disposable signed **synthetic-only** export
using an in-memory ephemeral Ed25519 key, verifies it and ingests it into an
ephemeral Research Memory instance, then checks the signed-only Advisor gate.
The private key is not persisted. The operation requires **no** access to
ForexPro, protected data, HOLDOUT, broker, credentials, or network.

### Future private exporter owner checklist

1. A source-authorized exporter must be developed *in the private ForexPro
   repository*, following source scientific controls and an independent export
   policy review; FRI **must not** be able to bypass these controls.
2. Export only finalized approved-for-export **closed** summaries. A
   `CLOSED_UNSUCCESSFUL` flag is not proof of a final scientific validation.
3. Sanitize free-text fields outside FRI: the FRI importer rejects invalid
   schemas but does not reliably detect proprietary or sensitive content.
4. Provision trust keys independently of payloads and control revocation,
   expiry and signing identities within the source owner's operational policy.
5. Run compatibility and rehearsal in a private isolated environment; never
   submit real bundles or trust infrastructure to public CI.
6. Record exporter version, policy revision, approval, and access-control
   evidence in the **private source system**. Current FRI v1 bundle schema
   does not cryptographically bind an independent authorization receipt.
7. For production readiness run schema conformance, historical provenance,
   restore drills, threat review, key rotation drills and a human go/no-go
   decision. This release intentionally **does not** decide go/no-go.

## Security invariants

The checker proves format and signature consistency at check time **only**.
Neither `CONTRACT_CONFORMANT_NOT_EXPORT_APPROVED` nor the synthetic test
`CONTRACT_REHEARSAL_PASS` means export permission, trade authorization,
independent scientific validation or causal effectiveness. All public CI
fixtures are synthetic and disposable.
