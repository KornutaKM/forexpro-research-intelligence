"""Read-only single-snapshot research dossier from minimal Research Memory.

Evidence-linked descriptions only: no performance reconstruction, causality,
scientific validation, protected data or broker permissions.
"""
from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from fractions import Fraction
from pathlib import Path
from typing import Any

from .analysis import canonical_json
from .comparison import _validate_expected
from .contracts import EvidenceError, _ID
from .failure_intelligence import _QUESTIONS
from .memory import _connect, _load

_REPORT_SCHEMA_VERSION = 1
_MAX_EXPERIMENTS = 5000
_MAX_SIMILAR = 10
_STATUSES = ('FAIL', 'PASS', 'NOT_EVALUABLE', 'UNOBSERVED')


def _reference(record: dict[str, Any]) -> dict[str, str]:
    return {'experiment_id': record['experiment_id'], 'entry_sha256': record['entry_sha256']}


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def build_dossier(
    db_path: str | Path,
    *,
    focus_experiment_id: str,
    expected_procedures: tuple[str, ...] | list[str] = (),
    min_support: int = 2,
) -> dict[str, Any]:
    """Produce one deterministic dossier in one SQLite read transaction.

    Expected procedures are operator declarations, not a verified contract.
    Historical support counts distinct stored experiments, not criteria.
    """
    if not isinstance(focus_experiment_id, str) or not _ID.fullmatch(focus_experiment_id):
        raise EvidenceError('focus_experiment_id must be a valid experiment ID')
    if type(min_support) is not int or not 2 <= min_support <= _MAX_EXPERIMENTS:
        raise EvidenceError('min_support must be an integer from 2 through 5000')
    expected = _validate_expected(expected_procedures)

    conn = _connect(db_path, creating=False)
    try:
        conn.execute('BEGIN')  # All sections come from one consistent read snapshot.
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise EvidenceError('SQLite integrity check failed')
        if conn.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise EvidenceError('SQLite foreign key check failed')
        ids = [row['experiment_id'] for row in conn.execute(
            'SELECT experiment_id FROM experiments ORDER BY experiment_id'
        ).fetchall()]
        if len(ids) > _MAX_EXPERIMENTS:
            raise EvidenceError('too many experiments for bounded dossier')
        if focus_experiment_id not in ids:
            raise EvidenceError('focus experiment not found in Research Memory')

        # _load checks source digest, counts and contradictory evaluability;
        # validate ALL records, including those outside the focus/analogues.
        records = {eid: _load(conn, eid) for eid in ids}
        all_states: dict[str, dict[str, str]] = {}
        focus_criteria: dict[str, list[dict[str, str]]] = {}
        focus_reasons: dict[str, str] = {}
        counts: dict[tuple[str, str], int] = Counter()

        for eid in ids:
            states: dict[str, str] = {}
            for row in conn.execute(
                'SELECT criterion_id, procedure, verdict, observation_sha256 '
                'FROM criteria WHERE experiment_id=? ORDER BY procedure, criterion_id', (eid,)
            ):
                proc = row['procedure']
                if row['verdict'] == 'FAIL':
                    states[proc] = 'FAIL'
                elif states.get(proc) != 'FAIL':
                    states[proc] = 'PASS'
                if eid == focus_experiment_id:
                    focus_criteria.setdefault(proc, []).append({
                        'criterion_id': row['criterion_id'],
                        'recorded_verdict': row['verdict'],
                        'observation_sha256': row['observation_sha256'],
                    })
            for row in conn.execute(
                'SELECT procedure, reason_sha256 FROM not_evaluable '
                'WHERE experiment_id=? ORDER BY procedure', (eid,)
            ):
                proc = row['procedure']
                if proc in states:
                    raise EvidenceError('contradictory procedure evaluability in Research Memory')
                states[proc] = 'NOT_EVALUABLE'
                if eid == focus_experiment_id:
                    focus_reasons[proc] = row['reason_sha256']
            all_states[eid] = states
            for proc, status in states.items():
                counts[(proc, status)] += 1

        source_refs = [_reference(records[eid]) for eid in ids]
        snapshot = _hash({'entries': source_refs})
        focus_row = records[focus_experiment_id]
        focus_states = all_states[focus_experiment_id]
        cohort_observed = {p for st in all_states.values() for p in st}
        observed_procedures = sorted(cohort_observed | set(expected))

        outcomes: list[dict[str, Any]] = []
        gaps: list[dict[str, Any]] = []
        for proc in observed_procedures:
            status = focus_states.get(proc, 'UNOBSERVED')
            reason = focus_reasons.get(proc)
            result = {
                'procedure': proc,
                'recorded_status': status,
                'expected_by_operator': proc in expected,
                'criteria_evidence': focus_criteria.get(proc, []),
                'not_evaluable_reason_sha256': reason,
            }
            outcomes.append(result)
            if status in {'NOT_EVALUABLE', 'UNOBSERVED'}:
                gaps.append({
                    'procedure': proc,
                    'recorded_status': status,
                    'basis': 'OPERATOR_DECLARED' if proc in expected else 'HISTORY_OBSERVED',
                    'reason_sha256': reason,
                    'focus_entry_sha256': focus_row['entry_sha256'],
                })

        signatures = {(p, s) for p, s in focus_states.items() if s != 'PASS'}
        matches: list[tuple[Fraction, str, set[tuple[str, str]], set[tuple[str, str]]]] = []
        for eid in ids:
            if eid == focus_experiment_id:
                continue
            candidate = {(p, s) for p, s in all_states[eid].items() if s != 'PASS'}
            shared = signatures & candidate
            if not shared:
                continue
            union = signatures | candidate
            matches.append((Fraction(len(shared), len(union)), eid, shared, union))
        matches.sort(key=lambda x: (-x[0], x[1]))
        analogues = [
            {
                'experiment': _reference(records[eid]),
                'shared_negative_signatures': [
                    {'procedure': proc, 'recorded_status': status} for proc, status in sorted(shared)
                ],
                'overlap': {'shared': len(shared), 'union': len(union)},
            }
            for _, eid, shared, union in matches[:_MAX_SIMILAR]
        ]

        recurring: list[dict[str, Any]] = []
        questions: list[dict[str, str]] = []
        for proc, status in sorted(signatures):
            question = _QUESTIONS.get(proc)
            if question:
                questions.append({'procedure': proc, 'recorded_status': status, 'question': question})
            support = counts[(proc, status)]
            if support >= min_support:
                members = [eid for eid in ids if all_states[eid].get(proc) == status]
                recurring.append({
                    'procedure': proc,
                    'recorded_status': status,
                    'affected_experiments': support,
                    'other_experiments': support - 1,
                    'evidence': [_reference(records[eid]) for eid in members],
                })
        recurring.sort(key=lambda x: (-x['affected_experiments'], x['procedure'], x['recorded_status']))

        report: dict[str, Any] = {
            'schema_version': _REPORT_SCHEMA_VERSION,
            'report_kind': 'NON_AUTHORITATIVE_RESEARCH_DOSSIER',
            'focus_experiment': {
                **_reference(focus_row),
                'source_revision': focus_row['source_revision'],
                'summary_sha256': focus_row['summary_sha256'],
                'recorded_disposition': focus_row['disposition'],
                'recorded_criterion_counts': {
                    'fail': focus_row['fail_count'],
                    'pass': focus_row['pass_count'],
                    'not_evaluable': focus_row['not_evaluable_count'],
                },
            },
            'observed_experiment_count': len(ids),
            'memory_snapshot_sha256': snapshot,
            'declared_expected_procedures': expected,
            'procedure_outcomes': outcomes,
            'evidence_visibility_gaps': gaps,
            'similar_observed_cases': analogues,
            'similar_cases_truncated': len(matches) > _MAX_SIMILAR,
            'recurring_negative_observations': recurring,
            'prospective_research_questions': questions,
            'min_support': min_support,
            'source_authenticity': 'NOT_ESTABLISHED_FROM_MEMORY',
            'scientific_authority': False,
            'holdout_access': False,
            'broker_authority': False,
            'limitations': [
                'Only already stored closed-experiment verdicts and digests are examined; metrics and free text are unavailable.',
                'Operator-expected procedures do NOT establish a ForexPro ValidationContract or a complete protocol.',
                'UNOBSERVED means no stored evidence, neither PASS nor FAIL; NOT_EVALUABLE remains distinct.',
                'History and similar cases may share data, code or lineage and are NOT proven independent.',
                'Recurring observations and negative-signature overlap do NOT establish causality or trading profitability.',
                'Stored SHA-256 digests verify self-consistency, NOT original exporter authorization or signature retention.',
                'Questions apply to NEW preregistered research, not modification or approval of closed experiments.',
                'No scientific approval, protected holdout access or broker trading permission is conferred.',
            ],
        }
        report['report_sha256'] = _hash(report)
        return report
    except sqlite3.Error as exc:
        raise EvidenceError(f'cannot build Research Dossier: {exc}') from exc
    finally:
        conn.close()


def render_markdown(report: dict[str, Any]) -> str:
    """Make one human-readable advisory report from the strict generated shape."""
    if report.get('report_kind') != 'NON_AUTHORITATIVE_RESEARCH_DOSSIER':
        raise EvidenceError('expected non-authoritative Research Dossier report')

    def safe(text: str) -> str:
        # Only generated identifiers, enumerated statuses and SHA digests are rendered.
        return str(text).replace('\\', '\\\\').replace('|', '\\|').replace('`', '\\`').replace('\r', ' ').replace('\n', ' ')

    target = report['focus_experiment']
    lines = [
        '# FRI Research Dossier (read-only advisory)',
        '',
        '**No scientific validation, promotion, HOLDOUT or broker authority.**',
        '',
        '## Closed experiment',
        '',
        f'- Experiment: `{safe(target["experiment_id"])}`',
        f'- Recorded disposition: `{safe(target["recorded_disposition"])}`',
        f'- Source revision: `{safe(target["source_revision"])}`',
        f'- Entry SHA-256: `{target["entry_sha256"]}`',
        f'- Summary SHA-256: `{target["summary_sha256"]}`',
        f'- Stored criterion counts: {target["recorded_criterion_counts"]}',
        '',
        '## Recorded procedure outcomes',
        '',
        '| Procedure | Recorded status | Operator-expected | Evidence digests |',
        '| --- | --- | --- | --- |',
    ]
    for item in report['procedure_outcomes']:
        digests = [c['observation_sha256'] for c in item['criteria_evidence']]
        if item['not_evaluable_reason_sha256']:
            digests.append(item['not_evaluable_reason_sha256'])
        evidence = ', '.join(f'`{digest}`' for digest in digests) or 'none'
        lines.append(
            f'| {safe(item["procedure"])} | {item["recorded_status"]} | '
            f'{"yes" if item["expected_by_operator"] else "no"} | {evidence} |'
        )
    lines.extend(['', '## Evidence visibility gaps', ''])
    if report['evidence_visibility_gaps']:
        for gap in report['evidence_visibility_gaps']:
            lines.append(
                f'- `{safe(gap["procedure"])}`: **{gap["recorded_status"]}** '
                f'({gap["basis"]}); reference `{gap["focus_entry_sha256"]}`'
            )
    else:
        lines.append('No visibility gaps among cohort-observed or operator-declared procedures.')
    lines.extend(['', '## Historically similar negative signatures', ''])
    if not report['similar_observed_cases']:
        lines.append('No matching recorded negative signatures in other stored experiments.')
    for analogue in report['similar_observed_cases']:
        shared = ', '.join(f'{safe(s["procedure"])}={s["recorded_status"]}' for s in analogue['shared_negative_signatures'])
        lines.append(
            f'- `{safe(analogue["experiment"]["experiment_id"])}` '
            f'({analogue["overlap"]["shared"]}/{analogue["overlap"]["union"]} shared/union): '
            f'{shared}; evidence `{analogue["experiment"]["entry_sha256"]}`'
        )
    if report['similar_cases_truncated']:
        lines.append('- Display is capped at ten cases; more matches exist.')
    lines.extend(['', '## Recurring negative observations', ''])
    if not report['recurring_negative_observations']:
        lines.append('No focus negative signatures met the requested distinct-experiment support.')
    for item in report['recurring_negative_observations']:
        lines.append(
            f'- `{safe(item["procedure"])}` / {item["recorded_status"]}: '
            f'{item["affected_experiments"]} stored experiments '
            f'({item["other_experiments"]} besides the focus).'
        )
    lines.extend(['', '## Questions for NEW preregistered research', ''])
    if not report['prospective_research_questions']:
        lines.append('No prospective question was generated from a recorded negative status.')
    for item in report['prospective_research_questions']:
        # Static questions are sourced from a code-reviewed mapping, not data prose.
        lines.append(f'- {item["procedure"]}: {item["question"]}')
    lines.extend([
        '', '## Provenance and limitations', '',
        f'- Memory snapshot SHA-256: `{report["memory_snapshot_sha256"]}`',
        f'- Dossier SHA-256: `{report["report_sha256"]}`',
        '- Export signature/authorization: **not established from Research Memory**.',
        '',
    ])
    for item in report['limitations']:
        lines.append('- ' + item)
    lines.append('')
    return '\n'.join(lines)
