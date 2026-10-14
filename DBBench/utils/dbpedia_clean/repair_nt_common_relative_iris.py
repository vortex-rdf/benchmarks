#!/usr/bin/env python3
from pathlib import Path
import argparse
import re
import sys

# Only repair common bare web IRIs inside angle brackets.
# Examples:
#   <www.example.org/path>  -> <http://www.example.org/path>
#   <example.org/path>      not touched
PATTERN = re.compile(r"<(www\.[^>\s]+)>")

def repair_line(line: str):
    repaired = PATTERN.sub(r"<http://\1>", line)
    return repaired, repaired != line

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--changed-log", required=True)
    parser.add_argument("--progress-every", type=int, default=1_000_000)
    args = parser.parse_args()

    total = 0
    changed = 0

    with Path(args.input).open("r", encoding="utf-8", errors="replace") as fin, \
         Path(args.output).open("w", encoding="utf-8") as fout, \
         Path(args.changed_log).open("w", encoding="utf-8") as flog:

        for line_no, line in enumerate(fin, start=1):
            total += 1
            repaired, was_changed = repair_line(line)
            fout.write(repaired)

            if was_changed:
                changed += 1
                flog.write(f"{line_no}\t{line.rstrip()}\t=>\t{repaired.rstrip()}\n")

            if total % args.progress_every == 0:
                print(f"lines={total:,} changed={changed:,}", file=sys.stderr, flush=True)

    print(f"DONE lines={total:,} changed={changed:,}", file=sys.stderr)

if __name__ == "__main__":
    main()