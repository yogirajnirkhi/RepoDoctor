from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
from . import __version__
from .models import ScanConfig
from .engine import Engine
from .persistence.db import DB
from .ingestion.ingest import cleanup_cache

def _wait(engine: Engine, sid: str, timeout_s: int = 1800):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        row = engine.db.get_scan(sid)
        if not row: time.sleep(0.2); continue
        st = row["state"]
        print(f"\r[{st}]            ", end="", flush=True)
        if st in ("COMPLETED","FAILED","CANCELLED"):
            print(); return st
        time.sleep(0.4)
    return "TIMEOUT"

def _serve(args):
    import uvicorn
    from .app.server import create_app
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")

def _scan(args):
    cfg = ScanConfig(target=args.target,
                     deep_git_audit=args.deep_git_audit,
                     branch=args.branch)
    engine = Engine()
    sid = engine.submit(cfg)
    print("scan_id:", sid)
    st = _wait(engine, sid, timeout_s=cfg.max_scan_duration_s)
    row = engine.db.get_scan(sid)
    summary = json.loads(row["summary_json"] or "{}")
    score   = json.loads(row["score_json"] or "{}")
    print("state:", st)
    print("summary:", json.dumps(summary, indent=2))
    print("score:", score.get("score"), "/100")
    arts = engine.db.exec("SELECT name,path FROM artifacts WHERE scan_id=?",(sid,))
    for a in arts: print(" artifact:", a["name"], "->", a["path"])
    return 0 if st == "COMPLETED" else 1

def _version(args): print(__version__); return 0

def _cleanup(args):
    n = cleanup_cache(0)
    print(f"removed {n} temp directories under /tmp/repodoctor")
    return 0

def main(argv=None):
    p = argparse.ArgumentParser(prog="repodoctor")
    sub = p.add_subparsers(dest="cmd")
    sp = sub.add_parser("serve", help="start the web UI")
    sp.add_argument("--host", default="127.0.0.1"); sp.add_argument("--port", type=int, default=8080)
    sp.set_defaults(fn=_serve)
    sc = sub.add_parser("scan", help="scan a repository")
    sc.add_argument("target")
    sc.add_argument("--deep-git-audit", action="store_true")
    sc.add_argument("--branch", default=None)
    sc.set_defaults(fn=_scan)
    sv = sub.add_parser("version"); sv.set_defaults(fn=_version)
    cl = sub.add_parser("cleanup-cache"); cl.set_defaults(fn=_cleanup)
    args = p.parse_args(argv)
    if not getattr(args, "cmd", None):
        # default: run the server
        return _serve(argparse.Namespace(host="127.0.0.1", port=8080))
    return args.fn(args) or 0

if __name__ == "__main__": sys.exit(main())
