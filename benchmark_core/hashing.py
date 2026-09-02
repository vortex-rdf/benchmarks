"""Deterministic SHA-256 helpers."""
from __future__ import annotations
import hashlib
from pathlib import Path


def sha256_bytes(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise TypeError("value must be bytes")
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: str | Path) -> str:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Not an existing file: {file_path}")
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
