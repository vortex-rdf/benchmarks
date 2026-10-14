"""Use the shared RDFLib execution path for WatDiv."""
from benchmark_core.rdf_execution import QueryTimeoutError, execute_query, run

__all__ = ['QueryTimeoutError', 'execute_query', 'run']
