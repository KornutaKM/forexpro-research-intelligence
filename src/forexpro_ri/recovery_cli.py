"""Explicit offline backup/recovery operator commands."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import EvidenceError
from .recovery import backup, drill, restore_backup, verify_backup


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='forexpro-ri recovery', description='Research Memory local disaster recovery')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('backup').add_argument('--db', type=Path, required=True)
    sub.choices['backup'].add_argument('--out', type=Path, required=True)
    sub.add_parser('verify').add_argument('--dir', type=Path, required=True)
    sub.add_parser('restore').add_argument('--dir', type=Path, required=True)
    sub.choices['restore'].add_argument('--db', type=Path, required=True)
    sub.add_parser('drill').add_argument('--db', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'backup':
            result = backup(args.db, args.out)
        elif args.command == 'verify':
            result = verify_backup(args.dir)
        elif args.command == 'restore':
            result = restore_backup(args.dir, args.db)
        else:
            result = drill(args.db)
        print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
        return 0
    except (EvidenceError, OSError) as exc:
        print(f'RECOVERY_REJECTED: {exc}', file=sys.stderr)
        return 2
