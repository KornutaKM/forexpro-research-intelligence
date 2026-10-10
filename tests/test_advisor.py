"""Adversarial v2.4 advisor: signed gate, evidence grounding and local-model isolation."""
from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from forexpro_ri.advisor import build_advisor, render_markdown
from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.local_model import _request_payload, enrich_with_local_model, validate_commentary
from forexpro_ri.memory import ingest

FIXTURES = Path(__file__).resolve().parents[1] / 'examples'


class _FakeResponse:
    status = 200
    def __init__(self, data):
        self.data = io.BytesIO(data)
    def __enter__(self):
        return self
    def __exit__(self, *_):
        self.data.close()
    def read(self, n):
        return self.data.read(n)


class _FakeOpener:
    def __init__(self, content):
        self.content = content
        self.last_request = None
    def open(self, req, timeout):
        self.last_request = req
        return _FakeResponse(self.content)


class AdvisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'memory.sqlite'

    def populate(self):
        ingest(FIXTURES / 'closed_synthetic', self.db, allow_unsigned_synthetic=True)
        ingest(FIXTURES / 'closed_synthetic_peer', self.db, allow_unsigned_synthetic=True)

    def pack(self):
        self.populate()
        return build_advisor(self.db, expected_procedures=['MONTE_CARLO', 'REGIME_STABILITY'],
                             allow_unsigned_synthetic=True)

    def test_deterministic_evidence_and_no_authority(self):
        a = self.pack()
        b = build_advisor(self.db, expected_procedures=['MONTE_CARLO', 'REGIME_STABILITY'],
                          allow_unsigned_synthetic=True)
        self.assertEqual(a, b)
        self.assertEqual(a['report_kind'], 'NON_AUTHORITATIVE_RESEARCH_ADVISOR')
        self.assertFalse(any(a['authority'].values()))
        self.assertFalse(a['signed_only_gate_passed'])
        self.assertGreater(a['proposal_count'], 0)
        for row in a['proposals']:
            self.assertEqual(len(row['item_id']), 24)
            self.assertEqual(row['interpretation'], 'DESCRIPTIVE_NOT_CAUSAL')
            self.assertEqual(len(row['full_evidence_program_sha256']), 64)
            self.assertTrue(all(len(e['entry_sha256']) == 64 for e in row['evidence_sample']))

    def test_no_source_prose_or_private_paths(self):
        r = self.pack()
        data = json.dumps(r) + render_markdown(r)
        self.assertNotIn('net PnL', data)
        self.assertNotIn('cost sensitivity', data)
        self.assertNotIn(str(self.root), data)
        self.assertIn('NEW preregistered', data)

    def test_signed_by_default_and_empty_memory_failure(self):
        self.populate()
        with self.assertRaisesRegex(EvidenceError, 'signed intake'):
            build_advisor(self.db)
        with self.assertRaises(EvidenceError):
            build_advisor(self.root / 'no-memory.sqlite', allow_unsigned_synthetic=True)

    def test_signed_synthetic_export_passes_gate(self):
        signed = self.root / 'signed'; keys = self.root / 'keys.json'
        create_synthetic_fixture(signed, keys)
        ingest(signed, self.db, trust_store=keys)
        r = build_advisor(self.db)
        self.assertTrue(r['signed_only_gate_passed'])
        self.assertEqual(r['provenance_counts']['signature_verified'], 1)
        self.assertFalse(any(r['authority'].values()))

    def test_input_validation(self):
        self.populate()
        for value in (0, True, 13, -1, 1.5, '5'):
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                build_advisor(self.db, max_items=value, allow_unsigned_synthetic=True)
        with self.assertRaises(EvidenceError):
            build_advisor(self.db, expected_procedures=['HOLDOUT'], allow_unsigned_synthetic=True)

    def test_tampered_memory_fails_closed(self):
        self.populate()
        with sqlite3.connect(self.db) as db:
            db.execute('DROP TRIGGER criteria_no_update')
            db.execute('UPDATE criteria SET verdict="PASS" WHERE verdict="FAIL"')
        with self.assertRaises(EvidenceError):
            build_advisor(self.db, allow_unsigned_synthetic=True)

    def test_cli_json_markdown_and_creation_only(self):
        self.populate()
        with redirect_stdout(io.StringIO()) as s:
            self.assertEqual(main(['advisor','--db',str(self.db),'--unsigned-synthetic',
                                   '--expected-procedure','MONTE_CARLO']), 0)
        self.assertGreater(json.loads(s.getvalue())['proposal_count'], 0)
        with redirect_stdout(io.StringIO()) as s:
            self.assertEqual(main(['advisor','--db',str(self.db),'--unsigned-synthetic',
                                   '--format','markdown']), 0)
        self.assertIn('Research Advisor', s.getvalue())
        target = self.root / 'advisor.json'
        self.assertEqual(main(['advisor','--db',str(self.db),'--unsigned-synthetic',
                               '--out',str(target)]), 0)
        self.assertEqual(main(['advisor','--db',str(self.db),'--unsigned-synthetic',
                               '--out',str(target)]), 2)
        self.assertFalse(target.is_symlink())
        self.assertEqual(main(['advisor','--db',str(self.db)]), 2)

    def test_model_request_contains_only_bounded_safe_codes(self):
        r = self.pack()
        b = _request_payload(r, 'qwen2.5:7b')
        body = json.loads(b)
        self.assertFalse(body['stream'])
        self.assertEqual(body['model'], 'qwen2.5:7b')
        self.assertNotIn('net PnL', body['prompt'])
        self.assertNotIn('SYNTHETIC-001', body['prompt'])
        self.assertIn(r['memory_snapshot_sha256'], body['prompt'])
        self.assertLess(len(b), 20000)

    def test_validate_commentary_references_only_existing_items(self):
        r = self.pack()
        ident = r['proposals'][0]['item_id']
        ok = validate_commentary({'items':[{'item_id':ident, 'question':'How to test robustness?',
                                              'rationale':'Uncertain: the observed sample is small.'}]},r)
        self.assertEqual(ok[0]['item_id'],ident)
        for bad in (
            {'items':[{'item_id':'unseen', 'question':'A', 'rationale':'B'}]},
            {'items':[{'item_id':ident, 'question':'A', 'rationale':'B'}]*2},
            {'items':[{'item_id':ident, 'question':'A', 'rationale':'B', 'authority':True}]},
            {'items':[{'item_id':ident, 'question':'A'*241, 'rationale':'B'}]},
            {'items':[{'item_id':ident, 'question':'A', 'rationale':''}]},
            {'items':[{'item_id':ident, 'question':'A\x00B', 'rationale':'B'}]},
            {'items':[], 'scientific_approval':True},
            {'items':'not-an-array'},
        ):
            with self.subTest(bad=bad),self.assertRaises(EvidenceError):
                validate_commentary(bad,r)

    def test_mock_local_model_success_is_unverified_and_escapes_html(self):
        r=self.pack(); ident=r['proposals'][0]['item_id']
        response={'response':json.dumps({'items':[{'item_id':ident,
                         'question':'<script>alert(1)</script>',
                         'rationale':'Uncertain whether the observation generalizes.'}]}), 'done':True}
        opener=_FakeOpener(json.dumps(response).encode())
        with patch('forexpro_ri.local_model.urllib.request.build_opener', return_value=opener) as mock:
            enriched=enrich_with_local_model(r,model='qwen2.5:7b')
        self.assertEqual(opener.last_request.full_url,'http://127.0.0.1:11434/api/generate')
        self.assertEqual(len(mock.call_args.args),2)
        self.assertEqual(enriched['model_inference'],'LOCAL_MODEL_UNVERIFIED_PROSE')
        self.assertNotEqual(enriched['report_sha256'],r['report_sha256'])
        self.assertEqual(enriched['proposals'],r['proposals'])
        self.assertNotIn('<script>',render_markdown(enriched))
        self.assertIn('&lt;script&gt;',render_markdown(enriched))

    def test_local_model_rejects_invalid_transport_response(self):
        r=self.pack()
        for bad in (b'',b'{}',b'{"done":false,"response":"{}"}', b'a'*32769,
                    json.dumps({'done':True,'response':json.dumps({'items':[{'item_id':'wrong',
                        'question':'ok','rationale':'ok'}]})}).encode()):
            opener=_FakeOpener(bad)
            with patch('forexpro_ri.local_model.urllib.request.build_opener',return_value=opener):
                with self.subTest(bad=bad[:20]),self.assertRaises(EvidenceError):
                    enrich_with_local_model(r,model='llama3.2')

    def test_local_model_invalid_name_and_timeout_do_not_network(self):
        r=self.pack()
        with patch('forexpro_ri.local_model.urllib.request.build_opener') as build:
            for invalid in ('', 'http://elsewhere', 'model name','../private','*', 'x'*65):
                with self.subTest(name=invalid),self.assertRaises(EvidenceError):
                    enrich_with_local_model(r,model=invalid)
            for timeout in (True, 0, 61, 1.5):
                with self.subTest(timeout=timeout),self.assertRaises(EvidenceError):
                    enrich_with_local_model(r,model='llama3.2',timeout=timeout)
            build.assert_not_called()

    def test_empty_worklist_rejected_by_local_model(self):
        r=self.pack()
        r['proposals']=[]
        with self.assertRaisesRegex(EvidenceError,'no advisory proposals'):
            enrich_with_local_model(r,model='llama3.2')


if __name__ == '__main__': unittest.main()
