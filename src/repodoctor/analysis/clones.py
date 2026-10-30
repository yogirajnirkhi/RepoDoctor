from __future__ import annotations
import hashlib
from dataclasses import dataclass
from pathlib import Path
from collections import defaultdict
from .parsers import language_for, parse_bytes

@dataclass
class CloneMember:
    file: str
    start_line: int
    end_line: int
    line_count: int

@dataclass
class CloneCluster:
    structural_hash: str
    token_count: int
    members: list[CloneMember]

# Named node types we treat as "variable identifier / literal" and normalize away.
NORMALIZE_TYPES = {
    "identifier","type_identifier","field_identifier","property_identifier","shorthand_property_identifier",
    "integer","float","string","interpreted_string_literal","raw_string_literal","character_literal",
    "number","true","false","null","none","nil","boolean","regex","template_string",
}

def _normalized_sexp(node, src: bytes) -> tuple[str, int]:
    """Return (normalized s-expression, token count). Identifiers/literals -> type only.
       Keeps structure: operators, control-flow, declarations, calls."""
    tcount = 0
    parts: list[str] = []
    def rec(n):
        nonlocal tcount
        if not n.is_named:
            return
        parts.append("(" + n.type)
        tcount += 1
        if n.type in NORMALIZE_TYPES or n.child_count == 0:
            parts.append(")")
            return
        for ch in n.children:
            if ch.is_named: rec(ch)
        parts.append(")")
    rec(node)
    return "".join(parts), tcount

def _candidate_blocks(root):
    """Collect code blocks worth comparing: functions, class bodies, loop/if blocks, lambdas."""
    targets = {
        "function_definition","function_declaration","method_declaration","method_definition",
        "arrow_function","func_literal","lambda_expression",
        "if_statement","for_statement","while_statement","switch_statement",
        "class_definition","class_declaration","block","compound_statement",
    }
    out = []
    stack = [root]
    while stack:
        n = stack.pop()
        if n.type in targets:
            out.append(n)
        for ch in n.children:
            stack.append(ch)
    return out

def detect_clones(files: list[tuple[Path, str, bytes]], *, min_tokens: int, min_lines: int) -> list[CloneCluster]:
    """files: list of (abs_path, rel_path, source_bytes)."""
    buckets: dict[str, list[CloneMember]] = defaultdict(list)
    tcounts: dict[str, int] = {}
    for abs_p, rel, data in files:
        lang = language_for(abs_p)
        if lang is None: continue
        try: tree = parse_bytes(lang, data)
        except Exception: continue
        for node in _candidate_blocks(tree.root_node):
            sl = node.start_point[0] + 1
            el = node.end_point[0] + 1
            lines = el - sl + 1
            if lines < min_lines: continue
            sexp, tc = _normalized_sexp(node, data)
            if tc < min_tokens: continue
            h = hashlib.sha256(sexp.encode("utf-8")).hexdigest()
            buckets[h].append(CloneMember(file=rel, start_line=sl, end_line=el, line_count=lines))
            tcounts[h] = tc
    clusters: list[CloneCluster] = []
    for h, members in buckets.items():
        files_seen = {m.file for m in members}
        if len(members) < 2 or len(files_seen) < 2: continue
        # merge overlaps within same file
        by_file: dict[str, list[CloneMember]] = defaultdict(list)
        for m in members: by_file[m.file].append(m)
        merged: list[CloneMember] = []
        for f, lst in by_file.items():
            lst.sort(key=lambda x: (x.start_line, -x.end_line))
            cur = None
            for m in lst:
                if cur and m.start_line <= cur.end_line:
                    cur = CloneMember(f, cur.start_line, max(cur.end_line, m.end_line),
                                      max(cur.end_line, m.end_line) - cur.start_line + 1)
                else:
                    if cur: merged.append(cur)
                    cur = m
            if cur: merged.append(cur)
        files_seen = {m.file for m in merged}
        if len(files_seen) < 2: continue
        clusters.append(CloneCluster(structural_hash=h, token_count=tcounts[h], members=merged))
    clusters.sort(key=lambda c: (len(c.members), c.token_count), reverse=True)
    return clusters
