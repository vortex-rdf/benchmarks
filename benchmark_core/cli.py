"""Public command-line interface."""
from __future__ import annotations
import argparse
import json
import sys
from benchmark_core import MANIFEST_SCHEMA_VERSION, RESULT_SCHEMA_VERSION, __version__
from benchmark_core.manifest import load_manifest
from benchmark_core.result import load_results

EXIT_SUCCESS = 0
EXIT_VALIDATION = 2
EXIT_IO = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vortex-rdf-bench")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("describe")
    manifest = commands.add_parser("manifest")
    manifest_commands = manifest.add_subparsers(dest="manifest_command", required=True)
    manifest_validate = manifest_commands.add_parser("validate")
    manifest_validate.add_argument("path")
    results = commands.add_parser("results")
    result_commands = results.add_subparsers(dest="results_command", required=True)
    results_validate = result_commands.add_parser("validate")
    results_validate.add_argument("path")
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "describe":
            print(json.dumps({
                "tool": "vortex-rdf-bench", "version": __version__,
                "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "commands": ["describe", "manifest validate", "results validate"],
            }, sort_keys=True))
            return EXIT_SUCCESS
        if args.command == "manifest":
            value = load_manifest(args.path)
            print(json.dumps({"valid": True, "queries": len(value["queries"])}, sort_keys=True))
            return EXIT_SUCCESS
        records = load_results(args.path)
        print(json.dumps({"valid": True, "records": len(records)}, sort_keys=True))
        return EXIT_SUCCESS
    except (OSError, json.JSONDecodeError) as error:
        print(f"I/O error: {error}", file=sys.stderr)
        return EXIT_IO
    except (TypeError, ValueError) as error:
        print(f"Validation error: {error}", file=sys.stderr)
        return EXIT_VALIDATION


if __name__ == "__main__":
    raise SystemExit(main())
