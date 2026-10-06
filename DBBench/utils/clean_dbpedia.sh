#!/usr/bin/env bash
# Turn the raw DBpedia 3.5.1 concatenation into the benchmark dataset (dbpedia_en_all.nt,
# 232,541,923 triples, sha256 in DBBench/checksums.json).
#
#   DBBench/utils/clean_dbpedia.sh [data-dir]      # same data-dir as download_dbpedia_3_5_1.sh
#
# Eight streaming steps, each reading the previous output. The order is the one the paper's
# dataset was produced in (reconstructed from the timestamps of the original logs). Each step
# writes a change/drop log; after the run the logs are compared with DBBench/expected-logs/,
# which hold the logs of the original run: identical logs mean identical decisions.
# The original run also used Apache Jena `riot` once, to find <None> placeholder objects; step 3
# does the same by pattern and is the scripted replacement. Intermediates are deleted as
# soon as the next step finishes (set KEEP_INTERMEDIATE=1 to keep them); peak extra disk ~75 GB.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${1:-$(dirname "$HERE")/data/dbpedia-3.5.1}"
CLEAN="$HERE/dbpedia_clean"
EXPECTED="$(dirname "$HERE")/expected-logs"
OUT="$DATA/dbpedia_en_all.nt"
LOGS="$DATA/logs"
mkdir -p "$LOGS"
current="$DATA/dbpedia_en_all.raw.nt"
[ -s "$current" ] || { echo "missing $current: run download_dbpedia_3_5_1.sh first" >&2; exit 1; }

# name  script  log-flag-name  log-file
STEPS=(
  "1 repair_dbpedia.py                 --changed-log  dbpedia_en_all.iri_spaces_fixed.tsv"
  "2 repair_nt_common_relative_iris.py --changed-log  dbpedia_en_all.www_relative_iri_fixed.tsv"
  "3 drop_placeholder_iri_objects.py   --dropped-log  dbpedia_en_all.dropped_placeholder_iris.tsv"
  "4 drop_relative_iri_terms.py        --dropped-log  dbpedia_en_all.dropped_relative_iris.tsv"
  "5 repair_surrogate_pairs_nt.py      --changed-log  dbpedia_en_all.repaired_surrogate_pairs.tsv"
  "6 repair_pyoxigraph_iri_chars.py    --changed-log  dbpedia_en_all.pyoxigraph_iri_char_fixes.tsv"
  "7 repair_bad_http_colon_host.py     --changed-log  dbpedia_en_all.fixed_bad_http_colon_host.tsv"
  "8 drop_bad_http_authority_port.py   --dropped-log  dbpedia_en_all.dropped_bad_http_authority_port_v2.tsv"
)
for step in "${STEPS[@]}"; do
  read -r number script flag logfile <<<"$step"
  next="$DATA/step$number.nt"
  [ "$number" = 8 ] && next="$OUT"
  if [ ! -s "$next" ]; then
    echo "[$number/8] $script"
    extra=()
    # step 5 also reports lines it had to drop (unpaired surrogates)
    [ "$script" = repair_surrogate_pairs_nt.py ] && extra=(--dropped-log "$LOGS/dbpedia_en_all.dropped_unpaired_surrogates.tsv")
    python3 "$CLEAN/$script" --input "$current" --output "$next.part" "$flag" "$LOGS/$logfile" ${extra[@]+"${extra[@]}"}
    mv "$next.part" "$next"
  fi
  if [ "$current" != "$DATA/dbpedia_en_all.raw.nt" ] && [ "${KEEP_INTERMEDIATE:-0}" != 1 ]; then rm -f "$current"; fi
  current="$next"
done

echo "comparing step logs with the original run's logs"
status=0
for step in "${STEPS[@]}"; do
  read -r _ _ _ logfile <<<"$step"
  if cmp -s "$LOGS/$logfile" "$EXPECTED/$logfile"; then echo "  identical  $logfile"; else echo "  DIFFERS    $logfile"; status=1; fi
done
if cmp -s "$LOGS/dbpedia_en_all.dropped_unpaired_surrogates.tsv" "$EXPECTED/dbpedia_en_all.dropped_unpaired_surrogates.tsv"; then echo "  identical  dbpedia_en_all.dropped_unpaired_surrogates.tsv"; else echo "  DIFFERS    dbpedia_en_all.dropped_unpaired_surrogates.tsv"; status=1; fi
python3 "$HERE/verify_dbpedia_checksum.py" "$OUT" || status=1
exit $status
