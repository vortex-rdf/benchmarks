"""Deterministic SHA-256 helpers.

``sha256_file`` caches digests of large files by (device, inode, size, mtime_ns), so a
multi-gigabyte source that has not changed is read once instead of on every build run.
A file that is replaced (new inode) or modified (size or mtime change) is hashed again.
The cache lives at ~/.cache/krown/sha256-cache.json; set KROWN_SHA256_CACHE to another
path, or to "off" to disable it.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from pathlib import Path

CACHE_MIN_BYTES = 16 * 1024 * 1024
_DEFAULT_CACHE = Path.home() / ".cache/krown/sha256-cache.json"


def sha256_bytes(value: bytes) -> str:
    if not isinstance(value, bytes):
        raise TypeError("value must be bytes")
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("value must be a string")
    return sha256_bytes(value.encode("utf-8"))


def _cache_path() -> Path | None:
    value = os.environ.get("KROWN_SHA256_CACHE")
    if value == "off":
        return None
    return Path(value) if value else _DEFAULT_CACHE


def _identity(stat: os.stat_result) -> tuple[str, dict]:
    return f"{stat.st_dev}:{stat.st_ino}", {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _load(cache: Path) -> dict:
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _store(cache: Path, key: str, entry: dict) -> None:
    cache.parent.mkdir(parents=True, exist_ok=True)
    with (cache.parent / (cache.name + ".lock")).open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries = _load(cache)
        entries[key] = entry
        temporary = cache.with_name(cache.name + f".tmp-{os.getpid()}")
        temporary.write_text(json.dumps(entries, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(temporary, cache)


def cached_sha256(path: str | Path) -> str | None:
    """Return the cached digest when the file is unchanged since it was hashed."""
    cache = _cache_path()
    if cache is None:
        return None
    key, identity = _identity(Path(path).stat())
    entry = _load(cache).get(key)
    if entry and all(entry.get(name) == value for name, value in identity.items()):
        return entry["sha256"]
    return None


def record_sha256(path: str | Path, digest: str, source: str = "computed") -> None:
    """Record a digest for an unchanged file (``source`` says where it came from)."""
    cache = _cache_path()
    file_path = Path(path)
    stat = file_path.stat()
    if cache is None or stat.st_size < CACHE_MIN_BYTES:
        return
    key, identity = _identity(stat)
    _store(cache, key, {**identity, "sha256": digest, "path": str(file_path.resolve()),
                        "source": source, "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})


def sha256_file(path: str | Path) -> str:
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"Not an existing file: {file_path}")
    cached = cached_sha256(file_path)
    if cached is not None:
        return cached
    before = file_path.stat()
    digest = hashlib.sha256()
    with file_path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    value = digest.hexdigest()
    after = file_path.stat()
    if _identity(before) == _identity(after):  # do not cache a file that changed while read
        record_sha256(file_path, value)
    return value
