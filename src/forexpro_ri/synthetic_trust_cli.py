"""Explicit synthetic-only recipient trust continuity CLI; fail closed."""
from __future__ import annotations

import argparse
import base64
import binascii
import json
import sys
from pathlib import Path

from .contracts import EvidenceError, exact_keys
from .importer import _decode
from .synthetic_trust_continuity import (
    inspect_synthetic_recipient_trust_continuity,
)


def _operator_public_keys(path: Path) -> dict[str, bytes]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 8_192:
        raise EvidenceError("synthetic operator keyring invalid")
    payload = exact_keys(_decode(path.read_bytes(), "operator-test-public-keys.json"),
                         {"schema_version", "operator_keys"}, "operator test keyring")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise EvidenceError("operator test schema invalid")
    raw = payload["operator_keys"]
    if type(raw) is not list or not 1 <= len(raw) <= 8:
        raise EvidenceError("invalid synthetic operator test keys")
    keys: dict[str, bytes] = {}
    for row in raw:
        entry = exact_keys(row, {"key_id", "public_key_b64"}, "operator public test key")
        name, encoding = entry["key_id"], entry["public_key_b64"]
        if type(name) is not str or name in keys or type(encoding) is not str:
            raise EvidenceError("duplicate or invalid operator signer")
        try:
            key = base64.b64decode(encoding, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise EvidenceError("invalid operator key encoding") from exc
        if len(key) != 32 or base64.b64encode(key).decode("ascii") != encoding:
            raise EvidenceError("invalid operator public test key")
        keys[name] = key
    return keys


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="forexpro-ri synthetic-receiver-trust")
    parser.add_argument("--bundle", action="append", type=Path, required=True)
    parser.add_argument("--trust-store", type=Path, required=True)
    parser.add_argument("--checkpoint", action="append", type=Path, required=True)
    parser.add_argument("--operator-test-public-keys", type=Path, required=True)
    parser.add_argument("--operator-keyset-sha256", required=True)
    parser.add_argument("--expected-genesis-sha256", required=True)
    parser.add_argument("--expected-head-sha256", required=True)
    parser.add_argument("--expected-head-sequence", type=int, required=True)
    parser.add_argument("--minimum-sequence", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if len(args.checkpoint) > 16:
            raise EvidenceError("too many checkpoints")
        dirs = {item.resolve() for item in args.bundle}
        for file in (args.operator_test_public_keys, args.trust_store, *args.checkpoint):
            if file.is_symlink() or not file.is_file() or any(
                    file.resolve().is_relative_to(root) for root in dirs):
                raise EvidenceError("synthetic checkpoint/key file must be independently provisioned")
        keys = _operator_public_keys(args.operator_test_public_keys)
        chain = []
        for file in args.checkpoint:
            if file.stat().st_size > 4096:
                raise EvidenceError("synthetic checkpoint oversized")
            chain.append(file.read_bytes())
        result = inspect_synthetic_recipient_trust_continuity(
            args.bundle, trust_store=args.trust_store,
            signed_checkpoints=tuple(chain), operator_test_public_keys=keys,
            expected_operator_keyset_sha256=args.operator_keyset_sha256,
            expected_genesis_sha256=args.expected_genesis_sha256,
            expected_latest_sha256=args.expected_head_sha256,
            expected_latest_sequence=args.expected_head_sequence,
            independent_minimum_sequence=args.minimum_sequence,
        )
    except (EvidenceError, OSError, ValueError, TypeError):
        # No input names, key IDs, paths or observations in operator error logs.
        print("SYNTHETIC_RECIPIENT_TRUST_DENIED", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, separators=(",", ":")))
    return 0
