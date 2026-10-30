from __future__ import annotations
import asyncio, json, os, time
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..models import ScanConfig
from ..persistence.db import DB
from ..engine import Engine

BASE_DIR = Path(__file__).parent

def create_app(db: Optional[DB] = None, engine: Optional[Engine] = None) -> FastAPI:
    db = db or DB()
    engine = engine or Engine(db=db)
    app = FastAPI(title="RepoDoctor", version="0.1.0")
    app.mount("/static", StaticFiles(directory=str(BASE_DIR/"static")), name="static")
    templates = Jinja2Templates(directory=str(BASE_DIR/"templates"))
    templates.env.filters["fromjson"] = json.loads

    def _scan_row(scan_id):
        row = db.get_scan(scan_id)
        if not row: raise HTTPException(404, "scan not found")
        return row

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        scans = db.list_scans()
        return templates.TemplateResponse(request, "index.html", {"request": request, "scans": scans})

    @app.get("/new", response_class=HTMLResponse)
    def new_scan(request: Request):
        return templates.TemplateResponse(request, "new.html", {"request": request})

    @app.post("/scans", response_class=HTMLResponse)
    def submit_scan(request: Request,
                    target: str = Form(...),
                    deep: Optional[str] = Form(None),
                    branch: Optional[str] = Form(None),
                    stale_days: int = Form(90),
                    complexity: int = Form(10),
                    clone_tokens: int = Form(20),
                    clone_lines: int = Form(5),
                    ignore: str = Form("")):
        extra = [x.strip() for x in (ignore or "").split(",") if x.strip()]
        cfg = ScanConfig(
            target=target.strip(),
            deep_git_audit=bool(deep),
            branch=(branch or None),
            stale_days=stale_days,
            complexity_refactor_threshold=complexity,
            clone_min_tokens=clone_tokens,
            clone_min_lines=clone_lines,
        )
        if extra: cfg.ignore_patterns = list(set(cfg.ignore_patterns + extra))
        sid = engine.submit(cfg)
        return HTMLResponse("", headers={"HX-Redirect": f"/scans/{sid}"})

    @app.get("/scans/{sid}", response_class=HTMLResponse)
    def scan_detail(request: Request, sid: str):
        row = _scan_row(sid)
        return templates.TemplateResponse(request, "scan.html", {"request": request, "scan": row})

    @app.get("/scans/{sid}/pane/{name}", response_class=HTMLResponse)
    def scan_pane(request: Request, sid: str, name: str):
        row = _scan_row(sid)
        state = row["state"]
        if state != "COMPLETED":
            return HTMLResponse(f"<div class='notice'>Scan state: <b>{state}</b>. Panels available after completion.</div>")
        summary = json.loads(row["summary_json"] or "{}")
        score   = json.loads(row["score_json"] or "{}")
        ctx = {"request": request, "sid": sid, "scan": row, "summary": summary, "score": score}
        if name == "overview":
            ctx["branches"] = db.exec("SELECT * FROM branches WHERE scan_id=? ORDER BY age_days DESC LIMIT 20",(sid,))
            ctx["top_fns"] = db.exec("SELECT * FROM functions WHERE scan_id=? ORDER BY complexity DESC LIMIT 10",(sid,))
            ctx["cycles"] = db.exec("SELECT * FROM dependency_cycles WHERE scan_id=? LIMIT 10",(sid,))
            return templates.TemplateResponse(request, "pane_overview.html", ctx)
        if name == "git":
            ctx["branches"] = db.exec("SELECT * FROM branches WHERE scan_id=? ORDER BY age_days DESC",(sid,))
            ctx["blobs"]    = db.exec("SELECT * FROM git_objects WHERE scan_id=? ORDER BY disk_size DESC",(sid,))
            return templates.TemplateResponse(request, "pane_git.html", ctx)
        if name == "code":
            ctx["fns"] = db.exec("SELECT * FROM functions WHERE scan_id=? ORDER BY complexity DESC LIMIT 500",(sid,))
            ctx["clusters"] = db.exec("SELECT * FROM clone_clusters WHERE scan_id=? ORDER BY members DESC LIMIT 100",(sid,))
            # inline members
            cluster_members = {}
            for c in ctx["clusters"]:
                cluster_members[c["id"]] = db.exec("SELECT * FROM clone_members WHERE cluster_id=?",(c["id"],))
            ctx["cluster_members"] = cluster_members
            return templates.TemplateResponse(request, "pane_code.html", ctx)
        if name == "deps":
            return templates.TemplateResponse(request, "pane_deps.html", ctx)
        if name == "findings":
            ctx["findings"] = db.exec("SELECT * FROM findings WHERE scan_id=? ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 WHEN 'LOW' THEN 3 ELSE 4 END",(sid,))
            return templates.TemplateResponse(request, "pane_findings.html", ctx)
        if name == "artifacts":
            ctx["artifacts"] = db.exec("SELECT * FROM artifacts WHERE scan_id=?",(sid,))
            return templates.TemplateResponse(request, "pane_artifacts.html", ctx)
        raise HTTPException(404)

    # ---- JSON API ----
    @app.post("/api/scans")
    def api_submit(payload: dict):
        cfg = ScanConfig(target=payload["target"], deep_git_audit=bool(payload.get("deep_git_audit")),
                         branch=payload.get("branch"))
        sid = engine.submit(cfg)
        return {"scan_id": sid}

    @app.get("/api/scans/{sid}")
    def api_scan(sid: str):
        row = _scan_row(sid)
        return dict(row)

    @app.get("/api/scans/{sid}/summary")
    def api_summary(sid: str):
        row = _scan_row(sid)
        return {"state": row["state"], "summary": json.loads(row["summary_json"] or "{}"),
                "score": json.loads(row["score_json"] or "{}")}

    @app.get("/api/scans/{sid}/findings")
    def api_findings(sid: str):
        return [dict(r) for r in db.exec("SELECT * FROM findings WHERE scan_id=?",(sid,))]

    @app.get("/api/scans/{sid}/complexity")
    def api_complexity(sid: str):
        return [dict(r) for r in db.exec("SELECT file,name,start_line,end_line,lines,complexity,classification FROM functions WHERE scan_id=?",(sid,))]

    @app.get("/api/scans/{sid}/clones")
    def api_clones(sid: str):
        clusters = db.exec("SELECT * FROM clone_clusters WHERE scan_id=?",(sid,))
        out = []
        for c in clusters:
            members = db.exec("SELECT * FROM clone_members WHERE cluster_id=?",(c["id"],))
            out.append({"id": c["id"], "structural_hash": c["structural_hash"],
                        "token_count": c["token_count"], "members": [dict(m) for m in members]})
        return out

    @app.get("/api/scans/{sid}/dependency-graph")
    def api_depgraph(sid: str):
        nodes = db.exec("SELECT module,file FROM dependency_nodes WHERE scan_id=?",(sid,))
        edges = db.exec("SELECT src,dst FROM dependency_edges WHERE scan_id=?",(sid,))
        cycles = [dict(r) for r in db.exec("SELECT * FROM dependency_cycles WHERE scan_id=?",(sid,))]
        for c in cycles:
            c["modules"] = json.loads(c["modules_json"]); c["edges"] = json.loads(c["edges_json"]); c["path"] = json.loads(c["path_json"])
        cycle_nodes = {m for c in cycles for m in c["modules"]}
        cycle_edges = {(a,b) for c in cycles for a,b in c["edges"]}
        return {"nodes":[{"id":r["module"],"file":r["file"],"in_cycle": r["module"] in cycle_nodes} for r in nodes],
                "edges":[{"source":r["src"],"target":r["dst"],"in_cycle": (r["src"],r["dst"]) in cycle_edges} for r in edges],
                "cycles": cycles}

    @app.get("/api/scans/{sid}/treemap")
    def api_treemap(sid: str):
        # read from analysis.json artifact
        rows = db.exec("SELECT path FROM artifacts WHERE scan_id=? AND name='analysis.json'",(sid,))
        if not rows: return []
        try:
            data = json.loads(Path(rows[0]["path"]).read_text("utf-8"))
            return data.get("treemap", [])
        except Exception:
            return []

    @app.get("/api/scans/{sid}/events")
    async def api_events(sid: str):
        broker = engine.broker(sid)
        async def gen():
            # replay persisted events
            for ev in db.exec("SELECT ts,stage,status,message FROM scan_events WHERE scan_id=? ORDER BY id",(sid,)):
                yield f"data: {json.dumps(dict(ev))}\n\n"
            while True:
                try:
                    ev = await asyncio.get_event_loop().run_in_executor(None, broker.q.get, True, 15)
                except Exception:
                    yield ": keepalive\n\n"; continue
                yield f"data: {json.dumps(ev)}\n\n"
                if ev.get("stage") == "end": break
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/scans/{sid}/artifacts/{name}")
    def api_artifact(sid: str, name: str):
        # protect against path traversal: artifacts live in a per-scan directory and names are whitelisted
        row = db.exec("SELECT path FROM artifacts WHERE scan_id=? AND name=?",(sid,name))
        if not row: raise HTTPException(404)
        p = Path(row[0]["path"]).resolve()
        base = (engine.artifacts_root / sid).resolve()
        if not str(p).startswith(str(base) + os.sep):
            raise HTTPException(400, "invalid artifact path")
        return FileResponse(p, filename=name)

    return app
