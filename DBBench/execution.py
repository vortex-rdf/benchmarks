"""Manifest-driven RDFLib execution for DBBench."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile
import time
from typing import Any

from rdflib import Graph
from benchmark_core import RESULT_SCHEMA_VERSION
from benchmark_core.manifest import load_manifest
from benchmark_core.result import validate_result


class QueryTimeoutError(TimeoutError):
    """Raised when a query exceeds its configured wall-clock limit."""


def _term(value: Any) -> str:
    return value.n3() if hasattr(value, 'n3') else str(value)


def _fingerprint_result(result: Any, mode: str) -> tuple[int, str]:
    result_type = str(getattr(result, 'type', 'SELECT')).upper()
    if result_type == 'ASK':
        rows = ['true' if bool(result.askAnswer) else 'false']
    elif result_type in {'CONSTRUCT', 'DESCRIBE'}:
        rows = sorted(
            ' '.join((_term(s), _term(p), _term(o)))
            for s, p, o in result.graph
        )
    else:
        rows = ['\t'.join(_term(value) for value in row) for row in result]
        if mode != 'ordered_fingerprint':
            rows.sort()
    payload = ('\n'.join(rows) + '\n').encode('utf-8')
    return len(rows), hashlib.sha256(payload).hexdigest()


def _timeout(signum, frame):
    raise QueryTimeoutError('query exceeded timeout')


def execute_query(graph: Graph, query: dict[str, Any], timeout_s: float | None) -> dict[str, Any]:
    old_handler = None
    start = time.perf_counter_ns()
    try:
        if timeout_s is not None and timeout_s > 0:
            old_handler = signal.signal(signal.SIGALRM, _timeout)
            signal.setitimer(signal.ITIMER_REAL, timeout_s)
        result = graph.query(query['query'])
        count, fingerprint = _fingerprint_result(
            result, query.get('comparison_mode', 'unordered_fingerprint')
        )
        return {
            'status': 'ok', 'elapsed_ns': time.perf_counter_ns() - start,
            'result_count': count, 'result_fingerprint': fingerprint,
            'result_type': str(getattr(result, 'type', query.get('query_result_type', 'SELECT'))).upper(),
            'error_type': None, 'error': None,
        }
    except QueryTimeoutError as error:
        return {
            'status': 'timeout', 'elapsed_ns': time.perf_counter_ns() - start,
            'result_count': None, 'result_fingerprint': None,
            'result_type': query.get('query_result_type'),
            'error_type': type(error).__name__, 'error': str(error),
        }
    except Exception as error:
        return {
            'status': 'engine_error', 'elapsed_ns': time.perf_counter_ns() - start,
            'result_count': None, 'result_fingerprint': None,
            'result_type': query.get('query_result_type'),
            'error_type': type(error).__name__, 'error': str(error),
        }
    finally:
        if timeout_s is not None and timeout_s > 0:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)


def run(*, manifest_path: Path, dataset_path: Path, output: Path,
        experiment_id: str, warmup_runs: int = 1, measured_runs: int = 5,
        timeout_s: float | None = 60.0, resume: bool = False) -> list[dict[str, Any]]:
    if warmup_runs < 0 or measured_runs < 1:
        raise ValueError('warmup_runs must be non-negative and measured_runs must be positive')
    manifest = load_manifest(manifest_path)
    graph = Graph()
    graph.parse(dataset_path)
    completed: set[tuple[str, str, int]] = set()
    existing: list[dict[str, Any]] = []
    if resume and output.exists():
        for line in output.read_text(encoding='utf-8').splitlines():
            if line.strip():
                record = validate_result(json.loads(line))
                existing.append(record)
                completed.add((record['query_id'], record['phase'], record['run']))
    records = list(existing)
    order = len(records)
    for query in manifest['queries']:
        for phase, runs in (('warmup', warmup_runs), ('measured', measured_runs)):
            for run_index in range(runs):
                if (query['query_id'], phase, run_index) in completed:
                    continue
                measured = execute_query(graph, query, timeout_s)
                record = {
                    'schema_version': RESULT_SCHEMA_VERSION,
                    'experiment_id': experiment_id, 'system': 'rdflib',
                    'dataset': manifest['dataset'], 'workload': manifest['workload'],
                    'query_id': query['query_id'], 'phase': phase,
                    'run': run_index, 'order': order,
                    **measured,
                    'engine': {'name': 'rdflib'},
                    'dataset_path': str(dataset_path),
                    'manifest_path': str(manifest_path),
                }
                records.append(validate_result(record)); order += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f'.{output.name}.', dir=output.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            for record in records:
                stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, output)
    except BaseException:
        try: os.unlink(name)
        except FileNotFoundError: pass
        raise
    return records
