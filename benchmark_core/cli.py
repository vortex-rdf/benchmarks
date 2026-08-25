"""Public command-line interface."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from DBBench.execution import run as run_dbbench
from DBBench.manifest import prepare as prepare_dbbench
from BSBM.execution import run as run_bsbm
from BSBM.manifest import prepare as prepare_bsbm
from benchmark_core import MANIFEST_SCHEMA_VERSION, RESULT_SCHEMA_VERSION, __version__
from benchmark_core.manifest import load_manifest
from benchmark_core.result import load_results
from benchmark_core.representation import create_inventory, create_receipt, load_receipt

EXIT_SUCCESS = 0
EXIT_VALIDATION = 2
EXIT_IO = 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vortex-rdf-bench")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("describe")
    representation = commands.add_parser("representation")
    representation_commands = representation.add_subparsers(dest="representation_command", required=True)
    verify_receipt = representation_commands.add_parser("verify-receipt")
    verify_receipt.add_argument("path")
    inventory = representation_commands.add_parser("create-inventory")
    inventory.add_argument("--output", required=True); inventory.add_argument("--benchmark", required=True)
    inventory.add_argument("--dataset", required=True); inventory.add_argument("--receipt", action="append", required=True)
    bsbm = commands.add_parser("bsbm")
    bsbm_commands = bsbm.add_subparsers(dest="bsbm_command", required=True)
    bsbm_prepare = bsbm_commands.add_parser("prepare")
    bsbm_source = bsbm_prepare.add_mutually_exclusive_group(required=True)
    bsbm_source.add_argument("--query-root")
    bsbm_source.add_argument("--query-stream")
    bsbm_prepare.add_argument("--generation-receipt")
    bsbm_prepare.add_argument("--dataset-path")
    bsbm_prepare.add_argument("--selection", choices=("smoke", "full"), default="smoke")
    bsbm_prepare.add_argument("--output", required=True)
    bsbm_prepare.add_argument("--workload", default="bsbm-explore")
    bsbm_prepare.add_argument("--dataset", required=True)
    bsbm_run = bsbm_commands.add_parser("run")
    bsbm_run.add_argument("--manifest", required=True)
    bsbm_run.add_argument("--dataset-path", required=True)
    bsbm_run.add_argument("--output", required=True)
    bsbm_run.add_argument("--experiment-id", required=True)
    bsbm_run.add_argument("--warmup-runs", type=int, default=1)
    bsbm_run.add_argument("--measured-runs", type=int, default=5)
    bsbm_run.add_argument("--timeout-s", type=float, default=60.0)
    bsbm_run.add_argument("--resume", action="store_true")
    dbbench = commands.add_parser("dbbench")
    dbbench_commands = dbbench.add_subparsers(dest="dbbench_command", required=True)
    prepare = dbbench_commands.add_parser("prepare")
    source = prepare.add_mutually_exclusive_group(required=True)
    source.add_argument("--inventory")
    source.add_argument("--query-root")
    prepare.add_argument("--output", required=True)
    prepare.add_argument("--workload", default="dbbench-tp-joins")
    prepare.add_argument("--dataset", required=True)
    prepare.add_argument("--groups", nargs="+", default=["TP", "JOINS"])
    prepare.add_argument("--join-sizes", nargs="+", default=["small", "big"])
    prepare.add_argument("--query-id-file")
    run_command = dbbench_commands.add_parser("run")
    run_command.add_argument("--manifest", required=True)
    run_command.add_argument("--dataset-path", required=True)
    run_command.add_argument("--output", required=True)
    run_command.add_argument("--experiment-id", required=True)
    run_command.add_argument("--warmup-runs", type=int, default=1)
    run_command.add_argument("--measured-runs", type=int, default=5)
    run_command.add_argument("--timeout-s", type=float, default=60.0)
    run_command.add_argument("--resume", action="store_true")
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
        if args.command == "representation" and args.representation_command == "verify-receipt":
            value = load_receipt(Path(args.path)); print(json.dumps({"valid": True, "representation": value["representation"]}, sort_keys=True)); return EXIT_SUCCESS
        if args.command == "representation":
            value = create_inventory(inventory_path=Path(args.output), benchmark=args.benchmark, dataset=args.dataset, receipt_paths=args.receipt)
            print(json.dumps({"written": args.output, "representations": len(value["representations"])}, sort_keys=True)); return EXIT_SUCCESS
        if args.command == "describe":
            print(json.dumps({
                "tool": "vortex-rdf-bench", "version": __version__,
                "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
                "result_schema_version": RESULT_SCHEMA_VERSION,
                "commands": ["describe", "manifest validate", "results validate"],
            }, sort_keys=True))
            return EXIT_SUCCESS
        if args.command == "bsbm" and args.bsbm_command == "run":
            records = run_bsbm(
                manifest_path=Path(args.manifest), dataset_path=Path(args.dataset_path),
                output=Path(args.output), experiment_id=args.experiment_id,
                warmup_runs=args.warmup_runs, measured_runs=args.measured_runs,
                timeout_s=args.timeout_s, resume=args.resume,
            )
            print(json.dumps({"records": len(records), "written": args.output}, sort_keys=True))
            return EXIT_SUCCESS
        if args.command == "bsbm":
            manifest = prepare_bsbm(
                query_root=Path(args.query_root) if args.query_root else None,
                query_stream=Path(args.query_stream) if args.query_stream else None,
                generation_receipt=(Path(args.generation_receipt) if args.generation_receipt else None),
                dataset_path=Path(args.dataset_path) if args.dataset_path else None,
                selection=args.selection, output=Path(args.output),
                workload=args.workload, dataset=args.dataset,
            )
            print(json.dumps({"written": args.output, "queries": len(manifest["queries"])}, sort_keys=True))
            return EXIT_SUCCESS
        if args.command == "dbbench" and args.dbbench_command == "run":
            records = run_dbbench(
                manifest_path=Path(args.manifest), dataset_path=Path(args.dataset_path),
                output=Path(args.output), experiment_id=args.experiment_id,
                warmup_runs=args.warmup_runs, measured_runs=args.measured_runs,
                timeout_s=args.timeout_s, resume=args.resume,
            )
            print(json.dumps({"records": len(records), "written": args.output}, sort_keys=True))
            return EXIT_SUCCESS
        if args.command == "dbbench":
            manifest = prepare_dbbench(
                output=Path(args.output), workload=args.workload,
                dataset=args.dataset,
                inventory=Path(args.inventory) if args.inventory else None,
                query_root=Path(args.query_root) if args.query_root else None,
                groups=args.groups, join_sizes=args.join_sizes,
                query_id_file=(Path(args.query_id_file)
                               if args.query_id_file else None),
            )
            print(json.dumps({"written": args.output,
                              "queries": len(manifest["queries"])},
                             sort_keys=True))
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
