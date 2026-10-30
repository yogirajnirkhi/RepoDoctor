from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from tree_sitter import Language, Parser

EXT_LANG = {
    ".py": "python",
    ".go": "go",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".c": "c", ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
}

@lru_cache(maxsize=None)
def _language(name: str) -> Language:
    if name == "python":
        import tree_sitter_python as m;    return Language(m.language())
    if name == "go":
        import tree_sitter_go as m;        return Language(m.language())
    if name == "javascript":
        import tree_sitter_javascript as m;return Language(m.language())
    if name == "typescript":
        import tree_sitter_typescript as m;return Language(m.language_typescript())
    if name == "c":
        import tree_sitter_c as m;         return Language(m.language())
    if name == "cpp":
        import tree_sitter_cpp as m;       return Language(m.language())
    raise ValueError(name)

def language_for(path: Path) -> str | None:
    return EXT_LANG.get(path.suffix.lower())

@lru_cache(maxsize=None)
def parser_for(name: str) -> Parser:
    return Parser(_language(name))

def parse_bytes(name: str, data: bytes):
    return parser_for(name).parse(data)
