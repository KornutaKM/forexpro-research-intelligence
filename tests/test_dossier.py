"""Synthetic-only Research Dossier tests; no protected evidence or private keys."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from forexpro_ri import __version__
from forexpro_ri.analysis import canonical_json
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.dossier import build_dossier, render_markdown
from forexpro_ri.memory import ingest, verify


class ResearchDossierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        self.db = self.root / 'memory.sqlite'

    def add(self, suffix, criteria=(), unavailable=()):
        eid = f'SYNTHETIC-{suffix}'
        summary = {
            'experiment_id': eid,
            'disposition': 'CLOSED_UNSUCCESSFUL' if any(status == 'FAIL' for _, status in criteria) else 'CLOSED_INCOMPLETE',
            'criteria': [
                {'criterion_id': f'test-{i}', 'procedure': procedure, 'verdict': verdict,
                 'observation': 'synthetic HIGHLY-PRIVATE-OBSERVATION-NEVER-OUTPUT'}
                for i, (procedure, verdict) in enumerate(criteria)
            ],
            'not_evaluable': [
                {'procedure': procedure, 'reason': 'synthetic HIGHLY-PRIVATE-REASON-NEVER-OUTPUT'}
                for procedure in unavailable
            ],
        }
        raw = (json.dumps(summary, sort_keys=True) + '\n').encode()
        manifest = {
            'schema_version': 1, 'export_kind': 'CLOSED_EXPERIMENT_SUMMARY',
            'source_system': 'forexpro', 'experiment_id': eid,
            'source_revision': 'a' * 40, 'summary_sha256': hashlib.sha256(raw).hexdigest(),
            'approved_scope': 'READ_ONLY_ADVISORY', 'holdout_access': False,
            'promotion_authority': False, 'broker_authority': False,
        }
        (self.bundle / 'summary.json').write_bytes(raw)
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        ingest(self.bundle, self.db, allow_unsigned_synthetic=True)

    def populate(self, order=('A', 'B', 'C', 'D')):
        fixtures = {
            'A': ([('COST_STRESS', 'FAIL'), ('OUT_OF_SAMPLE', 'FAIL'),
                   ('OUT_OF_SAMPLE', 'PASS'), ('MONTE_CARLO', 'PASS')], ['REGIME_STABILITY']),
            'B': ([('COST_STRESS', 'FAIL'), ('OUT_OF_SAMPLE', 'FAIL')], ['REGIME_STABILITY']),
            'C': ([('COST_STRESS', 'FAIL'), ('OUT_OF_SAMPLE', 'PASS')], []),
            'D': ([('MONTE_CARLO', 'PASS')], ['REGIME_STABILITY']),
        }
        for suffix in order:
            self.add(suffix, *fixtures[suffix])

    def dossier(self, focus='SYNTHETIC-A', expected=(), min_support=2):
        return build_dossier(self.db, focus_experiment_id=focus,
                             expected_procedures=expected, min_support=min_support)

    def test_project_version(self):
        self.assertEqual(__version__, '2.4.0')

    def test_focus_verdicts_evidence_and_unobserved_are_separate(self):
        self.populate()
        report = self.dossier(expected=['DETERMINISTIC_RERUN'])
        rows = {item['procedure']: item for item in report['procedure_outcomes']}
        self.assertEqual(rows['OUT_OF_SAMPLE']['recorded_status'], 'FAIL')
        self.assertEqual(len(rows['OUT_OF_SAMPLE']['criteria_evidence']), 2)
        self.assertEqual(rows['MONTE_CARLO']['recorded_status'], 'PASS')
        self.assertEqual(rows['REGIME_STABILITY']['recorded_status'], 'NOT_EVALUABLE')
        self.assertEqual(len(rows['REGIME_STABILITY']['not_evaluable_reason_sha256']), 64)
        self.assertEqual(rows['DETERMINISTIC_RERUN']['recorded_status'], 'UNOBSERVED')
        self.assertEqual(rows['DETERMINISTIC_RERUN']['criteria_evidence'], [])
        self.assertIsNone(rows['DETERMINISTIC_RERUN']['not_evaluable_reason_sha256'])
        gap_by_proc = {item['procedure']: item for item in report['evidence_visibility_gaps']}
        self.assertEqual(gap_by_proc['REGIME_STABILITY']['basis'], 'HISTORY_OBSERVED')
        self.assertEqual(gap_by_proc['DETERMINISTIC_RERUN']['basis'], 'OPERATOR_DECLARED')
        self.assertTrue(rows['DETERMINISTIC_RERUN']['expected_by_operator'])

    def test_report_is_deterministic_and_content_addressed(self):
        self.populate()
        a = self.dossier(expected=['MONTE_CARLO', 'REGIME_STABILITY'])
        b = self.dossier(expected=['REGIME_STABILITY', 'MONTE_CARLO'])
        self.assertEqual(a, b)
        self.assertEqual(a['report_kind'], 'NON_AUTHORITATIVE_RESEARCH_DOSSIER')
        self.assertEqual(a['observed_experiment_count'], 4)
        digest = a.pop('report_sha256')
        self.assertEqual(digest, hashlib.sha256(canonical_json(a).encode()).hexdigest())

    def test_repeated_negative_signatures_count_distinct_experiments(self):
        self.populate()
        report = self.dossier()
        rows = {item['procedure'] + ':' + item['recorded_status']: item
                for item in report['recurring_negative_observations']}
        self.assertEqual(rows['COST_STRESS:FAIL']['affected_experiments'], 3)
        self.assertEqual(rows['COST_STRESS:FAIL']['other_experiments'], 2)
        self.assertEqual(rows['OUT_OF_SAMPLE:FAIL']['affected_experiments'], 2)
        self.assertEqual(rows['REGIME_STABILITY:NOT_EVALUABLE']['affected_experiments'], 3)
        self.assertTrue(all(len(e['entry_sha256']) == 64 for row in rows.values() for e in row['evidence']))
        self.assertEqual(self.dossier(min_support=4)['recurring_negative_observations'], [])

    def test_similar_cases_rank_and_pass_only_not_matching(self):
        self.populate()
        analogues = self.dossier()['similar_observed_cases']
        self.assertEqual([a['experiment']['experiment_id'] for a in analogues],
                         ['SYNTHETIC-B', 'SYNTHETIC-C', 'SYNTHETIC-D'])
        self.assertEqual(analogues[0]['overlap'], {'shared': 3, 'union': 3})
        self.assertFalse(any(a['experiment']['experiment_id'] == 'SYNTHETIC-A' for a in analogues))
        self.assertEqual(analogues[-1]['shared_negative_signatures'],
                         [{'procedure': 'REGIME_STABILITY', 'recorded_status': 'NOT_EVALUABLE'}])

    def test_single_experiment_is_valid_dossier(self):
        self.add('SOLO', [('COST_STRESS', 'FAIL')])
        report = self.dossier('SYNTHETIC-SOLO')
        self.assertEqual(report['observed_experiment_count'], 1)
        self.assertEqual(report['similar_observed_cases'], [])
        self.assertEqual(report['recurring_negative_observations'], [])
        self.assertTrue(any(q['procedure'] == 'COST_STRESS' for q in report['prospective_research_questions']))

    def test_pass_only_focus_creates_no_spurious_questions(self):
        self.add('PASS', [('MONTE_CARLO', 'PASS')])
        report = self.dossier('SYNTHETIC-PASS')
        self.assertEqual(report['prospective_research_questions'], [])
        self.assertEqual(report['similar_observed_cases'], [])
        self.assertEqual(report['recurring_negative_observations'], [])
        self.assertEqual(report['focus_experiment']['recorded_disposition'], 'CLOSED_INCOMPLETE')

    def test_does_not_reveal_raw_observations_or_unverified_provenance(self):
        self.populate()
        report = self.dossier()
        text = json.dumps(report)
        md = render_markdown(report)
        for secret in ('HIGHLY-PRIVATE-OBSERVATION-NEVER-OUTPUT', 'HIGHLY-PRIVATE-REASON-NEVER-OUTPUT'):
            self.assertNotIn(secret, text)
            self.assertNotIn(secret, md)
            self.assertNotIn(secret, self.db.read_bytes().decode('latin-1'))
        self.assertFalse(report['scientific_authority'])
        self.assertFalse(report['holdout_access'])
        self.assertFalse(report['broker_authority'])
        self.assertEqual(report['source_authenticity'], 'HISTORICAL_INTAKE_VERIFICATION_ONLY')
        self.assertEqual(report['focus_intake_provenance']['verification_status'], 'UNSIGNED_SYNTHETIC')
        self.assertIn('NOT proven independent', text)
        self.assertIn('NOT establish causality', text)

    def test_ingest_order_independence_including_snapshot_hash(self):
        self.populate()
        report_a = self.dossier()
        self.db = self.root / 'second.sqlite'
        self.populate(order=('D', 'C', 'B', 'A'))
        self.assertEqual(report_a, self.dossier())

    def test_unknown_focus_and_invalid_inputs_fail_closed(self):
        self.add('A', [('OUT_OF_SAMPLE', 'FAIL')])
        for name in ('SYNTHETIC-NOT-FOUND', '', 'A|B', '\n', None):
            with self.subTest(name=name), self.assertRaises(EvidenceError):
                self.dossier(focus=name)
        for procedures in (['HOLDOUT'], ['COST_STRESS', 'COST_STRESS'], 'COST_STRESS', [None]):
            with self.subTest(procedures=procedures), self.assertRaises(EvidenceError):
                self.dossier(expected=procedures)
        for n in (1, 0, 5001, True, '2'):
            with self.subTest(n=n), self.assertRaises(EvidenceError):
                self.dossier(min_support=n)

    def test_detects_focus_and_unselected_corruption(self):
        self.populate()
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TRIGGER criteria_no_update')
            conn.execute("UPDATE criteria SET verdict='PASS' WHERE experiment_id='SYNTHETIC-C' AND procedure='COST_STRESS'")
        with self.assertRaisesRegex(EvidenceError, 'integrity mismatch'):
            self.dossier()

    def test_detects_orphan_without_mutating_database(self):
        self.populate()
        with sqlite3.connect(self.db) as conn:
            conn.execute('PRAGMA foreign_keys=OFF')
            conn.execute("INSERT INTO criteria VALUES ('ORPHAN', 'a', 'OUT_OF_SAMPLE', 'FAIL', '0')")
        with self.assertRaisesRegex(EvidenceError, 'foreign key'):
            self.dossier()

    def test_database_unchanged_after_dossier(self):
        self.populate()
        before = verify(self.db)
        raw = self.db.read_bytes()
        self.dossier()
        self.assertEqual(before, verify(self.db))
        self.assertEqual(raw, self.db.read_bytes())

    def test_markdown_renders_all_sections_and_evidence(self):
        self.populate()
        report = self.dossier(expected=['DETERMINISTIC_RERUN'])
        md = render_markdown(report)
        self.assertIn('# FRI Research Dossier', md)
        self.assertIn('## Evidence visibility gaps', md)
        self.assertIn('## Historically similar negative signatures', md)
        self.assertIn('## Recurring negative observations', md)
        self.assertIn('## Questions for NEW preregistered research', md)
        self.assertIn('| DETERMINISTIC_RERUN | UNOBSERVED | yes |', md)
        self.assertIn(report['report_sha256'], md)
        self.assertIn(report['memory_snapshot_sha256'], md)
        self.assertTrue(md.endswith('\n'))
        with self.assertRaises(EvidenceError):
            render_markdown({'report_kind': 'AUTHORITATIVE_VALIDATION'})

    def test_cli_json_markdown_and_error(self):
        self.populate()
        command = ['memory', 'dossier', '--db', str(self.db), '--focus', 'SYNTHETIC-A',
                   '--expected-procedure', 'DETERMINISTIC_RERUN']
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(command), 0)
        self.assertEqual(json.loads(out.getvalue())['focus_experiment']['experiment_id'], 'SYNTHETIC-A')
        out = StringIO()
        with redirect_stdout(out):
            self.assertEqual(main(command + ['--format', 'markdown']), 0)
        self.assertIn('## Recurring negative observations', out.getvalue())
        err = StringIO()
        with redirect_stderr(err):
            self.assertEqual(main(command + ['--expected-procedure', 'HOLDOUT']), 2)
        self.assertIn('MEMORY_REJECTED', err.getvalue())

    def test_more_than_ten_analogues_are_truncated_deterministically(self):
        self.add('F', [('OUT_OF_SAMPLE', 'FAIL')])
        for i in range(12):
            self.add(f'X{i:02}', [('OUT_OF_SAMPLE', 'FAIL')])
        report = self.dossier('SYNTHETIC-F')
        self.assertTrue(report['similar_cases_truncated'])
        self.assertEqual(len(report['similar_observed_cases']), 10)
        self.assertEqual([s['experiment']['experiment_id'] for s in report['similar_observed_cases']],
                         [f'SYNTHETIC-X{i:02}' for i in range(10)])


if __name__ == '__main__':
    unittest.main()
