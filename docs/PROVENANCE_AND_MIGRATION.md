# FRI v0.9 — historical intake provenance & operational readiness

## Three deliverables

1. **Verified-at-import receipts:** a schema-v2 `intake_receipts` row is
   inserted atomically with every new closed experiment. It binds the entry's
   SHA-256 to the historical verifier result. For signed bundles it stores
   only the signer **public key ID**, the public-key fingerprint, and SHA-256
   digests of the attestation and manifest. It does not retain signatures,
   raw observations, private signing keys, trading credentials, or bundles.
2. **Conservative version migration:** upgrading a version-1 database first
   verifies all existing entry hashes and counts; old entries become
   `LEGACY_UNATTESTED`. Signed status cannot be reconstructed. Upgrade is
   transactional. A conflicting later signed re-import is refused rather
   than silently promoting a preexisting legacy row.
3. **Operational audit:** `memory audit` checks SQLite/foreign-key and entry
   integrity and summarizes historical receipt statuses deterministically.
   `--require-signed` rejects empty, unsigned or legacy history.
   Research Dossiers include focus provenance and bind all receipt hashes
   into their local memory snapshot checksum.

## Offline commands

```bash
# Back up and protect a real local database OUTSIDE any public GitHub repo.
cp /private/research.sqlite /private/research.sqlite.backup
python -m forexpro_ri.cli memory migrate --db /private/research.sqlite
python -m forexpro_ri.cli memory verify --db /private/research.sqlite
python -m forexpro_ri.cli memory audit --db /private/research.sqlite
python -m forexpro_ri.cli memory audit --db /private/research.sqlite --require-signed
```

`--require-signed` returns failure when even one record is unsigned or legacy.
**Do not** equate an all-signed memory with an authorized ForexPro export, a
freshly valid key, scientific acceptance, evidence completeness, or broker
approval. Signed import only authenticates the attached bundle against a
local operator-provisioned key **at that moment**.

## Threat model and limitations

- A detached Ed25519 signature is verified once against the trust store at
  intake; the SQLite receipt is **not itself cryptographically signed**.
- A key revoked *after* import remains historically reported as verified-at-
  import. A future operator would need original bundles, detached signatures,
  and a current trust store for complete revalidation. FRI intentionally stores
  none of those source contents.
- SQLite triggers and SHA-256 detect ordinary/accidental modifications. A
  privileged local attacker who can rewrite the database, disable triggers,
  and recompute all hashes can forge the history. Protect backups and consider
  a separately governed external anchor for tamper-evident operation.
- `--unsigned-synthetic` and Python `allow_unsigned_synthetic=True` are
  **test-only** escape hatches. Labels do not provide actual sanitization;
  never pass real data to them.
- FRI does not examine ForexPro Core, handle MT5 orders, re-run PROJECT
  VALIDATION, access HOLDOUT, or change scientific state.
- To integrate actual ForexPro later, an exporter under the private Core's
  authority must enforce closure state, artifact allowlist, sanitization,
  individual permission and signed custody outside this public repository.

## Acceptance checks (offline, synthetic only)

- Signed imports create one receipt bound to experiment entry, and idempotent
  replay does not alter it.
- Unsigned input fails by default in both CLI and Python API; explicitly
  labeled synthetic input is recorded as unsigned, never signed.
- Unknown/revoked keys, altered signatures and conflicting claims fail closed.
- Missing or tampered receipt is detected even if an attacker drops an UPDATE
  trigger, provided they cannot forge/recompute all digest fields.
- v1 migration preserves history but never retroactively signs it; corrupted
  legacy history blocks migration.
- `memory audit --require-signed` fails for legacy, unsigned or empty memory.
- Research Dossier marks historical signed status, not current authorization.
