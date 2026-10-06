# Reproducing the paper benchmarks (BSBM and DBpedia)

This guide takes you from a fresh clone to benchmark numbers for **Vortex-RDF** (and, if you want, the
13 other systems of the paper), measured with one protocol: every system answers SPARQL over HTTP.

* [Quick start: test Vortex on BSBM 10K](#quick-start-test-vortex-on-bsbm-10k) (about 30 minutes of work)
* [Testing another vortex-rdflib version, or an ablation](#testing-another-vortex-rdflib-version-or-an-ablation)
* [BSBM 100K and DBpedia](#bsbm-100k-and-dbpedia)
* [Reproducing all 14 systems](#reproducing-all-14-systems)
* [What is measured](#what-is-measured-the-protocol) · [Troubleshooting](#troubleshooting)

> **Status.** The HTTP runner described here is new. Earlier paper numbers were measured with embedded
> (in-process) workers for the rdflib-based systems; the HTTP campaign that replaces them has not been
> published yet. Until it is, expect HTTP latencies to be a little higher than the embedded numbers
> (one local HTTP round trip plus result serialization are now inside the timer).

## 1. Requirements

| | |
|---|---|
| OS | Linux x86-64 with **cgroup v2** (memory is read from the containers' cgroups) |
| Docker | a recent Docker Engine; your user must be able to run `docker` without sudo |
| Python | 3.11 or newer (the paper used 3.13) |
| Git, curl | yes |
| Rust (`cargo`) | to build the `vortex-rdf-cli` that writes `.vortex` stores (stable toolchain) |
| RAM | the paper machine had 62 GiB; every server container is limited to **58 GiB** (`VORTEX_RDF_BENCH_MEMORY_GIB` lowers it, but then numbers are not comparable with the paper) |
| CPU | 6 cores on the paper machine |
| Disk | BSBM 10K: ~2 GB. BSBM 100K: ~15 GB. DBpedia: ~50 GB of inputs and representations, ~100 GB more while cleaning, and 30-45 GB per server store if you run the full comparison |
| sudo (optional) | `sudo -n sysctl vm.drop_caches=3` without a password, to start every system with a cold page cache. Without it pass `--no-drop-caches` (results are then warmer) |

Everything is run **one system at a time**. Do not run anything else heavy on the machine while measuring.

## 2. Install

```bash
git clone https://github.com/vortex-rdf/benchmarks.git
cd benchmarks
python3 -m venv .venv && . .venv/bin/activate     # on Debian/Ubuntu: apt install python3-venv, or use `uv venv .venv`
pip install -e ".[vortex]"          # use an editable install: the Dockerfiles in docker/ are found relative to the repo
vortex-rdf-bench describe           # prints the available commands
```

All data and artifacts go under the git-ignored `*/data/` directories of this repository. Server images
are **built locally from `docker/`** on first use (they are not published on a registry); every download
in them is pinned by checksum or digest.

## Quick start: test Vortex on BSBM 10K

This builds the BSBM 10K inputs, writes the Vortex-RDF stores, starts one container per Vortex
configuration and measures all 13,750 queries (1,250 warm-up + 12,500 measured) of the official Explore stream.

**Step 1: generate the dataset and query stream** (about 2 minutes, needs Docker; no Java on the host)

```bash
BSBM/tools/generate.sh 10000
```

This writes `BSBM/data/explore-10k/{dataset.nt, explore.csv, generation-receipt.json}` and checks them
against the paper's hashes in `BSBM/checksums.json` (3,421,251 triples). The generator, JVM image and
time zone are pinned: the generator derives dates from the JVM time zone, so a different zone changes
the dataset (and its hash).

**Step 2: build the Vortex-RDF CLI at the commit the paper's stores were written with**

```bash
git clone https://github.com/vortex-rdf/vortex-rdf.git ../vortex-rdf
git -C ../vortex-rdf checkout 5623c36        # v0.10.0 plus three JavaScript dependency updates
export VORTEX_RDF_REPO="$PWD/../vortex-rdf"
(cd "$VORTEX_RDF_REPO" && cargo build --release -p vortex-rdf-cli)
```

The `.vortex` file format is read by both vortex-rdf 0.10 and 0.11, so stores built here can be queried
with vortex-rdflib 0.1.x and 0.2.x. Using a newer CLI writes different stores (0.11 changes the column
encodings), which is a legitimate experiment but no longer the paper's input.

**Step 3: write the Vortex stores** (two layouts; about 20 seconds each at 10K, about 3 minutes each at 100K)

```bash
python run_bsbm_10k_representation_builds_v1.py --triple-count 3421251 --only vortex
```

This creates `dataset-dictionary-secondary-by-copy.vortex` and `...-by-reference.vortex` next to the
dataset, the receipts that bind them to the dataset hash, and `dataset-inventory.json`. (Without
`--only vortex` it also builds HDT and COTTAS; see [Reproducing all 14 systems](#reproducing-all-14-systems).)

**Step 4: prepare the query manifest**

```bash
D=BSBM/data/explore-10k
vortex-rdf-bench bsbm prepare --query-stream $D/explore.csv \
  --generation-receipt $D/generation-receipt.json --dataset-path $D/dataset.nt \
  --selection full --output $D/full-manifest.json \
  --dataset bsbm-explore-10k --workload bsbm-explore-10k-full
```

> **Quick sanity check first.** `--selection smoke` instead of `--selection full` (and `smoke-manifest.json`
> as the manifest in step 5) selects 11 queries, one per template. The whole run, steps 4 to 6, takes about a
> minute once the image is built. It is a pipeline check, not a measurement.

**Step 5: run the four Vortex configurations over HTTP**

```bash
vortex-rdf-bench run \
  --declaration BSBM/experiments/explore-10k-full.json --benchmark-root BSBM \
  --manifest BSBM/data/explore-10k/full-manifest.json \
  --system vortex-rdf/dictionary-secondary-by-copy        --system vortex-rdf/dictionary-secondary-by-copy-memory \
  --system vortex-rdf/dictionary-secondary-by-reference   --system vortex-rdf/dictionary-secondary-by-reference-memory \
  --output-root runs --store-root stores
```

The first run builds the endpoint image `vortex-rdf-bench/rdflib-endpoint:vrl-0.1.3` (about 4 minutes).
Add `--no-drop-caches` if you cannot use sudo. Progress is printed one line per query
(`RDF_PROGRESS ...`); redirect it to a file for long runs.

The four systems are Vortex-RDF with the *secondary index by copy* or *by reference*, each opened
**file-backed** (the file is read in place) or **in memory** (`-memory`).

**Step 6: read the results**

```bash
vortex-rdf-bench report runs/bsbm-explore-10k-explore-full
```

prints one row per system (successes, timeouts, errors, skipped attempts, mean/median/p95 latency in ms,
peak container memory, start-to-ready time) and the mean latency per BSBM query template. The full
per-attempt records are in `runs/<experiment>/<system>/results.jsonl` and run metadata (image digests,
package versions, repository revision, resource limits, memory per phase) in `results.summary.json`.

## Testing another vortex-rdflib version, or an ablation

The vortex-rdflib version is a property of the endpoint image:

```bash
VORTEX_RDFLIB_VERSION=0.2.0 vortex-rdf-bench run ...        # builds vrl-0.2.0 (with vortex-rdf 0.11.0) on first use
```

`0.1.x` pairs with vortex-rdf 0.10.0 and `0.2.x` with 0.11.0; for other versions set `VORTEX_RDF_VERSION`.
A different image name can be forced with `VORTEX_RDFLIB_IMAGE`. The version actually served is recorded
in `results.summary.json` (`server_extra.identity`).

* **Pushdown ablation.** Append `-no-pushdown` to a Vortex system id
  (`vortex-rdf/dictionary-secondary-by-copy-memory-no-pushdown`). The endpoint then starts with
  `VORTEX_RDF_DISABLE_PUSHDOWN=1`: rdflib's own evaluator runs over the same store, layout and dictionary,
  so the difference to the plain system is exactly the custom SPARQL pushdown. The server refuses to start
  if the hook state differs from the requested one. These ids are not in the committed declarations; add
  bindings to a copy of the declaration (the representation is the same as for the plain system).
* **Tuning variables.** `VORTEX_RDF_NATIVE_FILTERS`, `VORTEX_RDF_FILTER_FAST`, `VORTEX_RDF_DISABLE_CODE_PATH`,
  `VORTEX_RDF_DICT_MAX_RESIDENT_BYTES` and `VORTEX_RDF_PUSHDOWN_OPS` set in your shell are passed into the
  container and recorded in the run summary.
* **A development checkout of vortex-rdflib.** Build the image from your tree instead of PyPI: copy your
  wheel into `docker/rdflib-endpoint/`, change the `pip install vortex-rdflib==...` line of the Dockerfile
  and tag the image yourself; select it with `VORTEX_RDFLIB_IMAGE`.

## BSBM 100K and DBpedia

**BSBM 100K** is the same procedure with `BSBM/tools/generate.sh 100000` (a 9 GB dataset and a stream run against a 35-million-triple
Oxigraph; `generate.sh` has been verified for 10K but not yet regenerated for 100K, whose receipt predates the pins),
`run_bsbm_100k_representation_builds_v1.py --triple-count 35159904 --only vortex`, a manifest from
`BSBM/data/explore-100k/` (`--dataset bsbm-explore-100k --workload bsbm-explore-100k-full`) and the
declaration `BSBM/experiments/explore-100k-full.json`. Queries time out after 10 s; after three timeouts
of one query template the remaining attempts of that template are recorded as `skipped` (default
`--quarantine-threshold 3`). Pass `--max-wall-s 19800` to stop a system after 5.5 hours, as the paper did.

**DBpedia** (232,541,923 triples, 35.6 GB of N-Triples) in four steps. These commands are in place but have
not yet been run end to end by a clean checkout.

1. *Dataset.* The paper used the English DBpedia **3.5.1** files, concatenated and repaired by a fixed
   pipeline (the 3.5.1 query constants come from that release).
   `DBBench/utils/download_dbpedia_3_5_1.sh` downloads and concatenates the 23 files;
   `DBBench/utils/clean_dbpedia.sh` runs the eight cleaning steps (about 100 GB of temporary space, several
   hours) and compares each step's log with `DBBench/expected-logs/` and the result with the expected
   sha256 in `DBBench/checksums.json` (`2a6949c6...`). If you are given the cleaned file instead, place it at
   `DBBench/data/dbpedia-3.5.1/dbpedia_en_all.nt` and check it with
   `python DBBench/utils/verify_dbpedia_checksum.py <file>`.
2. *Queries.* `mkdir -p DBBench/data && curl -L https://dataweb.infor.uva.es/queries-k2triples.tgz | tar xz -C DBBench/data`
   (creates `DBBench/data/queries`). Then
   ```bash
   vortex-rdf-bench dbbench prepare --query-root DBBench/data/queries --dataset dbpedia \
       --workload dbbench-dbpedia-full --output DBBench/data/dbpedia-base.json
   vortex-rdf-bench dbbench schedule --base DBBench/data/dbpedia-base.json \
       --invalid DBBench/invalid-queries.json --output DBBench/data/dbpedia-tp3.json
   ```
   `schedule` expands the 4,808 valid queries into the phased TP3 schedule of the paper (15,683 attempts:
   every triple-pattern query once as warm-up, three measured passes over the 3,625 triple-pattern queries,
   then the 1,183 join queries once) and prints a `records_sha256` that must equal
   `DBBench/checksums.json["tp3-schedule"]`.
3. *Representations.*
   ```bash
   python run_dbbench_dbpedia_representation_builds_v1.py --triple-count 232541923 --stage vortex-copy
   python run_dbbench_dbpedia_representation_builds_v1.py --triple-count 232541923 --stage vortex-reference
   ```
   (outputs go to `DBBench/data/dbpedia-en-all`; override with `VORTEX_RDF_BENCH_DBPEDIA_NT` and
   `VORTEX_RDF_BENCH_DBPEDIA_OUT`). A `.vortex` store is about 8.5 GB (copy) / 6.3 GB (reference); each build took about 20 minutes in the paper environment.
4. *Run.* Declaration `DBBench/experiments/dbpedia-en-all-full.json` (5 s timeout), with
   `--quarantine-threshold 0` (the paper does not quarantine DBpedia) and `--max-wall-s 19800`. Results are
   compared by **count only** (fingerprinting 15 million result rows is too slow); `--correctness auto`
   picks this from the manifest. DBpedia file-backed stores need the large dictionary to stay readable; see
   the vortex-rdflib notes on `VORTEX_RDF_DICT_MAX_RESIDENT_BYTES`.

## Reproducing all 14 systems

The paper's systems and their identifiers:

| Family | System ids | Served by |
|---|---|---|
| Vortex-RDF | `vortex-rdf/dictionary-secondary-by-{copy,reference}[-memory]` | rdflib-endpoint image |
| RDFLib | `rdflib/default` | rdflib-endpoint image |
| COTTAS | `pycottas/default` (pycottas 1.1.0) | rdflib-endpoint image |
| HDT-RDFLib | `hdt-rdflib/optimized-in-memory` (rdflib-hdt 3.3 optimized BGP) | rdflib-endpoint image |
| Comunica | `comunica/hdt` (5.0.1) | Comunica's own `comunica-sparql-hdt-http` |
| Oxigraph | `oxigraph/memory`, `oxigraph/rocksdb` (0.5.9) | `oxigraph serve` |
| Fuseki | `fuseki/memory`, `fuseki/tdb2` (Jena 6.2.0) | `fuseki-server` |
| Virtuoso | `virtuoso/default` (7.2.17, bulk loader, 6 loader threads) | Virtuoso |
| QLever | `qlever/default` (0.6.0) | `qlever-server` |

Extra preparation beyond the Vortex quick start:

* **HDT.** `cargo install --root BSBM/data/tools/rdf2hdt-0.2.0 --locked --version 0.2.0 rdf2hdt` and
  `BSBM/tools/setup_hdt_runtime.sh` (compiles the pinned rdflib-hdt commit into a local virtual
  environment), then `export VORTEX_RDF_BENCH_HDT_PYTHON=BSBM/data/tools/rdflib-hdt-3.3/bin/python`.
* **COTTAS.** `pip install -e ".[vortex,cottas]"`.
* Run the builder without `--only` to produce HDT, COTTAS and both Vortex stores in one go.
* **Server stores** (Fuseki TDB2, Oxigraph RocksDB, QLever, Virtuoso) are built once from the N-Triples
  source by `run` itself, the first time the system is selected, into `--store-root/<system>/<dataset>/`,
  with build time and peak container memory recorded in `build.json`. A store is never rebuilt or
  overwritten; delete it yourself to rebuild. The in-memory systems (`oxigraph/memory`, `fuseki/memory`)
  and RDFLib load the data when the server starts (`start_to_ready_s`).
* Run all declared systems at once by omitting `--system`. Systems run sequentially; a system that fails to
  start (RDFLib cannot parse DBpedia in 58 GiB) leaves a `failed.json` and the run continues. A finished
  `results.jsonl` is never overwritten: delete it to rerun that system.

Time: BSBM 10K needs a few minutes per fast system and under an hour for the slow ones; BSBM 100K one to
several hours per Vortex configuration (the paper's whole BSBM 100K campaign took about two days);
DBpedia roughly 20 minutes per Vortex configuration plus the slow systems' timeouts.

## What is measured (the protocol)

* **Timer.** A persistent client keeps one HTTP connection per system. The timer starts when the request
  is written to the client and stops when the **complete response body** has been read (`elapsed_ns`).
  Parsing the result, counting rows and computing fingerprints happen afterwards and are not timed.
  The client talks to the container's address directly (not through Docker's port proxy) and acknowledges
  TCP segments immediately (`TCP_QUICKACK`), which removes a 40 ms delayed-ACK artifact on some servers.
* **Order.** Pre-expanded schedules (BSBM streams, DBpedia TP3) run in stream order. Warm-up attempts run
  first and are recorded but not reported.
* **Timeouts.** A query that exceeds the limit is recorded as `timeout`. The client is restarted; for
  servers that cannot cancel a running query the runner waits (untimed) until the server is idle again, or
  restarts it, before the next attempt. Comunica enforces the limit server-side (`-t`).
* **Quarantine.** After `--quarantine-threshold` measured timeouts of one template the rest of that
  template is `skipped` (BSBM: 3). Means over successful attempts therefore describe different query sets
  for different systems; compare per template or on common successes.
* **Memory.** Peak anonymous, file-cache and total memory of the **server container** from cgroup v2
  (`memory.stat`/`memory.current`, sampled every 10 ms), reported per phase. For the rdflib-based systems
  this includes the Python process.
* **Cold start.** The page cache is dropped before every system (`--no-drop-caches` skips it).
* **Correctness.** BSBM results are fingerprinted (order-insensitive unless the query has `ORDER BY`) and
  can be compared across systems; DBpedia is count-only.
* **Load time.** `start_to_ready_s` in `results.summary.json`: container start until the server answers
  a query (including data loading for in-memory servers).

Known differences between the systems that a reader of the numbers should keep in mind:

* The rdflib-based systems share one HTTP and serialization stack (rdflib-endpoint + uvicorn, one worker,
  rdflib's JSON serializer); the native servers each have their own. Serialization time is inside the timer.
* rdflib-endpoint answers DESCRIBE with a SPARQL-results content type; the image patches this to N-Triples.
  Its query-parse cache is disabled so that every query is parsed, as in an embedded run.
* rdflib-hdt prints a diagnostic line per triple pattern; the image discards it.
* QLever runs with its own result cache enabled (`--cache-max-size 8G`) as in the paper; Virtuoso and the
  others use default caching. No pass-to-pass speed-up is visible on the DBpedia triple-pattern passes.

## Adding your own system

Implement `benchmark_core.systems.base.ServerSystem` (a container that serves SPARQL over HTTP: `start`,
optionally `build`, and the `endpoint` property), register it in `benchmark_core/systems/registry.py` and
add a binding for it to a copy of the declaration. See `benchmark_core/systems/oxigraph.py` for a minimal
example.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `cannot drop the page cache` | no passwordless sudo for `sysctl`; use `--no-drop-caches` |
| `permission denied` talking to Docker | add your user to the `docker` group |
| memory columns empty | the host is not on cgroup v2 (`stat -fc %T /sys/fs/cgroup` should print `cgroup2fs`) |
| a port is in use (7878, 7001, 3030, 8890, 7880, 7881) | stop the other service; containers are named `vortex-rdf-bench-*` and are removed after each system |
| leftover store files owned by root | run `docker run --rm -v <dir>:/c --user 0:0 --entrypoint sh <any image> -c 'chmod -R a+rwX /c'` |
| `building ... this takes a few minutes` | first use of an image; the build is cached afterwards |
| generated BSBM dataset hash differs | the host or JVM time zone leaked in; use `BSBM/tools/generate.sh`, which pins it |
| a system shows only `skipped` attempts | quarantine after three timeouts of each template; lower the load or raise `--timeout-s` |

## Verifying your environment against the paper's inputs

* BSBM dataset and query stream: `BSBM/checksums.json` (checked by `generate.sh`).
* DBpedia: `DBBench/checksums.json` (dataset, TP3 schedule identity, query-tree identity).
* Vortex stores: the receipts written next to them record the CLI commit and binary hash. The paper's
  CLI binary had sha256 `ebc4cc24...`; yours will differ with the toolchain, which is expected.
