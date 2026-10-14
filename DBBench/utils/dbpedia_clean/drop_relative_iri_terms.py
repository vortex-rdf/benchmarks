#!/usr/bin/env python3
from pathlib import Path
import argparse
import sys
import re

SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")

def is_angle_iri(term: str) -> bool:
    return term.startswith("<") and term.endswith(">")

def iri_inner(term: str) -> str:
    return term[1:-1]

def is_relative_iri_term(term: str) -> bool:
    if not is_angle_iri(term):
        return False

    inner = iri_inner(term)

    # Empty or no scheme => relative/invalid for our NT benchmark input.
    if inner == "":
        return True

    return SCHEME_RE.match(inner) is None

def should_drop_line(line: str):
    stripped = line.strip()
    if not stripped:
        return False, None

    parts = stripped.split()

    # Need at least: s p o .
    if len(parts) < 4:
        return False, None

    # Subject, predicate, object.
    # This is safe for catching IRI terms; literal objects start with quotes.
    for idx, role in [(0, "subject"), (1, "predicate"), (2, "object")]:
        term = parts[idx]
        if is_relative_iri_term(term):
            return True, f"relative_{role}_iri:{term}"

    return False, None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dropped-log", required=True)
    parser.add_argument("--progress-every", type=int, default=1_000_000)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    dropped_log_path = Path(args.dropped_log)

    total = 0
    kept = 0
    dropped = 0

    with input_path.open("r", encoding="utf-8", errors="replace") as fin, \
         output_path.open("w", encoding="utf-8") as fout, \
         dropped_log_path.open("w", encoding="utf-8") as flog:

        for line_no, line in enumerate(fin, start=1):
            total += 1
            drop, reason = should_drop_line(line)

            if drop:
                dropped += 1
                flog.write(f"{line_no}\t{reason}\t{line.rstrip()}\n")
            else:
                kept += 1
                fout.write(line)

            if total % args.progress_every == 0:
                print(
                    f"lines={total:,} kept={kept:,} dropped={dropped:,}",
                    file=sys.stderr,
                    flush=True,
                )

    print(
        f"DONE lines={total:,} kept={kept:,} dropped={dropped:,}",
        file=sys.stderr,
    )

if __name__ == "__main__":
    main()