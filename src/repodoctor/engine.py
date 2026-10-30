from __future__ import annotations
import json, time, uuid, threading, queue, traceback
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from .models import ScanConfig, ScanState, to_jsonable
from .persistence.db import DB
from .ingestion.ingest import ingest, cleanup, Ingested
from .git.analyze import analyze as git_analyze
from .analysis.scan import collect_files, FileRecord
from .analysis.complexity import compute_complexity
from .analysis.clones import detect_clones
from .analysis.dependencies import build as build_deps
from .analysis.footprint import treemap as build_treemap
from .scoring.score import compute as compute_score
from .reports.findings import complexity_findings, clone_findings, cycle_findings, branch_findings, blob_findings
from .reports.report import write_health_md, write_cleanup_script, write_analysis_json

class _ScanBroker:
    """Per-scan SSE channel."""
    def __init__(self):
        self.q: "queue.Queue[dict]" = queue.Queue()
        self.done = False
    def emit(self, ev: dict):
        if not self.done: self.q.put(ev)
    def close(self):
        self.done = True; self.q.put({"stage":"end","status":"closed","message":""})

class Engine:
    def __init__(self, db: Optional[DB] = None, artifacts_root: Optional[Path] = None, max_concurrent: int = 2):
        self.db = db or DB()
        self.artifacts_root = Path(artifacts_root) if artifacts_root else Path.home()/".repodoctor"/"artifacts"
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self._sem = threading.Semaphore(max_concurrent)
        self._brokers: dict[str, _ScanBroker] = {}
        self._lock = threading.Lock()

    def broker(self, scan_id: str) -> _ScanBroker:
        with self._lock:
            b = self._brokers.get(scan_id)
            if not b:
                b = _ScanBroker(); self._brokers[scan_id] = b
            return b

    def submit(self, config: ScanConfig) -> str:
        scan_id = uuid.uuid4().hex[:16]
        self.db.create_scan(scan_id, config.target, ScanState.CREATED.value, json.dumps(to_jsonable(config)))
        t = threading.Thread(target=self._run, args=(scan_id, config), daemon=True)
        t.start()
        return scan_id

    def _emit(self, scan_id, stage, status, message=""):
        self.db.add_event(scan_id, stage, status, message)
        self.broker(scan_id).emit({"stage":stage, "status":status, "message":message, "ts": time.time()})

    def _run(self, scan_id: str, config: ScanConfig):
        with self._sem:
            ing: Optional[Ingested] = None
            try:
                self.db.set_state(scan_id, ScanState.VALIDATING.value)
                self._emit(scan_id, "validation", "running", config.target)
                self._emit(scan_id, "validation", "done")

                self.db.set_state(scan_id, ScanState.INGESTING.value)
                self._emit(scan_id, "ingestion", "running")
                ing = ingest(config.target, deep_git_audit=config.deep_git_audit)
                self._emit(scan_id, "ingestion", "done",
                           f"git={ing.is_git} remote={ing.is_remote} latency={ing.clone_latency_s:.2f}s")

                self.db.set_state(scan_id, ScanState.ANALYZING.value)

                # Git
                self._emit(scan_id, "git", "running")
                git_rep = git_analyze(
                    ing.path, clone_latency_s=ing.clone_latency_s, is_git=ing.is_git,
                    stale_days=config.stale_days, deep_audit=config.deep_git_audit,
                    target_ref=config.branch, max_deep_audit_bytes=config.max_deep_audit_bytes,
                )
                self._emit(scan_id, "git", "done",
                           f"branches={len(git_rep.branches)} blobs={len(git_rep.blobs)}")

                # Parse / collect
                self._emit(scan_id, "parsing", "running")
                files = collect_files(ing.path, config.ignore_patterns,
                                      max_files=config.max_files, max_source_bytes=config.max_source_bytes)
                self._emit(scan_id, "parsing", "done", f"files={len(files)}")

                # Complexity
                self._emit(scan_id, "complexity", "running")
                func_rows = []
                for fr in files:
                    if not fr.parse_ok: continue
                    abs_p = ing.path / fr.path
                    try: data = abs_p.read_bytes()
                    except OSError: continue
                    func_rows.extend(compute_complexity(abs_p, fr.path, data))
                self._emit(scan_id, "complexity", "done", f"functions={len(func_rows)}")

                # Clones
                self._emit(scan_id, "clones", "running")
                clone_input = []
                for fr in files:
                    if not fr.parse_ok: continue
                    abs_p = ing.path / fr.path
                    try: data = abs_p.read_bytes()
                    except OSError: continue
                    clone_input.append((abs_p, fr.path, data))
                clusters = detect_clones(clone_input,
                                         min_tokens=config.clone_min_tokens,
                                         min_lines=config.clone_min_lines)
                self._emit(scan_id, "clones", "done", f"clusters={len(clusters)}")

                # Dependencies
                self._emit(scan_id, "dependencies", "running")
                dep_graph = build_deps(ing.path, [ing.path / fr.path for fr in files])
                self._emit(scan_id, "dependencies", "done",
                           f"nodes={len(dep_graph.nodes)} edges={len(dep_graph.edges)} cycles={len(dep_graph.cycles)}")

                # Footprint
                tm = build_treemap(ing.path, config.ignore_patterns)
                repo_bytes = sum(x["size"] for x in tm)

                # Findings
                findings = []
                findings += complexity_findings(func_rows, threshold=config.complexity_refactor_threshold)
                findings += clone_findings(clusters)
                findings += cycle_findings(dep_graph)
                findings += branch_findings(git_rep, stale_days=config.stale_days)
                findings += blob_findings(git_rep)

                # Score
                score = compute_score(git_report=git_rep, functions=func_rows,
                                      clone_clusters=clusters, dep_graph=dep_graph,
                                      files=files, repo_bytes=repo_bytes)

                # Persist
                self._persist(scan_id, files, git_rep, func_rows, clusters, dep_graph, findings)

                # Artifacts
                self.db.set_state(scan_id, ScanState.GENERATING_ARTIFACTS.value)
                self._emit(scan_id, "report", "running")
                art_dir = self.artifacts_root / scan_id
                art_dir.mkdir(parents=True, exist_ok=True)
                limitations = []
                if not ing.is_git: limitations.append("Target is not a Git repository; Git-only features marked NOT EVALUATED.")
                if not config.deep_git_audit: limitations.append("Deep Git audit disabled; historical blob sizes NOT EVALUATED.")
                if git_rep.blob_note == "INCOMPLETE — resource limit reached":
                    limitations.append("Deep audit stopped at the configured byte limit; blob list may be incomplete.")
                analysis_payload = {
                    "scan_id": scan_id,
                    "target": config.target,
                    "config": to_jsonable(config),
                    "git": to_jsonable(git_rep),
                    "files": [asdict(f) for f in files],
                    "functions": [asdict(f) for f in func_rows],
                    "clones": [{"structural_hash":c.structural_hash,"token_count":c.token_count,
                                "members":[asdict(m) for m in c.members]} for c in clusters],
                    "dependencies": {"nodes": dep_graph.nodes, "edges": dep_graph.edges, "cycles": dep_graph.cycles},
                    "treemap": tm,
                    "findings": [asdict(f) for f in findings],
                    "score": score,
                }
                aj = write_analysis_json(art_dir, to_jsonable(analysis_payload))
                hp = write_health_md(art_dir, config=config, meta=git_rep.meta, score=score,
                                     git_report=git_rep, functions=func_rows, clusters=clusters,
                                     dep_graph=dep_graph, files=files, findings=findings,
                                     limitations=limitations)
                cp = write_cleanup_script(art_dir, git_rep.blobs)
                for name, path in [("HEALTH.md", hp), ("git-cleanup.sh", cp), ("analysis.json", aj)]:
                    self.db.exec("INSERT OR REPLACE INTO artifacts(scan_id,name,path,bytes) VALUES(?,?,?,?)",
                                 (scan_id, name, str(path), path.stat().st_size))

                summary = {
                    "is_git": ing.is_git,
                    "files": len(files),
                    "functions": len(func_rows),
                    "clusters": len(clusters),
                    "cycles": len(dep_graph.cycles),
                    "branches": len(git_rep.branches),
                    "stale_branches": sum(1 for b in git_rep.branches if b.stale),
                    "blobs": len(git_rep.blobs),
                    "repo_bytes": repo_bytes,
                    "findings": len(findings),
                }
                self.db.set_summary(scan_id, json.dumps(summary), json.dumps(score))
                self._emit(scan_id, "report", "done", f"artifacts in {art_dir}")

                self.db.set_state(scan_id, ScanState.COMPLETED.value)
                self._emit(scan_id, "scan", "completed")
            except Exception as e:
                tb = traceback.format_exc()
                self.db.set_state(scan_id, ScanState.FAILED.value, error=str(e))
                self._emit(scan_id, "scan", "failed", str(e))
                self._emit(scan_id, "scan", "trace", tb[-800:])
            finally:
                self.broker(scan_id).close()
                if ing is not None:
                    try: cleanup(ing)
                    except Exception: pass

    def _persist(self, scan_id, files, git_rep, functions, clusters, dep_graph, findings):
        db = self.db
        # files
        db.execmany("INSERT INTO files(scan_id,path,language,bytes,lines,parse_ok,syntax_errors) VALUES(?,?,?,?,?,?,?)",
            [(scan_id, f.path, f.language, f.bytes, f.lines, int(f.parse_ok), f.syntax_errors) for f in files])
        # git
        db.execmany("INSERT INTO branches(scan_id,name,last_commit,last_commit_date,age_days,merged_state,stale,safe_to_delete) VALUES(?,?,?,?,?,?,?,?)",
            [(scan_id,b.name,b.last_commit,b.last_commit_date,b.age_days,b.merged_state,int(b.stale),int(b.safe_to_delete)) for b in git_rep.branches])
        db.execmany("INSERT INTO git_objects(scan_id,path,blob_id,raw_size,disk_size,origin_commit,origin_date) VALUES(?,?,?,?,?,?,?)",
            [(scan_id,b.path,b.blob_id,b.raw_size,b.disk_size,b.origin_commit,b.origin_date) for b in git_rep.blobs])
        # functions
        db.execmany("INSERT INTO functions(scan_id,file,name,start_line,end_line,lines,complexity,classification) VALUES(?,?,?,?,?,?,?,?)",
            [(scan_id,f.file,f.name,f.start_line,f.end_line,f.lines,f.complexity,f.classification) for f in functions])
        # clones
        for c in clusters:
            cid = db.insert("INSERT INTO clone_clusters(scan_id,structural_hash,token_count,members) VALUES(?,?,?,?)",
                    (scan_id, c.structural_hash, c.token_count, len(c.members)))
            db.execmany("INSERT INTO clone_members(cluster_id,file,start_line,end_line,line_count) VALUES(?,?,?,?,?)",
                [(cid, m.file, m.start_line, m.end_line, m.line_count) for m in c.members])
        # deps
        db.execmany("INSERT INTO dependency_nodes(scan_id,module,file) VALUES(?,?,?)",
            [(scan_id, k, v) for k,v in dep_graph.nodes.items()])
        db.execmany("INSERT INTO dependency_edges(scan_id,src,dst) VALUES(?,?,?)",
            [(scan_id, a, b) for a,b in dep_graph.edges])
        for cy in dep_graph.cycles:
            db.exec("INSERT INTO dependency_cycles(scan_id,modules_json,edges_json,path_json) VALUES(?,?,?,?)",
                    (scan_id, json.dumps(cy["modules"]), json.dumps(cy["edges"]), json.dumps(cy["path"])))
        # findings
        db.execmany("INSERT INTO findings(scan_id,severity,category,title,path,evidence,threshold,remediation) VALUES(?,?,?,?,?,?,?,?)",
            [(scan_id,f.severity,f.category,f.title,f.path,f.evidence,f.threshold,f.remediation) for f in findings])
