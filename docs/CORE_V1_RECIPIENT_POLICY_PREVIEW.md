# FRI synthetic Core v1 recipient-policy preview (v2.7 draft)

**Status: unapproved policy candidate / synthetic signed fixtures only /
no real-source authorization / no import or export.**

This proposal improves the **recipient-side** defense-in-depth in the public
[ForexPro Research Intelligence](https://github.com/KornutaKM/forexpro-research-intelligence).
It is independent of the private source owner's existing scientific decisions
and does not activate any Core PR. The Core conservative v1 design baseline was
approved in [Issue #518](https://github.com/KornutaKM/1111222/issues/518);
actual source custody, field classification, closure, private recipient,
declassification and per-record export grants are still **unapproved**.

## What is enforced

`python -m forexpro_ri.cli core-policy --bundle ... --trust-store ...`
has a *separate*, explicitly synthetic and **read-only** recipient preview
API. Normal FRI signed import and historical Research Memory functionality
remain unchanged. It invokes the existing local Ed25519 signature verifier,
then enforces a **narrower proposed Core v1 policy**:

- Exactly the existing three signed v1 files; no nested objects, symlinks,
  unexpected files or oversized content. The trust-store file must be outside
  the bundle and must be accepted by the existing v1 verifier.
- Test-only labels: `SYNTHETIC-` experiment ID and `SYNTHETIC_` signer ID.
  These markings are a guardrail **not** a cryptographic proof of test origin.
- `disposition=CLOSED_UNSUCCESSFUL`, empty `not_evaluable`, at least one
  recorded `FAIL`, and claims for **all ten** of the allowlisted procedures.
  Duplicate criteria IDs and unsupported procedure kinds are already rejected
  by the base v1 protocol. Multiple distinct criteria per procedure are
  permitted, up to the v1 limit of 200.
- **Only** the exact finite fixed words from Core's *unapproved* candidate
  [PR #526](https://github.com/KornutaKM/1111222/pull/526).
  The deterministic catalog SHA-256 is checked on every invocation:
  `7dbe7ec841bc15262051128d55c2ec4ce2673ce1034d3740d7c0679083eff8d5`.
  This change-detection digest is **not a classification or DLP approval**.
  The complete candidate vocabulary contains ten procedures × PASS/FAIL.
- Bounded all-or-nothing batch checking of **1–20** packages with duplicate
  paths and repeated experiment IDs rejected. No batch contents are saved.
- No raw science, free-text observations, source IDs, paths, signer IDs or
  original data are included in the concise JSON output or CLI denial text.

## What is NOT checked or authorized

A valid signed v1 bundle plus one of twenty fixed words cannot prove Core
`ValidationContract` preregistration, the actual complete ten-procedure
`ValidationEvidence`, latest terminal closure, source code/data/split custody,
independent signer trust, or authorization for any real experiment. A caller
can forge synthetic labels, keys and matching signatures if they control the
trust store. This preview does not contact Core, inspect an actual source
registry, sign data, create an export, write a database, declassify original
observations, authorize a private recipient or permit feedback into an ongoing
scientific campaign.

The response **always** marks all real scientific/closure/release/privacy,
HOLDOUT/broker and feedback authorities `false`. A successful synthetic
preview must never become a database-ingestion or export-unlock token.

A future approved private recipient can adopt a separately reviewed final
dictionary and a **distinct** independently sourced human release-grant and
source-provenance policy; do not simply change `SYNTHETIC-` flags in this
module. `CLOSED_INCOMPLETE` remains DENIED by Core's conservative baseline
even though the older general FRI v1 parser can represent it.

## Reproducible tests and operational boundary

```bash
python -m unittest discover -s tests -p test_core_policy_preview.py -v
python -m unittest discover -s tests -v
# The command below requires locally generated synthetic, signed, ten-kind
# fixture files and a matching test-only public trust-store (not bundled).
python -m forexpro_ri.cli core-policy --bundle ./SYNTHETIC-BUNDLE --trust-store ./synthetic-public-trust.json
```

Tests construct disposable Ed25519-signed synthetic packages entirely in a
temporary directory with ephemeral private keys held in process memory. The
suite exercises exact vocabulary, complete negative procedure assertions,
different signed invalid dispositions and protected authority claims, tampered
bytes, wrong/revoked keys, extra files and symlinks, mixed/duplicate batch
inputs, fixed-output privacy and CLI denial handling.

No source data, protected metrics, signing secrets, FRI Research Memory DB,
network, Core runtime or broker is exercised; public CI runs these tests only.
On signing-key, snapshot, review or source authority uncertainty, **deny**.
