#!/usr/bin/env python3
"""Run one system's query manifest over SPARQL HTTP and write the common JSONL result records.

One call measures one system against one running endpoint. Starting and stopping the server
(and dropping the page cache) is the caller's job; see ``benchmark_core.http_runner.systems``.

Protocol (identical for every system):

* one persistent keep-alive client; the timer covers the request write until the complete
  response body has been read (see ``worker.py``); counting and fingerprinting are untimed;
* a manifest with ``stream_phase``/``stream_position`` fields is a pre-expanded schedule and is
  executed in stream order; otherwise every query runs ``warmup_runs`` then ``measured_runs`` times;
* after ``quarantine_threshold`` measured timeouts of one template (``bsbm_template_id``) the
  remaining attempts of that template are recorded as ``skipped`` and not sent;
* a wall-clock budget stops the run and records ``budget_exhausted`` instead of hanging.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from benchmark_core import RESULT_SCHEMA_VERSION
from benchmark_core.hashing import sha256_file
from benchmark_core.http_runner.memory import PhaseAwareMemorySampler
from benchmark_core.http_runner.worker import HttpQueryWorker, QueryOutcome, QueryTimeoutError
from benchmark_core.result import validate_result

SUMMARY_SCHEMA = "http-run-summary-v1"
_RESERVED = {"query"}


@dataclasses.dataclass(frozen=True)
class RunProfile:
    """Execution parameters that are part of the measurement protocol."""

    timeout_s: float
    correctness_mode: str = "fingerprint"      # fingerprint | count-only
    warmup_runs: int = 0                         # only for manifests without a pre-expanded schedule
    measured_runs: int = 1
    quarantine_threshold: int = 3                # measured timeouts per template; 0 disables
    max_wall_s: float = 0.0                      # 0 disables the wall-clock budget
    startup_timeout_s: float = 120.0
    skip_after_warmup_failure: bool = True       # skip a query's measured runs after a failed warm-up
    force_include: bool = False                  # ignore quarantine and warm-up skips

    def to_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class _MemoryProbe:
    """Adapt a worker to the sampler's probe interface."""

    def __init__(self, worker: HttpQueryWorker):
        self._worker = worker

    def __call__(self):
        return self._worker.current_rss_bytes()

    def lifetime_peak_bytes(self):
        return self._worker.lifetime_peak_bytes()


def _status_for_exception(error: BaseException) -> str:
    if isinstance(error, QueryTimeoutError):
        return "timeout"
    if isinstance(error, ConnectionError):
        return "connection_error"
    return "engine_error"


def _selector(query: Mapping[str, Any]) -> tuple[str, str] | None:
    template = query.get("bsbm_template_id")
    return None if template in (None, "") else ("bsbm_template_id", str(template).strip())


def _timing_fields(attempt_ns: int, stages: Mapping[str, int] | None = None) -> dict[str, Any]:
    stages = dict(stages or {})
    nested = sum(stages.values())
    stages["dispatch"] = stages.get("dispatch", 0) + attempt_ns - nested
    return {
        "elapsed_ns": attempt_ns, "client_elapsed_ns": attempt_ns, "attempt_elapsed_ns": attempt_ns,
        "timing_clock": "perf_counter_ns", "timing_schema": "rdf-attempt-timing-v1",
        "timing_stages_ns": stages, "timing_stages_sum_ns": sum(stages.values()),
        "timing_reconciled": sum(stages.values()) == attempt_ns,
    }


def _skipped(record: dict[str, Any], kind: str, reason: str, **extra: Any) -> dict[str, Any]:
    record.update({
        "status": "skipped", "elapsed_ns": 0, "client_elapsed_ns": 0, "attempt_elapsed_ns": 0,
        "timing_clock": "perf_counter_ns", "timing_schema": "rdf-attempt-timing-v1",
        "timing_stages_ns": {"dispatch": 0}, "timing_stages_sum_ns": 0, "timing_reconciled": True,
        "measurement_boundary": "query-skipped-before-adapter-dispatch",
        "skip_kind": kind, "skip_reason": reason, **extra,
    })
    return record


def _attempts(manifest: Mapping[str, Any], profile: RunProfile) -> list[tuple[str, int, int, dict[str, Any]]]:
    """(phase, run, order, query) in execution order."""
    queries = manifest["queries"]
    flagged = sum("stream_phase" in query or "stream_position" in query for query in queries)
    if flagged not in {0, len(queries)}:
        raise ValueError("pre-expanded stream metadata must be present on every query")
    if flagged:
        attempts = []
        previous = -1
        for order, query in enumerate(queries):
            phase = query.get("stream_phase")
            if phase not in {"warmup", "measured"}:
                raise ValueError(f"unsupported pre-expanded stream phase: {phase!r}")
            position = query.get("stream_position")
            if not isinstance(position, int) or isinstance(position, bool) or position <= previous:
                raise ValueError(f"pre-expanded stream positions must increase: "
                                 f"found {position!r} after {previous} at query {order}")
            previous = position
            attempts.append((phase, 0, order, query))
        return attempts
    attempts = []
    for phase, runs in (("warmup", profile.warmup_runs), ("measured", profile.measured_runs)):
        for run in range(runs):
            attempts.extend((phase, run, order, query) for order, query in enumerate(queries))
    return attempts


def run_system(*, manifest: Mapping[str, Any], system: str, experiment_id: str, endpoint: str,
               container: str | None, output: Path, profile: RunProfile,
               after_timeout: Callable[[], None] | None = None,
               extra_summary: Mapping[str, Any] | None = None,
               progress: Callable[[str], None] = print) -> dict[str, Any]:
    """Execute ``manifest`` against ``endpoint`` and return the run summary.

    ``after_timeout`` is called, untimed, after any attempt that timed out, so the caller can
    bring a server that keeps working on the abandoned query (or cannot cancel it) back to idle.
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    attempts = _attempts(manifest, profile)
    total = len(attempts)
    worker = HttpQueryWorker(endpoint=endpoint, container=container, system=system,
                             timeout_s=profile.timeout_s, startup_timeout_s=profile.startup_timeout_s,
                             correctness_mode=profile.correctness_mode)
    sampler = PhaseAwareMemorySampler(_MemoryProbe(worker), "docker-container-cgroup-v2") if container else None
    part = output.with_name(output.name + ".part")
    counts: dict[str, int] = {}
    timeout_counts: dict[tuple[str, str], int] = {}
    quarantined: dict[tuple[str, str], dict[str, Any]] = {}
    skip_after_warmup: dict[str, tuple[str, str]] = {}
    budget: dict[str, Any] | None = None
    stage_ns = {"open": 0, "warmup": 0, "measured": 0, "close": 0}
    memory_metrics = None
    started_ns = time.perf_counter_ns()
    max_wall_ns = int(profile.max_wall_s * 1e9)

    with part.open("w", encoding="utf-8") as stream:
        try:
            if sampler is not None:
                sampler.start()
                sampler.set_phase("artifact_open_or_load")
            opened = time.perf_counter_ns()
            worker.open()
            stage_ns["open"] = time.perf_counter_ns() - opened
            for ordinal, (phase, run, order, query) in enumerate(attempts, 1):
                if max_wall_ns and time.perf_counter_ns() - started_ns >= max_wall_ns:
                    budget = {"schema": "rdf-query-budget-exhaustion-v1", "status": "budget_exhausted",
                              "budget_kind": "actual-wall-time", "completed_attempt_count": ordinal - 1,
                              "expected_attempt_count": total,
                              "elapsed_ns": time.perf_counter_ns() - started_ns,
                              "maximum_actual_wall_ns": max_wall_ns}
                    break
                text = query["query"]
                record: dict[str, Any] = {
                    "schema_version": RESULT_SCHEMA_VERSION, "experiment_id": experiment_id, "system": system,
                    "dataset": manifest["dataset"], "workload": manifest["workload"],
                    "query_id": query["query_id"], "query_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "phase": phase, "stream_phase": phase, "stream_position": query.get("stream_position", order),
                    "run": run, "order": order, "status": "ok", "elapsed_ns": 0,
                    "result_count": None, "result_fingerprint": None, "error_type": None, "error_message": None,
                }
                for key, value in query.items():
                    if key in _RESERVED:
                        continue
                    if key in record:
                        if record[key] == value or key in {"stream_phase", "stream_position"}:
                            continue
                        raise ValueError(f"query metadata replaces reserved field: {key}")
                    record[key] = value
                selector = _selector(query)
                rule = None if profile.force_include or selector is None else quarantined.get(selector)
                if rule is not None:
                    _skipped(record, "in-run-template-timeout-quarantine", rule["reason"],
                             skip_selector_kind=selector[0], skip_selector_value=selector[1],
                             skip_timeout_count=rule["timeout_count"], skip_threshold=rule["threshold"],
                             skip_activated_at_attempt=rule["activated_at_attempt"])
                elif phase == "measured" and not profile.force_include and query["query_id"] in skip_after_warmup:
                    error_type, error_message = skip_after_warmup[query["query_id"]]
                    _skipped(record, "failed-warmup", error_message or "warm-up of this query failed")
                    record["error_type"], record["error_message"] = error_type, error_message
                else:
                    if sampler is not None:
                        sampler.set_phase(phase)
                    if worker.prepare_for_attempt() and sampler is not None:
                        sampler.set_phase("restart_load_or_parse")
                        sampler.snapshot()
                        sampler.set_phase(phase)
                    progress(_line("start", ordinal, total, system, record, worker, counts))
                    attempt_started = time.perf_counter_ns()
                    try:
                        outcome = worker.execute(text)
                        attempt_ns = time.perf_counter_ns() - attempt_started
                        _apply_outcome(record, outcome, attempt_ns)
                    except BaseException as error:
                        if isinstance(error, KeyboardInterrupt):
                            raise
                        attempt_ns = time.perf_counter_ns() - attempt_started
                        record.update(_timing_fields(attempt_ns))
                        record.update({"status": _status_for_exception(error),
                                       "measurement_boundary": "rdf-adapter-attempt-until-failure",
                                       "error_type": type(error).__name__, "error_message": str(error)})
                    stage_ns[phase] += int(record.get("attempt_elapsed_ns") or 0)
                    if record["status"] == "timeout" and after_timeout is not None:
                        after_timeout()
                    if (phase == "measured" and record["status"] == "timeout" and selector is not None
                            and profile.quarantine_threshold > 0 and not profile.force_include):
                        count = timeout_counts[selector] = timeout_counts.get(selector, 0) + 1
                        if count >= profile.quarantine_threshold and selector not in quarantined:
                            quarantined[selector] = {
                                "reason": f"{selector[0]}={selector[1]} reached {profile.quarantine_threshold} "
                                          "measured query timeouts in the current system execution",
                                "timeout_count": count, "threshold": profile.quarantine_threshold,
                                "activated_at_attempt": ordinal}
                    if phase == "warmup" and profile.skip_after_warmup_failure and record["status"] != "ok":
                        skip_after_warmup[query["query_id"]] = (record["error_type"], record["error_message"])
                counts[record["status"]] = counts.get(record["status"], 0) + 1
                progress(_line("done", ordinal, total, system, record, worker, counts))
                stream.write(json.dumps(validate_result(record), ensure_ascii=False, sort_keys=True) + "\n")
                stream.flush()
        finally:
            closing = time.perf_counter_ns()
            if sampler is not None:
                sampler.set_phase("engine_shutdown")
            worker.close()
            stage_ns["close"] = time.perf_counter_ns() - closing
            if sampler is not None:
                memory_metrics = sampler.stop()
    os.replace(part, output)
    summary = {
        "schema": SUMMARY_SCHEMA, "system": system, "experiment_id": experiment_id, "endpoint": endpoint,
        "container": container, "profile": profile.to_json(), "attempts_expected": total,
        "status_counts": counts, "total_wall_ns": time.perf_counter_ns() - started_ns,
        "stages_ns": stage_ns, "budget": budget, "phase_memory_metrics": memory_metrics,
        "worker_restarts": worker.recovery_restarts,
        "manifest_sha256": manifest.get("_sha256"), "records_sha256": sha256_file(output),
        **(dict(extra_summary) if extra_summary else {}),
    }
    output.with_name(output.name.removesuffix(".jsonl") + ".summary.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def _apply_outcome(record: dict[str, Any], outcome: QueryOutcome, attempt_ns: int) -> None:
    stages = dict(outcome.stage_timings_ns)
    if sum(stages.values()) > attempt_ns:
        raise RuntimeError(f"timing stages exceed attempt total: {sum(stages.values())} > {attempt_ns}")
    record.update(_timing_fields(attempt_ns, stages))
    record["elapsed_ns"] = outcome.elapsed_ns
    record["result_count"] = outcome.result_count
    record["result_fingerprint"] = outcome.result_fingerprint
    for key, value in outcome.metadata.items():
        if key in record and record[key] != value:
            raise RuntimeError(f"worker metadata conflicts with existing field: {key}; "
                               f"query={record[key]!r}; worker={value!r}")
        record[key] = value


def _line(kind: str, ordinal: int, total: int, system: str, record: dict[str, Any],
          worker: HttpQueryWorker, counts: Mapping[str, int]) -> str:
    meta = worker.progress_metadata()
    failures = sum(n for status, n in counts.items() if status not in {"ok", "skipped"})
    line = (f"RDF_PROGRESS {kind} system={system} attempt={ordinal}/{total} phase={record['phase']} "
            f"position={record['stream_position']} query={record['query_id']}")
    if kind == "done":
        line += f" status={record['status']} elapsed_s={(record.get('elapsed_ns') or 0) / 1e9:.3f}"
    return f"{line} failures={failures} worker_pid={meta['worker_pid']} worker_restarts={meta['worker_restarts']}"
