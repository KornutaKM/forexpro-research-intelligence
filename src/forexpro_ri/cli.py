"""Small offline CLI. No GitHub token, broker credentials or network needed."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import analyze
from .contracts import EvidenceError
from .importer import import_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only ForexPro research evidence analysis")
    parser.add_argument("bundle", type=Path, help="Directory containing manifest.json and summary.json")
    parser.add_argument("--out", type=Path, help="Local output path for JSON report (outside ForexPro Core)")
    args = parser.parse_args(argv)
    try:
        manifest, summary = import_bundle(args.bundle)
        report = analyze(manifest, summary)
        contents = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.out:
            target = args.out
            if target.is_symlink():
                raise EvidenceError("cannot write report through symbolic link")
            # No unrestricted output back into the source bundle.
            if target.resolve().is_relative_to(args.bundle.resolve()):
                raise EvidenceError("output cannot be written inside evidence bundle")
            if target.exists():
                raise EvidenceError("output already exists; reports are immutable")
            if not target.parent.is_dir():
                raise EvidenceError("output directory must already exist")
            with target.open("x", encoding="utf-8") as f:
                f.write(contents)
        else:
            sys.stdout.write(contents)
        return 0
    except (EvidenceError, OSError) as exc:
        print(f"IMPORT_REJECTED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
