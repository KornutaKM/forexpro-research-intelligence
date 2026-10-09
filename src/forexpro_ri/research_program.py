"""Deterministic, non-authoritative research-question backlog for closed histories.

Ranks *review attention*, never profitability, expected return, experiment
promotion, novelty, statistical significance or causal explanations.
Only stored categorical verdicts and provenance receipts are considered.
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
STATUSES = ('FAIL', 'PASS', 'NOT_EVALUABLE', 'UNOBSERVED')


def _digest(obj: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(obj).encode('utf-8')).hexdigest()


def build_program(db_path: str | Path, *, expected_procedures: Sequence[str] = (),
                  min_support: int = 2, require_signed: bool = True) -> dict[str, Any]:
    """Produce a stable, evidence-linked agenda from one verified SQLite snapshot.

    Default requires all records to have signed-at-import receipts; a synthetic
    demo mode is a deliberate opt-out, not a privacy filter or validity claim.
    """
    if type(min_support) is not int or not 2 <= min_support <= MAX_EXPERIMENTS:
        raise EvidenceError('min_support must be an integer in 2..5000')
    if type(require_signed) is not bool:
        raise EvidenceError('require_signed must be bool')
    expected = _validate_expected(expected_procedures)
    conn = _connect(db_path, creating=False)
    try:
        conn.execute('BEGIN')
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise EvidenceError('Research Memory SQLite integrity check failed')
        if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise EvidenceError('Research Memory foreign key integrity failed')
        ids = [r['experiment_id'] for r in conn.execute('SELECT experiment_id FROM experiments ORDER BY experiment_id')]
        if not 1 <= len(ids) <= MAX_EXPERIMENTS:
            raise EvidenceError('research program requires 1..5000 stored closed experiments')
        records = {eid: _load(conn, eid) for eid in ids}  # entire memory, fail closed
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        receipts = {eid: (read_receipt(conn, eid, records[eid]['entry_sha256']) if version == 2
                          else make_receipt(eid, records[eid]['entry_sha256'], legacy=True))
                    for eid in ids}
        states = {eid: {} for eid in ids}
        for row in conn.execute('SELECT experiment_id,procedure,verdict FROM criteria '
                                'ORDER BY experiment_id,procedure,criterion_id'):
            status = states[row['experiment_id']]
            if row['verdict'] == 'FAIL':
                status[row['procedure']] = 'FAIL'
            elif status.get(row['procedure']) != 'FAIL':
                status[row['procedure']] = 'PASS'
        for row in conn.execute('SELECT experiment_id,procedure FROM not_evaluable '
                                'ORDER BY experiment_id,procedure'):
            status = states[row['experiment_id']]
            if row['procedure'] in status:
                raise EvidenceError('contradictory procedure evaluability')
            status[row['procedure']] = 'NOT_EVALUABLE'
        signed = [eid for eid in ids if receipts[eid]['verification_status'] == 'SIGNATURE_VERIFIED']
        if require_signed and len(signed) != len(ids):
            raise EvidenceError('program rejects unsigned or legacy evidence; use --allow-unsigned-synthetic only for demonstrations')
        if not require_signed and any(not eid.startswith('SYNTHETIC-') for eid in ids if eid not in signed):
            raise EvidenceError('unsigned demonstration mode requires synthetic identifiers')
        source = [{'experiment_id': eid, 'entry_sha256': records[eid]['entry_sha256'],
                   'receipt_sha256': receipts[eid]['receipt_sha256']}
                  for eid in ids]
        program: list[dict[str, Any]] = []
        for procedure in sorted(set(expected) | {p for outcomes in states.values() for p in outcomes}):
            groups = {status: [eid for eid in ids if states[eid].get(procedure, 'UNOBSERVED') == status]
                      for status in STATUSES}
            f, n, u = (len(groups[k]) for k in ('FAIL', 'NOT_EVALUABLE', 'UNOBSERVED'))
            if f >= min_support:
                attention = 'REPEATED_RECORDED_FAILURE'
                rank = 0
            elif n >= min_support or (procedure in expected and u >= min_support):
                attention = 'REPEATED_EVIDENCE_GAP'
                rank = 1
            elif f or n or (procedure in expected and u):
                attention = 'ISOLATED_NEGATIVE_OR_GAP'
                rank = 2
            else:
                attention = 'NO_NEGATIVE_OBSERVATION'
                rank = 3
            # Stable ordinal policy, not estimated scientific priority or independent rates.
            evidence = {
                state: [{'experiment_id': eid, 'entry_sha256': records[eid]['entry_sha256'],
                         'receipt_sha256': receipts[eid]['receipt_sha256']} for eid in groups[state]]
                for state in ('FAIL', 'NOT_EVALUABLE')
            }
            program.append({
                'procedure': procedure, 'attention_class': attention,
                'operator_declared_expected': procedure in expected,
                'recorded_counts': {k: len(groups[k]) for k in STATUSES},
                'mixed_pass_fail': bool(groups['PASS'] and groups['FAIL']),
                'support_is_distinct_experiments_not_independence': True,
                'negative_evidence': evidence,
                'future_research_question': _QUESTIONS.get(procedure) if rank < 3 else None,
                '_order': (rank, -f, -(n + (u if procedure in expected else 0)), procedure),
            })
        program.sort(key=lambda x: x['_order'])
        for item in program:
            del item['_order']
        c = Counter(receipts[eid]['verification_status'] for eid in ids)
        result = {
            'schema_version': 1,
            'report_kind': 'NON_AUTHORITATIVE_RESEARCH_QUESTION_PROGRAM',
            'experiment_count': len(ids), 'min_support': min_support,
            'expected_procedures_operator_supplied': expected,
            'intake_policy': 'SIGNED_AT_IMPORT_ONLY' if require_signed else 'SYNTHETIC_DEMONSTRATION',
            'intake_status_counts': dict(sorted(c.items())),
            'memory_snapshot_sha256': _digest({'entries': source}),
            'source_entries': source,
            'ranked_review_topics': program,
            'authority': {'scientific': False, 'execution': False, 'promotion': False,
                          'holdout': False, 'broker': False},
            'limitations': [
                'Ordinal review order is deterministic triage, not expected return or scientific ranking.',
                'Distinct experiment IDs do not establish independent data, lineage, protocols or replication.',
                'Expected procedures are operator declarations, not an authenticated validation contract.',
                'Absence is UNOBSERVED, not PASS, FAIL or NOT_EVALUABLE.',
                'Historical signature receipts do not establish current key validity or export approval.',
                'Observed coincidence cannot identify causes; all questions address NEW preregistered research.',
                'No strategy returns, raw observations or trading instructions are present in the report.',
            ],
        }
        result['report_sha256'] = _digest(result)
        return result
    except sqlite3.Error as exc:
        raise EvidenceError('research program SQLite read failed') from exc
    finally:
        conn.close()


def render_markdown(report: dict[str, Any]) -> str:
    """Escape any operator-supplied text before rendering a portable Markdown table."""
    def safe(value: object) -> str:
        return str(value).replace('\\', '\\\\').replace('|', '\\|').replace('\n', ' ')

    lines = [
        '# FRI Research Question Program (non-authoritative)', '',
        f"Experiments: {report['experiment_count']}; intake: {safe(report['intake_policy'])}",
        f"Snapshot SHA-256: `{report['memory_snapshot_sha256']}`", '',
        '| Review class | Procedure | FAIL | PASS | NOT_EVALUABLE | UNOBSERVED |',
        '|---|---|---:|---:|---:|---:|',
    ]
    for item in report['ranked_review_topics']:
        c = item['recorded_counts']
        lines.append(f"| {safe(item['attention_class'])} | {safe(item['procedure'])} | "
                     f"{c['FAIL']} | {c['PASS']} | {c['NOT_EVALUABLE']} | {c['UNOBSERVED']} |")
    lines.extend(['', '## Future research questions', ''])
    for item in report['ranked_review_topics']:
        if item['future_research_question']:
            lines.append(f"- **{safe(item['procedure'])}**: {safe(item['future_research_question'])}")
    lines.extend(['', '## Scope and limitations', ''])
    lines.extend(f'- {safe(note)}' for note in report['limitations'])
    lines.extend(['', f"Report SHA-256: `{report['report_sha256']}`", ''])
    return '\n'.join(lines)
