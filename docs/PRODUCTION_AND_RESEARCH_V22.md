# FRI v2.1–v2.2 — Offline hardening and Research Question Program

This release adds two related but *non-authoritative* features. It does not integrate
with ForexPro Core, query protected data, run strategies, or claim scientific approval.

## 1. Production hardening (v2.1)

### Pinned trust-store bytes

New signed job submissions record a SHA-256 digest of the *exact locally
provisioned public-key registry bytes* in the immutable request. At execution,
the worker compares the current bytes to that digest, and **rejects any
change**. It then independently checks the signature and key status through
the signed-export pipeline. If the operator rotates or revokes a key after
submission, the queued request must be superseded by a newly reviewed job.
A hash is not a signature or an external trust anchor; an administrator who can
rewrite both request and event history can defeat local integrity controls.

v2.0 signed requests without the optional `trust_store_sha256` field remain
readable so pending work does not break. They are reported as
`UNPINNED_LEGACY_TRUST` in `jobs watch`; review and re-submit them before
production usage. The SQLite job schema remains v1, without migrations.

### Audit-aware watcher

`jobs watch` verifies the queue event chain and published report files before
issuing a read-only health snapshot with categorical alerts. It cannot
repair, resubmit, promote or execute anything. It reports:

- `FAILED_JOB`: terminal local processing failure
- `EXPIRED_LEASE`: worker lease reached its deadline
- `OVERDUE_QUEUED`: queued for longer than the operator threshold
- `DUE_RETRY`: retry delay has elapsed
- `UNPINNED_LEGACY_TRUST`: old signed request lacks public-key registry pin
- `INPUT_CHANGED`: opt-in current local bundle/trust-store fingerprint check

The watcher exposes job IDs and codes only, not bundle paths or exception
messages. Alert truncation is explicit. Worker and watcher operate on separate
SQLite reads: results are diagnostic snapshots, not globally atomic system state.

```bash
python -m forexpro_ri.cli jobs watch --queue local_data/jobs.sqlite
python -m forexpro_ri.cli jobs watch --queue local_data/jobs.sqlite \
  --inspect-sources --overdue-seconds 3600
```

The worker also checks the job request SHA-256 before processing, so a modified
request is rejected before evidence import. Lease-fencing and immutable
Research Memory semantics from v2.0 remain in force. This implementation is
still an **operator-controlled offline CLI**, not a daemon and not a hosted API.

## 2. Research Question Program (v2.2)

A deterministic, one-snapshot, bounded (1–5,000 closed histories) synthesis
of *recorded categorical outcomes*, intended only for **human review of
future preregistered experiment design**. It verifies the entire memory and
historical signature receipts before reporting, and defaults to refusing
unsigned/legacy intakes.

```bash
python -m forexpro_ri.cli memory program --db local_data/research.sqlite \
  --expected-procedure MONTE_CARLO --expected-procedure COST_STRESS \
  --format markdown
```

The reviewed synthetic-only demonstration escape hatch is explicit:

```bash
python -m forexpro_ri.cli memory program --db local_data/demo.sqlite \
  --allow-unsigned-synthetic --expected-procedure RISK_LIMITS \
  --format json
```

`expected_procedures` are **operator-supplied expectations**, not the
scientific validation contract. The program counts **distinct experiment IDs**
per procedure in four disjoint categories:

- `FAIL`: at least one recorded criterion failed (even if others passed)
- `PASS`: one or more criteria passed and none failed
- `NOT_EVALUABLE`: explicitly recorded inability to assess the procedure
- `UNOBSERVED`: no recorded result; **not** an assertion that the procedure
  was required, attempted or passed

Order of **review topics**, not strategy or research quality ranking:

1. `REPEATED_RECORDED_FAILURE` — FAIL in at least `min_support` distinct IDs
2. `REPEATED_EVIDENCE_GAP` — NOT_EVALUABLE recurring, or operator-expected
   procedure UNOBSERVED repeatedly
3. `ISOLATED_NEGATIVE_OR_GAP` — a single relevant negative/gap
4. `NO_NEGATIVE_OBSERVATION` — no such recorded negative/gap

Within an ordinal class, outcomes are ordered by descriptive support counts,
then procedure identifier to make output reproducible. Counts are NOT failure
rates of any representative population and **do not establish independent
replications**, statistically significant signals, causes, strategy quality,
profitability or forecasts. Different experiment IDs may share the same
underlying data, parameters, or lineage. No experiments are executed.

The JSON and Markdown output contains source experiment IDs and hashed
entry/receipt references, the full snapshot digest, ordinal class, bounded
question text and explicit limitations. It excludes raw observations and
trading instructions. Historical signed receipts do not attest present
revocation status, exporter authorization or protected holdout access.

## 3. Verification and operations

- New tests cover signed trust pinning, changed trust registries, queue request
  tampering, stale leases, source drift, backward compatibility and repeatable
  program results with mixed FAIL/PASS and missing evidence.
- Public CI uses only synthetic evidence, including an ephemeral Ed25519 key
  held in process memory during test generation.
- Configure backups, OS access control, key provisioning and alert collection
  outside this repository before exposing real experimental metadata.
- Never expose the SQLite DB, private reports or raw exports in the public repo.

## Pending requirements

- Native offline workers still require explicit invocation or an external
  supervisor; availability and resource budgets have not been measured under
  a production workload.
- No end-to-end source export authorization: that belongs to private ForexPro.
- No certified secure audit storage: local hashes/triggers are tamper-evident
  against accidental edits, not privileged deletion or database replacement.
- No reliable causal inference or AI-based recommendations. These outputs are
  reproducible, human-oriented *research questions* only.
