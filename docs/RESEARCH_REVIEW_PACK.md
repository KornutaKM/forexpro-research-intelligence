# Research Review Pack — Issue #19 P0

This is a public-code, private-runtime, offline, read-only operator report. It
composes FRI's existing signed intake verification, append-only Research Memory,
provenance audit, Failure Intelligence, Research Dossier, Research Advisor and
structural quality checks. It does not replace any of those modules.

## One-command signed synthetic demonstration

Run from the FRI source checkout after installation (Python 3.12+):

    python -m pip install -e .
    python -m forexpro_ri.cli review demo --out local_data/review-demo
    python -m forexpro_ri.cli review verify --dir local_data/review-demo

Open local_data/review-demo/index.html locally, not through a hosted site.
The paired review.json is deterministic; verify recomputes its report hash
and checks byte identity with the HTML renderer. The demo uses an ephemeral
Ed25519 TEST key and one synthetic, signed, unsuccessful research fixture. It
does not assert independent replication; similar-case lists are empty unless
the local Research Memory contains other eligible entries.

The demo's public trust key, signed synthetic bundle and SQLite database exist
only in a temporary directory and are removed on exit. Only the operator-selected
output directory remains. The test signature does not give export, scientific,
HOLDOUT, promotion or trading permission.

## Review existing locally imported closed research

Only after separately approved operator intake into private Research Memory:

    python -m forexpro_ri.cli review pack \
      --db /private/local_data/research.sqlite \
      --out /private/reports/review-001 \
      --expected-procedure MONTE_CARLO \
      --expected-procedure REGIME_STABILITY
    python -m forexpro_ri.cli review verify --dir /private/reports/review-001

The default is signed-only at historical intake. Signatures authenticate
bytes against the then-configured trust store; they never prove current key
status, export permission, data classification or scientific correctness. FRI
does not independently establish current authority. Actual Core exports remain
blocked pending the owner decisions in Issue #19.

For independently constructed synthetic examples only, one may explicitly
pass --unsigned-synthetic to the pack subcommand. That mode requires all
stored experiment IDs to start with SYNTHETIC-, rejects legacy receipts and
labels the result SYNTHETIC_DEMONSTRATION. This is not a data-loss-prevention
guarantee and must not be used for real results.

## What the report shows

* Procedure coverage: separate FAIL, PASS, NOT_EVALUABLE and UNOBSERVED columns.
  Missing procedure observations are not counted as PASS.
* Advisor questions for NEW preregistered experiments, with stable item ID,
  reported basis, evidence sample, SHA-256 entry and receipt identities,
  explicit source-visibility status, and local read-only dossier anchors.
* Per-experiment dossiers: recorded disposition, procedure states, individual
  criterion digest references, not-evaluable reason digests, and recorded
  similar negative signatures. Similarity does not prove causal mechanisms
  or independent replication.
* Explicit limitations and an all-false authority declaration.
* An unambiguous NO_ELIGIBLE_DATA page for missing or empty approved local
  Research Memory, without inventing evidence.

The report contains no raw observation prose, local DB path, dataset,
strategy parameters, source credentials, brokerage data, or external web calls.
Output is HTML without JavaScript or external CSS. Untrusted values are escaped
before insertion into HTML. The renderer is not a general-purpose HTML sandbox;
do not add raw HTML fragments or remote assets.

## Integrity, privacy and concurrency

The pack checks all intake receipts and source hashes, cross-checks Advisor and
Dossier snapshot identities, validates sampled citations against the audited
local Research Memory, and repeats the provenance audit at the end. If provenance
changes during compilation it fails rather than mixing snapshots. This is an
optimistic read consistency gate, not a global database transaction and not
protection against privileged rewriting of the entire SQLite database.

Pack creation is bounded to 100 experiments to prevent uncontrolled fanout
when building individual dossiers. Larger cohorts require an independently
reviewed paging/snapshot design; do not silently drop cases. The output directory
must not already exist; two files are written in a private staging directory and
published together by directory rename. Protect the parent directory against
untrusted concurrent writers and use a private filesystem.

Review verify detects post-publication modifications that do not preserve the
source-linked report digest and HTML identity. Because SHA-256 is unkeyed, it
cannot authenticate a fully re-forged report, current custody, or owner permission.
The operator must retain trusted independent copies of source approvals.

## Safety boundaries

* No strategy creation, backtesting, data collection, optimization, or trade execution.
* No source Core write, HOLDOUT, PROJECT VALIDATION, promotion or broker access.
* No CSV preview conversion into scientific Research Memory.
* No authorization or independence inferred from signatures or experiment IDs.
* Human acceptance or rejection of proposed research questions remains mandatory.
* Only synthetic fixtures may be used in public CI. Keep real reports and
  private SQLite state out of GitHub repositories and logs.

For the two-lane exchange policy, see CORE_INTEROPERABILITY_LANES.md.


## Private, SHA-bound human review decisions

A Research Review Pack is a recommendation to a researcher, not an instruction
for the research engine. A separate private *human decision sidecar* allows
reviewing each generated question as a discussion candidate:

    python -m forexpro_ri.cli review decision-template \
      --dir local_data/review-cohort \
      --out local_data/operator-decisions-input.json

Edit the input file locally. Every item must retain its exact item_id and
the source_pack_sha256 must match the immutable Review Pack. Each decision
is one of:

| Choice | Allowed bounded reason code |
| --- | --- |
| DEFER | PENDING_REVIEW or NEEDS_INDEPENDENT_REVIEW |
| ACCEPT_FOR_DISCUSSION | NEW_EXPERIMENT_QUESTION or EVIDENCE_GAP_FOR_REVIEW |
| REJECT | DUPLICATE_PRIOR_WORK, UNSUPPORTED_OR_UNACTIONABLE or NEEDS_INDEPENDENT_REVIEW |

The operator must review **all** topics: missing or duplicate topic IDs are
rejected. The final validation command writes a separate private JSON file:

    python -m forexpro_ri.cli review decisions \
      --dir local_data/review-cohort \
      --input local_data/operator-decisions-input.json \
      --out local_data/operator-decisions-reviewed.json

This command verifies the original JSON and HTML, binds every choice to that
exact report SHA, checks choice/reason compatibility, and creates a new file
with restrictive local permissions. It never updates the Review Pack or
Research Memory and makes no Core request. ACCEPT_FOR_DISCUSSION is **not**
scientific admission, a preregistered experiment, permission to run a trial,
or authority over Core execution.

This self-reported sidecar does not authenticate a reviewer identity, provide
a signature, or prove consent. Use the organization's separate independent
review/custody process where identity attribution is required. No personal
names, free-text explanations, private paths, strategy parameters or raw
observations belong in the sidecar.
