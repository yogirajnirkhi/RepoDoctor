from __future__ import annotations
import os
from pathlib import Path
from dataclasses import dataclass
from .parsers import language_for, parse_bytes

@dataclass
class FileRecord:
    path: str
    language: str | None
    bytes: int
    lines: int
    parse_ok: bool
    syntax_errors: int

def _is_ignored(parts, ignore_set):
    return any(p in ignore_set for p in parts)

def iter_source_files(root: Path, ignore: list[str], *, max_files: int, max_total_bytes: int):
    ignore_set = set(ignore)
    total = 0
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        rel = Path(dirpath).relative_to(root)
        if _is_ignored(rel.parts, ignore_set):
            dirnames[:] = []; continue
        # prune
        dirnames[:] = [d for d in dirnames if d not in ignore_set and not d.startswith(".git")]
        for name in filenames:
            fp = Path(dirpath) / name
            if fp.is_symlink():  # avoid symlink escape
                target = fp.resolve()
                try:
                    target.relative_to(root.resolve())
                except ValueError:
                    continue
            if language_for(fp) is None:
                continue
            try:
                sz = fp.stat().st_size
            except OSError: continue
            total += sz; count += 1
            if count > max_files or total > max_total_bytes:
                return
            yield fp

def _count_errors(node) -> int:
    n = 0
    stack = [node]
    while stack:
        x = stack.pop()
        if x.has_error and x.type == "ERROR": n += 1
        for ch in x.children: stack.append(ch)
    return n

def collect_files(root: Path, ignore: list[str], *, max_files: int, max_source_bytes: int) -> list[FileRecord]:
    out: list[FileRecord] = []
    for fp in iter_source_files(root, ignore, max_files=max_files, max_total_bytes=max_source_bytes):
        try:
            data = fp.read_bytes()
        except OSError: continue
        lang = language_for(fp)
        rec = FileRecord(path=str(fp.relative_to(root)), language=lang, bytes=len(data),
                         lines=data.count(b"\n") + (0 if data.endswith(b"\n") else 1),
                         parse_ok=False, syntax_errors=0)
        try:
            tree = parse_bytes(lang, data)
            rec.parse_ok = not tree.root_node.has_error or True  # recorded; errors counted separately
            rec.syntax_errors = _count_errors(tree.root_node)
            rec.parse_ok = rec.syntax_errors == 0
        except Exception:
            rec.parse_ok = False
            rec.syntax_errors = 1
        out.append(rec)
    return out
