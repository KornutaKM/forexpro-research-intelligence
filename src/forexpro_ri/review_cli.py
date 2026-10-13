"""Operator CLI: one-command synthetic review, private pack and verification."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .contracts import EvidenceError
from .review_pack import (
    build_review_pack, publish_review_pack, render_review_html, verify_review_pack,
)

_MAX_REPORT_BYTES = 16 * 1024 * 1024
_MAX_HTML_BYTES = 32 * 1024 * 1024


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="forexpro-ri review",
        description="Offline review of prior closed research, never scientific or trading authorization",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("pack", help="Build HTML + JSON from existing Research Memory")
    make.add_argument("--db", type=Path, required=True)
    make.add_argument("--out", type=Path, required=True,
                      help="New local private output directory; must not exist")
    make.add_argument("--expected-procedure", action="append", default=[])
    make.add_argument("--min-support", type=int, default=2)
    make.add_argument("--max-items", type=int, default=12)
    make.add_argument("--unsigned-synthetic", action="store_true",
                      help="Explicitly labeled synthetic rehearsal ONLY, never real records")
    demo = commands.add_parser("demo", help="Single-command signed SYNTHETIC fixture rehearsal")
    demo.add_argument("--out", type=Path, required=True)
    cohort = commands.add_parser("cohort-demo", help="Twenty signed SYNTHETIC closed studies")
    cohort.add_argument("--out", type=Path, required=True)
    check = commands.add_parser("verify", help="Verify local pack digest and rendered HTML identity")
    check.add_argument("--dir", type=Path, required=True)
    benchmark = commands.add_parser("benchmark", help="Evaluate a pack against independent synthetic labels")
    benchmark.add_argument("--dir", type=Path, required=True)
    benchmark.add_argument("--labels", type=Path, required=True)
    study = commands.add_parser("study", help="Analyze private paired researcher timings (no uploads)")
    study.add_argument("--input", type=Path, required=True)
    template = commands.add_parser("decision-template", help="Private editable human review template")
    template.add_argument("--dir", type=Path, required=True)
    template.add_argument("--out", type=Path, required=True)
    decisions = commands.add_parser("decisions", help="Validate human accept/defer/reject sidecar")
    decisions.add_argument("--dir", type=Path, required=True)
    decisions.add_argument("--input", type=Path, required=True)
    decisions.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "study":
            from .review_time_study import analyze_paired_study
            source = args.input
            if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_REPORT_BYTES:
                raise EvidenceError("paired-study input must be a bounded real local file")
            result = analyze_paired_study(json.loads(source.read_text("utf-8")))
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command in ("verify", "benchmark", "decision-template", "decisions"):
            source = args.dir
            if source.is_symlink() or not source.is_dir():
                raise EvidenceError("pack directory missing or a symlink")
            j = source / "review.json"
            h = source / "index.html"
            if any(p.is_symlink() or not p.is_file() for p in (j, h)):
                raise EvidenceError("pack files absent or linked")
            if j.stat().st_size > _MAX_REPORT_BYTES or h.stat().st_size > _MAX_HTML_BYTES:
                raise EvidenceError("pack exceeds size limit")
            data = json.loads(j.read_text("utf-8"))
            verify_review_pack(data)
            if h.read_bytes() != render_review_html(data).encode("utf-8"):
                raise EvidenceError("pack HTML mismatch")
            if args.command in ("decision-template", "decisions"):
                from .review_decisions import decision_template, assess_review_decisions
                if args.command == "decision-template":
                    response = decision_template(data)
                else:
                    selected = args.input
                    if selected.is_symlink() or not selected.is_file() or selected.stat().st_size > _MAX_REPORT_BYTES:
                        raise EvidenceError("invalid decision input file")
                    response = assess_review_decisions(data, json.loads(selected.read_text("utf-8")))
                target = args.out
                if (target.is_symlink() or target.exists() or not target.parent.is_dir()
                        or target.parent.is_symlink() or target.resolve().is_relative_to(source.resolve())
                        or (args.command == "decisions" and target.resolve() == args.input.resolve())):
                    raise EvidenceError("unsafe decision output path")
                payload = json.dumps(response, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(payload)
                print(json.dumps({
                    "status": "PRIVATE_REVIEW_SIDECAR_CREATED", "authority": "NONE",
                    "topics": len(data["review_topics"]),
                }, sort_keys=True))
                return 0
            if args.command == "benchmark":
                from .review_quality import score_review_pack
                labels_path = args.labels
                if labels_path.is_symlink() or not labels_path.is_file():
                    raise EvidenceError("independent label file must be a regular file")
                if labels_path.stat().st_size > _MAX_REPORT_BYTES:
                    raise EvidenceError("benchmark labels exceed size limit")
                labels = json.loads(labels_path.read_text("utf-8"))
                score = score_review_pack(data, labels)
                print(json.dumps(score, sort_keys=True))
                return 0 if score["status"] == "STRUCTURAL_PASS" else 2
            print(json.dumps({"status": "LOCAL_PACK_INTEGRITY_PASS",
                              "report_sha256": data["report_sha256"],
                              "scientific_authority": False,
                              "source_export_permission_established": False},
                             sort_keys=True))
            return 0
        if args.command == "cohort-demo":
            from .review_cohort import make_signed_cohort
            with tempfile.TemporaryDirectory(prefix="fri-review-cohort-") as scratch:
                base = Path(scratch)
                db = base / "cohort.sqlite"
                cohort = make_signed_cohort(base, db)
                pack = build_review_pack(db, expected_procedures=cohort["expected_procedures"])
                result = publish_review_pack(pack, args.out)
        elif args.command == "demo":
            from .bridge import create_synthetic_fixture
            from .memory import ingest
            with tempfile.TemporaryDirectory(prefix="fri-review-demo-") as scratch:
                base = Path(scratch)
                fixture, trust, db = base / "signed-synthetic", base / "trusted-test-keys.json", base / "memory.sqlite"
                create_synthetic_fixture(fixture, trust)
                ingest(fixture, db, trust_store=trust)
                pack = build_review_pack(db, expected_procedures=["MONTE_CARLO", "REGIME_STABILITY"])
                result = publish_review_pack(pack, args.out)
        else:
            pack = build_review_pack(
                args.db, expected_procedures=args.expected_procedure,
                min_support=args.min_support, max_items=args.max_items,
                allow_unsigned_synthetic=args.unsigned_synthetic,
            )
            result = publish_review_pack(pack, args.out)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (EvidenceError, OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        # Avoid leaking private paths or values from SQLite or operator inputs.
        print("REVIEW_REJECTED: review input, evidence or publication failed", file=sys.stderr)
        return 2
