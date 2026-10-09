"""Deterministic study-design worklist, derived from a verified read-only snapshot.

Ranks *questions to examine*, never trading strategies or scientific results.
Distinct experiment counts are descriptive: replication and causality are unknown.
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

from .analysis import canonical_json
from .comparison import _validate_expected
from .contracts import EvidenceError
from .failure_intelligence import _QUESTIONS
from .memory import _connect, _load
from .provenance import make_receipt, read_receipt

MAX_EXPERIMENTS = 5000
MAX_ITEMS = 30
_KINDS = {'EVIDENCE_GAP': 0, 'REPEATED_NOT_EVALUABLE': 1, 'REPEATED_FAILURE': 2}


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def build_research_program(db_path: str | Path, *, expected_procedures: Sequence[str] = (),
                           min_support: int = 2, max_items: int = 20,
                           allow_unsigned_synthetic: bool = False) -> dict[str, Any]:
    """Build an immutable-evidence-linked advisory worklist in one DB snapshot.

    Signed-only by default; historical intake signatures are NOT reverified.
    """
    expected = _validate_expected(expected_procedures)
    if type(min_support) is not int or not 2 <= min_support <= MAX_EXPERIMENTS:
        raise EvidenceError('min_support must be an integer from 2 to 5000')
    if type(max_items) is not int or not 1 <= max_items <= MAX_ITEMS:
        raise EvidenceError('max_items must be an integer from 1 to 30')
    if type(allow_unsigned_synthetic) is not bool:
        raise EvidenceError('synthetic mode must be boolean')

    conn = _connect(db_path, creating=False)
    try:
        conn.execute('BEGIN')
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise EvidenceError('Research Memory integrity check failed')
        if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise EvidenceError('Research Memory foreign key integrity failed')
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        ids = [r['experiment_id'] for r in conn.execute(
            'SELECT experiment_id FROM experiments ORDER BY experiment_id').fetchall()]
        if not ids:
            raise EvidenceError('cannot prioritize an empty Research Memory')
        if len(ids) > MAX_EXPERIMENTS:
            raise EvidenceError('too many experiments for bounded research program')

        records = {eid: _load(conn, eid) for eid in ids}
        receipts = {eid: (read_receipt(conn, eid, records[eid]['entry_sha256'])
                          if version == 2 else make_receipt(eid, records[eid]['entry_sha256'], legacy=True))
                    for eid in ids}
        origin = Counter(r['verification_status'] for r in receipts.values())
        if not allow_unsigned_synthetic and (version != 2 or origin['SIGNATURE_VERIFIED'] != len(ids)):
            raise EvidenceError('research program requires wholly signed intake history; --unsigned-synthetic is for fixture testing only')

        states: dict[str, dict[str, str]] = {eid: {} for eid in ids}
        for row in conn.execute('SELECT experiment_id,procedure,verdict FROM criteria '
                                'ORDER BY experiment_id,procedure,criterion_id'):
            current = states[row['experiment_id']]
            if row['verdict'] == 'FAIL':
                current[row['procedure']] = 'FAIL'
            elif current.get(row['procedure']) != 'FAIL':
                current[row['procedure']] = 'PASS'
        for row in conn.execute('SELECT experiment_id,procedure FROM not_evaluable '
                                'ORDER BY experiment_id,procedure'):
            current = states[row['experiment_id']]
            if row['procedure'] in current:
                raise EvidenceError('conflicting procedure evaluability')
            current[row['procedure']] = 'NOT_EVALUABLE'

        procedures = sorted(set(expected) | {p for values in states.values() for p in values})
        refs = {eid: {'experiment_id': eid, 'entry_sha256': records[eid]['entry_sha256'],
                      'receipt_sha256': receipts[eid]['receipt_sha256']} for eid in ids}
        coverage = []
        worklist = []
        for procedure in procedures:
            groups = {status: [eid for eid in ids if states[eid].get(procedure, 'UNOBSERVED') == status]
                      for status in ('FAIL', 'PASS', 'NOT_EVALUABLE', 'UNOBSERVED')}
            coverage.append({
                'procedure': procedure, 'operator_expected': procedure in expected,
                'counts': {status.lower(): len(members) for status, members in groups.items()},
            })
            for kind, status in (('REPEATED_FAILURE', 'FAIL'),
                                 ('REPEATED_NOT_EVALUABLE', 'NOT_EVALUABLE')):
                if len(groups[status]) >= min_support:
                    worklist.append({
                        'kind': kind, 'procedure': procedure,
                        'affected_experiment_count': len(groups[status]),
                        'cohort_experiment_count': len(ids),
                        'evidence': [refs[eid] for eid in groups[status]],
                        'prospective_question': _QUESTIONS.get(procedure,
                            'For a NEW preregistered experiment, review this recorded procedure outcome.'),
                        'basis': 'RECORDED_CLOSED_EXPERIMENT_OUTCOMES',
                    })
            if procedure in expected:
                missing = groups['NOT_EVALUABLE'] + groups['UNOBSERVED']
                if missing:
                    worklist.append({
                        'kind': 'EVIDENCE_GAP', 'procedure': procedure,
                        'affected_experiment_count': len(missing),
                        'cohort_experiment_count': len(ids),
                        'evidence': [refs[eid] for eid in sorted(missing)],
                        'prospective_question': 'For a NEW preregistered experiment, specify how this operator-expected procedure will yield assessable evidence.',
                        'basis': 'OPERATOR_DECLARED_EXPECTATION_NOT_SOURCE_CONTRACT',
                    })

        # Navigational ordering only. Not an effectiveness, trading, or causality score.
        worklist.sort(key=lambda item: (_KINDS[item['kind']], -item['affected_experiment_count'], item['procedure']))
        snapshot = _digest({'entries': [refs[eid] for eid in ids]})
        report = {
            'schema_version': 1,
            'report_kind': 'NON_AUTHORITATIVE_RESEARCH_PROGRAM',
            'memory_snapshot_sha256': snapshot,
            'observed_experiment_count': len(ids),
            'operator_expected_procedures': expected,
            'min_support': min_support,
            'max_items': max_items,
            'provenance_counts': {x.lower(): origin[x] for x in ('SIGNATURE_VERIFIED','UNSIGNED_SYNTHETIC','LEGACY_UNATTESTED')},
            'signed_only_gate_passed': version == 2 and origin['SIGNATURE_VERIFIED'] == len(ids),
            'procedure_coverage': coverage,
            'worklist': worklist[:max_items],
            'worklist_truncated': len(worklist) > max_items,
            'total_worklist_items': len(worklist),
            'authority': {'scientific': False, 'holdout': False, 'promotion': False, 'broker': False},
            'limitations': [
                'The worklist prioritizes review topics using a fixed ordering, not strategies, risk, scientific approvals, or capital allocation.',
                'Counts are from operator-selected stored experiments, not independent replications or population failure rates.',
                'Recurring observations and missing procedures do not establish causes or prediction of profitability.',
                'Operator-expected procedures do not constitute a ForexPro validation contract.',
                'Historical intake signatures are not reverified and current key revocation/export permission is unknown.',
                'Only observation digests, identifiers and verdicts are available; protected data and free-text details are absent.',
                'All questions concern NEW preregistered research; closed outcomes cannot be revised by this report.',
            ],
        }
        report['report_sha256'] = _digest(report)
        return report
    except sqlite3.Error as exc:
        raise EvidenceError('research program cannot query Research Memory') from exc
    finally:
        conn.close()


def render_markdown(report: dict[str, Any]) -> str:
    """Render only the validated fixed-vocabulary procedure codes and digests."""
    lines = [
        '# FRI Research Program — advisory only', '',
        f'Observed closed experiments: {report["observed_experiment_count"]}',
        f'Memory snapshot: `{report["memory_snapshot_sha256"]}`',
        f'Signed-only intake history: {"yes" if report["signed_only_gate_passed"] else "no"}',
        '', '## Recorded coverage', '',
        '| Procedure | FAIL | PASS | NOT_EVALUABLE | UNOBSERVED | Operator expected |',
        '| --- | ---: | ---: | ---: | ---: | --- |',
    ]
    for item in report['procedure_coverage']:
        c = item['counts']
        lines.append(f'| {item["procedure"]} | {c["fail"]} | {c["pass"]} | '
                     f'{c["not_evaluable"]} | {c["unobserved"]} | '
                     f'{"yes" if item["operator_expected"] else "no"} |')
    lines.extend(['', '## Questions for NEW preregistered research', ''])
    if not report['worklist']:
        lines.append('No items met the declared criteria.')
    for item in report['worklist']:
        lines.append(f'- **{item["kind"]}** / `{item["procedure"]}`: '
                     f'{item["affected_experiment_count"]} of {item["cohort_experiment_count"]} stored cases. '
                     f'{item["prospective_question"]}')
        lines.append('  Evidence: ' + ', '.join(
            f'`{r["experiment_id"]}` (`{r["entry_sha256"]}`; receipt `{r["receipt_sha256"]}`)'
            for r in item['evidence']))
    if report['worklist_truncated']:
        lines.append(f'- Output truncated to {report["max_items"]} of {report["total_worklist_items"]} items.')
    lines.extend(['', '## Boundaries', ''])
    lines.extend(f'- {line}' for line in report['limitations'])
    lines.extend(['', f'Report SHA-256: `{report["report_sha256"]}`', ''])
    return '\n'.join(lines)
