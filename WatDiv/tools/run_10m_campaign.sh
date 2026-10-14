#!/usr/bin/env bash
# Run WatDiv 10M over SPARQL HTTP for all 14 systems, one at a time (cold page cache each).
#
#   WatDiv/tools/run_10m_campaign.sh [smoke|qualification|full]      (default: qualification)
#
# Resumable: a system whose results.summary.json exists is skipped. Environment:
#   VORTEX_RDFLIB_VERSION (default 0.1.3)   MAX_WALL_S (per system; default 4500 full / 1800 otherwise)
#   NO_DROP_CACHES=1  (no sudo)             SYSTEMS="id id ..." (subset)
set -euo pipefail
STAGE="${1:-qualification}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"
DATA=WatDiv/data
MANIFEST="$DATA/manifests/watdiv-10m-$STAGE.json"
EXPERIMENT="watdiv-10m-$STAGE-vrl${VORTEX_RDFLIB_VERSION:-0.1.3}"
OUT="${OUTPUT_ROOT:-$DATA/runs}"
case "$STAGE" in full) WALL="${MAX_WALL_S:-4500}" ;; *) WALL="${MAX_WALL_S:-1800}" ;; esac

[ -f "$MANIFEST" ] || vortex-rdf-bench watdiv prepare --dataset watdiv-10m --selection "$STAGE" --output "$MANIFEST"

DEFAULT_SYSTEMS="oxigraph/memory oxigraph/rocksdb qlever/default virtuoso/default fuseki/memory fuseki/tdb2 comunica/hdt
 vortex-rdf/dictionary-secondary-by-reference vortex-rdf/dictionary-secondary-by-reference-memory
 vortex-rdf/dictionary-secondary-by-copy vortex-rdf/dictionary-secondary-by-copy-memory
 pycottas/default hdt-rdflib/optimized-in-memory rdflib/default"
FLAGS=(--quarantine-threshold 3 --max-wall-s "$WALL")
[ -n "${NO_DROP_CACHES:-}" ] && FLAGS+=(--no-drop-caches)

for system in ${SYSTEMS:-$DEFAULT_SYSTEMS}; do
  dir="$OUT/$EXPERIMENT/$(echo "$system" | tr '/' '-')"
  if [ -f "$dir/results.summary.json" ]; then echo "skip $system (done)"; continue; fi
  echo "=== $(date -u +%FT%TZ) $system"
  vortex-rdf-bench run --declaration WatDiv/experiments/watdiv-10m-full.json --benchmark-root WatDiv \
    --manifest "$MANIFEST" --system "$system" --output-root "$OUT" --store-root "$DATA/http-stores" \
    --experiment-id "$EXPERIMENT" "${FLAGS[@]}" || echo "FAILED $system (continuing)"
done
echo "=== $(date -u +%FT%TZ) campaign done: $OUT/$EXPERIMENT"
