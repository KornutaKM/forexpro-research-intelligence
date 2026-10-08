"""Operations CLI for operator-selected offline evidence packages."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import EvidenceError
from .operations import ingest_batch, readiness, run as run_pipeline, verify_report_dir


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='forexpro-ri operations', description='Offline signed-evidence operations')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('batch', 'run'):
        cmd = sub.add_parser(name, help='Atomically ingest explicitly selected evidence bundles')
        cmd.add_argument('--db', type=Path, required=True)
        cmd.add_argument('--bundle', action='append', type=Path, required=True, help='Repeat 1..50 times')
        auth = cmd.add_mutually_exclusive_group(required=True)
        auth.add_argument('--trust-store', type=Path, help='Independently provisioned trusted Ed25519 keys')
        auth.add_argument('--unsigned-synthetic', action='store_true', help='Only literal synthetic fixtures')
    pipeline = sub.choices['run']
    pipeline.add_argument('--out', type=Path, required=True, help='New private output directory; must not exist')
    pipeline.add_argument('--expected-procedure', action='append', default=[])
    pipeline.add_argument('--min-support', type=int, default=2)
    report = sub.add_parser('verify-report', help='Check local artifact digests (not cryptographic authentication)')
    report.add_argument('--dir', type=Path, required=True)
    chk = sub.add_parser('readiness', help='Check local history integrity and import origin (not source authorization)')
    chk.add_argument('--db', type=Path, required=True)
    chk.add_argument('--allow-unsigned-synthetic', action='store_true', help='Only for synthetic rehearsal')
    args = parser.parse_args(argv)
    try:
        if args.command == 'verify-report':
            print(json.dumps(verify_report_dir(args.dir), sort_keys=True, ensure_ascii=False, indent=2))
            return 0
        if args.command == 'readiness':
            result = readiness(args.db, require_signed=not args.allow_unsigned_synthetic)
            print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))
            return 0 if result['status'] == 'LOCAL_INTAKE_READY' else 2
        common = {'trust_store': args.trust_store, 'allow_unsigned_synthetic': args.unsigned_synthetic}
        if args.command == 'batch':
            result = ingest_batch(args.bundle, args.db, **common)
        else:
            result = run_pipeline(args.bundle, args.db, args.out,
                                  expected_procedures=args.expected_procedure,
                                  min_support=args.min_support, **common)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))
        return 0
    except (EvidenceError, OSError) as exc:
        print(f'OPERATIONS_REJECTED: {exc}', file=sys.stderr)
        return 2
