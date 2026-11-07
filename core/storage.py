"""Crash-safe JSON writes. Callers hold their transaction lock across read + write."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_json(path: Path, value) -> None:
    payload = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)
    atomic_text(path, payload)


def atomic_text(path: Path, payload: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
