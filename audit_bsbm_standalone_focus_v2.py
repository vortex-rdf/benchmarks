#!/usr/bin/env python3
"""Focused static audit for making the BSBM benchmark independent of KROWN."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "bsbm-standalone-focused-audit-v2"
DEFAULT_ROOT = Path("/users/u0182905/benchmarks/BSBM")
DEFAULT_OUTPUT = Path("/users/u0182905/benchmarks/bsbm-standalone-focused-audit-v2.json")

# Vendored or generated trees are summarized, not searched recursively for source coupling.
EXCLUDED_DIR_NAMES = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "node_modules", "npm-cache", "target", "build", "dist", ".venv", "venv",
}
TEXT_SUFFIXES = {
    "", ".py", ".sh", ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".env", ".csv", ".rq", ".sparql", ".js",
    ".mjs", ".cjs", ".ts", ".xml",
}
ENTRYPOINT_NAMES = {
    "README.md", "execution.py", "manifest.py", "hdt.py", "cottas.py",
    "vortex_rdf.py", "pyproject.toml", "requirements.txt", "environment.yml",
    "Makefile", "Dockerfile",
}
COUPLING_PATTERNS = {
    "krown-name": re.compile(r"(?i)(?<![A-Za-z0-9_])krown(?![A-Za-z0-9_])"),
    "krown-path": re.compile(r"/users/[^/\s]+/KROWN(?:/[^\s'\"`)]*)?"),
    "user-absolute-path": re.compile(r"/users/[^/\s]+/(?:[^\s'\"`)]*)"),
    "home-absolute-path": re.compile(r"/home/[^/\s]+/(?:[^\s'\"`)]*)"),
    "python-import-krown": re.compile(r"(?m)^\s*(?:from|import)\s+(?:KROWN|krown)(?:\b|\.)"),
}
RUNTIME_PATTERNS = {
    "python-import": re.compile(r"(?m)^\s*(?:from\s+([A-Za-z_][\w.]*)\s+import|import\s+([A-Za-z_][\w.]*))"),
    "env-variable": re.compile(r"\b(?:os\.environ(?:\.get)?\s*\[?\(?[\"']|os\.getenv\s*\(\s*[\"']|\$\{?)([A-Z][A-Z0-9_]*)"),
    "subprocess-command": re.compile(r"(?i)\b(?:subprocess\.(?:run|Popen|check_call|check_output)|os\.system)\b"),
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def git(root: Path, *args: str) -> dict[str, Any]:
    proc = subprocess.run(
        ["git", *args], cwd=root, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    return {"returncode": proc.returncode, "stdout": proc.stdout.rstrip(), "stderr": proc.stderr.rstrip()}


def walk_files(root: Path) -> Iterable[Path]:
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in EXCLUDED_DIR_NAMES)
        base = Path(current)
        for name in sorted(files):
            yield base / name


def is_probably_text(path: Path) -> bool:
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return False
    try:
        sample = path.read_bytes()[:8192]
    except OSError:
        return False
    return b"\x00" not in sample


def line_hits(path: Path, root: Path) -> list[dict[str, Any]]:
    if not is_probably_text(path):
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as error:
        return [{"kind": "read-error", "path": str(path.relative_to(root)), "error": str(error)}]
    hits: list[dict[str, Any]] = []
    for number, line in enumerate(lines, 1):
        matched = [name for name, pattern in COUPLING_PATTERNS.items() if pattern.search(line)]
        if matched:
            hits.append({
                "path": str(path.relative_to(root)), "line": number,
                "kinds": matched, "text": line[:500],
            })
    return hits


def inspect_python(path: Path, root: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    imports = []
    for match in RUNTIME_PATTERNS["python-import"].finditer(text):
        imports.append((match.group(1) or match.group(2)).split(".")[0])
    env = sorted(set(RUNTIME_PATTERNS["env-variable"].findall(text)))
    return {
        "path": str(path.relative_to(root)),
        "imports": sorted(set(imports)),
        "environment_variables": env,
        "uses_subprocess": bool(RUNTIME_PATTERNS["subprocess-command"].search(text)),
        "has_main_guard": 'if __name__ == "__main__"' in text or "if __name__ == '__main__'" in text,
        "executable": bool(path.stat().st_mode & stat.S_IXUSR),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    if not root.is_dir():
        raise SystemExit(f"BSBM root does not exist: {root}")

    files = list(walk_files(root))
    coupling: list[dict[str, Any]] = []
    python_files: list[dict[str, Any]] = []
    entrypoints: list[dict[str, Any]] = []
    symlinks: list[dict[str, Any]] = []
    broken_symlinks: list[dict[str, Any]] = []

    for path in files:
        coupling.extend(line_hits(path, root))
        if path.suffix == ".py":
            python_files.append(inspect_python(path, root))
        if path.name in ENTRYPOINT_NAMES or (path.suffix in {".py", ".sh"} and path.stat().st_mode & stat.S_IXUSR):
            entrypoints.append({
                "path": str(path.relative_to(root)), "executable": bool(path.stat().st_mode & stat.S_IXUSR),
                "sha256": sha256_file(path), "size_bytes": path.stat().st_size,
            })

    # os.walk lists symlinked directories in dirs. Inspect all paths separately.
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            target = os.readlink(path)
            resolved = (path.parent / target).resolve()
            record = {
                "path": str(path.relative_to(root)), "target": target,
                "resolved": str(resolved), "target_exists": resolved.exists(),
                "escapes_root": not resolved.is_relative_to(root),
            }
            symlinks.append(record)
            if not resolved.exists():
                broken_symlinks.append(record)

    krown_hits = [h for h in coupling if "krown-name" in h.get("kinds", []) or "krown-path" in h.get("kinds", []) or "python-import-krown" in h.get("kinds", [])]
    absolute_hits = [h for h in coupling if "user-absolute-path" in h.get("kinds", []) or "home-absolute-path" in h.get("kinds", [])]
    escaping_links = [s for s in symlinks if s["escapes_root"]]

    missing_primary = [name for name in ("README.md", "execution.py", "manifest.py") if not (root / name).is_file()]
    findings: list[dict[str, Any]] = []
    runtime_krown_hits = [h for h in krown_hits if h.get("path") != "README.md"]
    runtime_absolute_hits = [h for h in absolute_hits if not h.get("path", "").startswith("data/")]
    if runtime_krown_hits:
        findings.append({"severity": "error", "id": "runtime-krown-coupling", "count": len(runtime_krown_hits), "evidence": runtime_krown_hits})
    if runtime_absolute_hits:
        findings.append({"severity": "error", "id": "runtime-absolute-user-paths", "count": len(runtime_absolute_hits), "evidence": runtime_absolute_hits})
    if krown_hits and not runtime_krown_hits:
        findings.append({"severity": "info", "id": "optional-krown-documentation", "count": len(krown_hits), "evidence": krown_hits})
    provenance_absolute_hits = [h for h in absolute_hits if h.get("path", "").startswith("data/")]
    if broken_symlinks:
        findings.append({"severity": "error", "id": "broken-symlinks", "count": len(broken_symlinks), "evidence": broken_symlinks})
    if escaping_links:
        findings.append({"severity": "warning", "id": "symlinks-outside-root", "count": len(escaping_links), "evidence": escaping_links})
    if missing_primary:
        findings.append({"severity": "error", "id": "missing-primary-entrypoints", "count": len(missing_primary), "evidence": missing_primary})

    result = {
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "output": str(output),
        "scope": {
            "purpose": "Identify exact KROWN coupling and portability blockers in first-party BSBM files.",
            "excluded_directory_names": sorted(EXCLUDED_DIR_NAMES),
            "note": "Vendored and generated trees are excluded from source-coupling scans but symlinks are still audited.",
        },
        "repository": {
            "head": git(root, "rev-parse", "HEAD"),
            "status": git(root, "status", "--short"),
            "top_level": git(root, "rev-parse", "--show-toplevel"),
        },
        "summary": {
            "scanned_files": len(files),
            "coupling_hits": len(coupling),
            "krown_hits": len(krown_hits),
            "absolute_path_hits": len(absolute_hits),
            "runtime_absolute_path_hits": len(runtime_absolute_hits),
            "provenance_absolute_path_hits": len(provenance_absolute_hits),
            "symlinks": len(symlinks),
            "broken_symlinks": len(broken_symlinks),
            "escaping_symlinks": len(escaping_links),
            "entrypoints": len(entrypoints),
            "findings": len(findings),
            "error_findings": sum(f["severity"] == "error" for f in findings),
            "warning_findings": sum(f["severity"] == "warning" for f in findings),
            "static_standalone_candidate": not any(f["severity"] == "error" for f in findings),
            "standalone_unit": "installed vortex-rdf-benchmarks distribution",
        },
        "findings": findings,
        "krown_references": krown_hits,
        "absolute_path_references": absolute_hits,
        "runtime_absolute_path_references": runtime_absolute_hits,
        "provenance_absolute_path_references": provenance_absolute_hits,
        "symlinks": symlinks,
        "entrypoints": entrypoints,
        "python_runtime_contracts": python_files,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
