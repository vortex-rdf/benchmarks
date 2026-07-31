# LDBC SPB — Semantic Publishing Benchmark

> **Status: planned** — no setup or results yet.

The [LDBC Semantic Publishing Benchmark](https://ldbcouncil.org/benchmarks/spb/)
models a **media/publishing workload** inspired by the BBC's Dynamic
Semantic Publishing: creative works annotated against reference taxonomies,
stored across **named graphs**, with concurrent editorial (INSERT/UPDATE)
and aggregation (analytical query) agents.

- **Data**: generator produces scalable datasets (commonly 64M / 256M / 1B
  triples) making heavy use of quads — a good fit for exercising
  vortex-rdf's native graph column and quad support.
- **Workloads**: *editorial* (updates) and *aggregation* (queries) run
  concurrently; throughput-oriented rather than per-query latency.
- **Tooling**: [github.com/ldbc/ldbc_spb_bm_2.0](https://github.com/ldbc/ldbc_spb_bm_2.0)
  (Java driver targeting a SPARQL endpoint).
- **Caveat**: the concurrent-update workload assumes a transactional SPARQL
  store; for vortex-rdf, the realistic near-term subset is the aggregation
  query mix over a pre-built dataset, plus bulk-ingestion metrics.

## Planned setup

1. Generate an SPB dataset into `LDBC-SPB/data/` (git-ignored).
2. Serialize to `.vortex` (quads preserved) and comparison-engine artifacts;
   record ingestion time and artifact sizes.
3. Run the aggregation query mix through the shared rdflib-store harness.
4. Commit curated results to `results/`.
