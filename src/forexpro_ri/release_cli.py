"""CLI for v2.5 quality and v2.6 integration-readiness tools."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from .contracts import EvidenceError


def run(argv: list[str]) -> int:
    if not argv or argv[0] not in {"quality", "integration"}:
        raise EvidenceError("unknown release command")
    group = argv[0]
    parser = argparse.ArgumentParser(prog=f"forexpro-ri {group}")
    sub = parser.add_subparsers(dest="command", required=True)
    if group == "quality":
        benchmark = sub.add_parser("benchmark")
        benchmark.add_argument("--db", type=Path, required=True)
        benchmark.add_argument("--unsigned-synthetic", action="store_true")
    else:
        check = sub.add_parser("check")
        check.add_argument("--bundle", type=Path, required=True)
        check.add_argument("--trust-store", type=Path, required=True)
        sub.add_parser("rehearsal")
    args = parser.parse_args(argv[1:])
    try:
        if group == "quality":
            from .quality import benchmark
            result = benchmark(db_path=str(args.db), allow_unsigned_synthetic=args.unsigned_synthetic)
        elif args.command == "check":
            from .integration_readiness import check_bundle
            result = check_bundle(args.bundle, args.trust_store)
        else:
            from .integration_readiness import rehearsal
            result = rehearsal()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0 if result.get("status") != "FAIL" else 2
    except (EvidenceError, OSError, ValueError) as exc:
        print(f"{group.upper()}_REJECTED: {type(exc).__name__}", file=sys.stderr)
        return 2
