"""Offline Research Memory CLI commands, isolated from the legacy analyze CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import EvidenceError
from .memory import history, ingest, patterns, verify


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='forexpro-ri memory', description='Private local read-only-advisory Research Memory')
    sub = parser.add_subparsers(dest='command', required=True)
    add = sub.add_parser('ingest', help='Import one validated closed experiment bundle')
    add.add_argument('bundle', type=Path)
    validation = add.add_mutually_exclusive_group(required=True)
    validation.add_argument('--trust-store', type=Path, help='Trusted public key registry outside bundle, required for real data')
    validation.add_argument('--unsigned-synthetic', action='store_true', help='ONLY for explicit synthetic fixtures; never for private research')
    for key in ('ingest', 'history', 'patterns', 'verify'):
        cmd = add if key == 'ingest' else sub.add_parser(key)
        cmd.add_argument('--db', type=Path, required=True, help='Local private SQLite database path')
    args = parser.parse_args(argv)
    try:
        if args.command == 'ingest':
            if args.unsigned_synthetic:
                from .importer import import_bundle
                manifest, summary = import_bundle(args.bundle)
                if not manifest.experiment_id.startswith('SYNTHETIC-') or any(
                    'synthetic' not in item['observation'].lower() for item in summary['criteria']
                ) or any('synthetic' not in item['reason'].lower() for item in summary['not_evaluable']):
                    raise EvidenceError('--unsigned-synthetic requires synthetic-labeled experiment and observations')
            result = ingest(args.bundle, args.db, trust_store=args.trust_store)
        elif args.command == 'history':
            result = history(args.db)
        elif args.command == 'patterns':
            result = patterns(args.db)
        else:
            result = verify(args.db)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))
        return 0
    except (EvidenceError, OSError) as exc:
        print(f'MEMORY_REJECTED: {exc}', file=sys.stderr)
        return 2
