"""Offline queue, durability, event audit, and failure boundary tests."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from forexpro_ri.contracts import EvidenceError
from forexpro_ri.jobs import (_finish, claim, drain, status, submit, verify,
                              work_once)
from forexpro_ri.operations import verify_report_dir

FIXTURES = Path(__file__).resolve().parents[1] / 'examples'
BUNDLE1 = FIXTURES / 'closed_synthetic'
BUNDLE2 = FIXTURES / 'closed_synthetic_peer'


class JobsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.queue = self.root / 'queue.sqlite'
        self.memory = self.root / 'memory.sqlite'
        self.output = self.root / 'outputs'
        self.output.mkdir()

    def put(self, bundles=(BUNDLE1,), **kwargs):
        return submit(self.queue, bundles, self.memory, self.output,
                      allow_unsigned_synthetic=True, now=100, **kwargs)

    def test_single_end_to_end(self):
        job = self.put()
        self.assertEqual(job['status'], 'QUEUED')
        result = work_once(self.queue, now=100)
        self.assertEqual(result['state'], 'SUCCEEDED')
        self.assertEqual(result['attempt'], 1)
        self.assertEqual(verify_report_dir(result['report_dir'])['status'], 'LOCAL_FILES_INTACT')
        self.assertEqual(status(self.queue)['counts']['SUCCEEDED'], 1)
        self.assertEqual(verify(self.queue)['event_count'], 3)

    def test_two_bundles_and_drain(self):
        self.put((BUNDLE1, BUNDLE2))
        self.assertEqual(drain(self.queue)['processed'], 1)
        self.assertEqual(status(self.queue)['counts']['SUCCEEDED'], 1)
        with sqlite3.connect(self.memory) as conn:
            self.assertEqual(conn.execute('select count(*) from experiments').fetchone()[0], 2)

    def test_duplicate_request_idempotent(self):
        first = self.put()
        second = self.put()
        self.assertEqual(second['status'], 'ALREADY_QUEUED')
        self.assertEqual(first['job_id'], second['job_id'])
        self.assertEqual(verify(self.queue)['event_count'], 1)

    def test_idle_worker_does_not_mutate(self):
        self.put()
        self.assertEqual(work_once(self.queue, now=99)['status'], 'IDLE')
        before = verify(self.queue)
        self.assertEqual(work_once(self.queue, now=99)['status'], 'IDLE')
        self.assertEqual(verify(self.queue), before)

    def test_leased_job_not_double_claimed(self):
        self.put()
        task = claim(self.queue, now=100, lease_seconds=30)
        self.assertIsNotNone(task)
        self.assertIsNone(claim(self.queue, now=129, lease_seconds=30))
        self.assertEqual(status(self.queue)['counts']['RUNNING'], 1)
        self.assertEqual(verify(self.queue)['event_count'], 2)

    def test_lease_reclaim_rejects_stale_worker(self):
        self.put()
        old = claim(self.queue, now=100, lease_seconds=30)
        new = claim(self.queue, now=131, lease_seconds=30)
        self.assertEqual(new['attempt'], 2)
        self.assertNotEqual(new['lease_token'], old['lease_token'])
        with self.assertRaisesRegex(EvidenceError, 'stale worker'):
            _finish(self.queue, old, success=False, error='INVALID_EVIDENCE', now=132)
        self.assertEqual(verify(self.queue)['event_count'], 4)

    def test_exhausted_lease_moves_to_dead_letter(self):
        self.put(max_attempts=1)
        claim(self.queue, now=100, lease_seconds=30)
        self.assertIsNone(claim(self.queue, now=131))
        self.assertEqual(status(self.queue)['counts']['FAILED'], 1)
        self.assertEqual(verify(self.queue)['event_count'], 3)

    def test_transient_error_retries_with_backoff(self):
        self.put()
        with patch('forexpro_ri.jobs.run_pipeline', side_effect=OSError('no space')):
            outcome = work_once(self.queue, now=100)
        self.assertEqual(outcome['state'], 'RETRY')
        self.assertEqual(outcome['error_code'], 'TRANSIENT_IO')
        self.assertEqual(work_once(self.queue, now=119)['status'], 'IDLE')
        outcome = work_once(self.queue, now=120)
        self.assertEqual(outcome['state'], 'SUCCEEDED')
        self.assertEqual(outcome['attempt'], 2)
        self.assertEqual(verify(self.queue)['event_count'], 5)

    def test_permanent_validation_failure_no_retry(self):
        self.put()
        with patch('forexpro_ri.jobs.run_pipeline', side_effect=EvidenceError('secret/path')):
            outcome = work_once(self.queue, now=100)
        self.assertEqual(outcome['state'], 'FAILED')
        self.assertEqual(outcome['error_code'], 'INVALID_EVIDENCE')
        self.assertNotIn('secret', json.dumps(status(self.queue)))
        self.assertEqual(verify(self.queue)['event_count'], 3)

    def test_unexpected_exception_is_sanitized(self):
        self.put()
        with patch('forexpro_ri.jobs.run_pipeline', side_effect=RuntimeError('private value')):
            outcome = work_once(self.queue, now=100)
        self.assertEqual(outcome['state'], 'FAILED')
        self.assertEqual(outcome['error_code'], 'UNEXPECTED_WORKER_ERROR')
        self.assertNotIn('private value', json.dumps(status(self.queue)))

    def test_tamper_stored_job_state_detected(self):
        self.put()
        with sqlite3.connect(self.queue) as conn:
            conn.execute("update jobs set state='FAILED' where state='QUEUED'")
        with self.assertRaisesRegex(EvidenceError, 'diverged'):
            verify(self.queue)

    def test_tamper_event_blocked_by_trigger(self):
        self.put()
        with sqlite3.connect(self.queue) as conn:
            with self.assertRaises(sqlite3.DatabaseError):
                conn.execute("update events set event_type='SUCCEEDED'")

    def test_report_modified_detected(self):
        self.put()
        result = work_once(self.queue, now=100)
        (Path(result['report_dir']) / 'run.json').write_text('{}')
        with self.assertRaises(EvidenceError):
            verify(self.queue)
        self.assertEqual(verify(self.queue, verify_outputs=False)['status'], 'QUEUE_INTACT')

    def test_input_file_mutation_after_submit_rejected(self):
        source = self.root / 'copy'
        source.mkdir()
        for p in BUNDLE1.iterdir():
            (source / p.name).write_bytes(p.read_bytes())
        self.put((source,))
        (source / 'summary.json').write_text('{"tamper":true}')
        result = work_once(self.queue, now=100)
        self.assertEqual(result['state'], 'FAILED')
        self.assertFalse(self.memory.exists())
        self.assertEqual(verify(self.queue)['event_count'], 3)

    def test_queue_separate_from_memory(self):
        with self.assertRaisesRegex(EvidenceError, 'separate'):
            submit(self.memory, (BUNDLE1,), self.memory, self.output, allow_unsigned_synthetic=True)

    def test_queue_inside_bundle_forbidden(self):
        with self.assertRaises(EvidenceError):
            submit(BUNDLE1 / 'queue.sqlite', (BUNDLE1,), self.memory, self.output,
                   allow_unsigned_synthetic=True)

    def test_synthetic_mode_must_be_explicit(self):
        with self.assertRaisesRegex(EvidenceError, 'select signed'):
            submit(self.queue, (BUNDLE1,), self.memory, self.output)

    def test_unknown_procedure_rejected_before_queue_creation(self):
        with self.assertRaises(EvidenceError):
            self.put(expected_procedures=['HOLDOUT'])
        self.assertFalse(self.queue.exists())

    def test_reject_bad_attempt_bounds(self):
        with self.assertRaises(EvidenceError):
            self.put(max_attempts=4)
        self.assertFalse(self.queue.exists())

    def test_reject_duplicate_bundle_path(self):
        with self.assertRaises(EvidenceError):
            self.put((BUNDLE1, BUNDLE1))
        self.assertFalse(self.queue.exists())

    def test_queue_missing_rejected(self):
        with self.assertRaises(EvidenceError):
            work_once(self.queue)
        with self.assertRaises(EvidenceError):
            verify(self.queue)

    def test_no_report_during_claim(self):
        self.put()
        claim(self.queue, now=100)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_queue_report_can_be_public_safe_json(self):
        self.put()
        r = status(self.queue)
        self.assertFalse(any(r['authority'].values()))
        self.assertNotIn('observation', json.dumps(r))

    def test_invalid_source_symlink_rejected(self):
        link = self.root / 'source_link'
        link.symlink_to(BUNDLE1, target_is_directory=True)
        with self.assertRaises(EvidenceError):
            self.put((link,))

    def test_replay_after_failed_io_preserves_idempotent_memory(self):
        self.put()
        # Simulate a process that committed evidence but failed before result acknowledgement.
        from forexpro_ri.operations import run as original
        def interrupted(*args, **kwargs):
            original(*args, **kwargs)
            raise OSError('acknowledgement lost')
        with patch('forexpro_ri.jobs.run_pipeline', side_effect=interrupted):
            first = work_once(self.queue, now=100)
        self.assertEqual(first['state'], 'RETRY')
        second = work_once(self.queue, now=120)
        self.assertEqual(second['state'], 'SUCCEEDED')
        with sqlite3.connect(self.memory) as conn:
            self.assertEqual(conn.execute('select count(*) from experiments').fetchone()[0], 1)
        self.assertEqual(verify(self.queue)['status'], 'QUEUE_INTACT')


    def test_manual_requeue_after_exhaustion(self):
        from forexpro_ri.jobs import requeue_failed
        self.put(max_attempts=1)
        claim(self.queue, now=100, lease_seconds=30)
        self.assertIsNone(claim(self.queue, now=131))
        result = requeue_failed(self.queue, status(self.queue)['jobs'][0]['job_id'], now=140)
        self.assertEqual(result['status'], 'EXPLICITLY_REQUEUED')
        self.assertEqual(work_once(self.queue, now=140)['state'], 'SUCCEEDED')
        self.assertEqual(verify(self.queue)['event_count'], 6)

    def test_manual_requeue_requires_failure(self):
        from forexpro_ri.jobs import requeue_failed
        job = self.put()
        with self.assertRaises(EvidenceError):
            requeue_failed(self.queue, job['job_id'])
        self.assertEqual(verify(self.queue)['event_count'], 1)

    def test_manual_requeue_rejects_changed_input(self):
        from forexpro_ri.jobs import requeue_failed
        source = self.root / 'fixture'
        source.mkdir()
        for p in BUNDLE1.iterdir():
            (source / p.name).write_bytes(p.read_bytes())
        job = self.put((source,), max_attempts=1)
        with patch('forexpro_ri.jobs.run_pipeline', side_effect=EvidenceError('reject')):
            self.assertEqual(work_once(self.queue, now=100)['state'], 'FAILED')
        (source / 'summary.json').write_text('{}')
        with self.assertRaises(EvidenceError):
            requeue_failed(self.queue, job['job_id'])
        self.assertEqual(status(self.queue)['counts']['FAILED'], 1)

    def test_health_no_scientific_authority(self):
        from forexpro_ri.jobs import health
        self.put()
        self.assertEqual(health(self.queue)['operational_status'], 'HEALTHY')
        work_once(self.queue, now=100)
        h = health(self.queue, self.memory, require_signed=False)
        self.assertEqual(h['operational_status'], 'HEALTHY')
        self.assertEqual(h['research_memory_readiness'], 'LOCAL_INTAKE_READY')
        self.assertFalse(h['scientific_approval'])
        self.assertFalse(h['source_platform_integrated'])
        self.assertEqual(health(self.queue, self.memory)['operational_status'], 'ATTENTION_REQUIRED')

    def test_signed_synthetic_fixture_e2e(self):
        from forexpro_ri.bridge import create_synthetic_fixture
        from forexpro_ri.jobs import health
        bundle = self.root / 'signed'
        trust = self.root / 'trust.json'
        create_synthetic_fixture(bundle, trust)
        submitted = submit(self.queue, [bundle], self.memory, self.output, trust_store=trust, now=100)
        self.assertEqual(submitted['state'], 'QUEUED')
        self.assertEqual(work_once(self.queue, now=100)['state'], 'SUCCEEDED')
        self.assertEqual(health(self.queue, self.memory)['operational_status'], 'HEALTHY')
        self.assertEqual(verify(self.queue)['status'], 'QUEUE_INTACT')

    def test_revoked_signer_rejected_at_execution(self):
        from forexpro_ri.bridge import create_synthetic_fixture
        bundle = self.root / 'signed'
        trust = self.root / 'trust.json'
        create_synthetic_fixture(bundle, trust)
        submit(self.queue, [bundle], self.memory, self.output, trust_store=trust, now=100)
        content = json.loads(trust.read_text())
        content['keys'][0]['status'] = 'REVOKED'
        trust.write_text(json.dumps(content))
        self.assertEqual(work_once(self.queue, now=100)['state'], 'FAILED')
        self.assertFalse(self.memory.exists())

    def test_submit_order_independent(self):
        a = self.put((BUNDLE1, BUNDLE2))
        b = self.put((BUNDLE2, BUNDLE1))
        self.assertEqual(a['job_id'], b['job_id'])
        self.assertEqual(b['status'], 'ALREADY_QUEUED')

    def test_failed_health_attention(self):
        from forexpro_ri.jobs import health
        self.put()
        with patch('forexpro_ri.jobs.run_pipeline', side_effect=EvidenceError('broken')):
            work_once(self.queue, now=100)
        self.assertEqual(health(self.queue)['operational_status'], 'ATTENTION_REQUIRED')

    def test_late_ack_without_reclaim_rejected(self):
        self.put()
        old = claim(self.queue, now=100, lease_seconds=30)
        with self.assertRaisesRegex(EvidenceError, 'stale worker'):
            _finish(self.queue, old, success=False, error='INVALID_EVIDENCE', now=131)
        self.assertEqual(verify(self.queue)['event_count'], 2)
        new = claim(self.queue, now=131, lease_seconds=30)
        self.assertNotEqual(new['lease_token'], old['lease_token'])

    def test_success_ack_error_not_reclassified_as_failure(self):
        self.put()
        with patch('forexpro_ri.jobs.run_pipeline', return_value={}), \
             patch('forexpro_ri.jobs._finish', side_effect=EvidenceError('expired')) as finish:
            with self.assertRaises(EvidenceError):
                work_once(self.queue, now=100)
            self.assertEqual(finish.call_count, 1)


if __name__ == '__main__':
    unittest.main()
