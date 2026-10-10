"""Small offline CLI. No GitHub token, broker credentials or network needed."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from .analysis import analyze
from .contracts import EvidenceError
from .importer import import_bundle


def main(argv: list[str] | None = None) -> int:
    command_line = list(sys.argv[1:] if argv is None else argv)
    if command_line and command_line[0] == 'control':
        from .control_center import run
        return run(command_line[1:])
    if command_line and command_line[0] == 'jobs':
        from .jobs_cli import run
        return run(command_line[1:])
    if command_line and command_line[0] == 'recovery':
        from .recovery_cli import run
        return run(command_line[1:])
    if command_line and command_line[0] == 'operations':
        from .operations_cli import run
        return run(command_line[1:])
    if command_line and command_line[0] == 'bridge':
        from .bridge_cli import run
        return run(command_line[1:])
    if command_line and command_line[0] == 'memory':
        from .memory_cli import run
        return run(command_line[1:])
    if command_line and command_line[0] == 'verify-export':
        verify_parser = argparse.ArgumentParser(prog='forexpro-ri verify-export')
        verify_parser.add_argument('bundle', type=Path)
        verify_parser.add_argument('--trust-store', type=Path, required=True)
        verify_args = verify_parser.parse_args(command_line[1:])
        try:
            from .attestation import verify_export
            _, _, receipt = verify_export(verify_args.bundle, verify_args.trust_store)
            print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        except (EvidenceError, OSError) as exc:
            print(f'ATTESTATION_REJECTED: {exc}', file=sys.stderr)
            return 2
    parser = argparse.ArgumentParser(description="Read-only ForexPro research evidence analysis")
    parser.add_argument("bundle", type=Path, help="Directory containing manifest.json and summary.json")
    parser.add_argument("--out", type=Path, help="Local output path for JSON report (outside ForexPro Core)")
    parser.add_argument("--trust-store", type=Path, help="Require detached signature verified against this locally provisioned trust store")
    args = parser.parse_args(command_line)
    try:
        if args.trust_store is not None:
            from .attestation import verify_export
            manifest, summary, receipt = verify_export(args.bundle, args.trust_store)
        else:
            manifest, summary, receipt = *import_bundle(args.bundle), None
        report = analyze(manifest, summary)
        if receipt is not None:
            report.pop('report_sha256')
            report['export_authenticity'] = 'SIGNATURE_VERIFIED'
            report['export_attestation'] = receipt
            from .analysis import canonical_json
            report['report_sha256'] = hashlib.sha256(canonical_json(report).encode('utf-8')).hexdigest()
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
