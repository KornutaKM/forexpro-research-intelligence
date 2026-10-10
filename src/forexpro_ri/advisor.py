"""Evidence-constrained research advisory. No scientific/trading authority.

Only fixed-vocabulary, hashed Research Memory observations enter this module;
free-text experiment observations, protected datasets and broker state never do.
"""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
from typing import Any, Sequence

from .analysis import canonical_json
from .contracts import EvidenceError
from . import research_program as _program_module

_MAX_ITEMS = 12
_MAX_CITATIONS = 8
_KINDS = {'EVIDENCE_GAP', 'REPEATED_NOT_EVALUABLE', 'REPEATED_FAILURE', 'ISOLATED_NEGATIVE_OR_GAP'}


def _sha(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def _load_program(db_path: str | Path, *, expected_procedures: Sequence[str],
                  min_support: int, allow_unsigned_synthetic: bool) -> dict[str, Any]:
    """Normalize the two published Research Program interfaces without guessing evidence."""
    if hasattr(_program_module, 'build_program'):
        old = _program_module.build_program(
            db_path, expected_procedures=expected_procedures, min_support=min_support,
            require_signed=not allow_unsigned_synthetic,
        )
        items = []
        for row in old['ranked_review_topics']:
            kind = row['attention_class']
            if kind == 'NO_NEGATIVE_OBSERVATION':
                continue
            counts = row['recorded_counts']
            if kind == 'REPEATED_RECORDED_FAILURE':
                category, affected = 'REPEATED_FAILURE', counts['FAIL']
            elif kind == 'REPEATED_EVIDENCE_GAP':
                category = ('REPEATED_NOT_EVALUABLE' if counts['NOT_EVALUABLE'] >= min_support
                            else 'EVIDENCE_GAP')
                affected = counts['NOT_EVALUABLE'] + (
                    counts['UNOBSERVED'] if row['operator_declared_expected'] else 0)
            else:
                category = 'ISOLATED_NEGATIVE_OR_GAP'
                affected = counts['FAIL'] + counts['NOT_EVALUABLE'] + (
                    counts['UNOBSERVED'] if row['operator_declared_expected'] else 0)
            # The source program exposes exact identities for FAIL/NOT_EVALUABLE,
            # but only aggregate counts for UNOBSERVED. Never attribute an
            # unobserved outcome to a particular experiment without evidence.
            sources = row['negative_evidence']['FAIL'] + row['negative_evidence']['NOT_EVALUABLE']
            sources = sorted(sources, key=lambda x: x['experiment_id'])
            items.append({
                'kind': category, 'procedure': row['procedure'],
                'affected_experiment_count': affected,
                'cohort_experiment_count': old['experiment_count'],
                'evidence': sources,
                'prospective_question': row['future_research_question'] or
                    'For a NEW preregistered experiment, review this recorded issue and evidence coverage.',
                'basis': ('OPERATOR_DECLARED_EXPECTATION_NOT_SOURCE_CONTRACT' if
                          row['operator_declared_expected'] and counts['UNOBSERVED'] else
                          'RECORDED_CLOSED_EXPERIMENT_OUTCOMES'),
            })
        counts = old['intake_status_counts']
        return {
            'report_sha256': old['report_sha256'],
            'memory_snapshot_sha256': old['memory_snapshot_sha256'],
            'signed_only_gate_passed': (old['intake_policy'] == 'SIGNED_AT_IMPORT_ONLY'
                                        and counts.get('SIGNATURE_VERIFIED', 0) == old['experiment_count']),
            'observed_experiment_count': old['experiment_count'],
            'provenance_counts': {name.lower(): counts.get(name, 0) for name in
                                  ('SIGNATURE_VERIFIED','UNSIGNED_SYNTHETIC','LEGACY_UNATTESTED')},
            'total_worklist_items': len(items),
            'worklist': items[:30],
        }
    # Older supported versions used a more fine-grained Research Program.
    return _program_module.build_research_program(
        db_path, expected_procedures=expected_procedures,
        min_support=min_support, max_items=30,
        allow_unsigned_synthetic=allow_unsigned_synthetic,
    )


def build_advisor(db_path: str | Path, *, expected_procedures: Sequence[str] = (),
                  min_support: int = 2, max_items: int = 12,
                  allow_unsigned_synthetic: bool = False) -> dict[str, Any]:
    """Compose a deterministic advisory pack from a verified single DB snapshot.

    Signed-only by default. Prior receipt verification is historic, not proof
    of a currently permitted source export or a scientifically approved trial.
    """
    if type(max_items) is not int or not 1 <= max_items <= _MAX_ITEMS:
        raise EvidenceError('advisor max_items must be an integer from 1 to 12')
    program = _load_program(
        db_path, expected_procedures=expected_procedures,
        min_support=min_support, allow_unsigned_synthetic=allow_unsigned_synthetic,
    )
    proposals = []
    for entry in program['worklist'][:max_items]:
        if entry['kind'] not in _KINDS:
            raise EvidenceError('unknown research program item')
        source = {
            'kind': entry['kind'], 'procedure': entry['procedure'],
            'evidence': entry['evidence'],
        }
        identifier = _sha(source)[:24]
        evidence = [{k: row[k] for k in ('experiment_id', 'entry_sha256', 'receipt_sha256')}
                    for row in entry['evidence'][:_MAX_CITATIONS]]
        proposals.append({
            'item_id': identifier,
            'kind': entry['kind'], 'procedure': entry['procedure'],
            'recorded_experiment_count': entry['affected_experiment_count'],
            'cohort_experiment_count': entry['cohort_experiment_count'],
            'question_for_new_experiment': entry['prospective_question'],
            'evidence_sample': evidence,
            'evidence_sample_truncated': len(entry['evidence']) > len(evidence),
            'full_evidence_program_sha256': program['report_sha256'],
            'basis': entry['basis'],
            'interpretation': 'DESCRIPTIVE_NOT_CAUSAL',
        })
    report: dict[str, Any] = {
        'schema_version': 1,
        'report_kind': 'NON_AUTHORITATIVE_RESEARCH_ADVISOR',
        'source_kind': 'VERIFIED_RESEARCH_PROGRAM_SNAPSHOT',
        'research_program_sha256': program['report_sha256'],
        'memory_snapshot_sha256': program['memory_snapshot_sha256'],
        'signed_only_gate_passed': program['signed_only_gate_passed'],
        'observed_experiment_count': program['observed_experiment_count'],
        'provenance_counts': program['provenance_counts'],
        'proposal_count': len(proposals),
        'proposals': proposals,
        'additional_items_not_shown': max(0, program['total_worklist_items'] - len(proposals)),
        'model_inference': 'NOT_REQUESTED',
        'authority': {'scientific': False, 'holdout': False, 'promotion': False,
                      'broker': False, 'experiment_execution': False},
        'limitations': [
            'Descriptive co-occurrence is not a causal finding, an independent replication or a forecast.',
            'Questions are for NEW preregistered experiments only; no closed result may be revised.',
            'Full negative-event citations are bound by the research program digest; samples can be truncated.',
            'An UNOBSERVED procedure may be counted without a per-experiment citation when the source program exposes only aggregate gaps.',
            'Historical signature receipts are not current export authorization or scientific approval.',
            'Only record identifiers, verdicts, procedure codes and cryptographic digests are used.',
            'This advisory has no trade, strategy, holdout, promotion or experiment-execution authority.',
        ],
    }
    report['report_sha256'] = _sha(report)
    return report


def render_markdown(report: dict[str, Any]) -> str:
    """Escape all model-generated prose; report is advisory, never instructions."""
    safe = lambda text: html.escape(str(text), quote=True).replace('|', '&#124;').replace('\n', ' ')
    lines = [
        '# FRI Research Advisor — advisory only', '',
        f'Observed experiments: {report["observed_experiment_count"]}',
        f'Signed-only intake gate: {"passed" if report["signed_only_gate_passed"] else "NOT PASSED"}',
        f'Research program SHA-256: `{report["research_program_sha256"]}`',
        f'Memory snapshot SHA-256: `{report["memory_snapshot_sha256"]}`',
        f'Model inference: {report["model_inference"]}', '',
        '## Questions for NEW preregistered research', '',
    ]
    if not report['proposals']:
        lines.append('No items satisfy the configured evidence criteria.')
    for row in report['proposals']:
        lines.append(f'### {safe(row["kind"])} / {safe(row["procedure"])}')
        lines.append(f'- Item: `{row["item_id"]}`')
        lines.append(f'- Cases: {row["recorded_experiment_count"]} of {row["cohort_experiment_count"]} stored records')
        lines.append(f'- Predefined question: {safe(row["question_for_new_experiment"])}')
        for ref in row['evidence_sample']:
            lines.append('- Evidence: `' + safe(ref['experiment_id']) + '` — entry `' +
                         safe(ref['entry_sha256']) + '`, receipt `' + safe(ref['receipt_sha256']) + '`')
        if row['evidence_sample_truncated']:
            lines.append('- Citation list abbreviated; inspect source research program digest for full provenance.')
    for row in report.get('model_commentary', []):
        lines.extend(['', f'#### Local model commentary for `{row["item_id"]}`',
                      '- Proposed question (UNVERIFIED): ' + safe(row['question']),
                      '- Explanation (UNVERIFIED): ' + safe(row['rationale'])])
    lines.extend(['', '## Boundaries and caveats', ''])
    lines.extend('- ' + safe(line) for line in report['limitations'])
    lines.extend(['', f'Report SHA-256: `{report["report_sha256"]}`', ''])
    return '\n'.join(lines)
