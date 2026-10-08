"""Command line entry points for the standalone bridge contract testbench."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bridge import create_synthetic_fixture, preflight, rehearsal
from .contracts import EvidenceError


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="forexpro-ri bridge", description="Offline protocol tests; never accesses ForexPro Core")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rehearsal", help="run complete signed synthetic export → memory → diagnostics flow")
    fixture = sub.add_parser("fixture", help="create a synthetic signed fixture; does not persist signing key")
    fixture.add_argument("--bundle", type=Path, required=True)
    fixture.add_argument("--trust-store", type=Path, required=True)
    check = sub.add_parser("preflight", help="verify signed export structure and provenance; no approval granted")
    check.add_argument("bundle", type=Path)
    check.add_argument("--trust-store", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "rehearsal":
            result = rehearsal()
        elif args.cmd == "fixture":
            result = create_synthetic_fixture(args.bundle, args.trust_store)
        else:
            result = preflight(args.bundle, args.trust_store)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (EvidenceError, OSError) as exc:
        print(f"BRIDGE_REJECTED: {exc}", file=sys.stderr)
        return 2
