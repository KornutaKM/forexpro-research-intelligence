"""Operator CLI: one-command synthetic review, private pack and verification."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from .contracts import EvidenceError
from .review_secureio import read_private_bytes, read_private_json
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
    cohort.add_argument("--max-items", type=int, default=12, help="Advisor synthetic top-N, 1..12")
    check = commands.add_parser("verify", help="Verify local pack digest and rendered HTML identity")
    check.add_argument("--dir", type=Path, required=True)
    audit = commands.add_parser("audit", help="Reconcile all evidence, procedure counts, links and hash")
    audit.add_argument("--dir", type=Path, required=True)
    triage = commands.add_parser("triage", help="Evidence-first operator summary from verified pack")
    triage.add_argument("--dir", type=Path, required=True)
    repetitions = commands.add_parser("repetition", help="Linked repeated negative-case cautions")
    repetitions.add_argument("--dir", type=Path, required=True)
    compare = commands.add_parser("compare", help="Compare two validated append-only review snapshots")
    compare.add_argument("--before", type=Path, required=True)
    compare.add_argument("--after", type=Path, required=True)
    compare.add_argument("--out", type=Path, required=True, help="New private JSON file")
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
    agreement = commands.add_parser("agreement", help="Review two private SHA-bound decision sidecars")
    agreement.add_argument("--dir", type=Path, required=True)
    agreement.add_argument("--left", type=Path, required=True)
    agreement.add_argument("--right", type=Path, required=True)
    agreement.add_argument("--out", type=Path, required=True)
    rubric_template = commands.add_parser("rubric-template", help="No-opinion human Advisor quality worksheet")
    rubric_template.add_argument("--dir", type=Path, required=True)
    rubric_template.add_argument("--out", type=Path, required=True)
    rubric_score = commands.add_parser("rubric-score", help="Validate curator labels against exactly one pack")
    rubric_score.add_argument("--dir", type=Path, required=True)
    rubric_score.add_argument("--input", type=Path, required=True)
    rubric_score.add_argument("--out", type=Path, required=True)
    rubric_compare = commands.add_parser("rubric-compare", help="Compare two separately submitted rubric assessments")
    rubric_compare.add_argument("--dir", type=Path, required=True)
    rubric_compare.add_argument("--left", type=Path, required=True)
    rubric_compare.add_argument("--right", type=Path, required=True)
    rubric_compare.add_argument("--out", type=Path, required=True)
    study_plan = commands.add_parser("study-plan", help="SHA-bound counterbalanced paired-task allocation")
    study_plan.add_argument("--dir", type=Path, required=True)
    study_plan.add_argument("--tasks", type=int, default=20)
    study_plan.add_argument("--out", type=Path, required=True)
    study_reconcile = commands.add_parser("study-reconcile", help="Validate task order against preregistered plan")
    study_reconcile.add_argument("--dir", type=Path, required=True)
    study_reconcile.add_argument("--plan", type=Path, required=True)
    study_reconcile.add_argument("--input", type=Path, required=True)
    study_reconcile.add_argument("--out", type=Path, required=True)
    recall = commands.add_parser("recall", help="Synthetic gold-label Advisor omissions and extra questions")
    recall.add_argument("--dir", type=Path, required=True)
    recall.add_argument("--labels", type=Path, required=True)
    adjudicate = commands.add_parser("reconcile-human", help="Check discussion choices against separate human rubric")
    adjudicate.add_argument("--dir", type=Path, required=True)
    adjudicate.add_argument("--decisions", type=Path, required=True)
    adjudicate.add_argument("--rubric", type=Path, required=True)
    adjudicate.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "compare":
            from .review_diff import compare_review_packs
            def checked_pack(source: Path):
                if source.is_symlink() or not source.is_dir():
                    raise EvidenceError("comparison pack folder invalid")
                a, b = source / "review.json", source / "index.html"
                if (a.is_symlink() or b.is_symlink() or not a.is_file()
                        or not b.is_file() or a.stat().st_size > _MAX_REPORT_BYTES
                        or b.stat().st_size > _MAX_HTML_BYTES):
                    raise EvidenceError("comparison pack has unsafe files")
                data = read_private_json(a)
                verify_review_pack(data)
                if read_private_bytes(b, limit=_MAX_HTML_BYTES) != render_review_html(data).encode("utf-8"):
                    raise EvidenceError("comparison report HTML differs from JSON")
                return data
            previous = checked_pack(args.before)
            current = checked_pack(args.after)
            result = compare_review_packs(previous, current)
            target = args.out
            if (target.is_symlink() or target.exists() or not target.parent.is_dir()
                    or target.parent.is_symlink()
                    or target.resolve().is_relative_to(args.before.resolve())
                    or target.resolve().is_relative_to(args.after.resolve())):
                raise EvidenceError("unsafe comparison output path")
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
            print(json.dumps({"status": "LOCAL_APPEND_ONLY_COMPARE_CREATED",
                              "report_sha256": result["report_sha256"],
                              "new_record_count": result["new_record_count"],
                              "scientific_authority": False}, sort_keys=True))
            return 0
        if args.command == "study":
            from .review_time_study import analyze_paired_study
            source = args.input
            if source.is_symlink() or not source.is_file() or source.stat().st_size > _MAX_REPORT_BYTES:
                raise EvidenceError("paired-study input must be a bounded real local file")
            result = analyze_paired_study(read_private_json(source))
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
            return 0
        if args.command in ("verify", "audit", "triage", "repetition", "agreement", "benchmark", "decision-template", "decisions", "rubric-template", "rubric-score", "rubric-compare", "study-plan", "study-reconcile", "recall", "reconcile-human"):
            source = args.dir
            if source.is_symlink() or not source.is_dir():
                raise EvidenceError("pack directory missing or a symlink")
            j = source / "review.json"
            h = source / "index.html"
            if any(p.is_symlink() or not p.is_file() for p in (j, h)):
                raise EvidenceError("pack files absent or linked")
            if j.stat().st_size > _MAX_REPORT_BYTES or h.stat().st_size > _MAX_HTML_BYTES:
                raise EvidenceError("pack exceeds size limit")
            data = read_private_json(j)
            verify_review_pack(data)
            if read_private_bytes(h, limit=_MAX_HTML_BYTES) != render_review_html(data).encode("utf-8"):
                raise EvidenceError("pack HTML mismatch")
            if args.command == "recall":
                from .review_recall import evaluate_advisor_recall
                result = evaluate_advisor_recall(data, read_private_json(args.labels))
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
                return 0 if result["status"] == "SCENARIO_LABELS_MATCH" else 2
            if args.command == "reconcile-human":
                from .review_adjudication import reconcile_human_evidence
                inputs = [args.decisions, args.rubric]
                response = reconcile_human_evidence(
                    data, read_private_json(inputs[0]), read_private_json(inputs[1])
                )
                target = args.out
                if (target.is_symlink() or target.exists() or not target.parent.is_dir()
                        or target.parent.is_symlink()
                        or target.resolve().is_relative_to(source.resolve())
                        or any(target.resolve() == p.resolve() for p in inputs)):
                    raise EvidenceError("unsafe human reconciliation output")
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(json.dumps(response, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps({"status": "PRIVATE_HUMAN_EVIDENCE_RECONCILIATION_CREATED",
                                  "questions_needing_review": response["questions_requiring_reconciliation"],
                                  "scientific_authority": False}, sort_keys=True))
                return 0
            if args.command in ("study-plan", "study-reconcile"):
                from .review_study_protocol import make_study_plan, assess_planned_study
                sources = []
                if args.command == "study-plan":
                    response = make_study_plan(data, task_count=args.tasks)
                else:
                    sources = [args.plan, args.input]
                    response = assess_planned_study(
                        data, read_private_json(args.plan), read_private_json(args.input)
                    )
                target = args.out
                if (target.is_symlink() or target.exists() or not target.parent.is_dir()
                        or target.parent.is_symlink()
                        or target.resolve().is_relative_to(source.resolve())
                        or any(target.resolve() == p.resolve() for p in sources)):
                    raise EvidenceError("unsafe study protocol output")
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(json.dumps(response, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps({"status": "PRIVATE_STUDY_PROTOCOL_CREATED",
                                  "kind": args.command, "scientific_authority": False,
                                  "source_pack_sha256": data["report_sha256"]}, sort_keys=True))
                return 0
            if args.command in ("rubric-template", "rubric-score", "rubric-compare"):
                from .review_curator import curator_template, assess_curator_rubric, compare_curator_rubrics
                referenced = []
                if args.command == "rubric-template":
                    response = curator_template(data)
                elif args.command == "rubric-score":
                    referenced = [args.input]
                    response = assess_curator_rubric(data, read_private_json(args.input))
                else:
                    referenced = [args.left, args.right]
                    response = compare_curator_rubrics(
                        data, read_private_json(args.left), read_private_json(args.right)
                    )
                destination = args.out
                if (destination.exists() or destination.is_symlink()
                        or not destination.parent.is_dir() or destination.parent.is_symlink()
                        or destination.resolve().is_relative_to(source.resolve())
                        or any(destination.resolve() == p.resolve() for p in referenced)):
                    raise EvidenceError("unsafe curator output path")
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | getattr(os, "O_NOFOLLOW", 0), 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(json.dumps(response, sort_keys=True, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps({"status": "PRIVATE_CURATOR_DOCUMENT_CREATED",
                                  "kind": args.command,
                                  "source_pack_sha256": data["report_sha256"],
                                  "scientific_authority": False}, sort_keys=True))
                return 0
            if args.command in ("decision-template", "decisions"):
                from .review_decisions import decision_template, assess_review_decisions
                if args.command == "decision-template":
                    response = decision_template(data)
                else:
                    selected = args.input
                    if selected.is_symlink() or not selected.is_file() or selected.stat().st_size > _MAX_REPORT_BYTES:
                        raise EvidenceError("invalid decision input file")
                    response = assess_review_decisions(data, read_private_json(selected))
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
            if args.command == "repetition":
                from .review_repetition import find_repeated_negatives
                result = find_repeated_negatives(data)
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
                return 0
            if args.command == "triage":
                from .review_triage import summarize_review
                result = summarize_review(data)
                print(json.dumps(result, ensure_ascii=False, sort_keys=True))
                return 0
            if args.command == "agreement":
                from .review_agreement import compare_human_reviews
                def checked_local_json(path: Path):
                    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_REPORT_BYTES:
                        raise EvidenceError("invalid private reviewer sidecar")
                    return read_private_json(path)
                response = compare_human_reviews(
                    data, checked_local_json(args.left), checked_local_json(args.right)
                )
                target = args.out
                if (target.is_symlink() or target.exists() or not target.parent.is_dir()
                        or target.parent.is_symlink()
                        or target.resolve().is_relative_to(source.resolve())
                        or target.resolve() in (args.left.resolve(), args.right.resolve())):
                    raise EvidenceError("unsafe reviewer comparison destination")
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    output.write(json.dumps(response, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
                print(json.dumps({"status": "PRIVATE_REVIEW_DISAGREEMENTS_RECORDED",
                                  "source_pack_sha256": data["report_sha256"],
                                  "disagreement_count": len(response["disagreements"]),
                                  "scientific_authority": False}, sort_keys=True))
                return 0
            if args.command == "audit":
                from .review_integrity import audit_review_structure
                print(json.dumps(audit_review_structure(data), ensure_ascii=False, sort_keys=True))
                return 0
            if args.command == "benchmark":
                from .review_quality import score_review_pack
                labels_path = args.labels
                if labels_path.is_symlink() or not labels_path.is_file():
                    raise EvidenceError("independent label file must be a regular file")
                if labels_path.stat().st_size > _MAX_REPORT_BYTES:
                    raise EvidenceError("benchmark labels exceed size limit")
                labels = read_private_json(labels_path)
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
                pack = build_review_pack(db, expected_procedures=cohort["expected_procedures"],
                                         max_items=args.max_items)
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
