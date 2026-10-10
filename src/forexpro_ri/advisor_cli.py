"""CLI for advisory packs and explicitly opted-in local model wording."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .advisor import build_advisor, render_markdown
from .contracts import EvidenceError
from .local_model import enrich_with_local_model


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog='forexpro-ri advisor')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--expected-procedure', action='append', default=[])
    parser.add_argument('--min-support', type=int, default=2)
    parser.add_argument('--max-items', type=int, default=12)
    parser.add_argument('--unsigned-synthetic', action='store_true',
                        help='ONLY for clearly synthetic Research Memory')
    parser.add_argument('--local-model', metavar='OLLAMA_MODEL',
                        help='Explicit opt-in: send limited hashed advisory context to localhost Ollama')
    parser.add_argument('--timeout', type=int, default=20)
    parser.add_argument('--format', choices=('json', 'markdown'), default='json')
    parser.add_argument('--out', type=Path, help='Write new local report, never overwrite')
    args = parser.parse_args(argv)
    try:
        report = build_advisor(args.db, expected_procedures=args.expected_procedure,
                               min_support=args.min_support, max_items=args.max_items,
                               allow_unsigned_synthetic=args.unsigned_synthetic)
        if args.local_model:
            report = enrich_with_local_model(report, model=args.local_model, timeout=args.timeout)
        rendered = (render_markdown(report) if args.format == 'markdown' else
                    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
        if args.out is None:
            print(rendered, end='')
        else:
            dest = args.out
            if dest.is_symlink() or not dest.parent.is_dir() or dest.resolve() == args.db.resolve():
                raise EvidenceError('invalid or unsafe advisor output path')
            with dest.open('x', encoding='utf-8') as target:
                target.write(rendered)
        return 0
    except (EvidenceError, OSError) as exc:
        print(f'ADVISOR_REJECTED: {type(exc).__name__}', file=sys.stderr)
        return 2
