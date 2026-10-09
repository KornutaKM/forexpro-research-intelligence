# FRI v1.1 — Research Memory backup, restore, recovery drills

FRI is an offline advisory research companion, not scientific authority.
Backups are **private operational artifacts**, not public CI outputs, and
contain experiment identities, recorded verdicts, digest metadata, historical
signer identifiers and receipt checksums. They never contain observation prose
or signing private keys, but may still disclose proprietary research metadata.

## Commands

```bash
# Back up committed state using the SQLite Online Backup API (safe with WAL):
python -m forexpro_ri.cli recovery backup --db local_data/research.sqlite --out private_backups/snapshot-001

# Reject any altered bytes, schema inconsistencies or provenance mismatches:
python -m forexpro_ri.cli recovery verify --dir private_backups/snapshot-001

# Restore to a NEW database only. The command NEVER overwrites a live DB:
python -m forexpro_ri.cli recovery restore --dir private_backups/snapshot-001 --db local_data/recovered.sqlite

# Rehearse backup + verify + restore inside a temporary private directory:
python -m forexpro_ri.cli recovery drill --db local_data/research.sqlite
```

The caller must create `private_backups/` and `local_data/` beforehand. Snapshot
directories and files are created with restrictive Unix permissions (`0700`
for the directory and `0600` for its children). Files have deterministic names:
`memory.sqlite` and `manifest.json`. The manifest includes SHA-256 of the
SQLite bytes, memory schema version, observed experiment count, saved
historical intake-provenance counts, provenance audit hash, and **zero
scientific/broker authority**. No filesystem path to the source DB is included
in the manifest.

## Constraints

- **Non-overwriting:** existing snapshot or restored database targets are refused.
  Restores use an exclusive hard-link operation to protect against a target
  appearing between the existence check and installation.
- **Bounded:** a snapshot must be at most 1 GiB. Restore and verification reject
  symlinks and unexpectedly shaped snapshot directories.
- **Consistent:** SQLite Online Backup includes committed WAL pages and excludes
  uncommitted transactions. The snapshot is converted to DELETE journal mode so
  the portable archive contains one self-contained database file.
- **Validating:** all existing experiments and historical receipts are checked,
  not just SQLite page integrity, before the backup can be considered valid.
- **Provenance preserving:** an unsigned/legacy historical record remains
  unsigned/legacy after restoration. Recovery cannot confer approval or trust.
- **Fail closed:** restore target is never replaced. Backup directory creation
  uses a private staging directory and then a rename; on filesystems allowing
  concurrent directory creation a destination race may exist. Operators should
  use a private single-writer backup parent directory.
- **Not authenticated:** checksums detect ordinary accidental changes, but a
  malicious person with write access to both the snapshot and manifest can
  replace both. Use independently secured and encrypted storage plus external
  signed inventory for actual retention or remote transfers.
- **No automatic cutover:** restored databases require manual approval before
  being used operationally. Neither this tool nor FRI accesses ForexPro Core.

## Recovery drill and acceptance criteria

The `drill` command creates an ephemeral online backup, verifies the manifest,
restores a second standalone SQLite database, re-runs semantic checks and
compares provenance hashes. It does not replace or edit the original DB. A
successful drill says only that **local storage is recoverable**, not that
research has been validated or export permission approved.

Tests include WAL-committed records, uncommitted exclusions, corruption,
truncated/mutated manifests, schema tampering, dangling symlinks, pre-existing
targets, and round-trip retention of audit status. Public GitHub Actions use
only synthetic fixtures and disposable SQLite files.
