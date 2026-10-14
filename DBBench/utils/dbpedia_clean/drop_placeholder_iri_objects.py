#!/usr/bin/env python3
from pathlib import Path
import argparse
import sys


PLACEHOLDER_IRIS = {
    "<None>",
    "<none>",
    "<NULL>",
    "<null>",
    "<N/A>",
    "<n/a>",
    "<NA>",
    "<na>",
    "<nil>",
    "<Nil>",
    "<NONE>",
    "<>",
}


def should_drop_line(line: str):
    """
    Drop syntactically invalid placeholder IRIs used as object terms.

    Expected simple NT shape:
      <s> <p> <None> .

    We intentionally only inspect whitespace-separated columns.
    This is safe for these placeholder IRI cases because the object has no spaces.
    """
    parts = line.strip().split()

    if len(parts) < 4:
        return False, None

    obj = parts[2]
    end = parts[3]

    if obj in PLACEHOLDER_IRIS and end == ".":
        return True, f"placeholder_object_iri:{obj}"

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