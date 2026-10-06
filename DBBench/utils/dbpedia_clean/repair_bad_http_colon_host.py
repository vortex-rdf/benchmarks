#!/usr/bin/env python3
from pathlib import Path
import argparse
import sys


def repair_iri_inner(iri: str) -> tuple[str, bool]:
    fixed = iri

    fixed = fixed.replace("http://:www.", "http://www.")
    fixed = fixed.replace("https://:www.", "https://www.")

    return fixed, fixed != iri


def repair_line(line: str):
    out = []
    changed = False

    in_literal = False
    in_iri = False
    escaped = False
    iri_buf = []

    for ch in line:
        if in_literal:
            out.append(ch)

            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_literal = False
            continue

        if in_iri:
            if ch == ">":
                iri = "".join(iri_buf)
                fixed, was_changed = repair_iri_inner(iri)
                out.append(fixed)
                out.append(">")
                changed = changed or was_changed
                iri_buf = []
                in_iri = False
            else:
                iri_buf.append(ch)
            continue

        if ch == '"':
            in_literal = True
            out.append(ch)
        elif ch == "<":
            in_iri = True
            out.append(ch)
        else:
            out.append(ch)

    # Defensive: if malformed unfinished IRI, preserve buffered text.
    if in_iri:
        out.append("".join(iri_buf))

    return "".join(out), changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--changed-log", required=True)
    parser.add_argument("--progress-every", type=int, default=1_000_000)
    args = parser.parse_args()

    total = 0
    changed_count = 0

    with Path(args.input).open("r", encoding="utf-8", errors="replace") as fin, \
         Path(args.output).open("w", encoding="utf-8") as fout, \
         Path(args.changed_log).open("w", encoding="utf-8") as flog:

        for line_no, line in enumerate(fin, start=1):
            total += 1
            repaired, changed = repair_line(line)
            fout.write(repaired)

            if changed:
                changed_count += 1
                flog.write(f"{line_no}\t{line.rstrip()}\t=>\t{repaired.rstrip()}\n")

            if total % args.progress_every == 0:
                print(
                    f"lines={total:,} changed={changed_count:,}",
                    file=sys.stderr,
                    flush=True,
                )

    print(f"DONE lines={total:,} changed={changed_count:,}", file=sys.stderr)


if __name__ == "__main__":
    main()