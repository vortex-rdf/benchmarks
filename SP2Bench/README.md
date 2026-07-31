# SP²Bench — SPARQL Performance Benchmark

> **Status: planned** — no setup or results yet.

[SP²Bench](http://dbis.informatik.uni-freiburg.de/index.php?project=SP2B)
(Schmidt et al., University of Freiburg) generates synthetic data mirroring
the structure and distributions of the **DBLP** bibliography, and pairs it
with queries deliberately designed to stress **SPARQL operator
combinations**: long join chains, OPTIONAL, FILTER (including negation via
bound checks), UNION, DISTINCT, and ORDER BY.

- **Data**: arbitrary-size DBLP-like RDF via the sp2b generator.
- **Queries**: 12 SELECT/ASK queries with well-understood complexity
  characteristics; some are intentionally expensive (e.g. Q4's cross-join
  filter) and commonly run with timeouts.
- For vortex-rdf this measures the rdflib + store stack; the interesting
  signal is how much the BGP pushdown absorbs of the operator-heavy plans.

## Planned setup

1. Build the sp2b generator; generate data at a few sizes (e.g. 1M, 5M, 25M
   triples) into `SP2Bench/data/` (git-ignored).
2. Serialize to `.vortex` and comparison-engine artifacts.
3. Run the query set through the shared rdflib-store harness with per-query
   timeouts (the DBBench driver's worker timeout mode fits directly).
4. Commit curated results to `results/`.
