#!/usr/bin/env python3
"""Classify SPARQL query features for safe result comparison."""

from dataclasses import asdict, dataclass
from typing import Any

from rdflib.plugins.sparql.processor import prepareQuery


@dataclass(frozen=True)
class QueryFeatures:
    """Store query features that affect result comparison."""

    result_type: str
    has_order_by: bool
    has_limit: bool
    has_offset: bool
    limit: int | None
    offset: int | None

    def as_metadata(self) -> dict[str, Any]:
        """Return canonical benchmark-record fields."""
        values = asdict(self)
        return {f'query_{key}': value for key, value in values.items()}


def _walk_algebra(node):
    """Yield each RDFLib algebra node recursively."""
    if node is None:
        return
    yield node
    if isinstance(node, dict):
        values = node.values()
    elif isinstance(node, (list, tuple)):
        values = node
    elif hasattr(node, 'items'):
        values = [value for _, value in node.items()]
    else:
        return
    for value in values:
        yield from _walk_algebra(value)


def classify_query(query: str) -> QueryFeatures:
    """Parse one query and identify features that affect comparison."""
    if not isinstance(query, str) or not query.strip():
        raise ValueError('query must be a non-empty string')
    prepared = prepareQuery(query)
    algebra = prepared.algebra
    root_name = getattr(algebra, 'name', '')
    result_types = {
        'SelectQuery': 'select',
        'AskQuery': 'ask',
        'ConstructQuery': 'construct',
        'DescribeQuery': 'describe',
    }
    result_type = result_types.get(root_name, 'unsupported')
    has_order_by = False
    limit = None
    offset = None
    has_slice = False

    for node in _walk_algebra(algebra):
        name = getattr(node, 'name', None)
        if name == 'OrderBy':
            has_order_by = True
        elif name == 'Slice':
            has_slice = True
            length = node['length'] if 'length' in node else None
            start = node['start'] if 'start' in node else None
            if length is not None:
                limit = int(length)
            if start is not None:
                offset = int(start)

    return QueryFeatures(
        result_type=result_type,
        has_order_by=has_order_by,
        has_limit=has_slice and limit is not None,
        has_offset=has_slice and offset not in (None, 0),
        limit=limit,
        offset=offset if offset not in (None, 0) else None,
    )


def comparison_metadata(features: QueryFeatures,
                        contains_blank_nodes: bool) -> dict[str, Any]:
    """Choose the strongest safe automatic comparison for one result."""
    warning = None
    if features.result_type == 'ask':
        mode = 'boolean'
    elif features.result_type not in {'select', 'construct', 'describe'}:
        mode = 'unsupported'
        warning = 'Unsupported query result type.'
    elif contains_blank_nodes:
        mode = 'provisional_blank_nodes'
        warning = (
            'Blank-node identifiers can differ across equivalent results.'
        )
    elif features.has_limit and not features.has_order_by:
        mode = 'count_only_nondeterministic_limit'
        warning = (
            'LIMIT without ORDER BY can select different valid subsets.'
        )
    elif features.has_order_by:
        mode = 'ordered_fingerprint'
    else:
        mode = 'unordered_multiset_fingerprint'

    metadata = features.as_metadata()
    metadata.update({
        'comparison_mode': mode,
        'comparison_warning': warning,
    })
    return metadata
