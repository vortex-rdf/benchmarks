# BSBM adapter

This adapter imports BSBM artifacts. It does not download, build, or run the BSBM generator.

## Generate outside the framework

Use the original BSBM tools in a separate checkout. Put each generated scale under the ignored `BSBM/data/` directory:

```text
BSBM/data/explore-1k/
  dataset.nt
  explore.csv
  generation-receipt.json
  td_data/
```

The receipt must record dataset and stream hashes, stream counts, generator commit, seed, product count, and BSBM use case. Generated assets stay outside Git.

## Import the official Explore stream

```bash
vortex-rdf-bench bsbm prepare \
  --query-stream BSBM/data/explore-1k/explore.csv \
  --generation-receipt BSBM/data/explore-1k/generation-receipt.json \
  --dataset-path BSBM/data/explore-1k/dataset.nt \
  --selection smoke \
  --output BSBM/data/explore-1k/smoke-manifest.json \
  --dataset bsbm-explore-1k \
  --workload bsbm-explore-smoke
```

`smoke` selects the first measured instance of each query template. `full` preserves every stream record. The adapter preserves repeated template IDs, stream positions, and the original warm-up or measured classification.

The query-directory mode remains available through `--query-root` for manually prepared workloads.

## Install and run without KROWN

The standalone unit is the `vortex-rdf-benchmarks` Python distribution. It owns `benchmark_core`, `BSBM`, and `DBBench`. Install it from the repository root. Do not add repository paths to `sys.path`.

```bash
cd /path/to/benchmarks
python -m pip install --editable .
```

Test the installed command from outside the repository and without `PYTHONPATH`:

```bash
cd /tmp
env -u PYTHONPATH vortex-rdf-bench describe
```

Prepare and validate a BSBM smoke manifest:

```bash
BENCHMARKS=/path/to/benchmarks
vortex-rdf-bench bsbm prepare \
  --query-stream "$BENCHMARKS/BSBM/data/explore-1k/explore.csv" \
  --generation-receipt "$BENCHMARKS/BSBM/data/explore-1k/generation-receipt.json" \
  --dataset-path "$BENCHMARKS/BSBM/data/explore-1k/dataset.nt" \
  --selection smoke \
  --output "$BENCHMARKS/BSBM/data/explore-1k/standalone-smoke-manifest.json" \
  --dataset bsbm-explore-1k \
  --workload bsbm-explore-smoke
vortex-rdf-bench manifest validate \
  "$BENCHMARKS/BSBM/data/explore-1k/standalone-smoke-manifest.json"
```

KROWN integration is optional. KROWN can import benchmark-owned manifests and receipts, but BSBM preparation and RDFLib execution do not import or invoke KROWN.

The committed smoke and full declarations do not reference a semantic baseline. KROWN owns its current 11-query smoke baseline and selects it in scenario configuration. Add `semantic_baseline` to a benchmark declaration only when this repository owns the referenced artifact.

## Representation receipts

Create `rdf/source`, `hdt/default`, `cottas/default`, and selected `vortex-rdf/<configuration>` receipts under `BSBM/data/explore-1k/`. Then create one inventory that references them. All receipts must retain the dataset hash from `generation-receipt.json`.

## Generate the HDT representation

An HDT representation is the physical `hdt/default` form of the same logical RDF dataset.
Use the pinned Rust `rdf2hdt` tool, version `0.2.0`:

```bash
cargo install --root BSBM/data/tools/rdf2hdt-0.2.0 --locked --version 0.2.0 rdf2hdt
vortex-rdf-bench bsbm generate-hdt \
  --source BSBM/data/explore-1k/dataset.nt \
  --output BSBM/data/explore-1k/dataset.hdt \
  --rdf-receipt BSBM/data/explore-1k/rdf-source-receipt.json \
  --hdt-receipt BSBM/data/explore-1k/hdt-default-receipt.json \
  --inventory BSBM/data/explore-1k/dataset-inventory.json \
  --rdf2hdt BSBM/data/tools/rdf2hdt-0.2.0/bin/rdf2hdt \
  --source-triple-count 374911
```

The command writes the HDT file atomically. It then records its size, SHA-256 value, producer,
and source RDF identity. The inventory references both `rdf/source` and `hdt/default`.
All generated files remain under the ignored `BSBM/data/` directory.

## Generate the COTTAS representation

A COTTAS representation is the physical `cottas/default` form of the same logical RDF dataset.
Use the pinned Python package `pycottas`, version `1.1.0`, with the `spo` index:

```bash
python -m pip install pycottas==1.1.0
vortex-rdf-bench bsbm generate-cottas \
  --source BSBM/data/explore-1k/dataset.nt \
  --output BSBM/data/explore-1k/dataset.cottas \
  --rdf-receipt BSBM/data/explore-1k/rdf-source-receipt.json \
  --cottas-receipt BSBM/data/explore-1k/cottas-default-receipt.json \
  --inventory BSBM/data/explore-1k/dataset-inventory.json \
  --source-triple-count 374911
```

The command writes the COTTAS file atomically. It verifies the file with `pycottas`.
It then records the file size, SHA-256 value, producer, and source RDF identity.
The inventory preserves existing representations and adds `cottas/default`.
All generated files remain under the ignored `BSBM/data/` directory.

## Generate the bootstrap Vortex-RDF representation

The bootstrap configuration uses the unified native RDF store. It uses a simple dictionary index.
Build the CLI from the pinned Vortex-RDF commit, then generate the artifact:

```bash
VORTEX_RDF=/path/to/vortex-rdf
BENCHMARKS=/path/to/benchmarks
cd "$VORTEX_RDF"
cargo build --release -p vortex-rdf-cli

cd "$BENCHMARKS"
vortex-rdf-bench bsbm generate-vortex-rdf \
  --source BSBM/data/explore-1k/dataset.nt \
  --output BSBM/data/explore-1k/dataset-bootstrap.vortex \
  --rdf-receipt BSBM/data/explore-1k/rdf-source-receipt.json \
  --vortex-receipt BSBM/data/explore-1k/vortex-rdf-bootstrap-receipt.json \
  --inventory BSBM/data/explore-1k/dataset-inventory.json \
  --vortex-cli "$VORTEX_RDF/target/release/vortex-rdf-cli" \
  --vortex-repository "$VORTEX_RDF" \
  --source-triple-count 374911
```

The physical representation identifier is `vortex-rdf/simple-dictionary-native-rdf-store`.
The receipt records the Vortex-RDF commit, release binary hash, index type, storage layout, command, and source identity.
