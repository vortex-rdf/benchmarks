#!/usr/bin/env python3
"""Check a generated BSBM directory against BSBM/checksums.json.

usage: verify_checksums.py <explore-10k|explore-100k> <dir>
Exit 0 when dataset and query stream match; exit 1 with a per-file report otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmark_core.hashing import sha256_file  # noqa: E402


def main() -> int:
    label, directory = sys.argv[1], Path(sys.argv[2])
    expected = json.loads((Path(__file__).resolve().parents[1] / "checksums.json").read_text())["datasets"][label]
    failed = False
    for key, name in (("dataset", "dataset.nt"), ("query_stream", "explore.csv")):
        path = directory / name
        want = expected[key]["sha256"]
        got = sha256_file(path) if path.is_file() else None
        ok = got == want
        failed |= not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name}: {got}" + ("" if ok else f" (expected {want})"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
