"""Atomic JSON and JSON Lines output."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterable, Mapping


def _replace_text(path: str | Path, writer) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n",
            prefix=f".{target.name}.", suffix=".tmp",
            dir=target.parent, delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json_atomic(path: str | Path, value: Any) -> None:
    def writer(stream):
        json.dump(value, stream, ensure_ascii=False, allow_nan=False,
                  indent=2, sort_keys=True)
        stream.write("\n")
    _replace_text(path, writer)


def write_jsonl_atomic(path: str | Path,
                       records: Iterable[Mapping[str, Any]]) -> int:
    validated = list(records)
    def writer(stream):
        for record in validated:
            json.dump(record, stream, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"), sort_keys=True)
            stream.write("\n")
    _replace_text(path, writer)
    return len(validated)
