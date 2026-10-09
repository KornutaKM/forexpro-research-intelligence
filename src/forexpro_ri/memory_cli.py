"""Offline Research Memory CLI commands, isolated from the legacy analyze CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import EvidenceError
from .memory import history, ingest, migrate, patterns, verify


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='forexpro-ri memory', description='Private local read-only-advisory Research Memory')
    sub = parser.add_subparsers(dest='command', required=True)
    add = sub.add_parser('ingest', help='Import one validated closed experiment bundle')
    add.add_argument('bundle', type=Path)
    validation = add.add_mutually_exclusive_group(required=True)
    validation.add_argument('--trust-store', type=Path, help='Trusted public key registry outside bundle, required for real data')
    validation.add_argument('--unsigned-synthetic', action='store_true', help='ONLY for explicit synthetic fixtures; never for private research')
    for key in ('ingest', 'history', 'patterns', 'verify', 'intelligence', 'compare', 'dossier', 'program', 'audit', 'migrate'):
        cmd = add if key == 'ingest' else sub.add_parser(key)
        cmd.add_argument('--db', type=Path, required=True, help='Local private SQLite database path')
    intel = sub.choices['intelligence']
    intel.add_argument('--focus', help='Optional stored experiment ID for matched historical cases')
    intel.add_argument('--min-support', type=int, default=2, help='Minimum distinct experiment support (2..5000)')
    comparison = sub.choices['compare']
    comparison.add_argument('--experiment', action='append', required=True, help='Explicit stored experiment ID; repeat 2..50 times')
    comparison.add_argument('--expected-procedure', action='append', default=[], help='Optional operator-expected procedure; repeat as needed')
    comparison.add_argument('--format', choices=['json', 'markdown'], default='json')
    sub.choices['audit'].add_argument('--require-signed', action='store_true', help='Reject histories with any unsigned or legacy intake')
    dossier = sub.choices['dossier']
    dossier.add_argument('--focus', required=True, help='Stored closed experiment ID')
    dossier.add_argument('--expected-procedure', action='append', default=[], help='Optional operator-declared procedure')
    dossier.add_argument('--min-support', type=int, default=2, help='Minimum distinct experiment support (2..5000)')
    dossier.add_argument('--format', choices=['json', 'markdown'], default='json')
    program = sub.choices['program']
    program.add_argument('--expected-procedure', action='append', default=[], help='Operator-declared, not a scientific ValidationContract')
    program.add_argument('--min-support', type=int, default=2)
    program.add_argument('--max-items', type=int, default=20)
    program.add_argument('--unsigned-synthetic', action='store_true', help='ONLY for synthetic fixture reports')
    program.add_argument('--format', choices=['json', 'markdown'], default='json')
    args = parser.parse_args(argv)
    try:
        if args.command == 'ingest':
            result = ingest(args.bundle, args.db, trust_store=args.trust_store, allow_unsigned_synthetic=args.unsigned_synthetic)
        elif args.command == 'audit':
            from .provenance import audit
            result = audit(args.db)
            if args.require_signed and not result['all_intakes_have_signed_receipts']:
                raise EvidenceError('intake audit is not fully signed; cannot pass --require-signed')
        elif args.command == 'migrate':
            result = migrate(args.db)
        elif args.command == 'history':
            result = history(args.db)
        elif args.command == 'patterns':
            result = patterns(args.db)
        elif args.command == 'intelligence':
            from .failure_intelligence import build_failure_report
            result = build_failure_report(args.db, focus_experiment_id=args.focus, min_support=args.min_support)
        elif args.command == 'compare':
            from .comparison import build_comparison, render_markdown
            result = build_comparison(args.db, experiment_ids=args.experiment, expected_procedures=args.expected_procedure)
            if args.format == 'markdown':
                print(render_markdown(result), end='')
                return 0
        elif args.command == 'program':
            from .research_program import build_research_program, render_markdown as render_program_markdown
            result = build_research_program(args.db, expected_procedures=args.expected_procedure,
                                            min_support=args.min_support, max_items=args.max_items,
                                            allow_unsigned_synthetic=args.unsigned_synthetic)
            if args.format == 'markdown':
                print(render_program_markdown(result), end='')
                return 0
        elif args.command == 'dossier':
            from .dossier import build_dossier, render_markdown as render_dossier_markdown
            result = build_dossier(args.db, focus_experiment_id=args.focus,
                                   expected_procedures=args.expected_procedure, min_support=args.min_support)
            if args.format == 'markdown':
                print(render_dossier_markdown(result), end='')
                return 0
        else:
            result = verify(args.db)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))
        return 0
    except (EvidenceError, OSError) as exc:
        print(f'MEMORY_REJECTED: {exc}', file=sys.stderr)
        return 2
