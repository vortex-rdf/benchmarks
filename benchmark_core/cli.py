"""Public command-line interface."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from DBBench.execution import run as run_dbbench
from DBBench.manifest import prepare as prepare_dbbench
from DBBench.schedule import records_sha256, write_schedule
from benchmark_core.http_runner.campaign import run_declaration
from benchmark_core.http_runner.report import format_report
from BSBM.execution import run as run_bsbm
from BSBM.manifest import prepare as prepare_bsbm
from BSBM.hdt import generate as generate_bsbm_hdt
from BSBM.cottas import generate as generate_bsbm_cottas
from BSBM.vortex_rdf import generate as generate_bsbm_vortex_rdf
from WatDiv.execution import run as run_watdiv
from WatDiv.manifest import DATASET_DECLARATIONS, prepare as prepare_watdiv
from WatDiv.representations import (
    REPRESENTATION_TYPES,
    build as build_watdiv_representation,
    inspect as inspect_watdiv_representation,
    validate as validate_watdiv_representation,
)
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
    bsbm_hdt = bsbm_commands.add_parser("generate-hdt")
    for option in ("source", "output", "rdf-receipt", "hdt-receipt", "inventory", "rdf2hdt"):
        bsbm_hdt.add_argument(f"--{option}", required=True)
    bsbm_hdt.add_argument("--source-triple-count", type=int, required=True)
    bsbm_cottas = bsbm_commands.add_parser("generate-cottas")
    for option in ("source", "output", "rdf-receipt", "cottas-receipt", "inventory"):
        bsbm_cottas.add_argument(f"--{option}", required=True)
    bsbm_cottas.add_argument("--source-triple-count", type=int, required=True)
    bsbm_vortex = bsbm_commands.add_parser("generate-vortex-rdf")
    for option in ("source", "output", "rdf-receipt", "vortex-receipt", "inventory", "vortex-cli", "vortex-repository"):
        bsbm_vortex.add_argument(f"--{option}", required=True)
    bsbm_vortex.add_argument("--source-triple-count", type=int, required=True)
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
    watdiv = commands.add_parser("watdiv")
    watdiv_commands = watdiv.add_subparsers(dest="watdiv_command", required=True)
    watdiv_prepare = watdiv_commands.add_parser("prepare")
    watdiv_prepare.add_argument("--dataset", required=True,
        choices=tuple(DATASET_DECLARATIONS))
    watdiv_prepare.add_argument("--output", required=True)
    watdiv_prepare.add_argument("--dataset-path")
    watdiv_prepare.add_argument("--workload-root")
    watdiv_prepare.add_argument("--workload")
    watdiv_prepare.add_argument("--expected-count", type=int, default=12400)
    watdiv_representation = watdiv_commands.add_parser("representation")
    watdiv_representation_commands = watdiv_representation.add_subparsers(
        dest="watdiv_representation_command", required=True
    )
    for command_name in ("build", "validate", "inspect"):
        command = watdiv_representation_commands.add_parser(command_name)
        command.add_argument("--dataset", required=True, choices=tuple(DATASET_DECLARATIONS))
        command.add_argument("--representation", required=True, choices=REPRESENTATION_TYPES)
        command.add_argument("--output-root")
        if command_name == "build":
            command.add_argument("--force", action="store_true")
            command.add_argument("--source-path")
            command.add_argument("--rdf2hdt")
            command.add_argument("--hdt-index-python")
            command.add_argument("--vortex-cli")
            command.add_argument("--vortex-repository")
            command.add_argument("--log-dir")
    run_command = watdiv_commands.add_parser("run")
    run_command.add_argument("--manifest", required=True)
    run_command.add_argument("--dataset-path", required=True)
    run_command.add_argument("--output", required=True)
    run_command.add_argument("--experiment-id", required=True)
    run_command.add_argument("--warmup-runs", type=int, default=1)
    run_command.add_argument("--measured-runs", type=int, default=5)
    run_command.add_argument("--timeout-s", type=float, default=60.0)
    run_command.add_argument("--resume", action="store_true")
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
    schedule = dbbench_commands.add_parser("schedule", help="expand a prepared manifest into the phased TP3 schedule")
    schedule.add_argument("--base", required=True, help="manifest written by `dbbench prepare`")
    schedule.add_argument("--invalid", required=True, help="invalid-query inventory (DBBench/invalid-queries.json)")
    schedule.add_argument("--output", required=True)
    schedule.add_argument("--tp-passes", type=int, default=3)
    run_command = dbbench_commands.add_parser("run")
    run_command.add_argument("--manifest", required=True)
    run_command.add_argument("--dataset-path", required=True)
    run_command.add_argument("--output", required=True)
    run_command.add_argument("--experiment-id", required=True)
    run_command.add_argument("--warmup-runs", type=int, default=1)
    run_command.add_argument("--measured-runs", type=int, default=5)
    run_command.add_argument("--timeout-s", type=float, default=60.0)
    run_command.add_argument("--resume", action="store_true")
    http_run = commands.add_parser("run", help="run a declaration against server systems over SPARQL HTTP")
    http_run.add_argument("--declaration", required=True)
    http_run.add_argument("--benchmark-root", required=True, help="directory the declaration's relative paths resolve against")
    http_run.add_argument("--manifest", required=True, help="query manifest (BSBM prepare / DBBench schedule output)")
    http_run.add_argument("--system", action="append", default=[], help="system id; repeat; default: all declared")
    http_run.add_argument("--output-root", required=True)
    http_run.add_argument("--store-root", required=True, help="where persistent server stores are built and kept")
    http_run.add_argument("--timeout-s", type=float, help="per-query limit; default from the declaration")
    http_run.add_argument("--correctness", choices=["auto", "fingerprint", "count-only"], default="auto")
    http_run.add_argument("--quarantine-threshold", type=int, default=3,
                          help="measured timeouts per query template before the template is skipped (0 disables)")
    http_run.add_argument("--max-wall-s", type=float, default=0.0, help="stop a system after this wall time (0 disables)")
    http_run.add_argument("--no-drop-caches", action="store_true", help="do not drop the page cache before each system")
    http_run.add_argument("--experiment-id")
    report = commands.add_parser("report", help="summarize the systems of one run directory")
    report.add_argument("run_dir", help="<output-root>/<experiment> written by `vortex-rdf-bench run`")
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
        if args.command == "bsbm" and args.bsbm_command == "generate-hdt":
            value = generate_bsbm_hdt(source=Path(args.source), output=Path(args.output),
                rdf_receipt=Path(args.rdf_receipt), hdt_receipt=Path(args.hdt_receipt),
                inventory=Path(args.inventory), rdf2hdt=Path(args.rdf2hdt),
                source_triple_count=args.source_triple_count)
            print(json.dumps({"written": args.output, "representation": value["representation"]}, sort_keys=True))
            return EXIT_SUCCESS
        if args.command == "bsbm" and args.bsbm_command == "generate-cottas":
            value = generate_bsbm_cottas(source=Path(args.source), output=Path(args.output),
                rdf_receipt=Path(args.rdf_receipt), cottas_receipt=Path(args.cottas_receipt),
                inventory=Path(args.inventory), source_triple_count=args.source_triple_count)
            print(json.dumps({"written": args.output, "representation": value["representation"]}, sort_keys=True))
            return EXIT_SUCCESS
        if args.command == "bsbm" and args.bsbm_command == "generate-vortex-rdf":
            value = generate_bsbm_vortex_rdf(source=Path(args.source), output=Path(args.output),
                rdf_receipt=Path(args.rdf_receipt), vortex_receipt=Path(args.vortex_receipt),
                inventory=Path(args.inventory), vortex_cli=Path(args.vortex_cli),
                vortex_repository=Path(args.vortex_repository), source_triple_count=args.source_triple_count)
            print(json.dumps({"written": args.output, "representation": value["representation"]}, sort_keys=True))
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
        if args.command == "watdiv" and args.watdiv_command == "prepare":
            manifest = prepare_watdiv(
                output=Path(args.output),
                dataset=args.dataset,
                dataset_path=Path(args.dataset_path) if args.dataset_path else None,
                workload_root=Path(args.workload_root) if args.workload_root else None,
                workload=args.workload,
                expected_count=args.expected_count,
            )
            print(json.dumps({"written": args.output, "queries": len(manifest["queries"])}, sort_keys=True))
            return EXIT_SUCCESS
        if args.command == "watdiv" and args.watdiv_command == "run":
            records = run_watdiv(
                manifest_path=Path(args.manifest),
                dataset_path=Path(args.dataset_path),
                output=Path(args.output),
                experiment_id=args.experiment_id,
                warmup_runs=args.warmup_runs,
                measured_runs=args.measured_runs,
                timeout_s=args.timeout_s,
                resume=args.resume,
            )
            print(json.dumps({"records": len(records), "written": args.output}, sort_keys=True))
            return EXIT_SUCCESS
        if args.command == "watdiv" and args.watdiv_command == "representation":
            if args.watdiv_representation_command == "inspect":
                value = inspect_watdiv_representation(
                    args.dataset, args.representation, args.output_root
                )
            elif args.watdiv_representation_command == "validate":
                value = validate_watdiv_representation(
                    args.dataset, args.representation, args.output_root
                )
            else:
                value = build_watdiv_representation(
                    dataset=args.dataset,
                    representation=args.representation,
                    output_root=args.output_root,
                    force=args.force,
                    source_path=args.source_path,
                    rdf2hdt=args.rdf2hdt,
                    hdt_index_python=args.hdt_index_python,
                    vortex_cli=args.vortex_cli,
                    vortex_repository=args.vortex_repository,
                    log_dir=args.log_dir,
                )
            print(json.dumps(value, sort_keys=True))
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
        if args.command == "report":
            print(format_report(Path(args.run_dir)))
            return EXIT_SUCCESS
        if args.command == "run":
            outcome = run_declaration(
                declaration=Path(args.declaration), benchmark_root=Path(args.benchmark_root),
                manifest_path=Path(args.manifest), systems=args.system, output_root=Path(args.output_root),
                store_root=Path(args.store_root), timeout_s=args.timeout_s, correctness=args.correctness,
                quarantine_threshold=args.quarantine_threshold, max_wall_s=args.max_wall_s,
                drop_caches=not args.no_drop_caches, experiment_id=args.experiment_id)
            print(json.dumps(outcome, sort_keys=True, default=str))
            return EXIT_SUCCESS
        if args.command == "dbbench" and args.dbbench_command == "schedule":
            manifest = write_schedule(base=Path(args.base), invalid=Path(args.invalid),
                                      output=Path(args.output), tp_passes=args.tp_passes)
            print(json.dumps({"written": args.output, "queries": len(manifest["queries"]),
                              "records_sha256": records_sha256(manifest)}, sort_keys=True))
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
