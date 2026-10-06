"""Run an experiment declaration against server systems over SPARQL HTTP, one system at a time.

For every selected system: build its persistent store once (never overwriting an existing one),
optionally drop the page cache, start the server, run the manifest with the common runner,
record provenance and stop the server. Systems never run concurrently.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from benchmark_core.experiment import load_experiment_declaration
from benchmark_core.hashing import sha256_file
from benchmark_core.http_runner import provenance
from benchmark_core.http_runner.runner import RunProfile, run_system
from benchmark_core.manifest import load_manifest
from benchmark_core.systems.registry import get_system

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_name(system_id: str) -> str:
    return _SAFE.sub("-", system_id)


def drop_page_cache() -> dict[str, Any]:
    """Start each system with a cold page cache (needs passwordless sudo for sysctl)."""
    started = time.monotonic()
    subprocess.run(["sync"], check=False)
    result = subprocess.run(["sudo", "-n", "/usr/sbin/sysctl", "-q", "vm.drop_caches=3"],
                            capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("cannot drop the page cache (sudo -n sysctl vm.drop_caches=3): " + result.stderr.strip()
                           + "; pass --no-drop-caches to run warm")
    return {"status": "dropped", "elapsed_s": round(time.monotonic() - started, 3)}


def _representation_files(root: Path, receipt_relative: str) -> tuple[dict[str, Any], list[Path]]:
    receipt_path = (root / receipt_relative).resolve()
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    return receipt, [receipt_path.parent / entry["path"] for entry in receipt["files"]]


def _uniform_correctness(manifest: dict[str, Any]) -> str:
    modes = {query.get("comparison_mode") for query in manifest["queries"]}
    return "count-only" if modes == {"count-only"} else "fingerprint"


def run_declaration(*, declaration: Path, benchmark_root: Path, manifest_path: Path, systems: list[str],
                    output_root: Path, store_root: Path, timeout_s: float | None = None,
                    correctness: str = "auto", quarantine_threshold: int = 3, max_wall_s: float = 0.0,
                    drop_caches: bool = True, experiment_id: str | None = None,
                    repository: Path | None = None) -> dict[str, Any]:
    benchmark_root = Path(benchmark_root).resolve()
    declared = load_experiment_declaration(declaration)
    bindings = {item["system"]: item["representation"] for item in declared["bindings"]}
    selected = systems or list(bindings)
    unknown = [system for system in selected if system not in bindings]
    if unknown:
        raise ValueError(f"systems not in the declaration: {unknown}")
    manifest = load_manifest(manifest_path)
    manifest["_sha256"] = sha256_file(Path(manifest_path))
    mode = _uniform_correctness(manifest) if correctness == "auto" else correctness
    profile = RunProfile(timeout_s=timeout_s or float(declared["execution_policy"]["timeout_s"]),
                         correctness_mode=mode, quarantine_threshold=quarantine_threshold, max_wall_s=max_wall_s)
    experiment = experiment_id or declared["experiment"].replace("/", "-")
    run_dir = Path(output_root) / experiment
    run_dir.mkdir(parents=True, exist_ok=True)
    plan = {"schema": "http-campaign-plan-v1", "experiment_id": experiment, "declaration": str(Path(declaration).resolve()),
            "declaration_sha256": sha256_file(Path(declaration)), "manifest": str(Path(manifest_path).resolve()),
            "manifest_sha256": manifest["_sha256"], "systems": selected, "profile": profile.to_json(),
            "drop_caches": drop_caches,
            "provenance": provenance.collect(repository or Path(__file__).resolve().parents[2])}
    plan_path = run_dir / "campaign-plan.json"
    if not plan_path.exists():
        plan_path.write_text(json.dumps(plan, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    results: dict[str, Any] = {}
    for system_id in selected:
        results[system_id] = _run_one(system_id, bindings[system_id], declared, benchmark_root, manifest, run_dir,
                                      Path(store_root), profile, experiment, drop_caches)
    return {"experiment_id": experiment, "run_dir": str(run_dir), "systems": results}


def _run_one(system_id: str, representation: str, declared: dict[str, Any], root: Path, manifest: dict[str, Any],
             run_dir: Path, store_root: Path, profile: RunProfile, experiment: str, drop_caches: bool) -> dict[str, Any]:
    directory = run_dir / safe_name(system_id)
    output = directory / "results.jsonl"
    if output.exists():
        return {"status": "exists", "output": str(output)}   # never overwrite a finished result
    directory.mkdir(parents=True, exist_ok=True)
    system = get_system(system_id)
    _, rep_files = _representation_files(root, declared["representations"][representation])
    source = None
    if "rdf/source" in declared["representations"]:
        _, source_files = _representation_files(root, declared["representations"]["rdf/source"])
        source = source_files[0]
    artifact = rep_files[0]
    store: Path | None = artifact
    build_info: dict[str, Any] = {}
    if system.persistent:
        store = store_root / safe_name(system_id) / declared["dataset"]
        marker = store.parent / f"{declared['dataset']}.built.json"
        if not marker.exists():
            if source is None:
                raise ValueError(f"{system_id} needs an rdf/source representation to build its store")
            build_info = system.build(source=source, store=store)
            marker.write_text(json.dumps(build_info, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8")
        else:
            build_info = json.loads(marker.read_text(encoding="utf-8"))
        (directory / "build.json").write_text(json.dumps(build_info, indent=1, sort_keys=True, default=str) + "\n",
                                              encoding="utf-8")
    cache = drop_page_cache() if drop_caches else {"status": "skipped"}
    handle = system.start(source=source, store=store)
    try:
        after_timeout = lambda: system.settle()  # noqa: E731
        summary = run_system(
            manifest=manifest, system=system_id, experiment_id=experiment, endpoint=handle.endpoint,
            container=handle.container, output=output, profile=profile, after_timeout=after_timeout,
            extra_summary={"load": {"start_to_ready_s": handle.start_to_ready_s, "load_s": handle.load_s,
                                    "page_cache": cache},
                           "server": system.provenance(), "server_extra": handle.extra, "build": build_info})
    finally:
        system.stop()
    return {"status": "done", "output": str(output), "status_counts": summary["status_counts"]}
