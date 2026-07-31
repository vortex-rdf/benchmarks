# WDBench — Wikidata Benchmark

> **Status: planned** — no setup or results yet.

[WDBench](https://github.com/MillenniumDB/WDBench) (Angles et al., ISWC 2022)
is a benchmark built from **real Wikidata data and real user queries** taken
from the public Wikidata SPARQL query logs. Like WatDiv it focuses on graph
pattern matching rather than full SPARQL, which makes it highly relevant for
vortex-rdf — but with real-world data skew and at serious scale.

- **Data**: ~1.25 billion triples extracted from the Wikidata truthy dump
  (N-Triples download linked from the WDBench repo).
- **Queries**: thousands of real-log queries, split into four sets —
  single triple patterns, basic graph patterns (multiple triple patterns),
  optionals, and property paths / navigational queries (C2RPQs).
- Related: the smaller, earlier [Wikidata Graph Pattern Benchmark
  (WGPB)](https://zenodo.org/record/4035223) can serve as a lighter-weight
  stepping stone using the same data source.

## Planned setup

1. Download the WDBench data dump and query sets into `WDBench/data/`
   (git-ignored). Consider a truncated slice first — the full 1.25B-triple
   dataset is a serious ingestion test in itself (external merge sort,
   out-of-core builders).
2. Serialize to `.vortex` and comparison-engine artifacts; record ingestion
   time, peak memory, and artifact sizes as a first result set.
3. Run the pattern-matching query sets through the shared rdflib-store
   harness; property-path sets depend on rdflib's path evaluation.
4. Commit curated results to `results/`.
