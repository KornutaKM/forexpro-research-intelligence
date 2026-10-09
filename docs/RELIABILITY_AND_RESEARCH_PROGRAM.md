# FRI v2.1–v2.2: reliable intake and evidence-backed worklist

## v2.1 queue hardening

- At submission the exact bytes of an operator-provisioned Ed25519 **public-key** trust store are SHA-256 pinned in the queue request (no private keys or raw evidence stored).
- At execution the signed job is refused if the trust store is absent, is a symbolic link, exceeds 1 MiB, or its hash has changed. A legitimate key rotation or revocation invalidates pending requests; **resubmit explicitly** with the new trust store. v2.0 legacy signed pending jobs without a pin are refused at execution and require new submission. Legacy unsigned synthetic pending jobs retain compatibility.
- The worker's acknowledgement checks current lease expiration as well as token and attempt, rejecting stale completions even before another claimant intervenes. Once a lease expires, a new claim will recover or exhaust the task under the existing 1–3 attempt limit. Research Memory ingestion is idempotent, but file publication remains separate from the DB transaction and expired workers may have written orphan report directories.
- SHA-256 pinning is not a digital signature of a queue request. It cannot stop a privileged user rewriting the queue, an OS-level attacker changing trusted files between checks, or an attacker replacing the entire local database. Keep queue, trust store, bundles and reports within a private locked-down filesystem. Workers must complete within their 15-minute default lease; v2.2 has no lease heartbeat or continuously running service.

## v2.2 prospective Research Program

Run only on an already populated Research Memory. The input database is opened read-only, with a single read transaction for the entire report. Every entry checksum and historical receipt is verified. Under normal mode, **all** records must have `SIGNATURE_VERIFIED` historical status; `--unsigned-synthetic` is exclusively for explicitly synthetic tests and bypasses this intake-history gate, not integrity verification.

### Data and selection policy

- The output distinguishes `FAIL`, `PASS`, `NOT_EVALUABLE`, and `UNOBSERVED`. `FAIL` dominates mixed PASS/FAIL criteria for one procedure on the same experiment.
- Counts are by **distinct stored experiment ID**. Repeated criteria and shared lineage do not count as independent replications.
- A *repeated failure* item or *repeated not-evaluable* item needs at least `--min-support` distinct experiment IDs (2–5000).
- An *evidence gap* item arises only for a procedure the **operator explicitly declares** with `--expected-procedure`. An unobserved or not-evaluable record is a gap; missing evidence is not a FAIL. This operator list is not a source platform ValidationContract.
- Worklist reading order: evidence gaps first, repeated non-evaluable next, repeated fail last; within a category, larger affected counts first and procedure names break ties. This is a deterministic **navigation heuristic**, not a risk model, scientific probability, strategy ranking, or decision to trade.
- Output is capped by `--max-items` (1–30), with an explicit truncation flag and total count. It contains only stored identifiers, source-entry SHA-256 and provenance receipt SHA-256; no raw observation prose, protected data, broker identifiers or source bundles are loaded into reports.
- Report hash and snapshot hash allow local reproducibility checks, but are not cryptographic authentication or proof of current signer authority.

### CLI

```sh
python -m forexpro_ri.cli memory program --db local_data/research.sqlite \
  --expected-procedure OUT_OF_SAMPLE --expected-procedure MONTE_CARLO \
  --min-support 2 --max-items 20 --format json
```

For public CI and synthetic fixtures only add `--unsigned-synthetic`; otherwise the signed-intake gate fails closed. Human-readable Markdown is selected via `--format markdown`.

### Boundaries and deferred work

FRI never places orders, optimizes strategies, reads protected HOLDOUT, registers experiments, approves research, or modifies ForexPro Core. No inference of true root causes, independent replication or expected returns is possible using these metadata alone. Current trust-store revocation management, dataset lineage normalization, authenticated operator identity and the private approved ForexPro exporter are not implemented; they remain separate release gates.
