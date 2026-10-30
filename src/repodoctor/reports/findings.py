from __future__ import annotations
from ..models import Finding, Severity

def complexity_findings(functions, threshold=10):
    out = []
    for f in functions:
        if f.complexity <= threshold: continue
        sev = Severity.MEDIUM if f.complexity <= 20 else Severity.HIGH
        if f.complexity > 40: sev = Severity.CRITICAL
        out.append(Finding(
            severity=sev.value, category="complexity",
            title=f"High cyclomatic complexity in {f.name}",
            path=f.file,
            evidence=f"Cyclomatic complexity = {f.complexity}. Function = {f.name}. Lines {f.start_line}-{f.end_line}.",
            threshold=f"Configured threshold = {threshold}.",
            remediation="Refactor function into smaller units; extract conditionals; apply early-returns.",
        ))
    return out

def clone_findings(clusters):
    out = []
    for c in clusters:
        if len(c.members) < 2: continue
        total_lines = sum(m.line_count for m in c.members)
        sev = Severity.LOW
        if total_lines >= 50 or len(c.members) >= 4: sev = Severity.MEDIUM
        if total_lines >= 150: sev = Severity.HIGH
        members_desc = "; ".join(f"{m.file}:{m.start_line}-{m.end_line}" for m in c.members[:5])
        out.append(Finding(
            severity=sev.value, category="clone",
            title=f"Structural clone across {len(c.members)} locations",
            path=c.members[0].file,
            evidence=f"Normalized tokens = {c.token_count}. Hash = {c.structural_hash[:12]}. Locations: {members_desc}.",
            threshold="Default: 20 tokens, 5 lines, 2+ files.",
            remediation="Extract shared logic into a function/module; consider parameterizing differences.",
        ))
    return out

def cycle_findings(dep_graph):
    out = []
    for i, cy in enumerate(dep_graph.cycles if dep_graph else [], 1):
        mods = cy.get("modules", [])
        path = cy.get("path", [])
        out.append(Finding(
            severity=Severity.HIGH.value, category="dependency_cycle",
            title=f"Dependency cycle involving {len(mods)} module(s)",
            path=mods[0] if mods else "",
            evidence=f"Cycle path: {' -> '.join(path)}. Modules: {', '.join(mods)}.",
            threshold="Any strongly connected component of size > 1 or self-loop.",
            remediation="Break the cycle: introduce an interface, invert a dependency, or move shared code to a lower-level module.",
        ))
    return out

def branch_findings(git_report, stale_days=90):
    out = []
    for b in git_report.branches:
        if not b.stale: continue
        sev = Severity.LOW if b.merged_state == "MERGED" else Severity.INFO
        out.append(Finding(
            severity=sev.value, category="stale_branch",
            title=f"Stale branch {b.name}",
            path=b.name,
            evidence=f"Last commit = {b.last_commit[:12]}; age = {b.age_days:.0f}d; merged state = {b.merged_state}.",
            threshold=f"Stale threshold = {stale_days} days.",
            remediation=("Delete if MERGED and no longer needed."
                        if b.merged_state == "MERGED"
                        else "Review and decide; UNKNOWN_DUE_TO_SHALLOW_HISTORY means proof requires full history."),
        ))
    return out

def blob_findings(git_report):
    out = []
    for b in git_report.blobs:
        sev = Severity.MEDIUM if b.disk_size > 10*1024*1024 else Severity.LOW
        if b.disk_size > 100*1024*1024: sev = Severity.HIGH
        out.append(Finding(
            severity=sev.value, category="git_bloat",
            title=f"Large historical blob {b.path or b.blob_id[:12]}",
            path=b.path or b.blob_id,
            evidence=f"blob={b.blob_id[:12]} raw={b.raw_size} disk={b.disk_size} origin={b.origin_commit[:12]}",
            threshold="> 1 MiB raw.",
            remediation="If unneeded in history, use git-filter-repo (see git-cleanup.sh).",
        ))
    return out
