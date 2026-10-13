"""Private report IO: bounded no-follow, hardlink/JSON ambiguity rejection."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from forexpro_ri.contracts import EvidenceError
from forexpro_ri.review_secureio import read_private_bytes, read_private_json, parse_private_json
from forexpro_ri.bridge import create_synthetic_fixture
from forexpro_ri.cli import main
from forexpro_ri.memory import ingest
from forexpro_ri.review_pack import build_review_pack, publish_review_pack


class ReviewSecureIOTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_plain_json_and_bytes_round_trip(self):
        path = self.root / "source.json"
        path.write_text('{"a":1,"b":{"z":true}}', encoding="utf-8")
        self.assertEqual(read_private_json(path), {"a": 1, "b": {"z": True}})
        self.assertEqual(read_private_bytes(path), path.read_bytes())

    def test_duplicate_key_top_level_and_nested_rejected(self):
        for source in ('{"a":1,"a":2}', '{"b":{"a":1,"a":3}}'):
            path = self.root / "broken.json"
            path.write_text(source)
            with self.subTest(source=source), self.assertRaises(EvidenceError):
                read_private_json(path)

    def test_nonfinite_nan_inf_rejected(self):
        for source in ('{"time":NaN}', '{"time":Infinity}', '{"time":-Infinity}'):
            with self.subTest(source=source), self.assertRaises(EvidenceError):
                parse_private_json(source)

    def test_symlink_rejected(self):
        path = self.root / "original.json"
        path.write_text('{"ok":1}')
        alias = self.root / "alias.json"
        alias.symlink_to(path)
        with self.assertRaises(EvidenceError):
            read_private_json(alias)

    def test_hardlink_rejected(self):
        path = self.root / "original.json"
        path.write_text('{"ok":1}')
        alias = self.root / "alias.json"
        os.link(path, alias)
        with self.assertRaises(EvidenceError):
            read_private_json(alias)

    def test_oversize_and_empty_rejected(self):
        path = self.root / "large.json"
        path.write_text('{"f":"foobar"}')
        with self.assertRaises(EvidenceError):
            read_private_json(path, limit=6)
        path.write_bytes(b"")
        with self.assertRaises(EvidenceError):
            read_private_json(path)

    def test_nonregular_named_pipe_rejected_without_blocking(self):
        if not hasattr(os, "mkfifo"):
            self.skipTest("fifo unavailable")
        fifo = self.root / "pipe.json"
        os.mkfifo(fifo)
        with self.assertRaises(EvidenceError):
            read_private_json(fifo)

    def test_invalid_unicode_and_structure_rejected(self):
        path = self.root / "broken.json"
        path.write_bytes(b"\xff\xfe")
        with self.assertRaises(EvidenceError):
            read_private_json(path)
        path.write_text('{"broken":}', encoding="utf-8")
        with self.assertRaises(EvidenceError):
            read_private_json(path)

    def test_cli_fails_closed_on_duplicate_key_in_rehashed_report(self):
        fixture, trust, db = self.root / "signed", self.root / "keys.json", self.root / "memory.sqlite"
        create_synthetic_fixture(fixture, trust)
        ingest(fixture, db, trust_store=trust)
        report = build_review_pack(db)
        location = self.root / "report"
        publish_review_pack(report, location)
        source = (location / "review.json").read_text("utf-8")
        # Duplicate top-level schema_version is accepted by naive json.loads
        forged = source.replace('"schema_version": 1,', '"schema_version": 1, "schema_version": 1,', 1)
        (location / "review.json").write_text(forged, encoding="utf-8")
        self.assertEqual(main(["review", "verify", "--dir", str(location)]), 2)

    def test_cli_fails_closed_on_hardlinked_report(self):
        fixture, trust, db = self.root / "signed", self.root / "keys.json", self.root / "memory.sqlite"
        create_synthetic_fixture(fixture, trust)
        ingest(fixture, db, trust_store=trust)
        report = build_review_pack(db)
        location = self.root / "report"
        publish_review_pack(report, location)
        copied = self.root / "shared.json"
        os.link(location / "review.json", copied)
        self.assertEqual(main(["review", "verify", "--dir", str(location)]), 2)


if __name__ == "__main__":
    unittest.main()
