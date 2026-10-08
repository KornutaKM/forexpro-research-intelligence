"""Synthetic-only diagnostics: no private datasets or scientific approval."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.failure_intelligence import build_failure_report
from forexpro_ri.memory import ingest, verify


class FailureIntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'memory.sqlite'
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()

    def add(self, name, criteria=(), unavailable=(), revision='a' * 40):
        summary = {
            'experiment_id': f'SYNTHETIC-{name}',
            'disposition': 'CLOSED_UNSUCCESSFUL' if any(v == 'FAIL' for _, v in criteria) else 'CLOSED_INCOMPLETE',
            'criteria': [
                {'criterion_id': f'test-{i}', 'procedure': proc, 'verdict': verdict,
                 'observation': 'synthetic private-text-do-not-persist'}
                for i, (proc, verdict) in enumerate(criteria)
            ],
            'not_evaluable': [
                {'procedure': p, 'reason': 'synthetic private-reason-do-not-persist'}
                for p in unavailable
            ],
        }
        raw = (json.dumps(summary, sort_keys=True) + '\n').encode()
        manifest = {
            'schema_version': 1, 'export_kind': 'CLOSED_EXPERIMENT_SUMMARY',
            'source_system': 'forexpro', 'experiment_id': summary['experiment_id'],
            'source_revision': revision, 'summary_sha256': hashlib.sha256(raw).hexdigest(),
            'approved_scope': 'READ_ONLY_ADVISORY', 'holdout_access': False,
            'promotion_authority': False, 'broker_authority': False,
        }
        (self.bundle / 'summary.json').write_bytes(raw)
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest))
        ingest(self.bundle, self.db)

    def populate(self, order=('A', 'B', 'C', 'D')):
        cases = {
            'A': ([('COST_STRESS', 'FAIL'), ('OUT_OF_SAMPLE', 'FAIL'), ('MONTE_CARLO', 'PASS')], []),
            'B': ([('COST_STRESS', 'FAIL'), ('OUT_OF_SAMPLE', 'FAIL'), ('OUT_OF_SAMPLE', 'PASS')], []),
            'C': ([('COST_STRESS', 'FAIL'), ('OUT_OF_SAMPLE', 'PASS')], ['REGIME_STABILITY']),
            'D': ([('OUT_OF_SAMPLE', 'FAIL')], ['REGIME_STABILITY']),
        }
        for name in order:
            c, u = cases[name]
            self.add(name, c, u)

    def test_empty_database_is_valid_unobserved_cohort(self):
        self.add('EMPTY', [('MONTE_CARLO', 'PASS')])
        r = build_failure_report(self.db)
        self.assertEqual(r['observed_experiment_count'], 1)
        self.assertEqual(r['recurring_observations'], [])
        self.assertEqual(r['co_failure_patterns'], [])

    def test_procedure_counts_deduplicate_criteria_and_missing_is_not_pass(self):
        self.populate()
        r = build_failure_report(self.db)
        coverage = {p['procedure']: p for p in r['procedure_coverage']}
        self.assertEqual((coverage['COST_STRESS']['failed_experiments'], coverage['COST_STRESS']['unobserved_experiments']), (3, 1))
        self.assertEqual((coverage['OUT_OF_SAMPLE']['failed_experiments'], coverage['OUT_OF_SAMPLE']['passed_experiments']), (3, 1))
        self.assertEqual((coverage['REGIME_STABILITY']['not_evaluable_experiments'], coverage['REGIME_STABILITY']['unobserved_experiments']), (2, 2))
        self.assertEqual(coverage['MONTE_CARLO']['unobserved_experiments'], 3)
        self.assertEqual(len(coverage['OUT_OF_SAMPLE']['failure_evidence']), 3)
        self.assertEqual({x['experiment_id'] for x in coverage['OUT_OF_SAMPLE']['failure_evidence']}, {'SYNTHETIC-A','SYNTHETIC-B','SYNTHETIC-D'})
        self.assertEqual(len(r['recurring_observations']), 3)
        self.assertEqual(r['co_failure_patterns'][0]['procedures'], ['COST_STRESS', 'OUT_OF_SAMPLE'])
        self.assertEqual(r['co_failure_patterns'][0]['co_failed_experiments'], 2)
        self.assertIsNone(r['focus'])

    def test_only_prospective_questions_and_no_causes_or_authority(self):
        self.populate()
        r = build_failure_report(self.db)
        self.assertFalse(r['scientific_authority'])
        self.assertFalse(r['broker_authority'])
        self.assertFalse(r['holdout_access'])
        self.assertEqual(r['source_authenticity'], 'NOT_ESTABLISHED_FROM_MEMORY')
        for pattern in r['recurring_observations']:
            self.assertIn('NEW preregistered experiment', pattern['future_research_question'])
        text = json.dumps(r)
        self.assertNotIn('private-text-do-not-persist', text)
        self.assertNotIn('private-reason-do-not-persist', text)
        self.assertNotIn('synthetic private-', self.db.read_bytes().decode('latin-1'))
        self.assertIn('NOT identify causes', text)

    def test_focus_matches_signatures_not_raw_text_and_is_sorted(self):
        self.populate()
        r = build_failure_report(self.db, focus_experiment_id='SYNTHETIC-A')
        similar = r['focus']['similar_observed_cases']
        self.assertEqual([s['experiment']['experiment_id'] for s in similar], ['SYNTHETIC-B', 'SYNTHETIC-C', 'SYNTHETIC-D'])
        self.assertEqual(similar[0]['overlap'], {'shared': 2, 'union': 2})
        self.assertEqual(similar[1]['overlap'], {'shared': 1, 'union': 3})
        self.assertEqual(similar[2]['overlap'], {'shared': 1, 'union': 3})
        self.assertEqual(r['focus']['procedure_outcomes'][0]['recorded_status'], 'FAIL')

    def test_deterministic_under_ingest_order_and_repeated_queries(self):
        self.populate()
        a = build_failure_report(self.db, focus_experiment_id='SYNTHETIC-A')
        b = build_failure_report(self.db, focus_experiment_id='SYNTHETIC-A')
        self.assertEqual(a, b)
        self.assertEqual(a['report_sha256'], b['report_sha256'])
        another = self.root / 'second.sqlite'
        self.db = another
        self.populate(order=('D', 'C', 'B', 'A'))
        c = build_failure_report(self.db, focus_experiment_id='SYNTHETIC-A')
        self.assertEqual(a, c)

    def test_min_support_bounded_and_respected(self):
        self.populate()
        a = build_failure_report(self.db, min_support=3)
        self.assertEqual(a['co_failure_patterns'], [])
        self.assertEqual(len(a['recurring_observations']), 2)
        for x in (0, 1, -1, True, 5001, 1.4):
            with self.subTest(value=x), self.assertRaises(EvidenceError):
                build_failure_report(self.db, min_support=x)

    def test_unknown_focus_rejected(self):
        self.populate()
        with self.assertRaisesRegex(EvidenceError, 'focus experiment not found'):
            build_failure_report(self.db, focus_experiment_id='SYNTHETIC-Z')

    def test_tampered_entry_rejected_not_summarized(self):
        self.populate()
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TRIGGER criteria_no_update')
            conn.execute("UPDATE criteria SET verdict='PASS' WHERE experiment_id='SYNTHETIC-A' AND procedure='COST_STRESS'")
        with self.assertRaisesRegex(EvidenceError, 'integrity mismatch'):
            build_failure_report(self.db)

    def test_orphan_row_rejected(self):
        self.populate()
        with sqlite3.connect(self.db) as conn:
            conn.execute('PRAGMA foreign_keys=OFF')
            conn.execute("INSERT INTO criteria VALUES ('ORPHAN','x','COST_STRESS','FAIL','z')")
        with self.assertRaisesRegex(EvidenceError, 'foreign key'):
            build_failure_report(self.db)

    def test_cli_intelligence_synthetic_only(self):
        self.populate()
        io = StringIO()
        with redirect_stdout(io):
            self.assertEqual(main(['memory', 'intelligence', '--db', str(self.db), '--focus', 'SYNTHETIC-A']), 0)
        r = json.loads(io.getvalue())
        self.assertEqual(r['observed_experiment_count'], 4)
        self.assertEqual(r['focus']['experiment']['experiment_id'], 'SYNTHETIC-A')
        self.assertEqual(verify(self.db)['experiment_count'], 4)

    def test_empty_imported_memory_fails_closed_on_missing_focus(self):
        self.add('ONE', [('COST_STRESS', 'FAIL')])
        with self.assertRaises(EvidenceError):
            build_failure_report(self.db, focus_experiment_id='MISSING')


if __name__ == '__main__':
    unittest.main()
