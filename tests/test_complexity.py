from pathlib import Path
from repodoctor.analysis.complexity import compute_complexity

def test_python_complexity(tmp_path):
    code = b"""
def a(x):
    return x

def b(x):
    if x > 0:
        for i in range(10):
            if i % 2 == 0 and i < 5:
                return i
    return -1
"""
    p = tmp_path/"f.py"; p.write_bytes(code)
    rows = compute_complexity(p, "f.py", code)
    names = {r.name:r.complexity for r in rows}
    assert names["a"] == 1
    assert names["b"] >= 4
