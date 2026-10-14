#!/usr/bin/env python3
"""Compare the cleaned DBpedia file with DBBench/checksums.json (size, triple count, sha256)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmark_core.hashing import sha256_file  # noqa: E402

path = Path(sys.argv[1])
expected = json.loads((Path(__file__).resolve().parents[1] / "checksums.json").read_text())["dbpedia-en-all"]["dataset"]
got = {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}
ok = all(got[k] == expected[k] for k in got)
print(("OK   " if ok else "FAIL ") + f"{path.name}: {got['sha256']} ({got['size_bytes']} bytes)")
if not ok:
    print(f"expected {expected['sha256']} ({expected['size_bytes']} bytes)")
sys.exit(0 if ok else 1)
