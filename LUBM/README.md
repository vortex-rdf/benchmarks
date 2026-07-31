# LUBM — Lehigh University Benchmark

> **Status: planned** — no setup or results yet.

[LUBM](http://swat.cse.lehigh.edu/projects/lubm/) (Guo, Pan & Heflin) is one
of the oldest and most cited RDF benchmarks. It models a **university
domain** (universities, departments, professors, students, courses) and was
designed to test OWL **reasoning** as much as raw query performance.

- **Data**: the UBA generator scales by number of universities
  (LUBM(1) ≈ 100K triples, LUBM(1000) ≈ 130M triples).
- **Queries**: 14 fixed SELECT queries; several only return complete answers
  under RDFS/OWL inference (subclass/subproperty hierarchies, transitive
  properties).
- **Caveat for store-only comparisons**: vortex-rdf does no reasoning, so
  either pre-materialize the inferred closure with an external reasoner
  before serialization, or restrict the comparison to the queries answerable
  without inference — and state which variant a result set used.

## Planned setup

1. Generate LUBM data (and optionally its materialized closure) into
   `LUBM/data/` (git-ignored).
2. Serialize to `.vortex` and comparison-engine artifacts.
3. Run the 14 queries through the shared rdflib-store harness.
4. Commit curated results to `results/`.
