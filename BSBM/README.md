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

## KROWN

## Representation receipts

Create `rdf/source`, `hdt/default`, `cottas/default`, and selected `vortex-rdf/<configuration>` receipts under `BSBM/data/explore-1k/`. Then create one inventory that references them. All receipts must retain the dataset hash from `generation-receipt.json`.


Set `KROWN_BSBM_QUERY_STREAM`, `KROWN_BSBM_GENERATION_RECEIPT`, and `KROWN_RDF_DATASET_FILE`. KROWN imports and executes the artifacts. It does not generate them.

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
