#!/usr/bin/env python3
from pathlib import Path
import argparse
import re
import sys

IRI_RE = re.compile(r"<([^>\s]+)>")
HTTP_RE = re.compile(r"^https?://", re.IGNORECASE)


def bad_http_port(iri: str):
    """
    Detect http(s) IRIs whose authority has a colon-port component
    that is not purely digits.

    Examples dropped:
      http://www.cbiclubhouse.com:The
      http://www.DOI:0.1111/j.0963-1690.2004.00305.x

    Examples kept:
      http://example.org:8080/path
      http://example.org/path
    """
    if not HTTP_RE.match(iri):
        return False

    rest = iri.split("://", 1)[1]

    # authority ends before / ? #
    authority = re.split(r"[/?#]", rest, maxsplit=1)[0]

    # Ignore no-port case.
    if ":" not in authority:
        return False

    # Ignore IPv6-ish authorities conservatively by dropping only simple host:port.
    # For DBpedia old web URLs this is fine.
    host, port = authority.rsplit(":", 1)

    if port == "":
        return True

    return not port.isdigit()


def should_drop(line: str):
    for m in IRI_RE.finditer(line):
        iri = m.group(1)
        if bad_http_port(iri):
            return True, f"bad_http_authority_port:<{iri}>"

    return False, None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--dropped-log", required=True)
    parser.add_argument("--progress-every", type=int, default=1_000_000)
    args = parser.parse_args()

    total = kept = dropped = 0

    with Path(args.input).open("r", encoding="utf-8", errors="replace") as fin, \
         Path(args.output).open("w", encoding="utf-8") as fout, \
         Path(args.dropped_log).open("w", encoding="utf-8") as flog:

        for line_no, line in enumerate(fin, start=1):
            total += 1

            drop, reason = should_drop(line)

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