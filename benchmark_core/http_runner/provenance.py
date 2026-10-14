"""Run provenance: repository revision, interpreter and package versions, image digests."""
from __future__ import annotations

import importlib.metadata
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

PACKAGES = ("rdflib", "requests", "urllib3", "psutil", "vortex-rdf", "vortex-rdflib", "pycottas", "rdflib-hdt",
            "rdflib-endpoint", "uvicorn", "fastapi", "vortex-rdf-benchmarks")


def _git(root: Path, *args: str) -> str | None:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def repository_state(root: Path) -> dict[str, Any]:
    status = _git(root, "status", "--porcelain", "--untracked-files=no")
    return {"revision": _git(root, "rev-parse", "HEAD"), "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD"),
            "dirty": None if status is None else bool(status), "dirty_paths": (status or "").splitlines()[:20]}


def package_versions(names: Iterable[str] = PACKAGES) -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for name in names:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def collect(repository: Path, images: dict[str, str | None] | None = None) -> dict[str, Any]:
    return {"schema": "vortex-rdf-bench-provenance-v1", "repository": repository_state(repository),
            "python": sys.version.split()[0], "python_executable": sys.executable,
            "platform": platform.platform(), "packages": package_versions(), "images": images or {}}
