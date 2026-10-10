# FRI v2.9 — hermetic end-to-end synthetic recipient qualification

**Status: REVIEW CANDIDATE / SYNTHETIC ONLY / NO REAL INGESTION OR EXPORT.**

This is a single cohesive release-qualification rehearsal **stacked on**
[FRI Draft #17](https://github.com/KornutaKM/forexpro-research-intelligence/pull/17)
and [Draft #16](https://github.com/KornutaKM/forexpro-research-intelligence/pull/16).
It does not promote either draft to production. The private Core scientific
authority boundary and the FRI-TRUST-01…10 unresolved decisions in
[Core Issue #518](https://github.com/KornutaKM/1111222/issues/518) are
unchanged.

## User-facing entrypoint

```sh
python -m forexpro_ri.cli integration qualification
```

**No arguments and no input paths are accepted.** The command allocates a
fresh temporary directory, generates four Ed25519 **test** keys in memory
(two recipient operator keys, two exporter keys), and creates two
explicitly `SYNTHETIC-` signed three-file protocol bundles. The signer
public trust file is independently located within the temporary sandbox,
never inside a submitted evidence bundle. One test exporter is ACTIVE,
the other REVOKED. Neither private key is written to disk.

## End-to-end gates actually exercised

1. **Candidate v1 scientific report shape:** ten exact procedure kinds,
   one recorded `FAIL` per study, `CLOSED_UNSUCCESSFUL`, no
   `not_evaluable`, exact fixed candidate phrases from private Core
   PR #526, catalog digest
   `7dbe7ec841bc15262051128d55c2ec4ce2673ce1034d3740d7c0679083eff8d5`.
   **This is an unapproved phrase candidate, not DLP approval.**
2. **Cryptographic recipient provenance consistency:** signed FRI v1
   three-file bundles, *synthetic* operator checkpoint history
   sequence 1→2, explicit key epoch 1→2 rotation, retirement of the old
   operator and revocation of the second exporter, signed trust-store
   raw-byte SHA and externally **test caller**-pinned latest head/floor.
3. **Research Memory lifecycle in a disposable SQLite DB:** both bundles
   imported with the **signed** protocol, verified as two recorded studies;
   reimport of the first is `ALREADY_PRESENT`, not a new observation.
   This is **synthetic test ingestion**, never approval to import real
   source records.
4. **Research Advisor + quality:** two historical failures under
   `OUT_OF_SAMPLE` produce a repeated-failure prospective question
   (not causal proof or source science). The Advisor is signed-only,
   all scientific/trading authority is false, and the quality gate
   reports `PASS` without claiming model semantic truth.
5. **Recovery and continuity:** snapshot the disposable Research Memory,
   verify backup, restore only into a *new* database, verify the restored
   research count and identical Advisor evidence hash; trying to
   overwrite the live database fails closed.
6. **Adversarial recovery drills:** with the good Memory unchanged,
   reject an old checkpoint, an independent generation floor beyond the
   latest checkpoint, a revived revoked exporter/trust file rollback,
   mutated signed summary bytes and duplicate study identities. Recheck
   the original two studies and the restored trust chain afterward.
   A qualified run returns aggregate counts only; all private paths,
   experiments, key identifiers and observation strings are omitted.

The adversarial gate is an all-or-nothing **synthetic test result**, not
a durable transaction or per-record delivery approval. Temporary files,
including database, signed bundles and test public keys, are deleted when
the command exits (also on exceptions). No production secrets, protected
data, model API, network transport, MT5 or Core adapter are used.

## Explicit limitations

A caller who controls the test keyset, the supposedly independent head
pin and the test fixtures can construct a wholly consistent synthetic
history. This is **not** an authenticated latest production owner record
or approved current declassification. The report's fields
`candidate_dictionary_approved`, `real_source_closure_authenticated`,
`independent_operator_custody_proven`, `current_export_authorization`,
`real_ingestion_approved`, `scientific_approval`, `holdout_access`,
`broker_authority` and `same_campaign_feedback_authority` always
remain literal `false`.

Passing the drill does not open the live source, approve `CLOSED_INCOMPLETE`,
alter S1/S2 or HOLDOUT, or turn a draft dictionary into permitted prose.
It cannot be used as an attestation token for actual private export.
The operational work remains: privately governed source of terminal closure,
immutable current source snapshot, independently controlled current trust
roots and revocation, source owner/security classification approval,
per-record human release, retention, auditable delivery and a separate
no-go/go-live decision.

## Tests and CI

```sh
python -m unittest discover -s tests -p test_synthetic_qualification.py -v
python -m unittest discover -s tests -v
python -m forexpro_ri.cli integration qualification
```

The added dedicated `FRI v2.9 Hermetic Synthetic Qualification` workflow
runs this test suite plus the CLI on the repository's PR head without
production keys or external source access. The existing FRI Public-safe
CI and prior v2.7/v2.8 dedicated gates remain required. All pass
conditions are **engineering evidence only**, not export eligibility.
