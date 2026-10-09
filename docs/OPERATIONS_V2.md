# FRI v2.0 — offline durable advisory job processing

**Scope:** FRI runs only on explicit local closed-experiment summary bundles. It is **not** an experiment scheduler, model trainer, broker/trading executor, scientific authority, HOLDOUT gate, or system with access to ForexPro Core. ForexPro Core is not integrated.

## Components

- `jobs.py`: separate private SQLite queue (`user_version=1`), transactional job claims and event hash chain; no raw observations stored. Queue metadata does include **local filesystem paths**, which must remain private.
- `jobs_cli.py`: operator commands. No background process, network listener or GitHub credential is required.
- Existing `operations.py`: validates signed inputs (default), atomically imports up to 50 bundles into Research Memory and publishes immutable per-experiment Research Dossiers.
- Existing `recovery.py`: handles **Research Memory backups**, not automatic offsite queue backups.

The queue is separate from Research Memory. Jobs store absolute input paths, expected input file SHA-256 digests, signed/trust-store mode, output destination and optional expected procedures. Raw summaries, strategy parameters, free-text observations and private signing keys are not persisted to queue tables. Reports and databases are **private** runtime artifacts; never upload them to the public repo or CI artifacts.

## Basic synthetic walkthrough

```sh
python -m pip install -e .
mkdir -p local_data local_data/reports
python -m forexpro_ri.cli jobs submit \
  --queue local_data/jobs.sqlite --db local_data/research.sqlite \
  --out-root local_data/reports \
  --bundle examples/closed_synthetic \
  --bundle examples/closed_synthetic_peer --unsigned-synthetic
python -m forexpro_ri.cli jobs work --queue local_data/jobs.sqlite
python -m forexpro_ri.cli jobs status --queue local_data/jobs.sqlite
python -m forexpro_ri.cli jobs verify --queue local_data/jobs.sqlite
python -m forexpro_ri.cli jobs health --queue local_data/jobs.sqlite \
  --db local_data/research.sqlite --allow-unsigned-synthetic
```

The CLI displays job ID, attempt, status and output directory. Reports are created in a new `fri-<job-id>-attempt-<n>` directory. `jobs verify` checks the queue event-chain and completed report files; `jobs health` additionally checks Research Memory readiness when `--db` is provided. Both reports are *operational*, not scientific approval.

## Signed mode

```sh
# Signed fixtures for contract testing only; never use their key for production.
python -m forexpro_ri.cli bridge fixture \
  --bundle local_data/signed-fixture --trust-store local_data/synthetic-keys.json
python -m forexpro_ri.cli jobs submit \
  --queue local_data/signed-jobs.sqlite --db local_data/signed-memory.sqlite \
  --out-root local_data/reports \
  --bundle local_data/signed-fixture --trust-store local_data/synthetic-keys.json
python -m forexpro_ri.cli jobs work --queue local_data/signed-jobs.sqlite
python -m forexpro_ri.cli jobs verify --queue local_data/signed-jobs.sqlite
```

For eventual *real* signed exports, use a separately approved sanitized ForexPro exporter and independently provisioned Ed25519 public keys. A valid signature proves key possession only; it does not independently establish export authorization or scientific validity. Private Core integration remains a separate review and implementation.

## Worker semantics, recovery and safety

1. Submission validates all selected bundles immediately and stores SHA-256 input fingerprints; execution checks fingerprints **again** and re-verifies signatures/approval scope against the current trust store. Files must remain in their original locations until processing completes. In v2.2, signed jobs pin the entire trust-store SHA-256 at submission: any change, including key revocation, fails the queued job; the operator must submit a new job to use the changed trust store.
2. A worker transaction claims one due job with a unique lease token. Default lease is 15 minutes; an expired lease can be reclaimed. Stale worker completion attempts are rejected by token/attempt comparison **and by expiry time**, even if no second worker has claimed the job. The job must finish within its lease; there is no lease heartbeat in v2.2. An expired job can still have already committed idempotent Research Memory entries; the next attempt safely retries report generation.
3. Transient `OSError` errors retry up to **3 attempts**, with bounded exponential backoff. Contract-invalid evidence and unexpected programming exceptions stop in `FAILED` state. Error messages are reduced to **codes**, not stored with arbitrary potentially sensitive exception text.
4. `jobs work --limit N` processes up to 50 due jobs in the caller process. For periodic operation, run it under an explicitly authorized local scheduler (systemd timer or cron) on the trusted host; FRI does not poll, watch directories, or automatically discover research results.
5. `jobs requeue --queue ... --job-id ...` allows a human operator to requeue a **FAILED** job with unchanged input bytes. The action is recorded in the event log. It does not override evidence constraints or trust-store verification. If an input legitimately changes, submit a new job with the new fingerprint.
6. The SQLite Research Memory intake is atomic *per batch* but the subsequent report filesystem publication is separate. A crash after intake may leave orphaned report directories; retry uses a distinct attempt directory and immutable memory deduplication. The queue provides **at-least-once** delivery, not distributed exactly-once execution or a two-phase commit.
7. No heartbeat is implemented in v2.0. An unusually long running job could outlive its lease and execute concurrently with a replacement. Use one trusted worker at a time and do not use FRI for latency-critical operations. Bundle swaps during execution are not protected by filesystem snapshots; signed mode does authenticate exactly processed export bytes.
8. `jobs verify` is a self-contained SHA-256 continuity check and cannot withstand a malicious administrator who can rewrite the SQLite DB and its event chain. Protect queue and Memory files with OS permissions, separate backups and independent monitoring. It is **not** a cryptographic attestation of runtime integrity.

## Operator recovery

```sh
python -m forexpro_ri.cli jobs status --queue local_data/jobs.sqlite
python -m forexpro_ri.cli jobs health --queue local_data/jobs.sqlite \
  --db local_data/research.sqlite --allow-unsigned-synthetic
# When a failed job is safe to repeat with unchanged evidence:
python -m forexpro_ri.cli jobs requeue \
  --queue local_data/jobs.sqlite --job-id <job-id>
python -m forexpro_ri.cli jobs work --queue local_data/jobs.sqlite
python -m forexpro_ri.cli jobs verify --queue local_data/jobs.sqlite
# Research Memory backup/recovery remains separately available:
python -m forexpro_ri.cli recovery drill --db local_data/research.sqlite
```

## Limits and readiness for future integration

Bounded queue: 5,000 jobs; 1–50 bundles per batch; each input file no larger than 1 MiB; up to 3 attempts per queue cycle; at most 50 jobs per drain command. Queue and report integrity checks are non-authoritative. A v2.0 release is **operationally complete for offline, operator-approved signed exports**, but is **not production-integrated** with ForexPro Core. The integration gate requires a private exporter, custody and classification review, signer provision, key rotation, approved operator environment and a real-data acceptance rehearsal without enabling HOLDOUT or broker access.
