from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum

class ScanState(str, Enum):
    CREATED = "CREATED"
    VALIDATING = "VALIDATING"
    INGESTING = "INGESTING"
    ANALYZING = "ANALYZING"
    GENERATING_ARTIFACTS = "GENERATING_ARTIFACTS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

@dataclass
class ScanConfig:
    target: str
    deep_git_audit: bool = False
    branch: Optional[str] = None
    stale_days: int = 90
    complexity_refactor_threshold: int = 10
    clone_min_tokens: int = 20
    clone_min_lines: int = 5
    max_deep_audit_bytes: int = 2 * 1024 * 1024 * 1024  # 2 GiB
    max_files: int = 50_000
    max_source_bytes: int = 512 * 1024 * 1024          # 512 MiB
    max_scan_duration_s: int = 1800
    max_graph_nodes: int = 500
    workers: int = 2
    cache_ttl_s: int = 3600
    ignore_patterns: list[str] = field(default_factory=lambda: [
        ".git","node_modules","vendor","venv",".venv","__pycache__",
        "dist","build","target","coverage",".cache",".idea",".vscode",
    ])

@dataclass
class Finding:
    severity: str
    category: str
    title: str
    path: str
    evidence: str
    threshold: str
    remediation: str

def to_jsonable(obj):
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k,v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k,v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj
