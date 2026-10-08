"""Offline synthetic regression suite: receipt proof, migration, and readiness gates."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
from pathlib import Path

from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.cli import main
from forexpro_ri.contracts import EvidenceError
from forexpro_ri.dossier import build_dossier, render_markdown
from forexpro_ri.memory import ingest, verify
from forexpro_ri.provenance import audit


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='fri-provenance-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / 'signed'
        self.trust = self.root / 'trusted-public.json'
        self.db = self.root / 'memory.sqlite'

    def signed(self):
        create_synthetic_fixture(self.bundle, self.trust)
        return ingest(self.bundle, self.db, trust_store=self.trust)

    def unsigned(self):
        b = self.root / 'unsigned'
        b.mkdir(exist_ok=True)
        summary = {'experiment_id':'SYNTHETIC-UNSIGNED', 'disposition':'CLOSED_UNSUCCESSFUL',
                   'criteria':[{'criterion_id':'x', 'procedure':'COST_STRESS', 'verdict':'FAIL',
                                'observation':'SYNTHETIC cost fail'}], 'not_evaluable':[]}
        raw = json.dumps(summary).encode()
        manifest = {'schema_version':1, 'export_kind':'CLOSED_EXPERIMENT_SUMMARY',
                    'source_system':'forexpro', 'experiment_id':summary['experiment_id'],
                    'source_revision':'a'*40, 'summary_sha256':hashlib.sha256(raw).hexdigest(),
                    'approved_scope':'READ_ONLY_ADVISORY', 'holdout_access':False,
                    'promotion_authority':False, 'broker_authority':False}
        (b/'summary.json').write_bytes(raw)
        (b/'manifest.json').write_text(json.dumps(manifest))
        return b

    def test_signed_receipt_recorded_without_secret_data(self):
        result = self.signed()
        self.assertEqual(result['verification_status'], 'SIGNATURE_VERIFIED')
        a = audit(self.db)
        self.assertTrue(a['all_intakes_have_signed_receipts'])
        self.assertEqual(a['counts'], {'signature_verified':1,'unsigned_synthetic':0,'legacy_unattested':0})
        self.assertEqual(a['receipts'][0]['verification_status'], 'SIGNATURE_VERIFIED')
        self.assertEqual(len(a['receipts'][0]['attestation_sha256']), 64)
        self.assertFalse(any(a['authority'].values()))
        self.assertNotIn('SYNTHETIC: negative', self.db.read_bytes().decode('utf-8', errors='ignore'))

    def test_audit_deterministic_and_content_addressed(self):
        self.signed()
        first = audit(self.db)
        self.assertEqual(first, audit(self.db))
        digest = first.pop('report_sha256')
        from forexpro_ri.analysis import canonical_json
        self.assertEqual(digest, hashlib.sha256(canonical_json(first).encode('utf-8')).hexdigest())

    def test_explicit_migration_does_not_create_missing_database(self):
        from forexpro_ri.memory import migrate
        with self.assertRaisesRegex(EvidenceError,'missing'):
            migrate(self.db)
        self.assertFalse(self.db.exists())

    def test_explicit_migration_from_v1(self):
        from forexpro_ri.memory import migrate
        self.signed()
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TABLE intake_receipts')
            conn.execute('PRAGMA user_version=1')
        data = migrate(self.db)
        self.assertEqual(data['schema_version'], 2)
        self.assertEqual(audit(self.db)['counts']['legacy_unattested'], 1)
        self.assertEqual(migrate(self.db)['schema_version'], 2)

    def test_signed_repeat_idempotent_receipt(self):
        a = self.signed()
        receipt1 = audit(self.db)['receipts'][0]['receipt_sha256']
        b = ingest(self.bundle, self.db, trust_store=self.trust)
        self.assertEqual(b['status'], 'ALREADY_PRESENT')
        self.assertEqual(a['entry_sha256'], b['entry_sha256'])
        self.assertEqual(audit(self.db)['receipts'][0]['receipt_sha256'], receipt1)

    def test_unsigned_api_default_rejects_before_db_creation(self):
        b=self.unsigned()
        with self.assertRaisesRegex(EvidenceError, 'requires trust_store'):
            ingest(b,self.db)
        self.assertFalse(self.db.exists())

    def test_unsigned_explicit_fixture_status_not_signed(self):
        b=self.unsigned()
        result=ingest(b,self.db,allow_unsigned_synthetic=True)
        self.assertEqual(result['verification_status'],'UNSIGNED_SYNTHETIC')
        a=audit(self.db)
        self.assertFalse(a['all_intakes_have_signed_receipts'])
        self.assertEqual(a['counts']['unsigned_synthetic'],1)

    def test_unsigned_wrong_content_never_intakes(self):
        b=self.unsigned()
        s=json.loads((b/'summary.json').read_text());s['criteria'][0]['observation']='real account observation'
        raw=json.dumps(s).encode();(b/'summary.json').write_bytes(raw)
        m=json.loads((b/'manifest.json').read_text());m['summary_sha256']=hashlib.sha256(raw).hexdigest()
        (b/'manifest.json').write_text(json.dumps(m))
        with self.assertRaisesRegex(EvidenceError, 'synthetic fixtures'):
            ingest(b,self.db,allow_unsigned_synthetic=True)
        self.assertFalse(self.db.exists())

    def test_no_dual_mode(self):
        self.bundle.mkdir()
        with self.assertRaisesRegex(EvidenceError, 'mutually exclusive'):
            ingest(self.bundle,self.db,trust_store=self.trust,allow_unsigned_synthetic=True)

    def test_revoked_key_prevents_new_import(self):
        create_synthetic_fixture(self.bundle,self.trust)
        data=json.loads(self.trust.read_text());data['keys'][0]['status']='REVOKED'
        self.trust.write_text(json.dumps(data))
        with self.assertRaisesRegex(EvidenceError,'revoked'):
            ingest(self.bundle,self.db,trust_store=self.trust)
        self.assertFalse(self.db.exists())

    def test_cannot_downgrade_signed_entry_to_unsigned_synthetic(self):
        self.signed()
        with self.assertRaisesRegex(EvidenceError, 'conflicting immutable intake provenance'):
            ingest(self.bundle, self.db, allow_unsigned_synthetic=True)
        self.assertEqual(audit(self.db)['counts']['signature_verified'], 1)

    def test_mixed_history_is_not_fully_signed(self):
        self.signed()
        ingest(self.unsigned(), self.db, allow_unsigned_synthetic=True)
        report=audit(self.db)
        self.assertEqual(report['experiment_count'],2)
        self.assertEqual(report['counts']['signature_verified'],1)
        self.assertEqual(report['counts']['unsigned_synthetic'],1)
        self.assertFalse(report['all_intakes_have_signed_receipts'])
        dossier=build_dossier(self.db, focus_experiment_id='SYNTHETIC-BRIDGE-001')
        self.assertFalse(dossier['all_intakes_signed_at_import'])

    def test_later_revocation_does_not_claim_fresh_verification(self):
        self.signed()
        data=json.loads(self.trust.read_text());data['keys'][0]['status']='REVOKED'
        self.trust.write_text(json.dumps(data))
        a=audit(self.db)
        self.assertTrue(a['all_intakes_have_signed_receipts'])
        self.assertIn('does not reverify',a['limitations'][0])
        with self.assertRaisesRegex(EvidenceError,'revoked'):
            ingest(self.bundle,self.db,trust_store=self.trust)

    def test_provenance_record_trigger_immutable(self):
        self.signed()
        with sqlite3.connect(self.db) as conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("UPDATE intake_receipts SET verification_status='LEGACY_UNATTESTED'")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute('DELETE FROM intake_receipts')

    def test_dropped_trigger_modification_detected(self):
        self.signed()
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TRIGGER intake_receipts_no_update')
            conn.execute("UPDATE intake_receipts SET verification_status='UNSIGNED_SYNTHETIC'")
        with self.assertRaisesRegex(EvidenceError,'receipt integrity mismatch'):
            verify(self.db)
        with self.assertRaisesRegex(EvidenceError,'receipt integrity mismatch'):
            audit(self.db)

    def test_missing_receipt_detected(self):
        self.signed()
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TRIGGER intake_receipts_no_delete')
            conn.execute('DELETE FROM intake_receipts')
        with self.assertRaisesRegex(EvidenceError, 'missing intake receipt'):
            verify(self.db)

    def test_legacy_v1_migration_never_claims_signature(self):
        self.signed()
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TABLE intake_receipts')
            conn.execute('PRAGMA user_version=1')
        self.assertEqual(verify(self.db)['schema_version'],1)
        a=audit(self.db)
        self.assertEqual(a['counts']['legacy_unattested'],1)
        self.assertFalse(a['all_intakes_have_signed_receipts'])
        with self.assertRaisesRegex(EvidenceError,'conflicting immutable intake provenance'):
            ingest(self.bundle,self.db,trust_store=self.trust)
        self.assertEqual(verify(self.db)['schema_version'],2)
        self.assertEqual(audit(self.db)['receipts'][0]['verification_status'], 'LEGACY_UNATTESTED')

    def test_corrupt_legacy_refuses_migration(self):
        b=self.unsigned();ingest(b,self.db,allow_unsigned_synthetic=True)
        with sqlite3.connect(self.db) as conn:
            conn.execute('DROP TABLE intake_receipts')
            conn.execute('PRAGMA user_version=1')
            conn.execute('DROP TRIGGER experiments_no_update')
            conn.execute('UPDATE experiments SET fail_count=99')
        with self.assertRaisesRegex(EvidenceError,'integrity mismatch'):
            ingest(b,self.db,allow_unsigned_synthetic=True)
        with sqlite3.connect(self.db) as conn:
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0],1)

    def test_dossier_includes_historical_receipt_and_no_approval(self):
        self.signed()
        r=build_dossier(self.db,focus_experiment_id='SYNTHETIC-BRIDGE-001')
        self.assertEqual(r['focus_intake_provenance']['verification_status'],'SIGNATURE_VERIFIED')
        self.assertTrue(r['all_intakes_signed_at_import'])
        self.assertEqual(r['source_authenticity'],'HISTORICAL_INTAKE_VERIFICATION_ONLY')
        self.assertIn('Current revocation',render_markdown(r))
        self.assertFalse(r['scientific_authority'])

    def test_audit_cli_gate(self):
        b=self.unsigned();ingest(b,self.db,allow_unsigned_synthetic=True)
        with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
            self.assertEqual(main(['memory','audit','--db',str(self.db)]),0)
            self.assertEqual(main(['memory','audit','--db',str(self.db),'--require-signed']),2)

    def test_audit_cli_signed_gate_pass(self):
        self.signed()
        with redirect_stdout(StringIO()),redirect_stderr(StringIO()):
            self.assertEqual(main(['memory','audit','--db',str(self.db),'--require-signed']),0)

    def test_empty_history_not_readiness_pass(self):
        self.signed()
        with sqlite3.connect(self.db) as conn:
            for name in ('intake_receipts_no_delete','criteria_no_delete','not_evaluable_no_delete','experiments_no_delete'):
                conn.execute('DROP TRIGGER '+name)
            conn.execute('DELETE FROM intake_receipts')
            conn.execute('DELETE FROM criteria')
            conn.execute('DELETE FROM not_evaluable')
            conn.execute('DELETE FROM experiments')
        a=audit(self.db)
        self.assertFalse(a['all_intakes_have_signed_receipts'])
        self.assertEqual(a['experiment_count'],0)


if __name__=='__main__':
    unittest.main()
