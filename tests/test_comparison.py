"""Synthetic-only FRI cohort comparison regression and safety tests."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path

from forexpro_ri.analysis import canonical_json
from forexpro_ri.cli import main
from forexpro_ri.comparison import build_comparison, render_markdown
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import ingest, verify


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = self.root / 'memory.sqlite'
        self.bundle = self.root / 'input'
        self.bundle.mkdir()

    def add(self, eid: str, criteria=(), unevaluable=(), disposition=None):
        assert eid.startswith('SYNTHETIC-')
        summary = {
            'experiment_id': eid,
            'disposition': disposition or ('CLOSED_UNSUCCESSFUL' if any(s == 'FAIL' for _, s in criteria) else 'CLOSED_INCOMPLETE'),
            'criteria': [
                {'criterion_id': f'criterion-{i}', 'procedure': proc, 'verdict': outcome,
                 'observation': 'SYNTHETIC: secret metric value must not be copied'}
                for i, (proc, outcome) in enumerate(criteria)
            ],
            'not_evaluable': [
                {'procedure': proc, 'reason': 'SYNTHETIC: sensitive reason not retained'}
                for proc in unevaluable
            ],
        }
        raw = (json.dumps(summary, sort_keys=True) + '\n').encode('utf-8')
        manifest = {
            'schema_version': 1,
            'export_kind': 'CLOSED_EXPERIMENT_SUMMARY',
            'source_system': 'forexpro',
            'experiment_id': eid,
            'source_revision': 'a' * 40,
            'summary_sha256': hashlib.sha256(raw).hexdigest(),
            'approved_scope': 'READ_ONLY_ADVISORY',
            'holdout_access': False,
            'promotion_authority': False,
            'broker_authority': False,
        }
        (self.bundle / 'summary.json').write_bytes(raw)
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest))
        ingest(self.bundle, self.db)

    def populate(self, order=('A', 'B', 'C')):
        fixtures = {
            'A': ([('OUT_OF_SAMPLE', 'FAIL'), ('OUT_OF_SAMPLE', 'PASS'), ('COST_STRESS', 'FAIL')], []),
            'B': ([('OUT_OF_SAMPLE', 'PASS'), ('COST_STRESS', 'FAIL')], ['REGIME_STABILITY']),
            'C': ([('MONTE_CARLO', 'PASS')], ['REGIME_STABILITY']),
        }
        for suffix in order:
            criteria, missing = fixtures[suffix]
            self.add('SYNTHETIC-' + suffix, criteria, missing)

    def compare(self, ids=('SYNTHETIC-A', 'SYNTHETIC-B'), expected=()):
        return build_comparison(self.db, experiment_ids=ids, expected_procedures=expected)

    def test_two_experiments_and_status_differences(self):
        self.populate()
        r = self.compare()
        self.assertEqual(r['report_kind'], 'NON_AUTHORITATIVE_COHORT_COMPARISON')
        rows = {x['procedure']: x for x in r['comparison']}
        self.assertEqual([x['recorded_status'] for x in rows['OUT_OF_SAMPLE']['outcomes']], ['FAIL', 'PASS'])
        self.assertTrue(rows['OUT_OF_SAMPLE']['status_divergence'])
        self.assertEqual(rows['OUT_OF_SAMPLE']['counts'], {'FAIL': 1, 'PASS': 1, 'NOT_EVALUABLE': 0, 'UNOBSERVED': 0})
        self.assertEqual([x['recorded_status'] for x in rows['COST_STRESS']['outcomes']], ['FAIL', 'FAIL'])
        self.assertFalse(rows['COST_STRESS']['status_divergence'])
        self.assertEqual(len(rows['OUT_OF_SAMPLE']['outcomes'][0]['criteria_evidence']), 2)
        self.assertEqual(r['divergent_procedures'], ['OUT_OF_SAMPLE', 'REGIME_STABILITY'])

    def test_explicit_expectation_gap_does_not_become_failed_or_passed(self):
        self.populate()
        r = self.compare(expected=['MONTE_CARLO', 'DETERMINISTIC_RERUN'])
        rows = {x['procedure']: x for x in r['comparison']}
        self.assertTrue(rows['MONTE_CARLO']['expected_by_operator'])
        self.assertEqual(rows['MONTE_CARLO']['counts']['UNOBSERVED'], 2)
        gaps = [x for x in r['evidence_gaps'] if x['procedure'] == 'MONTE_CARLO']
        self.assertEqual(len(gaps), 2)
        self.assertTrue(all(g['basis'] == 'OPERATOR_DECLARED' for g in gaps))
        self.assertTrue(all(g['recorded_status'] == 'UNOBSERVED' for g in gaps))
        self.assertFalse(r['scientific_authority'])
        self.assertFalse(r['holdout_access'])

    def test_not_evaluable_is_distinct_from_unobserved(self):
        self.populate()
        r = self.compare()
        by_exp = {x['experiment_id']: x for x in next(p for p in r['comparison'] if p['procedure'] == 'REGIME_STABILITY')['outcomes']}
        self.assertEqual(by_exp['SYNTHETIC-A']['recorded_status'], 'UNOBSERVED')
        self.assertIsNone(by_exp['SYNTHETIC-A']['not_evaluable_reason_sha256'])
        self.assertEqual(by_exp['SYNTHETIC-B']['recorded_status'], 'NOT_EVALUABLE')
        self.assertEqual(len(by_exp['SYNTHETIC-B']['not_evaluable_reason_sha256']), 64)

    def test_cohort_observed_not_mistaken_for_policy(self):
        self.populate()
        r = self.compare()
        gaps = [x for x in r['evidence_gaps'] if x['procedure'] == 'REGIME_STABILITY']
        self.assertEqual([x['basis'] for x in gaps], ['COHORT_OBSERVED', 'COHORT_OBSERVED'])
        self.assertEqual(r['declared_expected_procedures'], [])
        self.assertIn('NOT a verified ForexPro ValidationContract', ' '.join(r['limitations']))

    def test_sort_independent_and_content_addressed(self):
        self.populate()
        a = self.compare(ids=['SYNTHETIC-B', 'SYNTHETIC-A'], expected=['OUT_OF_SAMPLE', 'MONTE_CARLO'])
        b = self.compare(ids=['SYNTHETIC-A', 'SYNTHETIC-B'], expected=['MONTE_CARLO', 'OUT_OF_SAMPLE'])
        self.assertEqual(a, b)
        sha = a.pop('report_sha256')
        self.assertEqual(sha, hashlib.sha256(canonical_json(a).encode('utf-8')).hexdigest())

    def test_same_case_order_independent_of_ingestion_order(self):
        self.populate()
        a = self.compare(ids=['SYNTHETIC-C', 'SYNTHETIC-A'])
        self.db = self.root / 'second.sqlite'
        self.populate(order=('C', 'B', 'A'))
        b = self.compare(ids=['SYNTHETIC-A', 'SYNTHETIC-C'])
        self.assertEqual(a, b)

    def test_selected_subset_excludes_nonselected_data(self):
        self.populate()
        r = self.compare()
        source = json.dumps(r)
        self.assertNotIn('SYNTHETIC-C', source)
        self.assertNotIn('sensitive reason', source)
        self.assertNotIn('secret metric', source)
        self.assertNotIn('secret metric', self.db.read_bytes().decode('latin-1'))
        self.assertEqual(len(r['selected_experiments']), 2)

    def test_not_an_authentication_proof(self):
        self.populate()
        r = self.compare()
        self.assertEqual(r['source_authenticity'], 'NOT_ESTABLISHED_FROM_MEMORY')
        self.assertFalse(r['broker_authority'])
        self.assertIn('not scientifically proven independent', ' '.join(r['limitations']))
        self.assertNotIn('source_export_signature_verified', r)

    def test_duplicate_or_too_few_experiments_rejected(self):
        self.populate()
        for ids in ([], ['SYNTHETIC-A'], ['SYNTHETIC-A', 'SYNTHETIC-A'], 'SYNTHETIC-A', ['SYNTHETIC-A'] * 51):
            with self.subTest(ids=ids), self.assertRaises(EvidenceError):
                self.compare(ids=ids)

    def test_invalid_expected_procedures_rejected(self):
        self.populate()
        for expected in (['HOLDOUT'], ['COST_STRESS', 'COST_STRESS'], ['TRAIN'], 'COST_STRESS', [None]):
            with self.subTest(expected=expected), self.assertRaises(EvidenceError):
                self.compare(expected=expected)

    def test_unknown_experiment_rejected(self):
        self.populate()
        with self.assertRaisesRegex(EvidenceError, 'unknown experiment IDs'):
            self.compare(ids=['SYNTHETIC-A', 'SYNTHETIC-Z'])

    def test_invalid_sqlite_content_rejected(self):
        self.populate()
        with sqlite3.connect(self.db) as db:
            db.execute('DROP TRIGGER criteria_no_update')
            db.execute("UPDATE criteria SET verdict='PASS' WHERE experiment_id='SYNTHETIC-A' AND procedure='COST_STRESS'")
        with self.assertRaisesRegex(EvidenceError, 'integrity mismatch'):
            self.compare()

    def test_unselected_tampered_row_also_rejected(self):
        self.populate()
        with sqlite3.connect(self.db) as db:
            db.execute('DROP TRIGGER experiments_no_update')
            db.execute("UPDATE experiments SET pass_count=999 WHERE experiment_id='SYNTHETIC-C'")
        with self.assertRaisesRegex(EvidenceError, 'integrity mismatch'):
            self.compare()

    def test_sqlite_orphan_rejected(self):
        self.populate()
        with sqlite3.connect(self.db) as db:
            db.execute('PRAGMA foreign_keys=OFF')
            db.execute("INSERT INTO criteria VALUES ('OTHER','x','COST_STRESS','FAIL','0')")
        with self.assertRaisesRegex(EvidenceError, 'foreign key'):
            self.compare()

    def test_markdown_rendering_contains_gaps_and_hashes(self):
        self.populate()
        r = self.compare()
        md = render_markdown(r)
        self.assertIn('| Procedure | SYNTHETIC-A | SYNTHETIC-B | Expected by operator |', md)
        self.assertIn('| OUT_OF_SAMPLE | FAIL | PASS | no |', md)
        self.assertIn('NOT_EVALUABLE', md)
        self.assertIn(r['report_sha256'], md)
        self.assertNotIn('sensitive reason', md)
        with self.assertRaises(EvidenceError):
            render_markdown({'report_kind': 'SOMETHING_ELSE'})

    def test_cli_json_and_markdown(self):
        self.populate()
        out = StringIO()
        args = ['memory', 'compare', '--db', str(self.db), '--experiment', 'SYNTHETIC-B', '--experiment', 'SYNTHETIC-A', '--expected-procedure', 'MONTE_CARLO']
        with redirect_stdout(out):
            code = main(args)
        self.assertEqual(code, 0)
        result = json.loads(out.getvalue())
        self.assertEqual(result['declared_expected_procedures'], ['MONTE_CARLO'])
        out = StringIO()
        with redirect_stdout(out):
            code = main(args + ['--format', 'markdown'])
        self.assertEqual(code, 0)
        self.assertIn('## Evidence visibility gaps', out.getvalue())
        self.assertTrue(out.getvalue().endswith('\n'))

    def test_cli_rejects_invalid_comparison(self):
        self.populate()
        err = StringIO()
        with redirect_stderr(err):
            code = main(['memory', 'compare', '--db', str(self.db), '--experiment', 'SYNTHETIC-A', '--experiment', 'SYNTHETIC-A'])
        self.assertEqual(code, 2)
        self.assertIn('MEMORY_REJECTED', err.getvalue())

    def test_database_unmodified_by_compare(self):
        self.populate()
        before = verify(self.db)
        binary = self.db.read_bytes()
        self.compare()
        after = verify(self.db)
        self.assertEqual(before, after)
        self.assertEqual(binary, self.db.read_bytes())


if __name__ == '__main__':
    unittest.main()
