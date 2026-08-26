# vortex-rdf benchmarks

Collection of benchmark setups and results measuring
[vortex-rdf](https://github.com/vortex-rdf/vortex-rdf) — a columnar RDF
serialization and queryable store built on the
[Vortex](https://docs.vortex.dev) data format — against other RDF stores and
serializations.

## Methodology

Wherever possible, engines are compared as **rdflib `Store` plugins**
(vortex-rdflib, pycottas/COTTAS, and candidates such as
[oxrdflib](https://github.com/oxigraph/oxrdflib)/Oxigraph and
[rdflib-hdt](https://github.com/RDFLib/rdflib-hdt)/HDT): SPARQL evaluation
is rdflib's engine for every contender, so the store serving triple patterns
is the only variable. Benchmarks whose workloads go beyond pattern matching
(full SPARQL mixes, updates) measure the combined rdflib + store stack, and
say so in their READMEs.

## Benchmarks

| Benchmark | Workload | Status |
|---|---|---|
| [DBBench](DBBench/) | DBpedia triple-pattern + join workload from the pycottas experiments | **runnable** (migrated from `vortex-rdf/scripts/DBBench`) |
| [WatDiv](WatDiv/) | Synthetic, structurally diverse BGPs (linear/star/snowflake/complex) | planned |
| [WDBench](WDBench/) | Real Wikidata data (~1.25B triples) + real query-log patterns and paths | planned |
| [BSBM](BSBM/) | E-commerce query mixes; broad SPARQL feature coverage | **adapter ready** |
| [LUBM](LUBM/) | University domain; classic 14-query set, inference-oriented | planned |
| [SP2Bench](SP2Bench/) | DBLP-like data; SPARQL operator-combination stress queries | planned |
| [FEASIBLE](FEASIBLE/) | Representative query sets mined from real DBpedia query logs | planned |
| [LDBC-SPB](LDBC-SPB/) | Media/publishing workload over named graphs (quads), updates + analytics | planned |

Other suites worth knowing about, currently out of scope: **FedBench** and
**LargeRDFBench** (federated SPARQL over multiple endpoints — not a store
comparison), and **DBPSB** (superseded by FEASIBLE). The
[IGUANA](https://github.com/dice-group/IGUANA) framework can drive several
of the above against SPARQL endpoints if an endpoint-based comparison is
ever needed.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the enforced boundary between external generators, benchmark adapters, and KROWN.

## Repository conventions

Physical RDF forms use strict `rdf-representation-receipt-v1` receipts. One `rdf-dataset-inventory-v1` file can reference several receipts only when all receipts record the same source RDF identity. Generated files and receipts stay under ignored `data/` directories. KROWN verifies them but does not generate them.


Each benchmark folder is self-contained:

```
<Benchmark>/
  README.md    # what it measures + how to set up, run, and reproduce
  data/        # datasets and engine artifacts — git-ignored, obtained/built per README
  runs/        # raw run output — git-ignored
  results/     # curated, committed results: one subfolder per published run
```

A committed result under `results/<run-id>/` must include the run manifest
and summary files plus a short `RESULTS.md` recording hardware, OS, engine
versions, dataset and scale, and any environment knobs — enough to reproduce
the run from the benchmark README alone.

## Experiment declarations

Benchmark-owned experiment intent is stored under `<Benchmark>/experiments/`. The versioned `rdf-experiment-declaration-v1` contract binds a logical workload to representation receipts, system identities, an execution policy, and a semantic baseline reference. KROWN reads this declaration and owns runtime orchestration.
