#!/usr/bin/env bash
# Generate a BSBM Explore dataset and query stream exactly as used in the paper.
#
#   BSBM/tools/generate.sh <products> [out-dir]      # products: 10000 (10K) or 100000 (100K)
#
# Produces <out-dir>/{dataset.nt, explore.csv, generation-receipt.json}; default out-dir is
# BSBM/data/explore-<N>k (git-ignored). Requires Docker and Git; no local Java.
#
# Reproducibility pins (all verified: the 10K dataset hash matches BSBM/checksums.json):
#   * generator   Tpt/bsbm-tools, commit da7c78d (branch bench-data), the jar committed there
#   * JVM         eclipse-temurin 21 JRE, image digest below
#   * time zone   Europe/Brussels. The generator derives dates from the JVM time zone: under UTC
#                 9,636 date triples of the 10K dataset differ by one day, so the hash changes.
#   * seed        the generator's default (808080), as in the original run: no -seed is passed
#   * query stream: the test driver (50 warm-up + 500 measured Explore mixes) run against a
#                 temporary Oxigraph server loaded with the dataset; only the request log is kept.
set -euo pipefail

PRODUCTS="${1:?usage: generate.sh <10000|100000> [out-dir]}"
case "$PRODUCTS" in 10000) LABEL=explore-10k ;; 100000) LABEL=explore-100k ;; *) echo "products must be 10000 or 100000" >&2; exit 2 ;; esac
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BSBM_DIR="$(dirname "$HERE")"
OUT="${2:-$BSBM_DIR/data/$LABEL}"
TOOLS_DIR="$BSBM_DIR/data/tools/bsbm-tools"
BSBM_TOOLS_REPO="https://github.com/Tpt/bsbm-tools.git"
BSBM_TOOLS_COMMIT="da7c78d8c6f4eeb19149b9848c24123a97f31e2f"
JRE_IMAGE="eclipse-temurin@sha256:eebd356ad7358b7094758e5787a6726f332917cfd56feab6457c56dab895cdbf"
OXIGRAPH_IMAGE="dtaikg/oxigraph@sha256:819f403db7f74b3d79e771e20ddc097e5bea04dabcc4f5f8ff39c6afdff57076"
TZ_NAME="Europe/Brussels"
WORK="$OUT/.work"
SERVER="bsbm-gen-oxigraph-$$"

mkdir -p "$OUT" "$(dirname "$TOOLS_DIR")"
if [ ! -d "$TOOLS_DIR/.git" ]; then git clone --quiet "$BSBM_TOOLS_REPO" "$TOOLS_DIR"; fi
git -C "$TOOLS_DIR" checkout --quiet --detach "$BSBM_TOOLS_COMMIT"
git -C "$TOOLS_DIR" diff --quiet || { echo "$TOOLS_DIR has local modifications; remove it and rerun" >&2; exit 1; }

# Fresh working copy: the generator writes next to its scripts.
rm -rf "$WORK"; mkdir -p "$WORK"
git -C "$TOOLS_DIR" archive "$BSBM_TOOLS_COMMIT" | tar -x -C "$WORK"
java_run() {  # run a bsbm-tools script in the JRE container as the current user
  docker run --rm -u "$(id -u):$(id -g)" --network "${DOCKER_NET:-bridge}" \
    -e JAVA_TOOL_OPTIONS="-Duser.timezone=$TZ_NAME" -v "$WORK:/w" -w /w "$JRE_IMAGE" "$@"
}

echo "[1/3] generating dataset ($PRODUCTS products)"
START=$(date +%s)
java_run ./generate -fc -pc "$PRODUCTS" -s nt -fn dataset -ud -ufn dataset-update
GEN_SECONDS=$(( $(date +%s) - START ))
mv "$WORK/dataset.nt" "$OUT/dataset.nt"

echo "[2/3] generating the Explore query stream against a temporary Oxigraph server"
cleanup() { docker rm -f "$SERVER" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker run -d --name "$SERVER" -v "$OUT:/data:ro" "$OXIGRAPH_IMAGE" serve --bind 0.0.0.0:7878 >/dev/null
SERVER_IP="$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$SERVER")"
for _ in $(seq 1 60); do
  if curl -fs "http://$SERVER_IP:7878/query" -H 'Accept: application/sparql-results+json' --data-urlencode 'query=ASK{}' >/dev/null; then break; fi
  sleep 1
done
curl -fs -X POST -H 'Content-Type: application/n-triples' --data-binary @"$OUT/dataset.nt" "http://$SERVER_IP:7878/store?default" >/dev/null
java_run ./testdriver -ucf usecases/explore/sparql.txt "http://$SERVER_IP:7878/query" -w 50 -runs 500 >"$WORK/testdriver.log" 2>&1
cp "$WORK/log.csv" "$OUT/explore.csv"

echo "[3/3] writing the generation receipt"
python3 "$HERE/write_generation_receipt.py" \
  --products "$PRODUCTS" --dataset "$OUT/dataset.nt" --stream "$OUT/explore.csv" \
  --generator-commit "$BSBM_TOOLS_COMMIT" --generator-repo "$BSBM_TOOLS_REPO" \
  --dataset-seconds "$GEN_SECONDS" --time-zone "$TZ_NAME" --jre-image "$JRE_IMAGE" \
  --output "$OUT/generation-receipt.json"
python3 "$HERE/verify_checksums.py" "$LABEL" "$OUT"
rm -rf "$WORK"
echo "done: $OUT"
