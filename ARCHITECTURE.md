# RDF benchmark architecture

This repository owns benchmark semantics. KROWN owns experiment orchestration.

## Responsibility boundary

### External benchmark tools

External tools generate datasets and workload inputs. The generated files stay under each benchmark's ignored `data/` directory. DBBench query files and official BSBM generator output are not created by KROWN.

### Benchmarks repository

Each benchmark adapter validates its native input and converts it to the common RDF workload manifest. `benchmark_core.rdf_execution` executes that manifest and writes the common JSONL result contract. Adapters can add benchmark metadata, but they do not define a second execution contract.

### KROWN

KROWN invokes the public `vortex-rdf-bench` interface. It stages external datasets, collects measurements and declared artifacts, guards large workloads, and validates semantic baselines. KROWN does not contain DBBench or BSBM workload-generation rules.

## Enforced invariants

The architecture audit verifies:

- DBBench and BSBM reuse the shared RDF execution runner.
- The package includes both adapters and the common contracts.
- Manifest and result records contain stable identities and provenance.
- Result publication is atomic.
- External datasets and raw runs remain ignored.
- Every benchmark README documents local data placement.

Run the audit with:

```bash
python -m unittest tests.test_architecture -v
```
