"""Server systems by identifier (the identifiers used in the experiment declarations)."""
from __future__ import annotations

from benchmark_core.systems.base import ServerSystem
from benchmark_core.systems.fuseki import Fuseki
from benchmark_core.systems.oxigraph import Oxigraph
from benchmark_core.systems.qlever import QLever
from benchmark_core.systems.virtuoso import Virtuoso

_FACTORIES = {
    "oxigraph/memory": lambda: Oxigraph("memory"), "oxigraph/rocksdb": lambda: Oxigraph("rocksdb"),
    "fuseki/memory": lambda: Fuseki("memory"), "fuseki/tdb2": lambda: Fuseki("tdb2"),
    "virtuoso/default": Virtuoso, "qlever/default": QLever,
}


def system_ids() -> list[str]:
    return sorted(_FACTORIES)


def get_system(system_id: str) -> ServerSystem:
    try:
        return _FACTORIES[system_id]()
    except KeyError:
        raise ValueError(f"unknown server system {system_id!r}; known: {', '.join(system_ids())}") from None
