from pathlib import Path
from repodoctor.analysis.dependencies import build

def test_python_cycle(tmp_path):
    (tmp_path/"a.py").write_text("from b import x\nx=1\n")
    (tmp_path/"b.py").write_text("from a import x\n")
    g = build(tmp_path, [tmp_path/"a.py", tmp_path/"b.py"])
    mods = {m for c in g.cycles for m in c["modules"]}
    assert "a" in mods and "b" in mods
