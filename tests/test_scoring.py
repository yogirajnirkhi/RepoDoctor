from repodoctor.scoring.score import compute
from types import SimpleNamespace

def test_score_not_eval_non_git():
    git = SimpleNamespace(is_git=False, branches=[], blobs=[], blobs_evaluated=False, blob_note="NOT EVALUATED")
    score = compute(git_report=git, functions=[], clone_clusters=[], dep_graph=SimpleNamespace(cycles=[]), files=[], repo_bytes=0)
    names = {c["name"]: c["points"] for c in score["components"]}
    assert names["Git Object Bloat"] is None
    assert names["Stale Branches"] is None
    assert 0 <= score["score"] <= 100
