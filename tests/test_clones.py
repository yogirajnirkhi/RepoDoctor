from pathlib import Path
from repodoctor.analysis.clones import detect_clones

def test_type2_clones(tmp_path):
    a = b"""
def process(items):
    total = 0
    for x in items:
        if x > 0:
            total += x
        else:
            total -= x
    return total
"""
    b = b"""
def summarize(records):
    acc = 0
    for r in records:
        if r > 0:
            acc += r
        else:
            acc -= r
    return acc
"""
    pa = tmp_path/"a.py"; pa.write_bytes(a)
    pb = tmp_path/"b.py"; pb.write_bytes(b)
    clusters = detect_clones([(pa,"a.py",a),(pb,"b.py",b)], min_tokens=10, min_lines=3)
    assert any(len(c.members) >= 2 for c in clusters), "expected a clone cluster across files"
