#!/usr/bin/env bash
set -euo pipefail

INPUT="$1"
OUT_PREFIX="$2"

mkdir -p data logs

current="$INPUT"
iteration=0
dropped_log="logs/${OUT_PREFIX}.dropped_riot_error_lines.tsv"
: > "$dropped_log"

while true; do
  iteration=$((iteration + 1))
  log="logs/${OUT_PREFIX}.riot.validate.iter${iteration}.log"

  echo "Validating iteration $iteration:"
  echo "  $current"

  set +e
  riot --syntax=NT --validate --sink "$current" > "$log" 2>&1
  status=$?
  set -e

  error_line="$(grep "ERROR riot" "$log" | head -n 1 || true)"

  if [ -z "$error_line" ]; then
    echo
    echo "No ERROR found."
    echo "Final valid file:"
    echo "$current"
    echo "Final validation log:"
    echo "$log"
    echo "Dropped lines log:"
    echo "$dropped_log"
    exit 0
  fi

  bad_line="$(echo "$error_line" | sed -E 's/.*\[line: ([0-9]+),.*/\1/')"

  if [ -z "$bad_line" ]; then
    echo "Could not parse bad line from:"
    echo "$error_line"
    exit 1
  fi

  next="data/${OUT_PREFIX}.syntaxdrop${iteration}.nt"

  echo "ERROR:"
  echo "  $error_line"
  echo "Dropping line $bad_line"

  offending="$(sed -n "${bad_line}p" "$current")"
  printf "%s\t%s\t%s\t%s\n" "$iteration" "$bad_line" "$error_line" "$offending" >> "$dropped_log"

  awk -v bad="$bad_line" 'NR != bad' "$current" > "$next"

  current="$next"
done