"""Bounded, no-follow local JSON/HTML evidence reads.

For local trusted directories only: parent-directory replacement by another
privileged process cannot be prevented without a protected directory tree.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from .contracts import EvidenceError

JSON_LIMIT = 16 * 1024 * 1024
HTML_LIMIT = 32 * 1024 * 1024


def read_private_bytes(path: str | Path, *, limit: int = JSON_LIMIT) -> bytes:
    """Reject symlinks, hardlinks, special files, oversized and drifting input."""
    p = Path(path)
    if type(limit) is not int or not 0 < limit <= HTML_LIMIT:
        raise EvidenceError("invalid private file size limit")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(p, flags)
        try:
            before = os.fstat(fd)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or not 0 < before.st_size <= limit):
                raise EvidenceError("unsafe or oversized private file")
            chunks, remaining = [], limit + 1
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            after = os.fstat(fd)
            if (len(data) > limit or len(data) != before.st_size
                    or before.st_dev != after.st_dev or before.st_ino != after.st_ino
                    or before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns
                    or before.st_ctime_ns != after.st_ctime_ns):
                raise EvidenceError("private file changed or exceeded size bound")
            return data
        finally:
            os.close(fd)
    except (OSError, ValueError) as exc:
        raise EvidenceError("unable to read safe local private file") from exc


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise EvidenceError("duplicate JSON object member")
        data[key] = value
    return data


def _invalid_constant(value: str) -> None:
    raise EvidenceError("non-finite JSON constant forbidden")


def read_private_json(path: str | Path, *, limit: int = JSON_LIMIT) -> Any:
    try:
        data = read_private_bytes(path, limit=limit).decode("utf-8")
        return json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("invalid local private JSON") from exc


def parse_private_json(data: str | bytes) -> Any:
    """Same strict parser for operator-provided, bounded already-read data."""
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    try:
        return json.loads(data, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("invalid JSON") from exc
