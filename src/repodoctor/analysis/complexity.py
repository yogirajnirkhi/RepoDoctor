from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from .parsers import language_for, parse_bytes

@dataclass
class FunctionComplexity:
    file: str
    name: str
    start_line: int
    end_line: int
    lines: int
    complexity: int
    classification: str

# Decision-point node types per language. Each node adds +1 to McCabe M.
DECISIONS = {
    "python": {"if_statement","elif_clause","for_statement","while_statement",
               "except_clause","conditional_expression","boolean_operator",
               "match_statement","case_clause","assert_statement"},
    "go":     {"if_statement","for_statement","type_switch_statement","expression_switch_statement",
               "communication_case","type_case","expression_case","select_statement",
               "binary_expression" },  # filtered to && || below
    "javascript":{"if_statement","for_statement","for_in_statement","for_of_statement",
                  "while_statement","do_statement","switch_case","catch_clause",
                  "ternary_expression","binary_expression"},
    "typescript":{"if_statement","for_statement","for_in_statement","for_of_statement",
                  "while_statement","do_statement","switch_case","catch_clause",
                  "ternary_expression","binary_expression"},
    "c":      {"if_statement","for_statement","while_statement","do_statement",
               "case_statement","conditional_expression","binary_expression"},
    "cpp":    {"if_statement","for_statement","while_statement","do_statement",
               "case_statement","conditional_expression","binary_expression","catch_clause"},
}
FUNC_TYPES = {
    "python":{"function_definition"},
    "go":{"function_declaration","method_declaration","func_literal"},
    "javascript":{"function_declaration","function","arrow_function","method_definition"},
    "typescript":{"function_declaration","function","arrow_function","method_definition","method_signature"},
    "c":{"function_definition"},
    "cpp":{"function_definition","lambda_expression"},
}
NAME_FIELD = {
    "python":"name","go":"name","javascript":"name","typescript":"name","c":"declarator","cpp":"declarator",
}

def classify(m: int) -> str:
    if m <= 5: return "LOW"
    if m <= 10: return "MODERATE"
    if m <= 20: return "HIGH"
    return "VERY HIGH"

def _is_short_circuit(node, src: bytes) -> bool:
    # count && and || as decisions, not every binary expression
    for ch in node.children:
        if ch.is_named: continue
        tok = src[ch.start_byte:ch.end_byte]
        if tok in (b"&&", b"||", b"and", b"or"): return True
    return False

def _func_name(node, lang: str, src: bytes) -> str:
    f = NAME_FIELD.get(lang)
    if not f: return "<anon>"
    nm = node.child_by_field_name(f)
    if nm is None: return "<anon>"
    try:
        return src[nm.start_byte:nm.end_byte].decode("utf-8","replace").strip().splitlines()[0][:80]
    except Exception:
        return "<anon>"

def compute_complexity(file_path: Path, rel: str, data: bytes) -> list[FunctionComplexity]:
    lang = language_for(file_path)
    if lang is None: return []
    try:
        tree = parse_bytes(lang, data)
    except Exception:
        return []
    decisions = DECISIONS[lang]; functypes = FUNC_TYPES[lang]
    results: list[FunctionComplexity] = []

    def walk(node, cur_fn=None):
        pushed = False
        if node.type in functypes:
            cur_fn = {"node": node, "name": _func_name(node, lang, data), "m": 1}
            pushed = True
        if cur_fn is not None and node.type in decisions:
            if node.type == "binary_expression":
                if _is_short_circuit(node, data):
                    cur_fn["m"] += 1
            else:
                cur_fn["m"] += 1
        for ch in node.children:
            walk(ch, cur_fn)
        if pushed:
            sl = cur_fn["node"].start_point[0] + 1
            el = cur_fn["node"].end_point[0] + 1
            m = cur_fn["m"]
            results.append(FunctionComplexity(
                file=rel, name=cur_fn["name"], start_line=sl, end_line=el,
                lines=el - sl + 1, complexity=m, classification=classify(m),
            ))
    walk(tree.root_node)
    return results
