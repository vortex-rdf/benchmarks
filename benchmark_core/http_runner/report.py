"""Summarize one or more HTTP run directories: per-template latency, outcomes and memory."""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

GIB = 2 ** 30


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low, high = int(position), min(int(position) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def load_system(results: Path) -> dict[str, Any]:
    ok: list[float] = []
    by_template: dict[str, list[float]] = defaultdict(list)
    outcomes: Counter = Counter()
    for line in results.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["phase"] != "measured":
            continue
        outcomes[record["status"]] += 1
        if record["status"] == "ok":
            milliseconds = record["elapsed_ns"] / 1e6
            ok.append(milliseconds)
            by_template[str(record.get("bsbm_template_id", "all"))].append(milliseconds)
    summary_path = results.with_name(results.name.removesuffix(".jsonl") + ".summary.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    memory = (summary.get("phase_memory_metrics") or {}).get("phases", {}).get("measured", {})
    return {"ok": ok, "by_template": by_template, "outcomes": outcomes, "memory": memory,
            "load": summary.get("load", {}), "summary": summary}


def format_report(run_dir: Path) -> str:
    systems = sorted(path.parent for path in Path(run_dir).glob("*/results.jsonl"))
    lines = [f"{'system':58s} {'ok':>6s} {'timeout':>7s} {'error':>5s} {'skipped':>7s} {'mean ms':>9s} {'median':>8s} "
             f"{'p95':>9s} {'anon GiB':>8s} {'file GiB':>8s} {'ready s':>8s}"]
    details = []
    for directory in systems:
        data = load_system(directory / "results.jsonl")
        o, ok = data["outcomes"], data["ok"]
        error = sum(n for status, n in o.items() if status not in {"ok", "timeout", "skipped"})
        memory, load = data["memory"], data["load"]
        anon = memory.get("peak_anon_bytes"), memory.get("peak_file_bytes")
        lines.append(f"{directory.name:58s} {o['ok']:6d} {o['timeout']:7d} {error:5d} {o['skipped']:7d} "
                     f"{statistics.mean(ok) if ok else float('nan'):9.2f} {statistics.median(ok) if ok else float('nan'):8.2f} "
                     f"{_percentile(ok, 0.95) if ok else float('nan'):9.2f} "
                     f"{(anon[0] or 0) / GIB:8.2f} {(anon[1] or 0) / GIB:8.2f} {load.get('start_to_ready_s') or 0:8.1f}")
        details.append((directory.name, data["by_template"]))
    for name, templates in details:
        if len(templates) > 1:
            lines.append("")
            lines.append(f"per template, mean ms (successful measured attempts) -- {name}")
            lines.append("  " + "  ".join(f"{template}:{statistics.mean(values):.2f}"
                                          for template, values in sorted(templates.items(), key=lambda kv: kv[0])))
    for failure in sorted(Path(run_dir).glob("*/failed.json")):
        info = json.loads(failure.read_text(encoding="utf-8"))
        lines.append(f"FAILED {failure.parent.name}: {info.get('phase')} {info.get('error', '')[:160]}")
    return "\n".join(lines)
