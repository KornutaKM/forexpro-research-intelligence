"""Explicit, offline, synthetic-only Core v1 recipient-policy preview CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .contracts import EvidenceError
from .core_policy_preview import inspect_synthetic_core_v1_batch


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="forexpro-ri core-policy")
    parser.add_argument("--bundle", action="append", type=Path, required=True)
    parser.add_argument("--trust-store", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = inspect_synthetic_core_v1_batch(
            args.bundle, trust_store=args.trust_store)
    except (EvidenceError, OSError, ValueError, TypeError):
        # Never echo untrusted file names, observations, private IDs or paths.
        print("SYNTHETIC_CORE_POLICY_PREVIEW_DENIED", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
    return 0
