#!/usr/bin/env bash
set -euo pipefail

INPUT="$1"
OUT_PREFIX="$2"

mkdir -p logs

drops="logs/${OUT_PREFIX}.drop_original_lines.txt"
dropped_tsv="logs/${OUT_PREFIX}.dropped_riot_error_lines.tsv"

: > "$drops"
: > "$dropped_tsv"

validate_filtered() {
  awk -v drops="$drops" '
    BEGIN {
      while ((getline line < drops) > 0) {
        if (line != "") drop[line] = 1
      }
      close(drops)
    }
    !(NR in drop)
  ' "$INPUT" | riot --syntax=NT --validate --sink - 
}

map_filtered_line_to_original_line() {
  filtered_target="$1"

  awk -v drops="$drops" -v target="$filtered_target" '
    BEGIN {
      while ((getline line < drops) > 0) {
        if (line != "") drop[line] = 1
      }
      close(drops)
      kept = 0
    }
    !(NR in drop) {
      kept++
      if (kept == target) {
        print NR
        exit
      }
    }
  ' "$INPUT"
}

iteration=0

while true; do
  iteration=$((iteration + 1))
  log="logs/${OUT_PREFIX}.riot.validate.filtered.iter${iteration}.log"

  echo "Validating filtered stream iteration $iteration"
  echo "Current dropped-line count: $(wc -l < "$drops")"

  set +e
  validate_filtered > "$log" 2>&1
  status=$?
  set -e

  error_msg="$(grep "ERROR riot" "$log" | head -n 1 || true)"

  if [ -z "$error_msg" ]; then
    echo
    echo "No ERROR found."
    echo "Bad original line numbers:"
    echo "$drops"
    echo "Dropped line details:"
    echo "$dropped_tsv"
    echo "Final validation log:"
    echo "$log"
    exit 0
  fi

  filtered_line="$(echo "$error_msg" | sed -E 's/.*\[line: ([0-9]+),.*/\1/')"

  if [ -z "$filtered_line" ]; then
    echo "Could not parse filtered line from:"
    echo "$error_msg"
    exit 1
  fi

  original_line="$(map_filtered_line_to_original_line "$filtered_line")"

  if [ -z "$original_line" ]; then
    echo "Could not map filtered line $filtered_line to original line."
    exit 1
  fi

  offending="$(sed -n "${original_line}p" "$INPUT")"

  echo "ERROR:"
  echo "  $error_msg"
  echo "Filtered line: $filtered_line"
  echo "Original line: $original_line"
  echo "Offending:"
  echo "  $offending"

  printf "%s\t%s\t%s\t%s\t%s\n" \
    "$iteration" "$filtered_line" "$original_line" "$error_msg" "$offending" \
    >> "$dropped_tsv"

  echo "$original_line" >> "$drops"

  tmp="${drops}.tmp"
  sort -n -u "$drops" > "$tmp"
  mv "$tmp" "$drops"
done