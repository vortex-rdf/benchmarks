"""Use the shared RDFLib execution path for BSBM."""
from benchmark_core.rdf_execution import QueryTimeoutError, execute_query, run

__all__ = ['QueryTimeoutError', 'execute_query', 'run']
