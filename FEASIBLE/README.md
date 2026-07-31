# FEASIBLE — Query-Log-Derived Benchmark Generator

> **Status: planned** — no setup or results yet.

[FEASIBLE](https://github.com/dice-group/FEASIBLE) (Saleem et al., AKSW /
DICE group, Leipzig) is not a fixed benchmark but a **benchmark generator**:
it selects a small, maximally representative query set out of a real SPARQL
**query log** by clustering queries on their features (query form, operator
usage, result size, runtime). The published instantiations use the DBpedia
and Semantic Web Dog Food logs; it supersedes the earlier DBpedia SPARQL
Benchmark (DBPSB).

- **Data**: whatever dataset the log belongs to — typically a DBpedia
  release, which pairs naturally with the DBpedia artifacts already used by
  [DBBench](../DBBench/).
- **Queries**: generated benchmark sets (e.g. 15–175 queries) spanning
  SELECT/ASK/CONSTRUCT/DESCRIBE with realistic operator mixes.
- Related from the same group: [IGUANA](https://github.com/dice-group/IGUANA),
  a benchmark *execution* framework usable to drive any of the suites in
  this repo against SPARQL endpoints.

## Planned setup

1. Reuse the DBpedia dataset/artifacts from DBBench, or pin a specific
   DBpedia release into `FEASIBLE/data/` (git-ignored).
2. Take a published FEASIBLE query set (or generate one from the logs).
3. Run through the shared rdflib-store harness; queries that exceed
   rdflib/store capabilities are recorded as unsupported rather than
   silently dropped.
4. Commit curated results to `results/`.
