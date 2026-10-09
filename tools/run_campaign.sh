#!/usr/bin/env bash
# Run one benchmark manifest over SPARQL HTTP for many systems, one at a time (cold page cache each).
#
#   tools/run_campaign.sh <benchmark-root> <declaration> <manifest> <experiment-id> [system ...]
#
# Without systems, every system bound in the declaration runs, in the order below (fast servers first).
# Resumable: a system whose results.summary.json exists is skipped. Environment:
#   MAX_WALL_S (per-system cap, default 14400)   QUARANTINE (default 3)   NO_DROP_CACHES=1 (no sudo)
#   IN_PROCESS=1 (library mode, no HTTP)   OUTPUT_ROOT (default <benchmark-root>/data/runs)   STORE_ROOT (default <benchmark-root>/data/http-stores)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
BENCH="$1"; DECL="$2"; MANIFEST="$3"; EXPERIMENT="$4"; shift 4
OUT="${OUTPUT_ROOT:-$BENCH/data/runs}"
STORES="${STORE_ROOT:-$BENCH/data/http-stores}"
ORDER="oxigraph/memory oxigraph/rocksdb qlever/default virtuoso/default fuseki/memory fuseki/tdb2 comunica/hdt
 vortex-rdf/dictionary-secondary-by-reference vortex-rdf/dictionary-secondary-by-reference-memory
 vortex-rdf/dictionary-secondary-by-copy vortex-rdf/dictionary-secondary-by-copy-memory
 vortex-rdf/dictionary-no-index vortex-rdf/dictionary-no-index-memory
 vortex-rdf/default-secondary-by-reference vortex-rdf/default-secondary-by-reference-memory
 vortex-rdf/default-secondary-by-copy vortex-rdf/default-secondary-by-copy-memory
 vortex-rdf/default-no-index vortex-rdf/default-no-index-memory
 pycottas/default hdt-rdflib/optimized-in-memory rdflib/default"
if [ "$#" -eq 0 ]; then
  BOUND=$(python3 -c "import json,sys; print(' '.join(b['system'] for b in json.load(open(sys.argv[1]))['bindings']))" "$DECL")
  set -- $(for s in $ORDER; do case " $BOUND " in *" $s "*) echo "$s";; esac; done)
fi
FLAGS=(--quarantine-threshold "${QUARANTINE:-3}" --max-wall-s "${MAX_WALL_S:-14400}")
[ -n "${NO_DROP_CACHES:-}" ] && FLAGS+=(--no-drop-caches)
[ -n "${IN_PROCESS:-}" ] && FLAGS+=(--in-process)    # library mode (rdflib-endpoint systems only)

for system in "$@"; do
  dir="$OUT/$EXPERIMENT/$(echo "$system" | tr '/' '-')"
  if [ -f "$dir/results.summary.json" ]; then echo "skip $system (done)"; continue; fi
  echo "=== $(date -u +%FT%TZ) $system   (free disk $(df -h --output=avail "$ROOT" | tail -1 | tr -d ' '))"
  vortex-rdf-bench run --declaration "$DECL" --benchmark-root "$BENCH" --manifest "$MANIFEST" --system "$system" \
    --output-root "$OUT" --store-root "$STORES" --experiment-id "$EXPERIMENT" "${FLAGS[@]}" || echo "FAILED $system (continuing)"
done
echo "=== $(date -u +%FT%TZ) campaign done: $OUT/$EXPERIMENT"
