"""Compatibility wrapper for shared RDFLib benchmark execution."""
from benchmark_core.rdf_execution import QueryTimeoutError, execute_query, run

__all__ = ['QueryTimeoutError', 'execute_query', 'run']
