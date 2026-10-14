from pathlib import Path


def test_hdt_builder_keeps_rust_serializer_and_adds_query_index():
    root = Path(__file__).resolve().parents[1]
    hdt = (root / "BSBM/hdt.py").read_text(encoding="utf-8")
    runner = (root / "run_bsbm_10k_representation_builds_v1.py").read_text(encoding="utf-8")
    assert '[str(rdf2hdt), "convert"' in hdt
    assert 'HDT_INDEX_SUFFIX = ".index.v1-1"' in hdt
    assert 'HDTStore(sys.argv[1], mapped=True, indexed=True, safe_mode=True)' in hdt
    assert 'store.__len__(None) >= 0; store.close()' in hdt
    assert 'assert len(store) >= 0' not in hdt
    assert 'files=[output.name, index_output.name]' in hdt
    assert '[hdt, hdt_index]' in runner
    assert 'KROWN_HDT_INDEX_PYTHON' in runner


def test_query_ready_publication_is_pairwise_and_temporary():
    root = Path(__file__).resolve().parents[1]
    source = (root / "BSBM/hdt.py").read_text(encoding="utf-8")
    assert 'temporary_index = Path(str(temporary) + HDT_INDEX_SUFFIX)' in source
    assert 'temporary.replace(output)' in source
    assert 'temporary_index.replace(index_output)' in source
    assert 'temporary_index.unlink(missing_ok=True)' in source
