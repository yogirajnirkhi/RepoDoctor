from pathlib import Path
import json, time, tempfile
from repodoctor.engine import Engine
from repodoctor.persistence.db import DB
from repodoctor.models import ScanConfig

def test_end_to_end_local(tmp_path):
    # Create a tiny non-git source tree with Python, a cycle, a clone, a complex fn.
    (tmp_path/"src").mkdir()
    (tmp_path/"src"/"a.py").write_text(
        "from .b import f\n"
        "def complex_fn(x):\n"
        "  if x > 0:\n"
        "    for i in range(x):\n"
        "      if i % 2 == 0 and i > 1:\n"
        "        return i\n"
        "      elif i < 0:\n"
        "        continue\n"
        "  return -1\n"
        "def clone(items):\n"
        "  total = 0\n"
        "  for x in items:\n"
        "    if x > 0:\n"
        "      total += x\n"
        "    else:\n"
        "      total -= x\n"
        "  return total\n"
    )
    (tmp_path/"src"/"b.py").write_text(
        "from .a import complex_fn\n"
        "def f(): return 1\n"
        "def near_clone(records):\n"
        "  acc = 0\n"
        "  for r in records:\n"
        "    if r > 0:\n"
        "      acc += r\n"
        "    else:\n"
        "      acc -= r\n"
        "  return acc\n"
    )
    (tmp_path/"src"/"__init__.py").write_text("")
    dbp = tmp_path/"db.sqlite"
    art = tmp_path/"art"
    e = Engine(db=DB(dbp), artifacts_root=art)
    sid = e.submit(ScanConfig(target=str(tmp_path), clone_min_tokens=10, clone_min_lines=3))
    for _ in range(200):
        row = e.db.get_scan(sid)
        if row and row["state"] in ("COMPLETED","FAILED"): break
        time.sleep(0.1)
    assert row["state"] == "COMPLETED", row["error"]
    s = json.loads(row["summary_json"])
    assert s["files"] >= 2
    assert s["functions"] >= 3
    arts = e.db.exec("SELECT name FROM artifacts WHERE scan_id=?",(sid,))
    names = {a["name"] for a in arts}
    assert names == {"HEALTH.md","git-cleanup.sh","analysis.json"}
    assert (art/sid/"HEALTH.md").exists()
