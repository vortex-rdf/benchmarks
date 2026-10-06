from pathlib import Path

def test_dbbench_builder_uses_shared_builders_and_current_vortex_indexes():
 root=Path(__file__).resolve().parents[1]
 wrapper=(root/'DBBench/representations.py').read_text()
 runner=(root/'run_dbbench_dbpedia_representation_builds_v1.py').read_text()
 assert 'from BSBM.cottas import' in wrapper
 assert 'from BSBM.hdt import' in wrapper
 assert "'secondary-by-reference'" in runner
 assert "'secondary-by-copy'" in runner
 assert "run_build_command" in runner
 assert "measure_representation_size" in runner
 assert 'run_build_command' in runner
 assert 'measure_representation_size' in runner
 assert "--delete-legacy-v10" in runner
 assert 'LEGACY_SHA' in runner
