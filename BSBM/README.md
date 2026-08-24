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

Set `KROWN_BSBM_QUERY_STREAM`, `KROWN_BSBM_GENERATION_RECEIPT`, and `KROWN_RDF_DATASET_FILE`. KROWN imports and executes the artifacts. It does not generate them.
