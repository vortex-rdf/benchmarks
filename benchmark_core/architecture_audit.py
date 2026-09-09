"""Audit the benchmark-owned side of the shared RDF architecture."""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

BENCHMARKS = ('DBBench', 'BSBM')


def _imports_shared_runner(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == 'benchmark_core.rdf_execution'
        and any(alias.name == 'run' for alias in node.names)
        for node in ast.walk(tree)
    )


def audit_repository(root: Path) -> dict[str, Any]:
    """Return a deterministic report or raise when one invariant is broken."""
    root = root.resolve()
    required = [
        'benchmark_core/manifest.py', 'benchmark_core/result.py',
        'benchmark_core/rdf_execution.py', 'benchmark_core/atomic_io.py',
        'DBBench/manifest.py', 'DBBench/execution.py', 'DBBench/README.md',
        'BSBM/manifest.py', 'BSBM/execution.py', 'BSBM/README.md',
    ]
    missing = [path for path in required if not (root / path).is_file()]
    if missing:
        raise ValueError('Missing architecture files: ' + ', '.join(missing))

    wrappers = {}
    for benchmark in BENCHMARKS:
        execution = root / benchmark / 'execution.py'
        wrappers[benchmark.lower()] = _imports_shared_runner(execution)
        if not wrappers[benchmark.lower()]:
            raise ValueError(f'{benchmark} does not reuse benchmark_core.rdf_execution.run')

    gitignore = (root / '.gitignore').read_text(encoding='utf-8').splitlines()
    for pattern in ('**/data/', '**/runs/'):
        if pattern not in gitignore:
            raise ValueError(f'Missing Git-ignore rule: {pattern}')

    pyproject = (root / 'pyproject.toml').read_text(encoding='utf-8')
    for package in ('benchmark_core*', 'DBBench*', 'BSBM*'):
        if package not in pyproject:
            raise ValueError(f'pyproject.toml does not package {package}')

    core_execution = (root / 'benchmark_core/rdf_execution.py').read_text(encoding='utf-8')
    for token in ('manifest_sha256', 'dataset_sha256', 'validate_result', 'os.replace'):
        if token not in core_execution:
            raise ValueError(f'Shared execution misses invariant: {token}')

    for benchmark in BENCHMARKS:
        readme = (root / benchmark / 'README.md').read_text(encoding='utf-8').lower()
        if 'data/' not in readme:
            raise ValueError(f'{benchmark} README does not document local data placement')

    bsbm_readme = (root / 'BSBM/README.md').read_text(encoding='utf-8').lower()
    if 'does not' not in bsbm_readme or 'generator' not in bsbm_readme:
        raise ValueError('BSBM README does not keep generation outside the adapter')

    return {
        'schema': 'rdf-benchmark-architecture-audit-v1',
        'repository_role': 'benchmark-semantics-and-adapters',
        'benchmarks': ['dbbench', 'bsbm'],
        'shared_execution_wrappers': wrappers,
        'external_assets_ignored': True,
        'atomic_publication': True,
        'provenance_fields': ['manifest_sha256', 'dataset_sha256'],
    }
