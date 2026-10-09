"""Synthetic-only tests of advisory prioritization and queue trust/lease fences."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.jobs import _finish, claim, submit, verify as verify_queue, work_once
from forexpro_ri.memory import ingest
from forexpro_ri.research_program import build_research_program, render_markdown


class ResearchProgramTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / 'memory.sqlite'

    def add(self, ident, criteria=(), unevaluable=(), *, revision='b' * 40):
        root = self.root / ('fixture-' + self.db.stem + '-' + ident)
        root.mkdir()
        summary = {
            'experiment_id': 'SYNTHETIC-' + ident,
            'disposition': 'CLOSED_UNSUCCESSFUL' if any(x[1] == 'FAIL' for x in criteria) else 'CLOSED_INCOMPLETE',
            'criteria': [{'criterion_id': str(i), 'procedure': proc, 'verdict': verdict,
                          'observation': 'synthetic confidential example'}
                         for i, (proc, verdict) in enumerate(criteria)],
            'not_evaluable': [{'procedure': proc, 'reason': 'synthetic confidential reason'} for proc in unevaluable],
        }
        raw = (json.dumps(summary, sort_keys=True) + '\n').encode()
        manifest = {'schema_version': 1, 'export_kind': 'CLOSED_EXPERIMENT_SUMMARY',
                    'source_system': 'forexpro', 'experiment_id': summary['experiment_id'],
                    'source_revision': revision, 'summary_sha256': hashlib.sha256(raw).hexdigest(),
                    'approved_scope': 'READ_ONLY_ADVISORY', 'holdout_access': False,
                    'promotion_authority': False, 'broker_authority': False}
        (root / 'summary.json').write_bytes(raw)
        (root / 'manifest.json').write_text(json.dumps(manifest))
        ingest(root, self.db, allow_unsigned_synthetic=True)

    def populate(self, order=('A','B','C')):
        cases = {
            'A': ([('OUT_OF_SAMPLE', 'FAIL'), ('COST_STRESS','FAIL')], ['REGIME_STABILITY']),
            'B': ([('OUT_OF_SAMPLE', 'FAIL'), ('COST_STRESS','FAIL')], []),
            'C': ([('OUT_OF_SAMPLE', 'PASS')], ['REGIME_STABILITY']),
        }
        for i in order:
            c, unavailable = cases[i]
            self.add(i, c, unavailable)

    def test_signed_gate_fails_closed_on_unsigned(self):
        self.populate()
        with self.assertRaisesRegex(EvidenceError, 'signed intake'):
            build_research_program(self.db)

    def test_empty_db_is_rejected(self):
        self.add('A', [('OUT_OF_SAMPLE','FAIL')])
        # Missing DB is refused, not created by an advisory query.
        with self.assertRaises(EvidenceError):
            build_research_program(self.root / 'missing.sqlite', allow_unsigned_synthetic=True)

    def test_procedure_coverage_and_evidence_gaps(self):
        self.populate()
        report = build_research_program(self.db, expected_procedures=['MONTE_CARLO','REGIME_STABILITY'],
                                        allow_unsigned_synthetic=True)
        coverage = {x['procedure']: x for x in report['procedure_coverage']}
        self.assertEqual(coverage['OUT_OF_SAMPLE']['counts'], {'fail': 2, 'pass': 1, 'not_evaluable': 0, 'unobserved': 0})
        self.assertEqual(coverage['REGIME_STABILITY']['counts'], {'fail': 0, 'pass': 0, 'not_evaluable': 2, 'unobserved': 1})
        self.assertEqual(coverage['MONTE_CARLO']['counts']['unobserved'], 3)
        recurring = {(i['kind'], i['procedure']) for i in report['worklist']}
        self.assertIn(('REPEATED_FAILURE','OUT_OF_SAMPLE'), recurring)
        self.assertIn(('REPEATED_NOT_EVALUABLE','REGIME_STABILITY'), recurring)
        self.assertIn(('EVIDENCE_GAP','MONTE_CARLO'), recurring)
        self.assertIn(('EVIDENCE_GAP','REGIME_STABILITY'), recurring)
        self.assertEqual(report['worklist'][0]['kind'], 'EVIDENCE_GAP')
        self.assertFalse(any(report['authority'].values()))
        self.assertFalse(report['signed_only_gate_passed'])

    def test_distinct_experiment_support_not_criterion_count(self):
        self.add('A', [('OUT_OF_SAMPLE','FAIL'),('OUT_OF_SAMPLE','FAIL')])
        self.add('B', [('MONTE_CARLO','PASS')])
        r = build_research_program(self.db, allow_unsigned_synthetic=True)
        self.assertFalse(any(x['kind']=='REPEATED_FAILURE' for x in r['worklist']))

    def test_signed_single_fixture_passes_signed_gate(self):
        fixture = self.root / 'signed'
        keys = self.root / 'trusted.json'
        create_synthetic_fixture(fixture, keys)
        ingest(fixture, self.db, trust_store=keys)
        report = build_research_program(self.db)
        self.assertTrue(report['signed_only_gate_passed'])
        self.assertEqual(report['provenance_counts']['signature_verified'], 1)
        self.assertFalse(any(report['authority'].values()))

    def test_hash_and_report_deterministic(self):
        self.populate()
        a = build_research_program(self.db, expected_procedures=['MONTE_CARLO'],allow_unsigned_synthetic=True)
        b = build_research_program(self.db, expected_procedures=['MONTE_CARLO'],allow_unsigned_synthetic=True)
        self.assertEqual(a,b)
        original = self.db
        self.db = self.root / 'ordered.sqlite'
        self.populate(order=('C','A','B'))
        c = build_research_program(self.db, expected_procedures=['MONTE_CARLO'],allow_unsigned_synthetic=True)
        self.assertEqual(a,c)
        self.db=original

    def test_bounded_and_truncated(self):
        self.populate()
        r = build_research_program(self.db, expected_procedures=['MONTE_CARLO','REGIME_STABILITY'],
                                   max_items=2,allow_unsigned_synthetic=True)
        self.assertTrue(r['worklist_truncated'])
        self.assertEqual(len(r['worklist']),2)
        self.assertGreater(r['total_worklist_items'], 2)

    def test_invalid_parameters(self):
        self.populate()
        for options in ({'min_support':1},{'min_support':True},{'min_support':5001},
                        {'max_items':0},{'max_items':31},{'max_items':True},
                        {'expected_procedures':['HOLDOUT']},
                        {'expected_procedures':['OUT_OF_SAMPLE','OUT_OF_SAMPLE']},
                        {'allow_unsigned_synthetic':'yes'}):
            with self.subTest(options=options), self.assertRaises(EvidenceError):
                build_research_program(self.db, **options)

    def test_does_not_store_or_report_observation_prose(self):
        self.populate()
        r = build_research_program(self.db, expected_procedures=['REGIME_STABILITY'],
                                   allow_unsigned_synthetic=True)
        payload = json.dumps(r) + render_markdown(r)
        self.assertNotIn('confidential', payload)
        self.assertIn('operator-selected', payload)
        self.assertEqual(len(r['worklist'][0]['evidence'][0]['receipt_sha256']), 64)

    def test_tampered_history_rejected(self):
        self.populate()
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TRIGGER criteria_no_update')
            conn.execute("UPDATE criteria SET verdict='PASS' WHERE experiment_id='SYNTHETIC-A' AND verdict='FAIL'")
        with self.assertRaisesRegex(EvidenceError, 'integrity mismatch'):
            build_research_program(self.db, allow_unsigned_synthetic=True)

    def test_cli_json_markdown_and_default_signed(self):
        self.populate()
        with redirect_stdout(StringIO()) as stream:
            self.assertEqual(main(['memory','program','--db',str(self.db),
                                   '--unsigned-synthetic','--expected-procedure','REGIME_STABILITY']),0)
        report=json.loads(stream.getvalue())
        self.assertEqual(report['report_kind'],'NON_AUTHORITATIVE_RESEARCH_PROGRAM')
        with redirect_stdout(StringIO()) as stream:
            self.assertEqual(main(['memory','program','--db',str(self.db),
                                   '--unsigned-synthetic','--format','markdown']),0)
        self.assertIn('Research Program',stream.getvalue())
        with redirect_stdout(StringIO()):
            self.assertEqual(main(['memory','program','--db',str(self.db)]),2)


class QueueHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.queue=self.root/'queue.sqlite'
        self.memory=self.root/'memory.sqlite'
        self.out=self.root/'reports'
        self.out.mkdir()

    def signed(self):
        bundle=self.root/'signed'
        trust=self.root/'keys.json'
        create_synthetic_fixture(bundle,trust)
        return bundle,trust

    def test_signed_jobs_pin_trust_store(self):
        bundle,trust=self.signed()
        submit(self.queue,[bundle],self.memory,self.out,trust_store=trust,now=100)
        with sqlite3.connect(self.queue) as conn:
            row=json.loads(conn.execute('select request_json from jobs').fetchone()[0])
        self.assertEqual(row['trust_store_sha256'],hashlib.sha256(trust.read_bytes()).hexdigest())
        self.assertEqual(work_once(self.queue,now=100)['state'],'SUCCEEDED')
        self.assertEqual(verify_queue(self.queue)['status'],'QUEUE_INTACT')

    def test_trust_store_substitution_is_fatal_even_with_valid_key(self):
        bundle,trust=self.signed()
        submit(self.queue,[bundle],self.memory,self.out,trust_store=trust,now=100)
        # Pretty-printing the same valid keys still changes the frozen input bytes.
        trust.write_text(json.dumps(json.loads(trust.read_text()),indent=2))
        result=work_once(self.queue,now=100)
        self.assertEqual(result['state'],'FAILED')
        self.assertEqual(result['error_code'],'INVALID_EVIDENCE')
        self.assertFalse(self.memory.exists())
        self.assertEqual(verify_queue(self.queue)['status'],'QUEUE_INTACT')

    def test_missing_trust_file_rejected_without_partial_intake(self):
        bundle,trust=self.signed()
        submit(self.queue,[bundle],self.memory,self.out,trust_store=trust,now=100)
        trust.unlink()
        self.assertEqual(work_once(self.queue,now=100)['state'],'FAILED')
        self.assertFalse(self.memory.exists())

    def test_expired_lease_rejects_completion_without_reclaim(self):
        from forexpro_ri.jobs import submit as _submit
        fixtures=Path(__file__).resolve().parents[1]/'examples'/'closed_synthetic'
        _submit(self.queue,[fixtures],self.memory,self.out,allow_unsigned_synthetic=True,now=100)
        claim_ = claim(self.queue, now=100, lease_seconds=30)
        with self.assertRaisesRegex(EvidenceError,'expired'):
            _finish(self.queue,claim_,success=False,error='INVALID_EVIDENCE',now=131)
        # No implicit acknowledgement or lease transition. A future claimant owns recovery.
        with sqlite3.connect(self.queue) as conn:
            self.assertEqual(conn.execute('select state from jobs').fetchone()[0],'RUNNING')
        new=claim(self.queue,now=131,lease_seconds=30)
        self.assertNotEqual(new['lease_token'],claim_['lease_token'])

    def test_legacy_signed_queue_requires_resubmission(self):
        from forexpro_ri.jobs import _check_inputs
        bundle,trust=self.signed()
        submit(self.queue,[bundle],self.memory,self.out,trust_store=trust,now=100)
        with sqlite3.connect(self.queue) as conn:
            cfg=json.loads(conn.execute('select request_json from jobs').fetchone()[0])
        cfg.pop('trust_store_sha256')
        with self.assertRaisesRegex(EvidenceError,'legacy signed'):
            _check_inputs(cfg)

    def test_unsigned_queue_remains_supported(self):
        fixtures=Path(__file__).resolve().parents[1]/'examples'/'closed_synthetic'
        submit(self.queue,[fixtures],self.memory,self.out,allow_unsigned_synthetic=True,now=100)
        self.assertEqual(work_once(self.queue,now=100)['state'],'SUCCEEDED')
