# BSBM adapter

This folder contains the BSBM adapter. The adapter converts instantiated BSBM SPARQL queries to the common RDF workload manifest.

## Required local files

Do not commit benchmark datasets or generated query instances. Place them at:

```text
BSBM/data/dataset.ttl
BSBM/data/queries/
  query-01.rq
  query-02.rq
  ...
```

`dataset.ttl` can also use `.nt`, `.nq`, or `.trig`. Each file under `queries/` must contain one complete executable query. Use `.rq` or `.sparql`. Do not place parameterized templates there. Instantiate all BSBM parameters first.

The repository `.gitignore` excludes every `data/` directory. The user must obtain or generate these files with the official BSBM tools.

## Prepare a manifest

```bash
vortex-rdf-bench bsbm prepare \
  --query-root BSBM/data/queries \
  --output BSBM/data/bsbm-manifest.json \
  --dataset bsbm-local \
  --workload bsbm-explore
```

## KROWN

Set `KROWN_RDF_DATASET_FILE` to the local dataset file. The KROWN scenario calls this adapter through `benchmark_root=/users/u0182905/benchmarks`. It then uses the generic RDF query resource.
