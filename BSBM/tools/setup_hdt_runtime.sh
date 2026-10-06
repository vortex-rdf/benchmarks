#!/usr/bin/env bash
# Create the isolated Python runtime used to build the HDT query-ready index (rdflib-hdt "3.3").
#
#   BSBM/tools/setup_hdt_runtime.sh [target-dir]    # default: BSBM/data/tools/rdflib-hdt-3.3
#
# rdflib-hdt 3.3 is not on PyPI: it is the upstream repository at the commit pinned below, compiled
# against rdflib 7.6.0 (needs git, a C++ compiler and Python >= 3.10). The runtime is a separate
# virtual environment because rdflib-hdt patches rdflib's BGP evaluation globally.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET="${1:-$(dirname "$HERE")/data/tools/rdflib-hdt-3.3}"
COMMIT="58b82c27a5a0a1c5db833dd9fb1fd63b3a22c783"
PYTHON="${PYTHON:-python3}"
if [ -x "$TARGET/bin/python" ]; then echo "already present: $TARGET"; exit 0; fi
"$PYTHON" -m venv "$TARGET"
"$TARGET/bin/pip" install --quiet --upgrade pip setuptools wheel pybind11
"$TARGET/bin/pip" install --quiet "rdflib==7.6.0"
"$TARGET/bin/pip" install --quiet --no-build-isolation "git+https://github.com/RDFLib/rdflib-hdt.git@$COMMIT"
"$TARGET/bin/python" -c "import rdflib, rdflib_hdt, importlib.metadata as m; print('rdflib', rdflib.__version__, 'rdflib-hdt', m.version('rdflib-hdt'))"
echo "export VORTEX_RDF_BENCH_HDT_PYTHON=$TARGET/bin/python"
