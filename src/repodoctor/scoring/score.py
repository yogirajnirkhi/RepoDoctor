from __future__ import annotations
from dataclasses import dataclass, asdict

NOT_EVAL = "NOT EVALUATED"

@dataclass
class Component:
    name: str
    max_points: float
    points: float | None   # None => NOT EVALUATED
    detail: str

def _clamp(x, lo, hi): return max(lo, min(hi, x))

def compute(*, git_report, functions, clone_clusters, dep_graph, files, repo_bytes: int) -> dict:
    comps: list[Component] = []

    # --- Git Hygiene (25) ---
    # Bloat (10) + Stale branches (15)
    if git_report.is_git:
        if git_report.blobs_evaluated:
            over = sum(1 for b in git_report.blobs if b.disk_size > 10*1024*1024)
            top_bytes = sum(b.disk_size for b in git_report.blobs)
            # 0 blobs > 10MiB => 10; each large blob loses 2 points
            pts = _clamp(10 - 2*over, 0, 10)
            comps.append(Component("Git Object Bloat", 10, pts,
                f"{len(git_report.blobs)} large blobs; {over} > 10MiB; total {top_bytes/1_048_576:.1f} MiB in top list"))
        else:
            comps.append(Component("Git Object Bloat", 10, None, NOT_EVAL + " (standard mode)"))
        total_branches = max(1, len(git_report.branches))
        stale = [b for b in git_report.branches if b.stale]
        pts = 15 * (1 - min(1.0, len(stale)/total_branches))
        comps.append(Component("Stale Branches", 15, round(pts, 2),
            f"{len(stale)} stale / {total_branches} branches (>= 90d)"))
    else:
        comps.append(Component("Git Object Bloat", 10, None, NOT_EVAL + " (not a Git repository)"))
        comps.append(Component("Stale Branches", 15, None, NOT_EVAL + " (not a Git repository)"))

    # --- Code Structure (45) ---
    # Complexity (20) + Clones (15) + Dependency cycles (10)
    if functions:
        over = sum(1 for f in functions if f.complexity > 10)
        very_high = sum(1 for f in functions if f.complexity > 20)
        frac = over / max(1, len(functions))
        pts = 20 * (1 - min(1.0, frac*4)) - 2*very_high
        comps.append(Component("Cyclomatic Complexity", 20, max(0, round(pts, 2)),
            f"{over}/{len(functions)} functions > 10; {very_high} VERY HIGH"))
    else:
        comps.append(Component("Cyclomatic Complexity", 20, 20.0, "No parsed functions found"))

    # Clones
    clone_members = sum(len(c.members) for c in clone_clusters)
    pts = 15 - min(15, len(clone_clusters)*1.0 + clone_members*0.2)
    comps.append(Component("Structural Clones", 15, round(max(0,pts),2),
        f"{len(clone_clusters)} clusters, {clone_members} members"))

    # Cycles
    n_cycles = len(dep_graph.cycles) if dep_graph else 0
    pts = 10 - min(10, n_cycles*2)
    comps.append(Component("Dependency Cycles", 10, round(max(0,pts),2),
        f"{n_cycles} cycles detected"))

    # --- Repository (30) ---
    # Footprint (15) + File count sanity (15)
    mib = repo_bytes / 1_048_576
    if mib < 100: f_pts = 15
    elif mib < 500: f_pts = 12
    elif mib < 1024: f_pts = 8
    elif mib < 4096: f_pts = 4
    else: f_pts = 1
    comps.append(Component("Repository Footprint", 15, float(f_pts), f"{mib:.1f} MiB source"))

    n = len(files)
    if n < 1000: n_pts = 15
    elif n < 5000: n_pts = 12
    elif n < 20000: n_pts = 8
    elif n < 50000: n_pts = 4
    else: n_pts = 1
    comps.append(Component("File Count", 15, float(n_pts), f"{n} source files parsed"))

    evaluated = [c for c in comps if c.points is not None]
    total = round(sum(c.points for c in evaluated), 2)
    max_eval = sum(c.max_points for c in evaluated)
    normalized = round(total * (100.0 / max_eval), 2) if max_eval else 0.0
    return {
        "score": normalized,
        "raw_points": total,
        "max_evaluated": max_eval,
        "max_total": 100,
        "components": [asdict(c) for c in comps],
    }
