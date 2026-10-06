#!/usr/bin/env python3
from pathlib import Path
import argparse
import re
import sys

SHORT_ESC_RE = re.compile(r"\\u([0-9a-fA-F]{4})")
LONG_SURROGATE_RE = re.compile(r"\\U0000[dD][89aAbB][0-9a-fA-F]{2}")


def is_high_surrogate(x):
    return 0xD800 <= x <= 0xDBFF


def is_low_surrogate(x):
    return 0xDC00 <= x <= 0xDFFF


def has_actual_surrogate(s):
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in s)


def repair_line(line):
    """
    Converts valid UTF-16 surrogate-pair escapes:
      \\uD801\\uDC56
    into scalar Unicode escape:
      \\U00010456

    Drops line if it contains unpaired surrogate escapes.
    """
    if LONG_SURROGATE_RE.search(line) or has_actual_surrogate(line):
        return None, "actual_or_long_surrogate"

    out = []
    i = 0
    changed = False

    while i < len(line):
        if line.startswith("\\u", i) and i + 6 <= len(line):
            hex1 = line[i + 2:i + 6]

            if re.fullmatch(r"[0-9a-fA-F]{4}", hex1):
                cp1 = int(hex1, 16)

                if is_high_surrogate(cp1):
                    # Need immediate low-surrogate escape after it.
                    j = i + 6
                    if line.startswith("\\u", j) and j + 6 <= len(line):
                        hex2 = line[j + 2:j + 6]
                        if re.fullmatch(r"[0-9a-fA-F]{4}", hex2):
                            cp2 = int(hex2, 16)

                            if is_low_surrogate(cp2):
                                scalar = 0x10000 + ((cp1 - 0xD800) << 10) + (cp2 - 0xDC00)
                                out.append(f"\\U{scalar:08X}")
                                i = j + 6
                                changed = True
                                continue

                    return None, f"unpaired_high_surrogate:\\u{hex1}"

                if is_low_surrogate(cp1):
                    return None, f"unpaired_low_surrogate:\\u{hex1}"

        out.append(line[i])
        i += 1

    return "".join(out), "repaired_surrogate_pair" if changed else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--changed-log", required=True)
    parser.add_argument("--dropped-log", required=True)
    parser.add_argument("--progress-every", type=int, default=1_000_000)
    args = parser.parse_args()

    total = kept = changed = dropped = 0

    with Path(args.input).open("r", encoding="utf-8", errors="replace") as fin, \
         Path(args.output).open("w", encoding="utf-8") as fout, \
         Path(args.changed_log).open("w", encoding="utf-8") as fchanged, \
         Path(args.dropped_log).open("w", encoding="utf-8") as fdropped:

        for line_no, line in enumerate(fin, start=1):
            total += 1

            repaired, reason = repair_line(line)

            if repaired is None:
                dropped += 1
                fdropped.write(f"{line_no}\t{reason}\t{line.rstrip()}\n")
            else:
                kept += 1
                fout.write(repaired)

                if reason == "repaired_surrogate_pair":
                    changed += 1
                    fchanged.write(f"{line_no}\t{line.rstrip()}\t=>\t{repaired.rstrip()}\n")

            if total % args.progress_every == 0:
                print(
                    f"lines={total:,} kept={kept:,} changed={changed:,} dropped={dropped:,}",
                    file=sys.stderr,
                    flush=True,
                )

    print(
        f"DONE lines={total:,} kept={kept:,} changed={changed:,} dropped={dropped:,}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()