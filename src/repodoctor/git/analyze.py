from __future__ import annotations
import os, subprocess, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

def _run(args, cwd=None, timeout=120, env=None):
    env = env or os.environ.copy()
    env.setdefault("GIT_TERMINAL_PROMPT","0")
    env.setdefault("GIT_PAGER","cat")
    r = subprocess.run(args, cwd=str(cwd) if cwd else None,
                       capture_output=True, timeout=timeout, env=env,
                       # IMPORTANT: no shell=True anywhere.
                       )
    return r.returncode, r.stdout.decode("utf-8","replace"), r.stderr.decode("utf-8","replace")

@dataclass
class RepoMeta:
    head: Optional[str] = None
    default_branch: Optional[str] = None
    branch_count: int = 0
    commit_count: int = 0
    repo_age_days: Optional[float] = None
    clone_latency_s: float = 0.0

@dataclass
class BranchInfo:
    name: str
    last_commit: str
    last_commit_date: float
    age_days: float
    merged_state: str  # MERGED / UNMERGED / UNKNOWN / UNKNOWN_DUE_TO_SHALLOW_HISTORY
    stale: bool
    safe_to_delete: bool

@dataclass
class BlobInfo:
    path: str
    blob_id: str
    raw_size: int
    disk_size: int
    origin_commit: str
    origin_date: float

@dataclass
class GitReport:
    is_git: bool
    meta: RepoMeta
    branches: list[BranchInfo] = field(default_factory=list)
    blobs: list[BlobInfo] = field(default_factory=list)
    blobs_evaluated: bool = False
    blob_note: str = ""   # NOT EVALUATED / INCOMPLETE — resource limit reached / ""

def gather_meta(repo: Path, clone_latency_s: float) -> RepoMeta:
    m = RepoMeta(clone_latency_s=clone_latency_s)
    rc, out, _ = _run(["git","rev-parse","HEAD"], cwd=repo)
    if rc == 0: m.head = out.strip()
    rc, out, _ = _run(["git","symbolic-ref","--short","HEAD"], cwd=repo)
    if rc == 0: m.default_branch = out.strip()
    else:
        rc, out, _ = _run(["git","remote","show","origin"], cwd=repo)
        if rc == 0:
            for ln in out.splitlines():
                ln = ln.strip()
                if ln.startswith("HEAD branch:"):
                    m.default_branch = ln.split(":",1)[1].strip(); break
    rc, out, _ = _run(["git","for-each-ref","--format=%(refname:short)","refs/heads","refs/remotes"], cwd=repo)
    if rc == 0:
        m.branch_count = len([x for x in out.splitlines() if x.strip() and not x.endswith("/HEAD")])
    rc, out, _ = _run(["git","rev-list","--count","--all"], cwd=repo)
    if rc == 0 and out.strip().isdigit(): m.commit_count = int(out.strip())
    rc, out, _ = _run(["git","log","--reverse","--format=%ct","--max-count=1"], cwd=repo, timeout=60)
    if rc == 0 and out.strip():
        try:
            first = float(out.splitlines()[0])
            m.repo_age_days = (time.time()-first)/86400.0
        except Exception: pass
    return m

def analyze_branches(repo: Path, stale_days: int, target_ref: Optional[str]) -> list[BranchInfo]:
    rc, out, _ = _run(["git","for-each-ref","--format=%(refname:short)|%(objectname)|%(committerdate:unix)",
                        "refs/heads","refs/remotes"], cwd=repo, timeout=60)
    if rc != 0: return []
    # detect shallow
    shallow = (repo/".git"/"shallow").exists() or (repo/"shallow").exists()
    rc_h, head_sha, _ = _run(["git","rev-parse", target_ref or "HEAD"], cwd=repo)
    head_sha = head_sha.strip() if rc_h == 0 else ""
    now = time.time()
    branches: list[BranchInfo] = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) != 3: continue
        name, sha, ts = parts
        if name.endswith("/HEAD"): continue
        try: ts_f = float(ts)
        except: ts_f = 0.0
        age = (now - ts_f)/86400.0 if ts_f else 0.0
        merged = "UNKNOWN"
        safe = False
        if head_sha and sha:
            rc_m, _, _ = _run(["git","merge-base","--is-ancestor", sha, head_sha], cwd=repo)
            if rc_m == 0:
                merged = "MERGED"; safe = (age >= stale_days)
            elif rc_m == 1:
                merged = "UNMERGED"
            else:
                merged = "UNKNOWN_DUE_TO_SHALLOW_HISTORY" if shallow else "UNKNOWN"
        elif shallow:
            merged = "UNKNOWN_DUE_TO_SHALLOW_HISTORY"
        stale = age >= stale_days
        branches.append(BranchInfo(name=name, last_commit=sha, last_commit_date=ts_f,
                                   age_days=age, merged_state=merged, stale=stale,
                                   safe_to_delete=safe))
    return branches

def deep_blob_audit(repo: Path, *, max_bytes: int, top_n: int = 10, min_bytes: int = 1024*1024) -> tuple[list[BlobInfo], str]:
    """Download Git objects (unshallow + fetch all blobs up to max_bytes) and
    rank historical blobs by disk size. Returns (blobs, note)."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    note = ""
    # try to unshallow and fetch missing blobs
    rc, _, _ = _run(["git","fetch","--unshallow","--filter=blob:none"], cwd=repo, timeout=600, env=env)
    # ignore errors (already complete / no origin)
    # Enumerate blob objects
    rc, out, _ = _run(["git","rev-list","--objects","--all"], cwd=repo, timeout=600, env=env)
    if rc != 0:
        return [], "NOT EVALUATED"
    pairs = []
    for ln in out.splitlines():
        if " " in ln:
            sha, path = ln.split(" ",1)
            pairs.append((sha,path))
    # batch cat-file --batch-check for sizes
    try:
        p = subprocess.Popen(["git","cat-file","--batch-check=%(objectname) %(objecttype) %(objectsize) %(objectsize:disk)"],
                             cwd=str(repo), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        q, _ = p.communicate(("\n".join(s for s,_ in pairs)).encode(), timeout=600)
    except Exception:
        return [], "INCOMPLETE — resource limit reached"
    sizes = {}
    downloaded = 0
    truncated = False
    for ln in q.decode("utf-8","replace").splitlines():
        parts = ln.split()
        if len(parts) < 4 or parts[1] != "blob": continue
        try:
            raw = int(parts[2]); disk = int(parts[3])
        except: continue
        downloaded += disk
        if downloaded > max_bytes:
            truncated = True; break
        sizes[parts[0]] = (raw, disk)
    path_by_sha: dict[str,str] = {}
    for sha, path in pairs:
        path_by_sha.setdefault(sha, path)
    # Build and filter
    rows: list[BlobInfo] = []
    for sha,(raw,disk) in sizes.items():
        if raw < min_bytes: continue
        rows.append(BlobInfo(path=path_by_sha.get(sha,""), blob_id=sha,
                             raw_size=raw, disk_size=disk, origin_commit="", origin_date=0.0))
    rows.sort(key=lambda b: b.disk_size, reverse=True)
    rows = rows[:top_n]
    # resolve origin commit for the top-N only (expensive)
    for b in rows:
        rc, out, _ = _run(["git","log","--all","--format=%H %ct","--diff-filter=A","--max-count=1","--", b.path],
                           cwd=repo, timeout=60, env=env)
        if rc == 0 and out.strip():
            try:
                sha, ts = out.strip().split()
                b.origin_commit, b.origin_date = sha, float(ts)
            except Exception: pass
    if truncated:
        note = "INCOMPLETE — resource limit reached"
    return rows, note

def analyze(repo: Path, *, clone_latency_s: float, is_git: bool,
            stale_days: int, deep_audit: bool, target_ref: Optional[str],
            max_deep_audit_bytes: int) -> GitReport:
    if not is_git:
        return GitReport(is_git=False, meta=RepoMeta(), blob_note="NOT EVALUATED")
    meta = gather_meta(repo, clone_latency_s)
    branches = analyze_branches(repo, stale_days, target_ref or meta.default_branch)
    if deep_audit:
        blobs, note = deep_blob_audit(repo, max_bytes=max_deep_audit_bytes)
        return GitReport(is_git=True, meta=meta, branches=branches, blobs=blobs,
                         blobs_evaluated=True, blob_note=note)
    return GitReport(is_git=True, meta=meta, branches=branches,
                     blobs_evaluated=False, blob_note="NOT EVALUATED")
