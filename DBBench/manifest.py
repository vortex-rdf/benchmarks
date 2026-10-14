#!/usr/bin/env python3
"""Prepare standalone DBBench query manifests."""
from __future__ import annotations
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from benchmark_core.atomic_io import write_json_atomic
from benchmark_core.hashing import sha256_file, sha256_text
from benchmark_core.manifest import validate_manifest
from DBBench.query_features import classify_query, comparison_metadata

MANIFEST_SCHEMA_VERSION = 1
GROUPS = frozenset({'TP', 'JOINS'})
JOIN_SIZES = frozenset({'small', 'big'})
REQUIRED_INVENTORY_FIELDS = (
    'query_id', 'relative_path', 'top_group', 'dataset', 'size_group',
    'file_name', 'query_index_in_file', 'line_no', 'contains_limit', 'query',
)



def split_dbbench_queries(path: Path) -> list[tuple[int, str]]:
    """Read one SELECT query from each non-empty source line."""
    raw = path.read_text(encoding='utf-8', errors='replace')
    queries = []
    for line_no, line in enumerate(raw.splitlines(), start=1):
        query = line.strip()
        if query and query.lower().startswith('select'):
            queries.append((line_no, query))
    return queries


def iter_query_files(root: Path, dataset: str, groups: Iterable[str], join_sizes: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    selected_groups = tuple(groups)
    if 'TP' in selected_groups:
        directory = root / 'TP' / dataset
        if directory.is_dir():
            files.extend(sorted(directory.glob('*.txt')))
    if 'JOINS' in selected_groups:
        for size in join_sizes:
            directory = root / 'JOINS' / dataset / size
            if directory.is_dir():
                files.extend(sorted(directory.glob('*.txt')))
    return files


def build_inventory(root: Path, dataset: str, groups: Iterable[str], join_sizes: Iterable[str]) -> list[dict[str, Any]]:
    records = []
    for path in iter_query_files(root, dataset, groups, join_sizes):
        relative = path.relative_to(root)
        top_group = relative.parts[0]
        size_group = relative.parts[2] if top_group == 'JOINS' else None
        for index, (line_no, query) in enumerate(split_dbbench_queries(path)):
            records.append({
                'query_id': f'{relative.as_posix()}::q{index:04d}',
                'relative_path': relative.as_posix(),
                'top_group': top_group,
                'dataset': dataset,
                'size_group': size_group,
                'file_name': path.name,
                'query_index_in_file': index,
                'line_no': line_no,
                'contains_limit': 'limit' in query.lower(),
                'query': query,
            })
    return records


def load_inventory(path: Path) -> list[dict[str, Any]]:
    with path.open('r', encoding='utf-8') as stream:
        value = json.load(stream)
    if not isinstance(value, list):
        raise ValueError('inventory root must be an array')
    return value


def _validate_source(record: Any, index: int) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError(f'inventory record {index} must be an object')
    missing = [field for field in REQUIRED_INVENTORY_FIELDS if field not in record]
    if missing:
        raise ValueError(f'inventory record {index} misses fields: {", ".join(missing)}')
    query_id = record['query_id']
    query = record['query']
    if not isinstance(query_id, str) or not query_id:
        raise ValueError(f'inventory record {index} has an invalid query_id')
    if not isinstance(query, str) or not query.strip():
        raise ValueError(f'inventory record {index} has an invalid query')
    if record['top_group'] not in GROUPS:
        raise ValueError(f'inventory record {index} has an unsupported top_group')
    if record['top_group'] == 'JOINS' and record['size_group'] not in JOIN_SIZES:
        raise ValueError(f'inventory record {index} has an unsupported join size')
    for field in ('query_index_in_file', 'line_no'):
        value = record[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f'inventory record {index} has an invalid {field}')
    if not isinstance(record['contains_limit'], bool):
        raise ValueError(f'inventory record {index} has an invalid contains_limit')
    return record


def convert_records(records: Iterable[dict[str, Any]], workload: str, dataset: str) -> dict[str, Any]:
    records = [_validate_source(record, index) for index, record in enumerate(records)]
    ids = Counter(record['query_id'] for record in records)
    duplicates = sorted(query_id for query_id, count in ids.items() if count > 1)
    if duplicates:
        raise ValueError(f'duplicate query_id values: {", ".join(duplicates)}')
    hashes: dict[str, list[str]] = defaultdict(list)
    converted = []
    for source in records:
        query = source['query']
        digest = sha256_text(query)
        hashes[digest].append(source['query_id'])
        metadata: dict[str, Any] = {
            'query_sha256': digest,
            'source_relative_path': source['relative_path'],
            'source_top_group': source['top_group'],
            'source_dataset': source['dataset'],
            'source_size_group': source['size_group'],
            'source_file_name': source['file_name'],
            'source_query_index': source['query_index_in_file'],
            'source_line': source['line_no'],
            'source_contains_limit': source['contains_limit'],
        }
        try:
            features = classify_query(query)
            metadata.update(comparison_metadata(features, contains_blank_nodes=False))
            metadata['query_parse_status'] = 'ok'
            metadata['query_parse_error'] = None
        except Exception as error:
            metadata.update({
                'query_parse_status': 'error',
                'query_parse_error': f'{type(error).__name__}: {error}',
                'comparison_mode': 'unsupported',
                'comparison_warning': 'The query classifier could not parse this query.',
            })
        converted.append({'query_id': source['query_id'], 'query': query, **metadata})
    converted.sort(key=lambda record: record['query_id'])
    duplicate_content = [
        {'query_sha256': digest, 'query_ids': sorted(query_ids)}
        for digest, query_ids in sorted(hashes.items()) if len(query_ids) > 1
    ]
    return {
        'schema_version': MANIFEST_SCHEMA_VERSION,
        'workload': workload,
        'dataset': dataset,
        'source_format': 'dbbench',
        'query_count': len(converted),
        'duplicate_query_content': duplicate_content,
        'queries': converted,
    }


def convert(*, output: Path, workload: str, dataset: str, inventory: Path | None = None,
            query_root: Path | None = None, groups: Iterable[str] = ('TP', 'JOINS'),
            join_sizes: Iterable[str] = ('small', 'big')) -> dict[str, Any]:
    if (inventory is None) == (query_root is None):
        raise ValueError('provide exactly one of inventory or query_root')
    records = load_inventory(inventory) if inventory else build_inventory(query_root, dataset, groups, join_sizes)
    if not records:
        raise ValueError('DBBench input contains no queries')
    manifest = convert_records(records, workload, dataset)
    write_json_atomic(output, validate_manifest(manifest))
    return manifest




def select_query_records(records: Iterable[dict[str, Any]],
                         query_ids: Iterable[str] | None = None
                         ) -> list[dict[str, Any]]:
    """Select known query identifiers and keep deterministic order."""
    records = list(records)
    if query_ids is None:
        return sorted(records, key=lambda record: record['query_id'])
    selected = list(query_ids)
    duplicates = sorted(
        query_id for query_id, count in Counter(selected).items() if count > 1
    )
    if duplicates:
        raise ValueError(
            f'duplicate selected query_id values: {", ".join(duplicates)}'
        )
    by_id = {record['query_id']: record for record in records}
    unknown = sorted(set(selected) - set(by_id))
    if unknown:
        raise ValueError(f'unknown selected query_id values: {", ".join(unknown)}')
    if not selected:
        raise ValueError('query selection must not be empty')
    return sorted((by_id[query_id] for query_id in selected),
                  key=lambda record: record['query_id'])


def query_tree_provenance(root: Path, dataset: str,
                          groups: Iterable[str],
                          join_sizes: Iterable[str]) -> dict[str, Any]:
    """Build deterministic provenance for selected DBBench query files."""
    entries = []
    digest = hashlib.sha256()
    for path in iter_query_files(root, dataset, groups, join_sizes):
        relative = path.relative_to(root).as_posix()
        file_hash = sha256_file(path)
        size = path.stat().st_size
        entry = {'path': relative, 'size_bytes': size, 'sha256': file_hash}
        entries.append(entry)
        digest.update(json.dumps(entry, sort_keys=True,
                                 separators=(',', ':')).encode('utf-8'))
        digest.update(b'\n')
    if not entries:
        raise ValueError('DBBench query tree contains no selected files')
    return {'sha256': digest.hexdigest(), 'files': entries}


def read_query_ids(path: Path) -> list[str]:
    """Read query identifiers from one text file."""
    return [line.strip() for line in path.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


def prepare(*, output: Path, workload: str, dataset: str,
            inventory: Path | None = None, query_root: Path | None = None,
            groups: Iterable[str] = ('TP', 'JOINS'),
            join_sizes: Iterable[str] = ('small', 'big'),
            query_id_file: Path | None = None) -> dict[str, Any]:
    """Prepare one validated manifest with deterministic provenance."""
    if (inventory is None) == (query_root is None):
        raise ValueError('provide exactly one of inventory or query_root')
    groups = tuple(groups)
    join_sizes = tuple(join_sizes)
    if inventory is not None:
        records = load_inventory(inventory)
        source = {
            'kind': 'inventory',
            'path': str(inventory),
            'sha256': sha256_file(inventory),
        }
    else:
        records = build_inventory(query_root, dataset, groups, join_sizes)
        provenance = query_tree_provenance(
            query_root, dataset, groups, join_sizes
        )
        source = {
            'kind': 'query_tree',
            'path': str(query_root),
            'sha256': provenance['sha256'],
            'files': provenance['files'],
        }
    selected_ids = None
    selection_hash = None
    if query_id_file is not None:
        selected_ids = read_query_ids(query_id_file)
        selection_hash = sha256_file(query_id_file)
    records = select_query_records(records, selected_ids)
    if not records:
        raise ValueError('DBBench input contains no queries')
    manifest = convert_records(records, workload, dataset)
    source.update({
        'selected_query_count': len(records),
        'groups': sorted(groups),
        'join_sizes': sorted(join_sizes),
        'query_id_file': str(query_id_file) if query_id_file else None,
        'query_id_file_sha256': selection_hash,
    })
    manifest['source'] = source
    write_json_atomic(output, validate_manifest(manifest))
    return manifest

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--inventory', type=Path)
    source.add_argument('--query-root', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--workload', required=True)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--groups', nargs='+', choices=sorted(GROUPS), default=['TP', 'JOINS'])
    parser.add_argument('--join-sizes', nargs='+', choices=sorted(JOIN_SIZES), default=['small', 'big'])
    parser.add_argument('--query-id-file', type=Path)
    args = parser.parse_args()
    manifest = prepare(output=args.output, workload=args.workload, dataset=args.dataset,
                       inventory=args.inventory, query_root=args.query_root,
                       groups=args.groups, join_sizes=args.join_sizes,
                       query_id_file=args.query_id_file)
    print(f'Wrote {len(manifest["queries"])} queries to {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
