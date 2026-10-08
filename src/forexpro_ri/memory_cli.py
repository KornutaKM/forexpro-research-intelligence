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
    for key in ('ingest', 'history', 'patterns', 'verify'):
        cmd = add if key == 'ingest' else sub.add_parser(key)
        cmd.add_argument('--db', type=Path, required=True, help='Local private SQLite database path')
    args = parser.parse_args(argv)
    try:
        if args.command == 'ingest':
            result = ingest(args.bundle, args.db)
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
