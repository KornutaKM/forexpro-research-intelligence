"""Synthetic-only triage tests: descriptive evidence, no scientific authority."""
from __future__ import annotations
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.memory import ingest
from forexpro_ri.research_program import build_program, render_markdown

FIXTURES = Path(__file__).resolve().parents[1] / 'examples'


class ResearchProgramTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'memory.sqlite'

    def seed(self):
        for name in ('closed_synthetic', 'closed_synthetic_peer'):
            ingest(FIXTURES/name, self.db, allow_unsigned_synthetic=True)

    def program(self, **kwargs):
        return build_program(self.db, require_signed=False, **kwargs)

    def test_default_requires_signatures(self):
        self.seed()
        with self.assertRaisesRegex(EvidenceError, 'unsigned or legacy'):
            build_program(self.db)

    def test_unobserved_is_not_failed(self):
        self.seed()
        report=self.program(expected_procedures=['MONTE_CARLO'])
        by={item['procedure']:item for item in report['ranked_review_topics']}
        self.assertEqual(by['MONTE_CARLO']['recorded_counts'], {'FAIL': 0,'PASS': 0,'NOT_EVALUABLE': 1,'UNOBSERVED': 1})
        self.assertEqual(by['REGIME_STABILITY']['recorded_counts']['NOT_EVALUABLE'], 1)
        self.assertEqual(by['REGIME_STABILITY']['recorded_counts']['UNOBSERVED'], 1)

    def test_recurring_failure_counts_distinct_experiments(self):
        self.seed()
        report=self.program()
        item=report['ranked_review_topics'][0]
        self.assertEqual(item['procedure'],'COST_STRESS')
        self.assertEqual(item['attention_class'],'REPEATED_RECORDED_FAILURE')
        self.assertEqual(item['recorded_counts']['FAIL'],2)
        self.assertEqual(len(item['negative_evidence']['FAIL']),2)

    def test_mixed_pass_fail_not_inferred_causal(self):
        self.seed()
        report=self.program()
        by={x['procedure']:x for x in report['ranked_review_topics']}
        self.assertTrue(by['OUT_OF_SAMPLE']['mixed_pass_fail'])
        self.assertEqual(by['OUT_OF_SAMPLE']['recorded_counts']['PASS'],1)
        self.assertTrue(any('causes' in x for x in report['limitations']))

    def test_explicit_expectation_creates_gap(self):
        self.seed()
        report=self.program(expected_procedures=['RISK_LIMITS'])
        by={x['procedure']:x for x in report['ranked_review_topics']}
        self.assertEqual(by['RISK_LIMITS']['attention_class'],'REPEATED_EVIDENCE_GAP')
        self.assertEqual(by['RISK_LIMITS']['recorded_counts']['UNOBSERVED'],2)
        self.assertTrue(by['RISK_LIMITS']['operator_declared_expected'])

    def test_unobserved_without_expected_is_not_gap_ranking(self):
        self.seed()
        report=self.program()
        by={x['procedure']:x for x in report['ranked_review_topics']}
        self.assertEqual(by['DETERMINISTIC_RERUN']['attention_class'],'NO_NEGATIVE_OBSERVATION')

    def test_same_report_independent_of_import_order(self):
        self.seed()
        a=self.program(expected_procedures=['MONTE_CARLO','RISK_LIMITS'])
        other=self.root/'other.sqlite'
        for name in ('closed_synthetic_peer', 'closed_synthetic'):
            ingest(FIXTURES/name, other, allow_unsigned_synthetic=True)
        b=build_program(other, require_signed=False, expected_procedures=['RISK_LIMITS','MONTE_CARLO'])
        self.assertEqual(a,b)
        self.assertEqual(a['report_sha256'], hashlib.sha256(json.dumps(
            {k:v for k,v in a.items() if k!='report_sha256'},
            sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest())

    def test_signature_verified_signed_default(self):
        bundle=self.root/'signed'; trust=self.root/'trust.json'
        create_synthetic_fixture(bundle,trust)
        ingest(bundle,self.db,trust_store=trust)
        report=build_program(self.db)
        self.assertEqual(report['intake_status_counts']['SIGNATURE_VERIFIED'],1)
        self.assertEqual(report['intake_policy'],'SIGNED_AT_IMPORT_ONLY')
        self.assertFalse(any(report['authority'].values()))

    def test_mixed_history_rejected_by_default(self):
        self.seed()
        with self.assertRaises(EvidenceError):
            build_program(self.db)

    def test_unknown_expected_rejected(self):
        self.seed()
        with self.assertRaises(EvidenceError):
            self.program(expected_procedures=['HOLDOUT'])

    def test_duplicate_expected_rejected(self):
        self.seed()
        with self.assertRaises(EvidenceError):
            self.program(expected_procedures=['MONTE_CARLO','MONTE_CARLO'])

    def test_invalid_min_support_rejected(self):
        self.seed()
        for value in (1,5001,2.0,True):
            with self.subTest(value=value),self.assertRaises(EvidenceError):
                self.program(min_support=value)

    def test_missing_memory_rejected(self):
        with self.assertRaises(EvidenceError):
            build_program(self.db)

    def test_empty_memory_rejected(self):
        self.seed()
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TRIGGER experiments_no_delete')
            conn.execute('DROP TRIGGER criteria_no_delete')
            conn.execute('DROP TRIGGER not_evaluable_no_delete')
            conn.execute('DROP TRIGGER intake_receipts_no_delete')
            conn.execute('DELETE FROM criteria')
            conn.execute('DELETE FROM not_evaluable')
            conn.execute('DELETE FROM intake_receipts')
            conn.execute('DELETE FROM experiments')
        with self.assertRaisesRegex(EvidenceError,'requires 1..5000'):
            self.program()

    def test_tampered_memory_rejected(self):
        self.seed()
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TRIGGER criteria_no_update')
            conn.execute("UPDATE criteria SET verdict='PASS' WHERE verdict='FAIL'")
        with self.assertRaises(EvidenceError):
            self.program()

    def test_report_never_contains_raw_observations(self):
        self.seed()
        raw=json.dumps(self.program())
        self.assertNotIn('transaction-cost',raw)
        self.assertNotIn('net PnL',raw)
        self.assertFalse('source_platform_integrated' in raw)

    def test_markdown_and_cli(self):
        self.seed()
        report=self.program(expected_procedures=['MONTE_CARLO'])
        text=render_markdown(report)
        self.assertIn('NON', report['report_kind'])
        self.assertIn('UNOBSERVED',text)
        self.assertIn(report['report_sha256'],text)
        self.assertEqual(main(['memory','program','--db',str(self.db),
                               '--expected-procedure','MONTE_CARLO',
                               '--allow-unsigned-synthetic','--format','markdown']),0)
        self.assertEqual(main(['memory','program','--db',str(self.db)]),2)

    def test_signed_claim_not_upgraded_from_legacy(self):
        self.seed()
        with sqlite3.connect(self.db) as conn:
            c=conn.execute('SELECT COUNT(*) FROM intake_receipts WHERE verification_status="SIGNATURE_VERIFIED"').fetchone()[0]
            self.assertEqual(c,0)
        self.assertEqual(self.program()['intake_status_counts']['UNSIGNED_SYNTHETIC'],2)


if __name__ == '__main__':
    unittest.main()
