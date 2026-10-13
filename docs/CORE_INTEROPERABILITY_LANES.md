# Core → FRI Interoperability: two isolated lanes (design only)

Status: PROPOSED, SOURCE-OWNER REVIEW REQUIRED. This is not an exporter, a
receiver enhancement, or authorization to exchange real Core scientific data.

## Source and consumer separation

| Control | PREVIEW lane | CLOSED_RESEARCH lane |
| --- | --- | --- |
| Source class | Future, operator-reviewed *generic* UI/MVP preview metadata | An explicitly closed scientific experiment with source owner release |
| Present integration status | NOT IMPLEMENTED | Existing FRI signed v1 receiver; actual Core feed BLOCKED |
| Meaning | PREVIEW_ONLY / LOCAL_UNVERIFIED | CLOSED_EXPERIMENT_SUMMARY, signed export format v1 |
| Eligible source fields | None approved yet; design-only candidate schema | Existing manifest / summary / attestation v1 exact allowlist, subject to new owner approval |
| Can use personal CSV or market/trade rows? | NO | NO |
| FRI Research Memory intake | NEVER | Only after independent explicit export and privacy release |
| FRI Failure Intelligence / Advisor counts | NEVER | Historical signed intakes may be examined; scientific approval never inferred |
| Allowed consumer | Future isolated preview viewer only, not implemented | Existing signed offline Research Memory receiver |
| Privacy and classification decision | Missing, requires human review | Missing, requires human review per export |
| Authentication | No accepted source authentication | Ed25519 plus independently provisioned trust store, verified at import |
| Is authentic signature export permission? | Not applicable | NO |
| Converts unknown / NOT_EVALUABLE / UNOBSERVED into PASS? | NEVER | NEVER |
| Allows model / FRI to send instructions to Core? | NO | NO |
| HOLDOUT / broker / strategy promotion | NO | NO |
| Allowed public CI material | Independent synthetic fakes only | Independent synthetic signed fakes only |

## Closed-research gates before ANY real Core export

1. Explicit source-owner release decision for exact finished experiment identities.
2. Exact allowlisted fields with type and length limits, no original observations.
3. Independent privacy/classification and redaction review; public repo is not storage.
4. Source-side confirmation of final closed scientific state, not MVP preview.
5. Independent reviewer and assigned evidence custodian.
6. Per-export signed release permission; historical signature is insufficient.
7. Approved recipient trust roots, current revocations and retention period.
8. Private, end-to-end rehearsal including failed tamper/revocation tests.
9. A review demonstrating no cross-lane promotion or ingestion by mislabeling.
10. Human sign-off after verifying the exact release / recipient / field set.

These gates belong to the Core source owner; FRI cannot self-authorize any of
them. An opened Issue, a green synthetic CI run, or a merged PR does not
constitute a release decision.

## Explicit rejection examples

* The Core MVP simulated SMA/price preview is NOT a closed scientific result.
* A LOCAL_UNVERIFIED CSV cannot be wrapped in a manifest claiming closure.
* Signed historical intake must not be called current approval.
* Different experiment IDs do not prove independent trials.
* Missing procedure results must be labeled UNOBSERVED; inability to evaluate
  must remain NOT_EVALUABLE, never PASS.
* A new proposed Advisor question is not registered as an experiment by FRI.
* FRI reports cannot trigger Core optimization, scientific-state mutations,
  trading, MT5, broker activity, or external data transfer.

## Boundaries of this PR

The Research Review Pack only composes already admitted Research Memory and
creates a local advisory report. This document records a compatibility policy;
it implements neither PREVIEW ingestion nor a production Core exporter.

Real source transfer is blocked until source-owner decisions resolve the
requirements listed above. See FRI Issue #19 and the private Core integration
governance issue referenced there.
