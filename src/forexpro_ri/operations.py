"""Offline operations: bounded atomic batch intake and reproducible advisory dossiers.

No runtime interaction with ForexPro, protected holdout, broker, or scientific state.
Public CI exercises only disposable synthetic fixtures.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .analysis import analyze, canonical_json
from .contracts import EvidenceError, _ID
from .dossier import build_dossier, render_markdown
from .memory import _canonical_entry, _connect, _load, _sha
from .provenance import audit, make_receipt, read_receipt

_MAX_BATCH = 50


def _prepare(bundle: Path, *, trust_store: Path | None, unsigned_synthetic: bool) -> dict[str, Any]:
    """Verify and convert one bounded bundle; never persist raw observation text."""
    if bundle.is_symlink() or not bundle.is_dir():
        raise EvidenceError('batch input must be a real bundle directory')
    expected = {'manifest.json', 'summary.json'} if unsigned_synthetic else {
        'manifest.json', 'summary.json', 'attestation.json'
    }
    if {p.name for p in bundle.iterdir()} != expected or any(
        not p.is_file() or p.is_symlink() for p in bundle.iterdir()
    ):
        raise EvidenceError('batch bundle must contain exactly the protocol files')
    if unsigned_synthetic:
        from .importer import import_bundle
        manifest, summary = import_bundle(bundle)
        if not manifest.experiment_id.startswith('SYNTHETIC-') or any(
            'synthetic' not in x['observation'].lower() for x in summary['criteria']
        ) or any('synthetic' not in x['reason'].lower() for x in summary['not_evaluable']):
            raise EvidenceError('unsigned batch intake is restricted to synthetic fixtures')
        verification = None
    else:
        from .attestation import verify_export
        assert trust_store is not None
        manifest, summary, verification = verify_export(bundle, trust_store)
    if {x['procedure'] for x in summary['criteria']} & {x['procedure'] for x in summary['not_evaluable']}:
        raise EvidenceError('same procedure cannot be evaluated and not evaluable')
    report = analyze(manifest, summary)
    criteria = [
        {'criterion_id': x['criterion_id'], 'procedure': x['procedure'], 'verdict': x['verdict'],
         'observation_sha256': _sha(x['observation'])} for x in summary['criteria']
    ]
    not_evaluable = [{'procedure': x['procedure'], 'reason_sha256': _sha(x['reason'])}
                     for x in summary['not_evaluable']]
    source = {
        'experiment_id': manifest.experiment_id,
        'source_revision': manifest.source_revision,
        'summary_sha256': manifest.summary_sha256,
        'report_sha256': report['report_sha256'],
        'disposition': summary['disposition'],
        'fail_count': report['counts']['fail'],
        'pass_count': report['counts']['pass'],
        'not_evaluable_count': report['counts']['not_evaluable'],
    }
    source['entry_sha256'] = _sha(canonical_json(_canonical_entry(source, criteria, not_evaluable)))
    receipt = make_receipt(manifest.experiment_id, source['entry_sha256'], verification)
    return {'source': source, 'criteria': criteria, 'not_evaluable': not_evaluable, 'receipt': receipt}


def ingest_batch(
    bundle_dirs: Sequence[str | Path], db_path: str | Path, *,
    trust_store: str | Path | None = None, allow_unsigned_synthetic: bool = False,
) -> dict[str, Any]:
    """Preverify every bundle, then atomically insert all or none into Research Memory.

    An existing database is fully validated before any new records are inserted.
    Identity collisions (including provenance collisions) abort the whole batch.
    """
    if not isinstance(bundle_dirs, (tuple, list)) or not 1 <= len(bundle_dirs) <= _MAX_BATCH:
        raise EvidenceError('batch must contain 1..50 explicitly selected bundles')
    if (trust_store is None) == (not allow_unsigned_synthetic):
        raise EvidenceError('select exactly one intake mode: trust_store or unsigned_synthetic')
    trust = Path(trust_store) if trust_store is not None else None
    bundles = [Path(b) for b in bundle_dirs]
    distinct = [b.resolve() for b in bundles]
    if len(set(distinct)) != len(distinct):
        raise EvidenceError('batch contains duplicate bundle path')
    db = Path(db_path)
    if any(db.resolve().is_relative_to(b) for b in distinct):
        raise EvidenceError('batch database may not reside inside a source bundle')
    prepared = [_prepare(b, trust_store=trust, unsigned_synthetic=allow_unsigned_synthetic) for b in bundles]
    ids = [p['source']['experiment_id'] for p in prepared]
    if len(set(ids)) != len(ids):
        raise EvidenceError('duplicate experiment_id in batch')
    prepared.sort(key=lambda p: p['source']['experiment_id'])
    conn = _connect(db, creating=True)
    try:
        conn.execute('BEGIN IMMEDIATE')
        current = conn.execute('SELECT experiment_id FROM experiments ORDER BY experiment_id').fetchall()
        if len(current) + len(prepared) > 5000:
            raise EvidenceError('batch exceeds bounded history limit')
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise EvidenceError('Research Memory database integrity failure')
        for row in current:
            _load(conn, row['experiment_id'])
        if trust is not None and current:
            for row in current:
                existing = conn.execute('SELECT entry_sha256 FROM experiments WHERE experiment_id=?',
                                        (row['experiment_id'],)).fetchone()
                if read_receipt(conn, row['experiment_id'], existing['entry_sha256'])['verification_status'] != 'SIGNATURE_VERIFIED':
                    raise EvidenceError('signed batch refuses existing unsigned or legacy history')
        results: list[dict[str, str]] = []
        for item in prepared:
            source = item['source']
            eid = source['experiment_id']
            previous = conn.execute('SELECT entry_sha256 FROM experiments WHERE experiment_id=?', (eid,)).fetchone()
            status = 'IMPORTED'
            if previous is not None:
                if previous['entry_sha256'] != source['entry_sha256']:
                    raise EvidenceError('conflicting immutable export for same experiment_id')
                _load(conn, eid)
                receipt = read_receipt(conn, eid, source['entry_sha256'])
                if receipt['receipt_sha256'] != item['receipt']['receipt_sha256']:
                    raise EvidenceError('conflicting immutable intake provenance for same experiment_id')
                status = 'ALREADY_PRESENT'
            else:
                conn.execute('INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)', tuple(source.values()))
                conn.executemany('INSERT INTO criteria VALUES (?, ?, ?, ?, ?)', [
                    (eid, c['criterion_id'], c['procedure'], c['verdict'], c['observation_sha256']) for c in item['criteria']
                ])
                conn.executemany('INSERT INTO not_evaluable VALUES (?, ?, ?)', [
                    (eid, c['procedure'], c['reason_sha256']) for c in item['not_evaluable']
                ])
                conn.execute('INSERT INTO intake_receipts VALUES (?, ?, ?, ?, ?, ?, ?, ?)', tuple(item['receipt'].values()))
            results.append({'experiment_id': eid, 'status': status, 'entry_sha256': source['entry_sha256'],
                            'receipt_sha256': item['receipt']['receipt_sha256'],
                            'verification_status': item['receipt']['verification_status']})
        conn.commit()
        result = {
            'schema_version': 1, 'report_kind': 'NON_AUTHORITATIVE_ATOMIC_INTAKE',
            'intake_mode': 'SIGNED' if trust is not None else 'SYNTHETIC_ONLY',
            'submitted_count': len(prepared), 'imported_count': sum(x['status'] == 'IMPORTED' for x in results),
            'already_present_count': sum(x['status'] == 'ALREADY_PRESENT' for x in results),
            'items': results, 'authority': {'scientific': False, 'holdout': False, 'promotion': False, 'broker': False},
        }
        result['report_sha256'] = hashlib.sha256(canonical_json(result).encode('utf-8')).hexdigest()
        return result
    except sqlite3.Error as exc:
        conn.rollback()
        raise EvidenceError(f'atomic batch write rejected: {exc}') from exc
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def readiness(db_path: str | Path, *, require_signed: bool = True) -> dict[str, Any]:
    """Local evidence status, NOT ForexPro scientific or exporter-authorization readiness."""
    from .memory import verify
    integrity = verify(db_path)
    provenance = audit(db_path)
    signed = provenance['all_intakes_have_signed_receipts']
    acceptable = (signed if require_signed else integrity['experiment_count'] > 0)
    result: dict[str, Any] = {
        'schema_version': 1,
        'report_kind': 'NON_AUTHORITATIVE_LOCAL_INTAKE_READINESS',
        'status': 'LOCAL_INTAKE_READY' if acceptable else 'NOT_READY',
        'require_signed': bool(require_signed),
        'integrity': integrity,
        'provenance_counts': provenance['counts'],
        'audit_report_sha256': provenance['report_sha256'],
        'experiment_count': provenance['experiment_count'],
        'source_platform_integrated': False,
        'export_authorization_verified': False,
        'scientific_approval': False,
        'holdout_access': False,
        'broker_authority': False,
        'limitations': [
            'Signature-verified means verified at import, not currently authorized or reverified.',
            'Local readiness only: source exporter authorization and scientific validity are outside FRI.',
            'Unsigned mode is synthetic-only and never acceptable for live integration.',
        ],
    }
    result['report_sha256'] = hashlib.sha256(canonical_json(result).encode('utf-8')).hexdigest()
    return result


def run(
    bundle_dirs: Sequence[str | Path], db_path: str | Path, output_dir: str | Path, *,
    trust_store: str | Path | None = None, allow_unsigned_synthetic: bool = False,
    expected_procedures: Sequence[str] = (), min_support: int = 2,
) -> dict[str, Any]:
    """Batch import + audit + per-experiment dossiers, publishing a new private folder.

    Intake is one SQLite transaction. Reports are committed *after* intake; a
    report I/O failure does not roll back the already committed intake. Rerunning
    identical bundles is safe and deterministic; choose a new output directory.
    """
    target = Path(output_dir)
    if target.is_symlink() or target.exists() or target.parent.is_symlink() or not target.parent.is_dir():
        raise EvidenceError('output directory must not exist and parent must be a real directory')
    if any(target.resolve().is_relative_to(Path(x).resolve()) for x in bundle_dirs):
        raise EvidenceError('output may not be placed inside a source bundle')
    if Path(db_path).resolve().is_relative_to(target.resolve()):
        raise EvidenceError('database may not be located inside new output directory')
    # Validate expected procedure list and support before any DB mutation.
    from .comparison import _validate_expected
    _validate_expected(expected_procedures)
    if type(min_support) is not int or not 2 <= min_support <= 5000:
        raise EvidenceError('min_support must be integer 2..5000')
    imported = ingest_batch(bundle_dirs, db_path, trust_store=trust_store,
                            allow_unsigned_synthetic=allow_unsigned_synthetic)
    check = readiness(db_path, require_signed=not allow_unsigned_synthetic)
    # A malformed or corrupted existing history fails closed in readiness/dossier.
    if check['status'] != 'LOCAL_INTAKE_READY':
        raise EvidenceError('post-intake readiness check failed; history remains committed')
    reports = {x['experiment_id']: build_dossier(
        db_path, focus_experiment_id=x['experiment_id'], expected_procedures=expected_procedures,
        min_support=min_support) for x in imported['items']}
    bundle_report = {
        'schema_version': 1,
        'report_kind': 'NON_AUTHORITATIVE_OPERATIONAL_RUN',
        'batch_report_sha256': imported['report_sha256'],
        'readiness_report_sha256': check['report_sha256'],
        'dossier_report_sha256': {eid: v['report_sha256'] for eid, v in sorted(reports.items())},
        'experiment_ids': sorted(reports),
        'source_platform_integrated': False,
        'scientific_approval': False,
        'authority': {'scientific': False, 'promotion': False, 'holdout': False, 'broker': False},
    }
    bundle_report['report_sha256'] = hashlib.sha256(canonical_json(bundle_report).encode('utf-8')).hexdigest()
    # Prevent mixing snapshots if another writer committed during dossier generation.
    if readiness(db_path, require_signed=not allow_unsigned_synthetic)['report_sha256'] != check['report_sha256']:
        raise EvidenceError('history changed during dossier construction; retry with fresh output path')
    files = {
        'intake.json': json.dumps(imported, indent=2, sort_keys=True) + '\n',
        'readiness.json': json.dumps(check, indent=2, sort_keys=True) + '\n',
        'run.json': json.dumps(bundle_report, indent=2, sort_keys=True) + '\n',
    }
    for eid, dossier in sorted(reports.items()):
        # Use digest-safe filenames rather than untrusted experiment ID/path content.
        safe_id = hashlib.sha256(eid.encode('utf-8')).hexdigest()[:20]
        files[f'dossier-{safe_id}.json'] = json.dumps(dossier, indent=2, sort_keys=True) + '\n'
        files[f'dossier-{safe_id}.md'] = render_markdown(dossier)
    artifacts = [{'name': name, 'size_bytes': len(value.encode('utf-8')),
                  'sha256': hashlib.sha256(value.encode('utf-8')).hexdigest()}
                 for name, value in sorted(files.items())]
    manifest = {'schema_version': 1, 'report_kind': 'NON_AUTHORITATIVE_LOCAL_FILE_INTEGRITY',
                'artifacts': artifacts, 'run_report_sha256': bundle_report['report_sha256'],
                'authority': 'NONE'}
    manifest['manifest_sha256'] = hashlib.sha256(canonical_json(manifest).encode('utf-8')).hexdigest()
    files['artifacts.json'] = json.dumps(manifest, indent=2, sort_keys=True) + '\n'
    staging = Path(tempfile.mkdtemp(prefix='.fri-operations-', dir=target.parent))
    try:
        staging.chmod(0o700)
        for name, content in files.items():
            with (staging / name).open('x', encoding='utf-8') as stream:
                stream.write(content)
            (staging / name).chmod(0o600)
        if target.exists() or target.is_symlink():
            raise EvidenceError('output target appeared during generation')
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return {'status': 'OPERATIONAL_RUN_COMPLETE', 'intake': imported, 'readiness': check['status'],
            'run_report_sha256': bundle_report['report_sha256'], 'report_count': len(files),
            'output_directory': str(target), 'source_platform_integrated': False}


def verify_report_dir(directory: str | Path) -> dict[str, Any]:
    """Check local report files match their run-time hashes; NOT authentication.

    The manifest is untrusted and self-hashed only: a privileged user can
    replace both content and manifest. Do not treat this as digital signing.
    """
    root = Path(directory)
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError('report directory must be a real directory')
    manifest_path = root / 'artifacts.json'
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 1024 * 1024:
        raise EvidenceError('report manifest missing or invalid')
    try:
        from .importer import _decode
        manifest = _decode(manifest_path.read_bytes(), 'artifacts.json')
    except OSError as exc:
        raise EvidenceError('cannot read report manifest') from exc
    if set(manifest) != {'schema_version', 'report_kind', 'artifacts', 'run_report_sha256', 'authority', 'manifest_sha256'}:
        raise EvidenceError('invalid report manifest fields')
    if type(manifest['schema_version']) is not int or manifest['schema_version'] != 1 or manifest['report_kind'] != 'NON_AUTHORITATIVE_LOCAL_FILE_INTEGRITY' or manifest['authority'] != 'NONE':
        raise EvidenceError('invalid report manifest kind')
    expected_hash = manifest['manifest_sha256']
    unsigned = {k: v for k, v in manifest.items() if k != 'manifest_sha256'}
    if not isinstance(expected_hash, str) or hashlib.sha256(canonical_json(unsigned).encode('utf-8')).hexdigest() != expected_hash:
        raise EvidenceError('report manifest digest mismatch')
    artifacts = manifest['artifacts']
    if not isinstance(artifacts, list) or not 3 <= len(artifacts) <= 103:
        raise EvidenceError('invalid report artifact list size')
    listed: set[str] = set()
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {'name', 'size_bytes', 'sha256'}:
            raise EvidenceError('invalid report artifact record')
        name = item['name']
        if not isinstance(name, str) or not name or name in listed or not (
            name in {'intake.json', 'readiness.json', 'run.json'} or
            name.startswith('dossier-') and (name.endswith('.md') or name.endswith('.json'))
        ) or '/' in name or '\\' in name or name in {'.', '..'} or '..' in name:
            raise EvidenceError('unsafe or duplicate report artifact name')
        listed.add(name)
        path = root / name
        if path.is_symlink() or not path.is_file() or type(item['size_bytes']) is not int or not 0 <= item['size_bytes'] <= 4 * 1024 * 1024 or path.stat().st_size != item['size_bytes']:
            raise EvidenceError('report artifact missing or size mismatch')
        if not isinstance(item['sha256'], str) or len(item['sha256']) != 64 or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']:
            raise EvidenceError('report artifact digest mismatch')
    if not {'intake.json', 'readiness.json', 'run.json'} <= listed:
        raise EvidenceError('mandatory report artifacts missing')
    all_files = {p.name for p in root.iterdir()}
    if all_files != listed | {'artifacts.json'}:
        raise EvidenceError('unexpected or missing files in report directory')
    run_path = root / 'run.json'
    run_doc = _decode(run_path.read_bytes(), 'run.json')
    report_hash = run_doc.get('report_sha256')
    if not isinstance(report_hash, str) or report_hash != manifest['run_report_sha256']:
        raise EvidenceError('run report digest disagreement')
    unsigned_run = {k: v for k, v in run_doc.items() if k != 'report_sha256'}
    if hashlib.sha256(canonical_json(unsigned_run).encode('utf-8')).hexdigest() != report_hash:
        raise EvidenceError('run report internal hash mismatch')
    return {'status': 'LOCAL_FILES_INTACT', 'report_kind': 'NON_AUTHORITATIVE_LOCAL_INTEGRITY_CHECK',
            'artifact_count': len(artifacts), 'manifest_sha256': expected_hash,
            'run_report_sha256': report_hash, 'cryptographically_authenticated': False,
            'scientific_approval': False}
