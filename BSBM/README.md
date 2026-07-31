# BSBM — Berlin SPARQL Benchmark

> **Status: planned** — no setup or results yet.

[BSBM](http://wbsg.informatik.uni-mannheim.de/bizer/berlinsparqlbenchmark/)
(Bizer & Schultz) is a classic SPARQL benchmark built around an
**e-commerce use case**: products with features, vendors, offers, and
reviews. Unlike WatDiv/WDBench it runs *query mixes* that simulate a user
session, and its queries use a broad slice of SPARQL (FILTER, OPTIONAL,
ORDER BY, DESCRIBE, CONSTRUCT, UNION) — so for vortex-rdf it measures the
combined rdflib + store stack rather than pattern matching alone.

- **Data**: generator scales by number of products (e.g. 10K products ≈ 3.5M
  triples; commonly run from 1M to 1B triples).
- **Workloads**: *Explore* (read-only query mix), *Explore-and-Update*, and
  a *Business Intelligence* (analytical) mix.
- **Tooling**: Java data generator + test driver
  ([sourceforge.net/projects/bsbmtools](https://sourceforge.net/projects/bsbmtools/)).
  The stock driver targets a SPARQL endpoint over HTTP, so either front
  vortex-rdf with a minimal endpoint (e.g. rdflib + a SPARQL HTTP wrapper)
  or replay the generated query mixes through the rdflib harness directly.

## Planned setup

1. Generate data at one or more scales into `BSBM/data/` (git-ignored).
2. Serialize to `.vortex` and comparison-engine artifacts.
3. Start with the Explore mix (read-only) replayed through the rdflib
   harness; updates require store write support and can come later.
4. Commit curated results to `results/`.
