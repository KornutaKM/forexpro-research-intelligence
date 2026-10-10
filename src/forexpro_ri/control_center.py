"""FRI local-only, read-only Research Control Center.

No mutating HTTP methods, raw bundle access, file serving outside packaged assets,
private keys, persistent token, ForexPro Core, holdout or broker access.
"""
from __future__ import annotations

import argparse
import hmac
import json
import secrets
import sqlite3
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .contracts import EvidenceError, _ID
from .dossier import build_dossier
from .jobs import status as queue_status, verify as queue_verify
from .memory import history as memory_history, verify as memory_verify
from . import research_program as research_program_module

_MAX_BODY = 2 * 1024 * 1024
_MAX_QUERY = 1024
_MAX_ROWS = 5000
_ALLOWED_STATIC = {'/': ('ui/index.html', 'text/html; charset=utf-8'),
                   '/app.css': ('ui/app.css', 'text/css; charset=utf-8'),
                   '/app.js': ('ui/app.js', 'text/javascript; charset=utf-8')}


def _safe_jobs(queue_db: Path) -> dict:
    """Only expose status fields; do not return path-valued queue metadata."""
    raw = queue_status(queue_db)
    return {
        'counts': raw['counts'],
        'jobs': [{k: row[k] for k in ('job_id', 'state', 'attempts', 'max_attempts', 'available_at', 'error_code')}
                 for row in raw['jobs'][-200:]],
        'truncated': len(raw['jobs']) > 200,
    }


def _safe_history(memory_db: Path) -> dict:
    raw = memory_history(memory_db)
    if len(raw) > _MAX_ROWS:
        raise EvidenceError('history exceeds Control Center limit')
    return {
        'count': len(raw),
        'experiments': [{k: row[k] for k in ('experiment_id', 'disposition', 'entry_sha256',
                                             'fail_count', 'pass_count', 'not_evaluable_count')}
                        for row in raw[-200:]],
        'truncated': len(raw) > 200,
    }


def overview(queue_db: Path, memory_db: Path) -> dict:
    """Live read-only status, never auto-create SQLite files or hide read errors."""
    response = {
        'report_kind': 'NON_AUTHORITATIVE_CONTROL_CENTER',
        'authority': {'scientific': False, 'holdout': False, 'broker': False, 'promotion': False},
        'queue': {'available': False}, 'memory': {'available': False}, 'warnings': [],
    }
    if queue_db.is_file() and not queue_db.is_symlink():
        response['queue'] = {'available': True, **_safe_jobs(queue_db)}
    else:
        response['warnings'].append('QUEUE_UNAVAILABLE')
    if memory_db.is_file() and not memory_db.is_symlink():
        response['memory'] = {'available': True, **_safe_history(memory_db)}
    else:
        response['warnings'].append('MEMORY_UNAVAILABLE')
    if response['queue'].get('available') and response['queue']['counts']['FAILED']:
        response['warnings'].append('FAILED_JOBS_PRESENT')
    if response['queue'].get('available') and response['queue']['counts']['RETRY']:
        response['warnings'].append('RETRIES_PENDING')
    response['status'] = 'READY' if not response['warnings'] else 'ATTENTION'
    return response


def dossier(memory_db: Path, experiment_id: str) -> dict:
    if not _ID.fullmatch(experiment_id):
        raise EvidenceError('invalid experiment id')
    raw = build_dossier(memory_db, focus_experiment_id=experiment_id)
    return {
        'report_kind': 'NON_AUTHORITATIVE_DOSSIER_VIEW',
        'focus': raw['focus_experiment'],
        'provenance': {key: raw['focus_intake_provenance'][key] for key in (
            'verification_status', 'receipt_sha256')},
        'procedures': [{'procedure': row['procedure'], 'status': row['recorded_status']}
                       for row in raw['procedure_outcomes']],
        'evidence_gaps': [{'procedure': row['procedure'], 'status': row['recorded_status']}
                          for row in raw['evidence_visibility_gaps']],
        'report_sha256': raw.get('dossier_sha256'),
        'limitations': [
            'Recorded observations and hashes, not scientific approval or trading advice.',
            'Prior signature checks do not establish current authorization.',
            'Repeated negative outcomes are not independent or causal proof.',
        ],
        'authority': {'scientific': False, 'holdout': False, 'broker': False},
    }


def program(memory_db: Path, *, synthetic: bool) -> dict:
    """Normalize v2.2 Research Program while maintaining older fixture support."""
    if hasattr(research_program_module, 'build_program'):
        raw = research_program_module.build_program(memory_db, require_signed=not synthetic)
        rows = raw['ranked_review_topics']
        worklist = [
            {
                'kind': row['attention_class'],
                'procedure': row['procedure'],
                'affected_experiment_count': row['recorded_counts']['FAIL']
                + row['recorded_counts']['NOT_EVALUABLE'],
                'prospective_question': row['future_research_question'] or
                'No negative observations; no new hypothesis is implied.',
                'basis': 'RECORDED_CLOSED_EXPERIMENT_OUTCOMES',
            }
            for row in rows if row['attention_class'] != 'NO_NEGATIVE_OBSERVATION'
        ][:20]
        count = raw['experiment_count']
        return {
            'report_kind': 'NON_AUTHORITATIVE_RESEARCH_PROGRAM_VIEW',
            'signed_only_gate_passed': (
                raw['intake_status_counts'].get('SIGNATURE_VERIFIED', 0) == count
                and raw['intake_policy'] == 'SIGNED_AT_IMPORT_ONLY'),
            'observed_experiment_count': count,
            'total_worklist_items': len([r for r in rows if r['attention_class'] != 'NO_NEGATIVE_OBSERVATION']),
            'worklist': worklist,
            'snapshot_sha256': raw['memory_snapshot_sha256'],
            'authority': {'scientific': False, 'holdout': False, 'broker': False},
        }
    # For the earlier prototype-only API, if explicitly installed by an operator.
    raw = research_program_module.build_research_program(
        memory_db, allow_unsigned_synthetic=synthetic)
    return {
        'report_kind': 'NON_AUTHORITATIVE_RESEARCH_PROGRAM_VIEW',
        'signed_only_gate_passed': raw['signed_only_gate_passed'],
        'observed_experiment_count': raw['observed_experiment_count'],
        'total_worklist_items': raw['total_worklist_items'],
        'worklist': [{k: row[k] for k in ('kind', 'procedure', 'affected_experiment_count',
                                         'prospective_question', 'basis')}
                     for row in raw['worklist']],
        'snapshot_sha256': raw['memory_snapshot_sha256'],
        'authority': {'scientific': False, 'holdout': False, 'broker': False},
    }


def audit(queue_db: Path, memory_db: Path) -> dict:
    # Explicit on-demand full verification. Raw results may contain paths,
    # so expose only whitelisted status/count data.
    q = queue_verify(queue_db)
    m = memory_verify(memory_db)
    return {
        'report_kind': 'NON_AUTHORITATIVE_CONTROL_AUDIT',
        'queue': {'status': q['status']},
        'memory': {'status': m['status'], 'experiment_count': m['experiment_count']},
        'scientific_approval': False,
    }


def create_server(queue_db: str | Path, memory_db: str | Path, *, token: str,
                  port: int = 8765, synthetic: bool = False) -> ThreadingHTTPServer:
    """Construct loopback-only server. Caller must close / serve_forever."""
    if not isinstance(token, str) or len(token) < 32:
        raise EvidenceError('Control Center requires a strong ephemeral token')
    if type(port) is not int or not 0 <= port <= 65535:
        raise EvidenceError('invalid loopback port')
    if type(synthetic) is not bool:
        raise EvidenceError('synthetic mode must be boolean')
    queue_db, memory_db = Path(queue_db), Path(memory_db)
    if queue_db.resolve() == memory_db.resolve():
        raise EvidenceError('queue and Research Memory must be different files')

    class Handler(BaseHTTPRequestHandler):
        server_version = 'FRI-Control-Center'
        sys_version = ''

        def log_message(self, fmt, *args):
            # Do not log request URL, query, bearer token or research identifiers.
            return

        def _send(self, status: HTTPStatus, data: bytes, content_type: str = 'application/json; charset=utf-8') -> None:
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store, max-age=0')
            self.send_header('Content-Security-Policy',
                             "default-src 'none'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: HTTPStatus, obj: dict) -> None:
            data = (json.dumps(obj, sort_keys=True, ensure_ascii=False,
                               separators=(',', ':')) + '\n').encode('utf-8')
            if len(data) > _MAX_BODY:
                self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, b'{"error":"RESPONSE_TOO_LARGE"}\n')
            else:
                self._send(status, data)

        def do_GET(self):
            local_host = self.headers.get('Host', '')
            if local_host not in {f'127.0.0.1:{self.server.server_port}',
                                  f'localhost:{self.server.server_port}'}:
                self._json(HTTPStatus.FORBIDDEN, {'error': 'HOST_REJECTED'})
                return
            if len(self.path) > _MAX_QUERY:
                self._json(HTTPStatus.REQUEST_URI_TOO_LONG, {'error': 'QUERY_TOO_LONG'})
                return
            parsed = urlsplit(self.path)
            if parsed.path in _ALLOWED_STATIC and not parsed.query and not parsed.fragment:
                file, mime = _ALLOWED_STATIC[parsed.path]
                asset = files('forexpro_ri').joinpath(file).read_bytes()
                self._send(HTTPStatus.OK, asset, mime)
                return
            if parsed.path not in {'/api/overview', '/api/dossier', '/api/program', '/api/audit'}:
                self._json(HTTPStatus.NOT_FOUND, {'error': 'NOT_FOUND'})
                return
            auth_header = self.headers.get('Authorization', '')
            if not hmac.compare_digest(auth_header, 'Bearer ' + token):
                self._json(HTTPStatus.UNAUTHORIZED, {'error': 'AUTH_REQUIRED'})
                return
            try:
                qs = parse_qs(parsed.query, keep_blank_values=True, strict_parsing=True, max_num_fields=3)
                if parsed.path == '/api/dossier':
                    if set(qs) != {'id'} or len(qs['id']) != 1:
                        raise EvidenceError('expected one experiment id')
                    value = dossier(memory_db, qs['id'][0])
                elif qs:
                    raise EvidenceError('unexpected query parameters')
                elif parsed.path == '/api/overview':
                    value = overview(queue_db, memory_db)
                elif parsed.path == '/api/program':
                    value = program(memory_db, synthetic=synthetic)
                else:
                    value = audit(queue_db, memory_db)
                self._json(HTTPStatus.OK, value)
            except (EvidenceError, sqlite3.Error, OSError, ValueError, KeyError) as exc:
                # Do not return private file names, raw exception text, SQL, or credentials.
                code = 'INVALID_QUERY' if parsed.path == '/api/dossier' and (not qs or not _ID.fullmatch(qs.get('id', [''])[0])) else 'DATA_UNAVAILABLE'
                self._json(HTTPStatus.BAD_REQUEST if code == 'INVALID_QUERY' else HTTPStatus.SERVICE_UNAVAILABLE,
                           {'error': code})

        def do_HEAD(self):
            self._json(HTTPStatus.METHOD_NOT_ALLOWED, {'error': 'READ_ONLY_GET'})

        def do_POST(self):
            self._json(HTTPStatus.METHOD_NOT_ALLOWED, {'error': 'READ_ONLY_GET'})

        do_PUT = do_DELETE = do_PATCH = do_POST

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.allow_reuse_address = False
    return server


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='forexpro-ri control', description='Loopback read-only Research Control Center')
    commands = parser.add_subparsers(dest='command', required=True)
    serve = commands.add_parser('serve', help='Start read-only localhost dashboard')
    serve.add_argument('--queue', type=Path, required=True)
    serve.add_argument('--db', type=Path, required=True)
    serve.add_argument('--port', type=int, default=8765)
    serve.add_argument('--allow-unsigned-synthetic', action='store_true', help='Only for local synthetic fixtures')
    args = parser.parse_args(argv)
    key = secrets.token_urlsafe(32)
    try:
        server = create_server(args.queue, args.db, token=key, port=args.port,
                               synthetic=args.allow_unsigned_synthetic)
        try:
            print(f'FRI Control Center: http://127.0.0.1:{server.server_port}/', flush=True)
            print(f'Session token (keep private; lost when server exits): {key}', flush=True)
            print('Read-only local server. Press Ctrl+C to stop.', flush=True)
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0
    except (EvidenceError, OSError) as exc:
        print(f'CONTROL_REJECTED: {type(exc).__name__}', file=sys.stderr)
        return 2
