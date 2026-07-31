# DBBench: vortex-rdf vs COTTAS over rdflib

Benchmarks vortex-rdf against [pycottas](https://github.com/cottas-rdf/pycottas)
(COTTAS) on the DBBench query workload. Both engines plug into rdflib as a
`Store`, so SPARQL evaluation is rdflib's engine for both — the store serving
triple patterns is the only variable.

## Layout

```
DBBench/
  dbbench_rdflib_benchmark.py        # the benchmark driver
  run_all_dbbench_engines.sh         # per-engine wrapper: logs + manifest
  run_big_dbbench_engines.sh         # full comparison with outer watchdog
  compare_dbbench_counts.py          # result-count equality check
  compare_dbbench_engine_timings.py  # per-query timing comparison + speedups
  utils/
    dbpedia_gen.py                   # slice a DBpedia dump to a target size
    smoke_compare_engines.py         # exact result-set equality smoke test
  data/                              # datasets + artifacts (git-ignored)
  runs/                              # raw run output (git-ignored)
  results/                           # curated, committed results
```

All commands below are given relative to this repository's root.

## Setup

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install vortex-rdflib pycottas psutil

# To benchmark unreleased binding changes instead of the published
# vortex-rdf wheel, build them from a vortex-rdf checkout:
#   cd ../vortex-rdf
#   pip install maturin && maturin develop --release -m python/Cargo.toml
```

## Data and queries (not in this repo)

The query workload is the **k²-Triples DBpedia testbed** — introduced by
Álvarez-García et al., ["Compressed k²-Triples for Full-In-Memory RDF
Engines"](https://arxiv.org/abs/1105.4004) (AMCIS 2011), reused by the
RDFCSA line of work (Brisaboa et al., J. Supercomputing 2023), and by the
COTTAS evaluation ([Arenas-Guerrero & Ferrada, ISWC
2025](https://sferrada.com/publication/2025-iswc-arenas-guerrero-cottas/))
whose DBpedia experiments this benchmark reproduces. Note: despite the
DBpedia focus, this is *not* the "DBpedia SPARQL Benchmark" (DBPSB) of
Morsey et al. — DBPSB uses 25 SELECT templates mined from endpoint logs,
not a TP/JOINS split.

The query tree is still hosted by the DataWeb group (Univ. of Valladolid):

```bash
curl -L https://dataweb.infor.uva.es/queries-k2triples.tgz | tar xz -C DBBench/data
# query root: DBBench/data/queries
```

Its shape (the driver globs `*.txt`, one **SPARQL SELECT per line**):

```
queries/
  TP/<dataset>/*.txt            # e.g. TP/dbpedia/spoSPARQL.txt ("V" in a name = variable)
  JOINS/<dataset>/small/*.txt   # join{SS,SO,OO}_<A..H>_{small,big}.txt:
  JOINS/<dataset>/big/*.txt     #   subject-subject / subject-object / object-object joins
```

Datasets covered: `dbpedia` (used here), plus `dblp`, `geonames`, `jamendo`.
The TP queries mix real queries from the USEWOD 2011 DBpedia query log with
patterns sampled from the dataset; joins pair two triple patterns, split
`small`/`big` by result size. The query constants were extracted from the
**DBpedia 3.5.1** dump, so use that dump (or accept that newer dumps return
empty results for some queries — engine-relative comparisons remain valid
since all engines see the same data).

Suggested local layout (git-ignored): put datasets and artifacts under
`DBBench/data/`.

### Preparing the benchmark artifacts

From a DBpedia N-Triples dump:

```bash
# Optional: slice the dump to a target size
python3 DBBench/utils/dbpedia_gen.py --input dbpedia.nt --limit 5000000 --output dbpedia_5M.nt

# .vortex artifacts (one per layout you want to benchmark),
# using the CLI from a vortex-rdf checkout:
cargo run --release -p vortex-rdf-cli -- serialize \
    -i dbpedia_5M.nt -o dbpedia_5M-dict.vortex --layout dictionary
cargo run --release -p vortex-rdf-cli -- serialize \
    -i dbpedia_5M.nt -o dbpedia_5M-default.vortex --layout default

# .cottas artifact for the comparison engine
python3 -c "import pycottas; pycottas.rdf2cottas('dbpedia_5M.nt', 'dbpedia_5M.cottas')"
```

(`vortex_rdf.serialize_rdf` does the same as the CLI serialize, from Python,
without needing a vortex-rdf checkout.)

## Running

Single invocation (all knobs):

```bash
python3 DBBench/dbbench_rdflib_benchmark.py \
    --query-root <query-root> \
    --engines cottas vortex \
    --cottas-path dbpedia_5M.cottas \
    --vortex-path dbpedia_5M-dict.vortex --vortex-layout dictionary \
    --timeout-mode worker --query-timeout-s 60 \
    --warmup-runs 1 --measured-runs 5 \
    --out-prefix DBBench/runs/dbpedia_dict
```

Per-engine wrapper with logs + manifest:

```bash
DBBench/run_all_dbbench_engines.sh \
    --query-root <query-root> \
    --cottas-path dbpedia_5M.cottas --vortex-path dbpedia_5M-dict.vortex \
    --measured-runs 5 --out-dir DBBench/runs/run1
```

Full comparison (cottas + vortex on dictionary and default layouts, outer
watchdog per configuration):

```bash
DBBench/run_big_dbbench_engines.sh \
    --query-root <query-root> \
    --cottas-path dbpedia_5M.cottas \
    --vortex-dictionary-path dbpedia_5M-dict.vortex \
    --vortex-default-path dbpedia_5M-default.vortex \
    --out-dir DBBench/runs/big1
```

### Timeout modes

- `worker` (recommended): one persistent child process per engine holding a
  warm `Graph`; on timeout the child is hard-killed and lazily restarted.
  Warm-store performance with safe timeouts.
- `process`: a fresh child process and `Graph` per run. Safest isolation, but
  pays the full store-open cost every run.
- `signal`: persistent in-process `Graph` with SIGALRM timeouts. **Cannot
  interrupt a blocking native call** (CPython only runs signal handlers
  between bytecodes), so a stuck query hangs the driver — use the other
  modes for unattended runs.

### BGP pushdown

The vortex engine registers a SPARQL BGP pushdown into rdflib
(joins evaluated in native code space rather than per-binding `triples()`
probes) — active by default and decisive for the JOINS group. Set
`VORTEX_RDF_DISABLE_PUSHDOWN=1` to benchmark the plain rdflib evaluation
path instead.

### File-backed vs in-memory

By default the vortex engine queries the `.vortex` file in place (lazy,
file-backed). Set `VORTEX_RDF_IN_MEMORY=1` to load the store into memory at
open — this removes the ~1 ms per-`triples()`-call file-scan floor, which
dominates JOIN queries (rdflib probes the store once per binding). Report
both modes: file-backed is the fair comparison against pycottas's
file-backed DuckDB engine; in-memory shows the format's ceiling.

### Dictionary residency

For Dictionary-layout stores, terms are served from memory only when the
dictionary fits the residency budget. For large datasets, force residency so
both engines answer from warm state:

```bash
export VORTEX_RDF_DICT_MAX_RESIDENT_TERMS=100000000
```

(Benchmark workers inherit the environment.)

## Outputs

Each run writes `<out-prefix>.queries.json` (inventory), `.raw.json` /
`.raw.csv` (every run: status, elapsed seconds, result count, RSS before /
after / delta), and `.summary.json` / `.summary.csv` (per-query mean /
median / min / max / stdev over the measured OK runs).

Post-processing:

```bash
# Result-count equality between engines (exit 1 on any mismatch)
python3 DBBench/compare_dbbench_counts.py \
    DBBench/runs/run1/dbpedia_cottas.raw.csv DBBench/runs/run1/dbpedia_vortex.raw.csv

# Per-query timing comparison + speedup table
python3 DBBench/compare_dbbench_engine_timings.py \
    --out-dir DBBench/runs/run1 --dataset dbpedia --engines cottas vortex

# Exact result-set equality on the first N TP queries (fresh interpreter per engine)
python3 DBBench/utils/smoke_compare_engines.py \
    --query-root <query-root> \
    --cottas-path dbpedia_5M.cottas --vortex-path dbpedia_5M-dict.vortex
```

## Publishing results

Copy the curated output of a run (manifest, `.summary.*`, the timing
comparison, and a short `RESULTS.md` recording hardware, OS, engine
versions, dataset size, and any environment knobs) into
`DBBench/results/<run-id>/`. Raw per-run files can stay in `runs/` locally;
only committed results are considered citable.
