"""Offline, bounded and strict import of explicitly exported read-only evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .contracts import BundleManifest, EvidenceError, parse_summary

_MAX_JSON_BYTES = 1024 * 1024


def _read_file(root: Path, name: str) -> bytes:
    # Intentionally fixed filenames: never follow a path from untrusted manifest JSON.
    path = root / name
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_JSON_BYTES:
        raise EvidenceError(f"missing, symbolic-link or oversized evidence file: {name}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise EvidenceError(f"cannot read {name}") from exc


def _decode(data: bytes, filename: str) -> dict:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError(f"duplicate JSON key in {filename}: {key}")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicates)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"invalid JSON: {filename}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"JSON root must be object: {filename}")
    return value


def import_bundle(bundle_dir: str | Path) -> tuple[BundleManifest, dict]:
    root = Path(bundle_dir)
    if root.is_symlink() or not root.is_dir():
        raise EvidenceError("bundle must be a real local directory")
    manifest_data = _read_file(root, "manifest.json")
    summary_data = _read_file(root, "summary.json")
    manifest = BundleManifest.parse(_decode(manifest_data, "manifest.json"))
    if hashlib.sha256(summary_data).hexdigest() != manifest.summary_sha256:
        raise EvidenceError("summary SHA-256 mismatch")
    summary = parse_summary(_decode(summary_data, "summary.json"), manifest.experiment_id)
    return manifest, summary
