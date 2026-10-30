from __future__ import annotations
import os
from pathlib import Path

def treemap(root: Path, ignore: list[str]) -> list[dict]:
    ignore_set = set(ignore)
    out = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = Path(dirpath).relative_to(root)
        if any(p in ignore_set for p in rel.parts): dirnames[:] = []; continue
        dirnames[:] = [d for d in dirnames if d not in ignore_set]
        for name in filenames:
            fp = Path(dirpath)/name
            try: sz = fp.stat().st_size
            except OSError: continue
            out.append({"path": str(fp.relative_to(root)), "size": sz, "type": fp.suffix.lower() or "<none>"})
    total = sum(x["size"] for x in out) or 1
    for x in out: x["percentage"] = round(100.0 * x["size"]/total, 4)
    return out
