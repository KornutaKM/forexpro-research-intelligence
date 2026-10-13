# FRI Operator Triage and Peer-Review Disagreement

Status: synthetic-only engineering qualification, built for FRI issue #19,
Draft PR #20. No owner-approved Core exporter or human identity attestation.
This feature does **not** validate the scientific truth of closed experiments.

## A. Evidence-first operator dashboard

Run the signed 20-case synthetic exercise and inspect it offline:

    python -m forexpro_ri.cli review cohort-demo --out local_data/cohort-brief
    python -m forexpro_ri.cli review triage --dir local_data/cohort-brief
    python -m forexpro_ri.cli review audit --dir local_data/cohort-brief

The main index.html shows an **Operator evidence triage** section before the
full coverage and Advisor questions. The triage also returns deterministic
JSON on stdout without writing outside the local pack. It is computed from
the complete verified report, never from LLM predictions.

Ordering (within each category by missing evidence and then observed FAILs)
is strictly **researcher attention**:

1. MISSING_RECORDED_EVIDENCE — at least one UNOBSERVED outcome
2. RECORDED_NOT_EVALUABLE — a recorded inability to evaluate
3. RECORDED_FAILURE_REVIEW — recorded FAIL, without those two gaps
4. NO_RECORDED_NEGATIVE_OR_GAP — no recorded negative or gap in the displayed
   operator-declared procedure set

A procedure can simultaneously have FAIL, NOT_EVALUABLE and UNOBSERVED across
different stored experiments. Only its **first matching attention class**
determines the table position; all four categorical counts remain visible.

Every procedure has at most four example links to the corresponding local
read-only dossiers with experiment ID, entry SHA-256, receipt SHA-256 and
recorded state. A truncation flag explicitly warns when the sample does not
cover all affected cases. Topic IDs for existing Advisor questions remain
linked without turning missing procedure states into fabricated direct
negative-evidence citations.

An all-UNOBSERVED procedure is *not* a failed scientific test, a PASS or proof
that the source contract required the procedure. Expected procedure names
can be **operator-declared**. The exported triage is non-authoritative and
never ranks expected returns, edge quality, strategy or causal importance.

## B. Two independent human review *documents*, not proven identities

To prepare two private discussion decision sets on the **same** immutable pack:

    python -m forexpro_ri.cli review decision-template \
      --dir local_data/cohort-brief --out local_data/reviewer-a-input.json
    python -m forexpro_ri.cli review decision-template \
      --dir local_data/cohort-brief --out local_data/reviewer-b-input.json

Each reviewer must edit their own file, using only DEFER,
ACCEPT_FOR_DISCUSSION or REJECT and the enumerated reason codes. Then produce
the separately verified SHA-bound sidecars:

    python -m forexpro_ri.cli review decisions \
      --dir local_data/cohort-brief \
      --input local_data/reviewer-a-input.json \
      --out local_data/reviewer-a-checked.json
    python -m forexpro_ri.cli review decisions \
      --dir local_data/cohort-brief \
      --input local_data/reviewer-b-input.json \
      --out local_data/reviewer-b-checked.json

Finally compare them without revealing reviewer names:

    python -m forexpro_ri.cli review agreement \
      --dir local_data/cohort-brief \
      --left local_data/reviewer-a-checked.json \
      --right local_data/reviewer-b-checked.json \
      --out local_data/reviewer-disagreements.json

Comparison validates the source report's exact HTML+JSON, recalculates every
decision sidecar from its approved topic choices, requires exact pack SHA
matching and checks all sidecar digests/authority flags. It reports the
number of matching choices, number with matching choice *and* reason, plus
topic IDs and bounded disagreement reason codes.

The result **always** requires human reconciliation. If both sidecars are
byte-identical, comparison is **rejected**: identical content does not prove
that two separate people performed reviews. Even differing content does not
establish identity or independence. Use a separate organization-approved
custody/identity process for the real study.

The output is new private JSON (creation-only), outside the original pack.
No commands, experiment registration, promotion, HOLDOUT, Core writes, broker
access, or network activity occur. Discussion agreement does not authorize a
new study; registration remains an independent human-controlled process.

## C. Acceptance limits

Unit tests intentionally reject malformed and stale sidecars, tampered
reported hashes, unsupported execution choices, files written inside the
original pack, symlinks and duplicate inputs. Public-safe CI uses only
synthetic ephemeral signing material. No real Core evidence or private
researcher details belong in GitHub, stdout or public CI artifacts.

No end-to-end data release from Core has been authorized. The proof boundary
is structural: report/citation/decision consistency, not semantic truth,
current signer revocation or authorized source export. Independent human
study remains necessary before claiming reduced analysis time.
