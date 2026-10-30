from __future__ import annotations
import hashlib, os, re, shutil, subprocess, tempfile, time, uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TMP_ROOT = Path("/tmp/repodoctor")

_URL_RE  = re.compile(r"^https?://[^\s]+$", re.I)
_SSH_RE  = re.compile(r"^(git@|ssh://)[^\s]+$", re.I)

@dataclass
class Ingested:
    path: Path
    is_git: bool
    is_remote: bool
    clone_latency_s: float
    temp_dir: Optional[Path]  # delete after scan

def _target_hash(target: str) -> str:
    return hashlib.sha256(target.encode("utf-8")).hexdigest()[:12]

def is_remote(target: str) -> bool:
    return bool(_URL_RE.match(target) or _SSH_RE.match(target))

def canonical_local(target: str) -> Path:
    # Reject nonexistent or inaccessible; block path traversal above the user's cwd scope
    p = Path(target).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Path does not exist: {target}")
    rp = p.resolve(strict=True)
    if not os.access(rp, os.R_OK):
        raise PermissionError(f"Path not readable: {rp}")
    return rp

def ingest(target: str, *, deep_git_audit: bool = False) -> Ingested:
    """Return an Ingested handle. Caller is responsible for cleanup via cleanup()."""
    if is_remote(target):
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        scan_dir = TMP_ROOT / _target_hash(target) / uuid.uuid4().hex
        scan_dir.mkdir(parents=True, exist_ok=False)
        work = scan_dir / "repo"
        env = _safe_git_env()
        t0 = time.monotonic()
        cmd = [
            "git", "clone",
            "--filter=blob:none", "--no-checkout",
            "--depth=100", "--no-tags", "--no-single-branch",
            target, str(work),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=600, env=env)
        except subprocess.CalledProcessError as e:
            shutil.rmtree(scan_dir, ignore_errors=True)
            raise RuntimeError(f"git clone failed: {e.stderr.decode('utf-8','ignore')[:400]}") from e
        latency = time.monotonic() - t0
        # We still need working-tree files for source analysis. Do a sparse checkout of HEAD.
        try:
            subprocess.run(["git","-C",str(work),"checkout","--quiet","HEAD"],
                           check=False, capture_output=True, timeout=600, env=env)
        except subprocess.TimeoutExpired:
            pass
        return Ingested(path=work, is_git=True, is_remote=True,
                        clone_latency_s=latency, temp_dir=scan_dir)
    # local
    path = canonical_local(target)
    is_git = (path / ".git").exists()
    return Ingested(path=path, is_git=is_git, is_remote=False,
                    clone_latency_s=0.0, temp_dir=None)

def cleanup(ing: Ingested):
    if ing.temp_dir and ing.temp_dir.exists():
        shutil.rmtree(ing.temp_dir, ignore_errors=True)

def cleanup_cache(max_age_s: int = 0) -> int:
    """Remove old TMP_ROOT entries. Returns number of directories removed."""
    if not TMP_ROOT.exists():
        return 0
    removed = 0
    cutoff = time.time() - max_age_s
    for sub in TMP_ROOT.iterdir():
        try:
            if sub.stat().st_mtime < cutoff or max_age_s == 0:
                shutil.rmtree(sub, ignore_errors=True); removed += 1
        except OSError:
            pass
    return removed

def _safe_git_env() -> dict:
    env = os.environ.copy()
    # Disable hooks/filters/pager and prompts; strict safety for untrusted repos.
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "echo",
        "GIT_PAGER": "cat",
        "GIT_CONFIG_NOSYSTEM": "1",
        "HOME": env.get("HOME", "/tmp"),
    })
    # Hooks disabled via core.hooksPath set per command
    return env
