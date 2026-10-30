import pytest
from repodoctor.ingestion.ingest import canonical_local, is_remote

def test_rejects_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        canonical_local(str(tmp_path/"does-not-exist"))

def test_is_remote():
    assert is_remote("https://github.com/u/r.git")
    assert is_remote("git@github.com:u/r.git")
    assert not is_remote("/tmp")
