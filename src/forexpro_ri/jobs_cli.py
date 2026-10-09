"""Offline job processing CLI; no service, secrets or network listeners."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import EvidenceError
from .jobs import drain, health, requeue_failed, status, submit, verify, work_once


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='forexpro-ri jobs', description='Bounded offline advisory jobs')
    commands = parser.add_subparsers(dest='command', required=True)
    sub = commands.add_parser('submit', help='Explicitly enqueue verified local evidence')
    sub.add_argument('--queue', type=Path, required=True)
    sub.add_argument('--db', type=Path, required=True, help='Private Research Memory file')
    sub.add_argument('--out-root', type=Path, required=True)
    sub.add_argument('--bundle', type=Path, action='append', required=True)
    auth = sub.add_mutually_exclusive_group(required=True)
    auth.add_argument('--trust-store', type=Path)
    auth.add_argument('--unsigned-synthetic', action='store_true')
    sub.add_argument('--expected-procedure', action='append', default=[])
    sub.add_argument('--min-support', type=int, default=2)
    sub.add_argument('--max-attempts', type=int, default=3)
    work = commands.add_parser('work', help='Process one due job, or drain bounded work')
    work.add_argument('--queue', type=Path, required=True)
    work.add_argument('--limit', type=int, default=1)
    watch = commands.add_parser('watch', help='Read-only queue health, overdue jobs, input drift and pinned trust')
    watch.add_argument('--queue', type=Path, required=True)
    watch.add_argument('--inspect-sources', action='store_true', help='Re-check local source bytes; never run research')
    watch.add_argument('--overdue-seconds', type=int, default=3600)
    for name in ('status', 'verify'):
        cmd = commands.add_parser(name)
        cmd.add_argument('--queue', type=Path, required=True)
    health_cmd = commands.add_parser('health', help='Audit queue and optional Research Memory readiness')
    health_cmd.add_argument('--queue', type=Path, required=True)
    health_cmd.add_argument('--db', type=Path)
    health_cmd.add_argument('--allow-unsigned-synthetic', action='store_true')
    retry_cmd = commands.add_parser('requeue', help='Explicitly retry a failed job without changing its inputs')
    retry_cmd.add_argument('--queue', type=Path, required=True)
    retry_cmd.add_argument('--job-id', required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'watch':
            from .queue_watch import inspect
            result = inspect(args.queue, inspect_sources=args.inspect_sources,
                             overdue_seconds=args.overdue_seconds)
        elif args.command == 'submit':
            result = submit(args.queue, args.bundle, args.db, args.out_root,
                            trust_store=args.trust_store, allow_unsigned_synthetic=args.unsigned_synthetic,
                            expected_procedures=args.expected_procedure, min_support=args.min_support,
                            max_attempts=args.max_attempts)
        elif args.command == 'work':
            result = work_once(args.queue) if args.limit == 1 else drain(args.queue, limit=args.limit)
        elif args.command == 'requeue':
            result = requeue_failed(args.queue, args.job_id)
        elif args.command == 'health':
            result = health(args.queue, args.db, require_signed=not args.allow_unsigned_synthetic)
        elif args.command == 'status':
            result = status(args.queue)
        else:
            result = verify(args.queue)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        if args.command == 'work' and (result.get('state') == 'FAILED' or any(
            x.get('state') == 'FAILED' for x in result.get('jobs', [])
        )):
            return 2
        if args.command == 'health' and result['operational_status'] != 'HEALTHY':
            return 2
        return 0
    except (EvidenceError, OSError) as exc:
        print(f'JOBS_REJECTED: {exc}', file=sys.stderr)
        return 2
