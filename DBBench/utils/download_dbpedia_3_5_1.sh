#!/usr/bin/env bash
# Download the 23 English DBpedia 3.5.1 N-Triples files and concatenate them (in list order)
# into the raw input of the cleaning pipeline.
#
#   DBBench/utils/download_dbpedia_3_5_1.sh [data-dir]      # default: DBBench/data/dbpedia-3.5.1
#
# Output: <data-dir>/en/*.nt.bz2 (kept) and <data-dir>/dbpedia_en_all.raw.nt (~36 GB).
# Next step: DBBench/utils/clean_dbpedia.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${1:-$(dirname "$HERE")/data/dbpedia-3.5.1}"
BASE_URL="${DBPEDIA_351_URL:-https://downloads.dbpedia.org/3.5.1/en}"
LIST="$HERE/dbpedia_clean/dbpedia_3_5_1_en_files.txt"
mkdir -p "$DATA/en"
while read -r name; do
  [ -n "$name" ] || continue
  if [ ! -s "$DATA/en/$name" ]; then
    echo "downloading $name"
    curl -fL --retry 5 --retry-delay 10 -C - -o "$DATA/en/$name.part" "$BASE_URL/$name"
    mv "$DATA/en/$name.part" "$DATA/en/$name"
  fi
done < "$LIST"
RAW="$DATA/dbpedia_en_all.raw.nt"
if [ ! -s "$RAW" ]; then
  echo "concatenating into $RAW"
  : > "$RAW.part"
  while read -r name; do [ -n "$name" ] && bzcat "$DATA/en/$name" >> "$RAW.part"; done < "$LIST"
  mv "$RAW.part" "$RAW"
fi
( cd "$DATA/en" && sha256sum *.bz2 ) > "$DATA/downloaded-files.sha256"
echo "raw triples file: $RAW ($(wc -l < "$RAW") lines)"
