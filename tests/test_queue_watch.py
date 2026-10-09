"""Operational boundaries: drift, stale leases, job auditing, signed trust freeze."""
from __future__ import annotations
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.jobs import claim, status, submit, verify, work_once
from forexpro_ri.queue_watch import inspect

BASE=Path(__file__).resolve().parents[1]/'examples'/'closed_synthetic'


class WatchTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory();self.addCleanup(t.cleanup)
        self.dir=Path(t.name)
        self.queue=self.dir/'jobs.sqlite';self.memory=self.dir/'memory.sqlite'
        self.reports=self.dir/'reports';self.reports.mkdir()

    def put(self, **kwargs):
        return submit(self.queue,[BASE],self.memory,self.reports,
                      allow_unsigned_synthetic=True,now=100,**kwargs)

    def test_empty_queue_rejected_without_creation(self):
        with self.assertRaises(EvidenceError):inspect(self.queue)
        self.assertFalse(self.queue.exists())

    def test_queued_idle_clear(self):
        self.put()
        watch=inspect(self.queue,at=100)
        self.assertEqual(watch['status'],'CLEAR')
        self.assertFalse(any(watch['authority'].values()))
        self.assertEqual(watch['inspected_job_count'],1)

    def test_queued_overdue(self):
        self.put()
        watch=inspect(self.queue,at=5000,overdue_seconds=60)
        self.assertEqual(watch['status'],'WATCH')
        self.assertEqual(watch['alert_counts']['OVERDUE_QUEUED'],1)

    def test_expired_lease_detected_read_only(self):
        self.put();claim(self.queue,now=100,lease_seconds=30)
        watch=inspect(self.queue,at=131)
        self.assertEqual(watch['status'],'ATTENTION_REQUIRED')
        self.assertEqual(watch['alert_counts']['EXPIRED_LEASE'],1)
        self.assertEqual(status(self.queue)['counts']['RUNNING'],1)
        self.assertEqual(verify(self.queue)['event_count'],2)

    def test_failed_job_detected_without_error_details(self):
        self.put(max_attempts=1)
        claim(self.queue,now=100,lease_seconds=30)
        claim(self.queue,now=131)
        watch=inspect(self.queue,at=132)
        self.assertEqual(watch['alert_counts']['FAILED_JOB'],1)
        self.assertNotIn('summary.json',json.dumps(watch))

    def test_changed_source_detected_with_opt_in(self):
        bundle=self.dir/'copy';bundle.mkdir()
        for p in BASE.iterdir():
            (bundle/p.name).write_bytes(p.read_bytes())
        submit(self.queue,[bundle],self.memory,self.reports,allow_unsigned_synthetic=True,now=100)
        (bundle/'summary.json').write_text('{}')
        self.assertEqual(inspect(self.queue,at=100)['status'],'CLEAR')
        report=inspect(self.queue,at=100,inspect_sources=True)
        self.assertEqual(report['alert_counts']['INPUT_CHANGED'],1)
        self.assertEqual(report['status'],'ATTENTION_REQUIRED')
        self.assertEqual(status(self.queue)['counts']['QUEUED'],1)

    def test_report_is_deterministic_for_same_time(self):
        self.put()
        self.assertEqual(inspect(self.queue,at=150),inspect(self.queue,at=150))

    def test_report_is_bounded_and_truncated(self):
        self.put();claim(self.queue,now=100,lease_seconds=30)
        r=inspect(self.queue,at=5000,max_alerts=1)
        self.assertEqual(len(r['alerts']),1)
        self.assertEqual(r['alert_counts']['EXPIRED_LEASE'],1)

    def test_invalid_limits_rejected(self):
        self.put()
        for field,value in [('overdue_seconds',1),('max_alerts',0),('max_alerts',501),
                             ('inspect_sources',1)]:
            with self.subTest(field=field),self.assertRaises(EvidenceError):
                inspect(self.queue,**{field:value})

    def test_signed_trust_store_pin(self):
        bundle=self.dir/'signed';trust=self.dir/'trust.json'
        create_synthetic_fixture(bundle,trust)
        submit(self.queue,[bundle],self.memory,self.reports,trust_store=trust,now=100)
        with sqlite3.connect(self.queue) as conn:
            cfg=json.loads(conn.execute('SELECT request_json FROM jobs').fetchone()[0])
        self.assertEqual(len(cfg['trust_store_sha256']),64)
        self.assertEqual(work_once(self.queue,now=100)['state'],'SUCCEEDED')
        self.assertEqual(verify(self.queue)['status'],'QUEUE_INTACT')

    def test_changed_signed_trust_store_refused_before_import(self):
        bundle=self.dir/'signed';trust=self.dir/'trust.json'
        create_synthetic_fixture(bundle,trust)
        submit(self.queue,[bundle],self.memory,self.reports,trust_store=trust,now=100)
        store=json.loads(trust.read_text());store['meta']='changed'
        trust.write_text(json.dumps(store))
        self.assertEqual(inspect(self.queue,at=100,inspect_sources=True)['alert_counts']['INPUT_CHANGED'],1)
        r=work_once(self.queue,now=100)
        self.assertEqual(r['state'],'FAILED')
        self.assertFalse(self.memory.exists())

    def test_signed_key_revocation_is_detected(self):
        bundle=self.dir/'signed';trust=self.dir/'trust.json'
        create_synthetic_fixture(bundle,trust)
        submit(self.queue,[bundle],self.memory,self.reports,trust_store=trust,now=100)
        store=json.loads(trust.read_text());store['keys'][0]['status']='REVOKED'
        trust.write_text(json.dumps(store))
        self.assertEqual(work_once(self.queue,now=100)['state'],'FAILED')

    def test_tampered_queue_request_blocks_execution(self):
        self.put()
        with sqlite3.connect(self.queue) as conn:
            c=json.loads(conn.execute('SELECT request_json FROM jobs').fetchone()[0]);c['min_support']=5
            conn.execute('UPDATE jobs SET request_json=?',(json.dumps(c),))
        self.assertEqual(work_once(self.queue,now=100)['state'],'FAILED')
        self.assertFalse(self.memory.exists())

    def test_queue_audit_failure_blocks_watch(self):
        self.put()
        with sqlite3.connect(self.queue) as conn:
            conn.execute("UPDATE jobs SET state='FAILED' WHERE state='QUEUED'")
        with self.assertRaises(EvidenceError):inspect(self.queue)

    def test_cli_watch(self):
        self.put()
        self.assertEqual(main(['jobs','watch','--queue',str(self.queue),
                               '--inspect-sources','--overdue-seconds','1000']),0)

    def test_legacy_v2_queue_request_still_supported(self):
        self.put()
        # Re-create a v2.0-shaped request and digest; no trust pin in unsigned mode.
        from forexpro_ri.jobs import _hash, _validate_config
        with sqlite3.connect(self.queue) as conn:
            cfg=json.loads(conn.execute('SELECT request_json FROM jobs').fetchone()[0]);del cfg['trust_store_sha256']
            _validate_config(cfg)
            conn.execute('UPDATE jobs SET request_json=?,request_sha256=?',(json.dumps(cfg),_hash(cfg)))
        self.assertEqual(work_once(self.queue,now=100)['state'],'SUCCEEDED')
        self.assertEqual(verify(self.queue)['status'],'QUEUE_INTACT')

if __name__=='__main__': unittest.main()
