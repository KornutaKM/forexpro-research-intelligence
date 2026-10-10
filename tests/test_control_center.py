"""Adversarial localhost HTTP/read-only dashboard tests; synthetic sources only."""
from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from forexpro_ri.control_center import create_server, overview, dossier, program, audit
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.jobs import submit, work_once
from forexpro_ri.memory import ingest

TOKEN = 'synthetic-ephemeral-token-for-unit-tests-123456'
FIXTURES = Path(__file__).resolve().parents[1] / 'examples'


class ControlCenterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.q, self.m, self.out = root / 'queue.sqlite', root / 'memory.sqlite', root / 'outputs'
        self.out.mkdir()
        self.server = create_server(self.q, self.m, token=TOKEN, port=0, synthetic=True)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.server_close()

    def request(self, route='/', *, token=None, host=None, method='GET'):
        port = self.server.server_port
        req = Request(f'http://127.0.0.1:{port}{route}', method=method)
        if token is not None:
            req.add_header('Authorization', 'Bearer ' + token)
        if host:
            req.add_header('Host', host)
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, response.headers, response.read()
        except HTTPError as error:
            return error.code, error.headers, error.read()

    def json(self, route, **kwargs):
        status, headers, body = self.request(route, token=TOKEN, **kwargs)
        return status, json.loads(body)

    def populate(self, *, two=False, queue=True):
        base = FIXTURES / 'closed_synthetic'
        ingest(base, self.m, allow_unsigned_synthetic=True)
        if two:
            ingest(FIXTURES / 'closed_synthetic_peer', self.m, allow_unsigned_synthetic=True)
        if queue:
            submit(self.q, [base], self.m, self.out, allow_unsigned_synthetic=True)

    def test_only_loopback_binding(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')

    def test_static_assets_public_but_never_contain_session_token(self):
        for uri, content_type in [('/', 'text/html'), ('/app.css', 'text/css'), ('/app.js', 'text/javascript')]:
            status, headers, body = self.request(uri)
            self.assertEqual(status, 200)
            self.assertIn(content_type, headers['Content-Type'])
            self.assertNotIn(TOKEN.encode(), body)
            self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
            self.assertIn('no-store', headers['Cache-Control'])
            self.assertIn("default-src 'none'", headers['Content-Security-Policy'])
            self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_denies_api_without_token(self):
        for endpoint in ('/api/overview', '/api/program', '/api/audit', '/api/dossier?id=SYNTHETIC-001'):
            status, _, _ = self.request(endpoint)
            self.assertEqual(status, 401, endpoint)

    def test_denies_wrong_token(self):
        self.assertEqual(self.request('/api/overview', token=TOKEN+'oops')[0], 401)

    def test_rejects_host_rebinding(self):
        self.assertEqual(self.request('/api/overview', token=TOKEN, host='attacker.example')[0], 403)

    def test_rejects_http_mutation_methods(self):
        for method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            status, _, data = self.request('/api/overview', method=method, token=TOKEN)
            self.assertEqual(status, 405)
            self.assertIn(b'READ_ONLY_GET', data)

    def test_empty_control_center_does_not_create_any_database(self):
        status, report = self.json('/api/overview')
        self.assertEqual(status, 200)
        self.assertEqual(report['status'], 'ATTENTION')
        self.assertFalse(report['queue']['available'])
        self.assertFalse(report['memory']['available'])
        self.assertFalse(self.m.exists())
        self.assertFalse(self.q.exists())

    def test_overview_with_synthetic_records(self):
        self.populate(two=True)
        status, report = self.json('/api/overview')
        self.assertEqual(status, 200)
        self.assertEqual(report['status'], 'READY')
        self.assertEqual(report['memory']['count'], 2)
        self.assertEqual(report['queue']['counts']['QUEUED'], 1)
        self.assertFalse(any(report['authority'].values()))
        self.assertEqual(report['memory']['experiments'][0]['experiment_id'], 'SYNTHETIC-001')
        self.assertNotIn('result_dir', report['queue']['jobs'][0])
        self.assertNotIn('summary_sha256', report['memory']['experiments'][0])

    def test_no_path_or_raw_observations_leak(self):
        self.populate()
        _, _, body = self.request('/api/overview', token=TOKEN)
        self.assertNotIn(str(self.m).encode(), body)
        self.assertNotIn(str(self.out).encode(), body)
        self.assertNotIn(b'net PnL', body)
        self.assertNotIn(b'private', body)

    def test_dossier_view_contains_non_authoritative_verdicts(self):
        self.populate(queue=False)
        status, report = self.json('/api/dossier?id=SYNTHETIC-001')
        self.assertEqual(status, 200)
        self.assertEqual(report['focus']['experiment_id'], 'SYNTHETIC-001')
        self.assertFalse(any(report['authority'].values()))
        self.assertIn('FAIL', {x['status'] for x in report['procedures']})
        self.assertEqual(report['provenance']['verification_status'], 'UNSIGNED_SYNTHETIC')
        self.assertNotIn('observation_sha256', str(report))

    def test_dossier_malformed_identifier_rejected(self):
        for query in ('?id=%3Cscript%3E', '?id=../../private', '?id=', '?other=x', '?id=SYNTHETIC-001&id=OTHER'):
            status, payload = self.json('/api/dossier'+query)
            self.assertIn(status, (400, 503), query)
            self.assertNotIn(str(self.m), str(payload))

    def test_reject_extra_api_query(self):
        status, _ = self.json('/api/overview?unused=yes')
        self.assertEqual(status, 503)

    def test_bounded_uri(self):
        self.assertEqual(self.request('/api/dossier?id='+'a'*1024, token=TOKEN)[0], 414)

    def test_research_program_synthetic(self):
        self.populate(two=True, queue=False)
        status, result = self.json('/api/program')
        self.assertEqual(status, 200)
        self.assertFalse(result['signed_only_gate_passed'])
        self.assertEqual(result['observed_experiment_count'], 2)
        self.assertFalse(any(result['authority'].values()))

    def test_research_program_signed_only_rejects_unsigned_history(self):
        self.populate(queue=False)
        self.server.shutdown(); self.thread.join(timeout=5); self.server.server_close()
        self.server = create_server(self.q, self.m, token=TOKEN, port=0, synthetic=False)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.assertEqual(self.json('/api/program')[0], 503)

    def test_full_integrity_audit(self):
        self.populate()
        status, report = self.json('/api/audit')
        self.assertEqual(status, 200)
        self.assertEqual(report['queue']['status'], 'QUEUE_INTACT')
        self.assertEqual(report['memory']['status'], 'OK')
        self.assertFalse(report['scientific_approval'])

    def test_completed_jobs_remain_read_only(self):
        self.populate()
        result = work_once(self.q)
        self.assertEqual(result['state'], 'SUCCEEDED')
        self.assertEqual(self.json('/api/overview')[1]['queue']['counts']['SUCCEEDED'], 1)
        self.assertEqual(self.json('/api/audit')[0], 200)

    def test_invalid_token_port_and_identical_databases_fail_closed(self):
        with self.assertRaises(EvidenceError):
            create_server(self.q, self.m, token='weak', port=0)
        with self.assertRaises(EvidenceError):
            create_server(self.q, self.m, token=TOKEN, port=-1)
        with self.assertRaises(EvidenceError):
            create_server(self.q, self.q, token=TOKEN, port=0)

    def test_missing_dossier_has_generic_error_without_paths(self):
        status, report = self.json('/api/dossier?id=SYNTHETIC-001')
        self.assertEqual(status, 503)
        self.assertEqual(report, {'error': 'DATA_UNAVAILABLE'})

    def test_security_headers_on_rejected_request(self):
        status, headers, _ = self.request('/api/overview')
        self.assertEqual(status, 401)
        self.assertEqual(headers['X-Frame-Options'], 'DENY')
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')


if __name__ == '__main__':
    unittest.main()
