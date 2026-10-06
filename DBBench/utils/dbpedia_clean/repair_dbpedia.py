#!/usr/bin/env python3
from pathlib import Path
import argparse
import sys


def repair_spaces_inside_iris(line: str):
    """
    Replace spaces inside <...> IRI tokens only when outside string literals.

    Safe for:
      <http://dbpedia.org/datatype/brake horsepower>
    Does NOT touch:
      "<17"@en .
      "some <literal text with spaces>" .
    """
    out = []
    changed = False

    in_iri = False
    in_literal = False
    escaped = False

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

        if ch == '"':
            in_literal = True
            out.append(ch)
        elif ch == "<" and not in_iri:
            in_iri = True
            out.append(ch)
        elif ch == ">" and in_iri:
            in_iri = False
            out.append(ch)
        elif ch == " " and in_iri:
            out.append("%20")
            changed = True
        else:
            out.append(ch)

    return "".join(out), changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--changed-log", required=True)
    parser.add_argument("--progress-every", type=int, default=1_000_000)
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    changed_log_path = Path(args.changed_log)

    total = 0
    changed_count = 0

    with input_path.open("r", encoding="utf-8", errors="replace") as fin, \
         output_path.open("w", encoding="utf-8") as fout, \
         changed_log_path.open("w", encoding="utf-8") as flog:

        for line_no, line in enumerate(fin, start=1):
            total += 1
            repaired, changed = repair_spaces_inside_iris(line)

            fout.write(repaired)

            if changed:
                changed_count += 1
                flog.write(
                    f"{line_no}\t{line.rstrip()}\t=>\t{repaired.rstrip()}\n"
                )

            if total % args.progress_every == 0:
                print(
                    f"lines={total:,} changed={changed_count:,}",
                    file=sys.stderr,
                    flush=True,
                )

    print(f"DONE lines={total:,} changed={changed_count:,}", file=sys.stderr)


if __name__ == "__main__":
    main()