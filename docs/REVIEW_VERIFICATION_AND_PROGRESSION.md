# Research Review Pack: integrity, evidence coverage and progression

Issue #19 qualification extension. This document describes additional
**offline, non-authoritative** checks in FRI. It does not approve exchange
of real Core research or access to HOLDOUT, broker, strategies or private data.

## 1. Why hashing the JSON was not enough

The first Review Pack checked its own SHA-256 and reproduced the HTML bytes.
That catches accidental changes but not a deliberately revised JSON whose
author recomputes its hash. Such a report could have contradictory criterion
verdicts, wrong aggregate counts or false citation identities.

The Review Pack now runs a separate semantic audit, in addition to its file
hash and canonical JSON checks:

    python -m forexpro_ri.cli review audit --dir local_data/review-cohort
    python -m forexpro_ri.cli review verify --dir local_data/review-cohort

Both commands reject mutated source JSON and HTML; audit additionally prints
bounded checked-case, criterion, gap, citation, procedure and similar-case
counts. This is internal structural consistency, **not** proof that the
source-signing key was trusted by the owner, the original experiment existed,
the export was authorized, or the scientific verdict was correct. A privileged
attacker can synthesize and rehash an entirely fabricated self-consistent
report; this gate is not a substitute for source custody and human oversight.

### Reconciliation rules

* Only the known report schema, bounded fields and all-false authority map.
* Every experiment appears once and retains an exact entry and receipt digest.
* Recompute the cohort snapshot SHA from ordered experiment ID + entry and
  intake receipt identity triples.
* Every procedure has at most one aggregate result per experiment. The
  resulting state is FAIL if any criterion FAILs, otherwise PASS if criteria
  pass, NOT_EVALUABLE if a reason exists, otherwise UNOBSERVED.
* A recorded reason cannot coexist with evaluated criteria for a procedure.
* Every NOT_EVALUABLE and UNOBSERVED state has the corresponding visibility-gap
  descriptor, reason digest or absence marker.
* Procedure coverage reconciles to all case states; failure and not-evaluable
  evidence identities must identify exactly the affected experiments.
* Every displayed similar case links to another present experiment, with the
  actual shared negative-state set and a matching overlap fraction.
* Every Advisor citation matches a displayed experiment's exact identity,
  is unique within its topic, and points to recorded FAIL or NOT_EVALUABLE
  evidence for that particular procedure; pure UNOBSERVED gaps have no
  invented per-experiment negative citation.
* Topic IDs are unique and content, source class, interpretation and citations
  remain within the signed/synthetic/review-only contract.
* An empty report never becomes a hidden PASS; it has no cases, source digests,
  counts or topics.

Operator-declared expected procedures previously could be absent from the
Failure Intelligence aggregate when all experiments lacked that procedure.
The Review Pack now adds them as **all-UNOBSERVED** cohort rows. A missing
procedure is never renamed PASS or NOT_EVALUABLE.

## 2. Compare two verified snapshots

Every Research Review Pack is immutable once published. Compare a previous
and a current private snapshot:

    python -m forexpro_ri.cli review compare \
      --before local_data/review-old \
      --after local_data/review-new \
      --out local_data/review-progress.json

Both inputs must be locally stored, valid HTML+JSON packs. The destination
must be a **new private file** outside either original report directory.

The comparison verifies both packs first, then applies the append-only
Research Memory rule: all old experiment IDs with their same entry and
receipt digests must remain present in the new report. Records must not be
silently deleted or modified. The comparison explicitly rejects changes
between an unsigned synthetic, a signed synthetic test and a historical
signed-intake cohort class. Empty -> reviewed is supported; reviewed -> empty
is rejected.

Result sections include new record references, procedure count changes,
added Advisor topic IDs and topics no longer displayed. A new topic may
appear or disappear just because the operator changed expected procedure
declarations or the Advisor top-N view: it is **not** a new scientific finding.
Likewise, a repeated FAIL can have dependent data lineage; a new ID cannot
establish independent replication, a causal mechanism or a profit forecast.

This is **not** a synchronization protocol or an authorized live Core feed.
The FRI report does not create/alter closed experiments, submit research
questions or execute downstream Core jobs.

## 3. Full synthetic operator acceptance

For deterministic categorical statuses, signed ephemeral fixtures and
human-review commands (Python 3.12+):

    python -m forexpro_ri.cli review cohort-demo --out local_data/review-cohort
    python -m forexpro_ri.cli review verify --dir local_data/review-cohort
    python -m forexpro_ri.cli review audit --dir local_data/review-cohort
    python -m forexpro_ri.cli review benchmark \
      --dir local_data/review-cohort \
      --labels examples/review_cohort_gold.json
    python -m forexpro_ri.cli review study \
      --input examples/review_time_study_synthetic.json
    python -m forexpro_ri.cli review decision-template \
      --dir local_data/review-cohort --out local_data/review-decisions.json

A human can privately edit discussion/defer/reject choices; the decisions
remain SHA-bound annotations with no experiment registration or Core command.

The repository's Public-safe CI runs all these smoke checks, plus a negative
comparison that would remove 19 previously recorded synthetic experiments.
It also runs adversarial unit tests for recomputed hashes, altered criterion
states, changed aggregate counts, fabricated receipts, broken citation
identity and authority escalation. Passing those tests is **engineering**
qualification only. No private Core exports are used in public CI.

## 4. Remaining gates

* Current signer key and revocation status, source-owner export permission,
  retention and privacy release remain separate owner-controlled gates.
* Complete semantic truth of Advisor explanations is not established by
  structural citation checks. Optional LLM wording remains unverified.
* No researcher-time improvement is established without independent paired
  review. The included timing input is synthetic.
* Current FRI artifacts reside in Draft PR #20; the production integration
  of actual closed Core research remains BLOCKED pending the decisions in
  FRI issue #19.
