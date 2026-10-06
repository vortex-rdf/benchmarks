"""DBBench representation wrappers over the shared RDF builders."""
from BSBM.cottas import generate as generate_cottas, verify as verify_cottas
from BSBM.hdt import generate as generate_hdt, verify as verify_hdt

__all__ = [
    "generate_cottas", "verify_cottas",
    "generate_hdt", "verify_hdt",
]
