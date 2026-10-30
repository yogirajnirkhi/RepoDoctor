from __future__ import annotations
import os, re
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict

@dataclass
class DepGraph:
    nodes: dict[str, str] = field(default_factory=dict)   # module -> file
    edges: list[tuple[str,str]] = field(default_factory=list)
    cycles: list[dict] = field(default_factory=list)      # [{modules, edges, path}]

PY_IMPORT = re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import\s+|import\s+([\w\.]+))", re.M)
JS_IMPORT = re.compile(r"""(?:import\s+(?:[^'"]+\s+from\s+)?|require\(\s*|export\s+[^'"]*from\s+)['"]([^'"]+)['"]""")
GO_IMPORT_BLOCK = re.compile(r'import\s*\(([^)]*)\)', re.S)
GO_IMPORT_LINE = re.compile(r'"([^"]+)"')
GO_SINGLE = re.compile(r'^\s*import\s+"([^"]+)"', re.M)
C_INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.M)

def _py_module_for(root: Path, fp: Path) -> str:
    rel = fp.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__": parts.pop()
    return ".".join(parts)

def _go_module_prefix(root: Path) -> str | None:
    gm = root / "go.mod"
    if not gm.exists(): return None
    try:
        for ln in gm.read_text("utf-8","replace").splitlines():
            if ln.startswith("module "):
                return ln.split(None,1)[1].strip()
    except Exception: pass
    return None

def _norm_js(base_file: Path, root: Path, spec: str) -> str | None:
    if not (spec.startswith(".") or spec.startswith("/")): return None  # external
    target = (base_file.parent / spec).resolve()
    try: rel = target.relative_to(root.resolve())
    except ValueError: return None
    # strip extensions / index
    s = str(rel)
    for suf in (".ts",".tsx",".js",".mjs",".cjs"):
        if s.endswith(suf): s = s[:-len(suf)]; break
    if s.endswith("/index"): s = s[:-6]
    return s.replace(os.sep, "/")

def build(root: Path, files: list[Path]) -> DepGraph:
    g = DepGraph()
    py_module_to_file: dict[str, str] = {}
    local_files_norm: set[str] = set()
    go_prefix = _go_module_prefix(root)
    # First pass: register nodes
    for fp in files:
        rel = str(fp.relative_to(root)).replace(os.sep, "/")
        local_files_norm.add(rel)
        suf = fp.suffix.lower()
        if suf == ".py":
            m = _py_module_for(root, fp); g.nodes[m] = rel; py_module_to_file[m] = rel
        elif suf == ".go":
            # package = directory relative to module path
            dir_rel = str(fp.parent.relative_to(root)).replace(os.sep, "/")
            mod = f"{go_prefix}/{dir_rel}".rstrip("/") if go_prefix else dir_rel or "."
            g.nodes[mod] = dir_rel
        elif suf in (".js",".mjs",".cjs",".ts",".tsx"):
            s = rel
            for sfx in (".ts",".tsx",".js",".mjs",".cjs"):
                if s.endswith(sfx): s = s[:-len(sfx)]; break
            if s.endswith("/index"): s = s[:-6]
            g.nodes[s] = rel
        elif suf in (".c",".h",".cc",".cpp",".cxx",".hpp",".hh"):
            g.nodes[rel] = rel
    # Second pass: edges
    for fp in files:
        try: src = fp.read_text("utf-8","replace")
        except Exception: continue
        rel = str(fp.relative_to(root)).replace(os.sep, "/")
        suf = fp.suffix.lower()
        if suf == ".py":
            me = _py_module_for(root, fp)
            for a, b in PY_IMPORT.findall(src):
                dep = a or b
                if dep in g.nodes and dep != me:
                    g.edges.append((me, dep))
                else:
                    # try progressively shorter prefixes
                    parts = dep.split(".")
                    for i in range(len(parts), 0, -1):
                        p = ".".join(parts[:i])
                        if p in g.nodes and p != me:
                            g.edges.append((me, p)); break
        elif suf == ".go":
            dir_rel = str(fp.parent.relative_to(root)).replace(os.sep, "/")
            me = f"{go_prefix}/{dir_rel}".rstrip("/") if go_prefix else dir_rel or "."
            def _add_go(spec: str):
                if go_prefix and spec.startswith(go_prefix):
                    tail = spec[len(go_prefix):].lstrip("/")
                    cand = f"{go_prefix}/{tail}".rstrip("/")
                    if cand in g.nodes and cand != me:
                        g.edges.append((me, cand))
            m = GO_IMPORT_BLOCK.search(src)
            if m:
                for spec in GO_IMPORT_LINE.findall(m.group(1)): _add_go(spec)
            for spec in GO_SINGLE.findall(src): _add_go(spec)
        elif suf in (".js",".mjs",".cjs",".ts",".tsx"):
            me = rel
            for sfx in (".ts",".tsx",".js",".mjs",".cjs"):
                if me.endswith(sfx): me = me[:-len(sfx)]; break
            if me.endswith("/index"): me = me[:-6]
            for spec in JS_IMPORT.findall(src):
                dep = _norm_js(fp, root, spec)
                if dep and dep in g.nodes and dep != me:
                    g.edges.append((me, dep))
        elif suf in (".c",".h",".cc",".cpp",".cxx",".hpp",".hh"):
            for inc in C_INCLUDE.findall(src):
                target = (fp.parent / inc).resolve()
                try: dep = str(target.relative_to(root.resolve())).replace(os.sep,"/")
                except ValueError: continue
                if dep in g.nodes and dep != rel:
                    g.edges.append((rel, dep))
    # Dedupe
    g.edges = sorted(set(g.edges))
    g.cycles = tarjan_sccs(g.nodes.keys(), g.edges)
    return g

def tarjan_sccs(nodes, edges) -> list[dict]:
    """Return cycles: SCCs of size > 1, and self-loops."""
    adj: dict[str, list[str]] = defaultdict(list)
    self_loops: list[str] = []
    for a,b in edges:
        if a == b: self_loops.append(a); continue
        adj[a].append(b)
    index = {}
    low = {}
    on_stack = set()
    stack: list[str] = []
    sccs: list[list[str]] = []
    counter = [0]
    def strong(v, it=None):
        work = [(v, iter(adj.get(v, [])))]
        index[v] = counter[0]; low[v] = counter[0]; counter[0]+=1
        stack.append(v); on_stack.add(v)
        while work:
            node, children = work[-1]
            try:
                w = next(children)
                if w not in index:
                    index[w] = counter[0]; low[w] = counter[0]; counter[0]+=1
                    stack.append(w); on_stack.add(w)
                    work.append((w, iter(adj.get(w, []))))
                elif w in on_stack:
                    low[node] = min(low[node], index[w])
            except StopIteration:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    comp = []
                    while True:
                        x = stack.pop(); on_stack.discard(x); comp.append(x)
                        if x == node: break
                    if len(comp) > 1:
                        sccs.append(comp)
    for v in list(nodes):
        if v not in index: strong(v)
    cycles: list[dict] = []
    for comp in sccs:
        comp_set = set(comp)
        comp_edges = [(a,b) for a,b in edges if a in comp_set and b in comp_set]
        # cycle path: BFS to find a cycle inside the SCC starting from comp[0]
        path = _any_cycle_path(comp[0], comp_edges)
        cycles.append({"modules": sorted(comp), "edges": comp_edges, "path": path})
    for v in self_loops:
        cycles.append({"modules":[v], "edges":[(v,v)], "path":[v,v]})
    return cycles

def _any_cycle_path(start, edges) -> list[str]:
    adj = defaultdict(list)
    for a,b in edges: adj[a].append(b)
    # DFS to find back edge to start
    stack = [(start, [start])]
    seen = set()
    while stack:
        node, path = stack.pop()
        for nxt in adj.get(node, []):
            if nxt == start and len(path) >= 1:
                return path + [start]
            if nxt in path: continue
            if (node, nxt) in seen: continue
            seen.add((node,nxt))
            stack.append((nxt, path + [nxt]))
    return [start]
