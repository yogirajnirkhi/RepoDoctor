from __future__ import annotations
import sqlite3, json, threading, os, time
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS scans (
  id TEXT PRIMARY KEY,
  target TEXT NOT NULL,
  state TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  config_json TEXT NOT NULL,
  summary_json TEXT,
  score_json TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_scans_state ON scans(state);
CREATE INDEX IF NOT EXISTS idx_scans_created ON scans(created_at);

CREATE TABLE IF NOT EXISTS scan_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  ts REAL NOT NULL,
  stage TEXT NOT NULL,
  status TEXT NOT NULL,
  message TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_scan ON scan_events(scan_id, id);

CREATE TABLE IF NOT EXISTS branches (
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  last_commit TEXT,
  last_commit_date REAL,
  age_days REAL,
  merged_state TEXT,
  stale INTEGER,
  safe_to_delete INTEGER
);
CREATE INDEX IF NOT EXISTS idx_branches_scan ON branches(scan_id);

CREATE TABLE IF NOT EXISTS commits (
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  sha TEXT NOT NULL,
  author TEXT,
  ts REAL,
  subject TEXT
);
CREATE INDEX IF NOT EXISTS idx_commits_scan ON commits(scan_id);

CREATE TABLE IF NOT EXISTS files (
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  path TEXT NOT NULL,
  language TEXT,
  bytes INTEGER,
  lines INTEGER,
  parse_ok INTEGER,
  syntax_errors INTEGER
);
CREATE INDEX IF NOT EXISTS idx_files_scan ON files(scan_id);
CREATE INDEX IF NOT EXISTS idx_files_lang ON files(scan_id, language);

CREATE TABLE IF NOT EXISTS git_objects (
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  path TEXT,
  blob_id TEXT,
  raw_size INTEGER,
  disk_size INTEGER,
  origin_commit TEXT,
  origin_date REAL
);
CREATE INDEX IF NOT EXISTS idx_gitobj_scan ON git_objects(scan_id, disk_size DESC);

CREATE TABLE IF NOT EXISTS functions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  file TEXT NOT NULL,
  name TEXT,
  start_line INTEGER,
  end_line INTEGER,
  lines INTEGER,
  complexity INTEGER,
  classification TEXT
);
CREATE INDEX IF NOT EXISTS idx_fn_scan ON functions(scan_id, complexity DESC);

CREATE TABLE IF NOT EXISTS clone_clusters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  structural_hash TEXT NOT NULL,
  token_count INTEGER,
  members INTEGER
);
CREATE INDEX IF NOT EXISTS idx_cluster_scan ON clone_clusters(scan_id);

CREATE TABLE IF NOT EXISTS clone_members (
  cluster_id INTEGER NOT NULL REFERENCES clone_clusters(id) ON DELETE CASCADE,
  file TEXT NOT NULL,
  start_line INTEGER,
  end_line INTEGER,
  line_count INTEGER
);
CREATE INDEX IF NOT EXISTS idx_cmember_cluster ON clone_members(cluster_id);

CREATE TABLE IF NOT EXISTS dependency_nodes (
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  module TEXT NOT NULL,
  file TEXT
);
CREATE INDEX IF NOT EXISTS idx_depn_scan ON dependency_nodes(scan_id);

CREATE TABLE IF NOT EXISTS dependency_edges (
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  src TEXT NOT NULL,
  dst TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_depe_scan ON dependency_edges(scan_id);

CREATE TABLE IF NOT EXISTS dependency_cycles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  modules_json TEXT NOT NULL,
  edges_json TEXT NOT NULL,
  path_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cycle_scan ON dependency_cycles(scan_id);

CREATE TABLE IF NOT EXISTS findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  severity TEXT,
  category TEXT,
  title TEXT,
  path TEXT,
  evidence TEXT,
  threshold TEXT,
  remediation TEXT
);
CREATE INDEX IF NOT EXISTS idx_findings_scan ON findings(scan_id, severity);

CREATE TABLE IF NOT EXISTS artifacts (
  scan_id TEXT NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  path TEXT NOT NULL,
  bytes INTEGER,
  PRIMARY KEY (scan_id, name)
);
"""

_lock = threading.Lock()

def default_db_path() -> Path:
    base = Path(os.environ.get("REPODOCTOR_HOME", str(Path.home()/".repodoctor")))
    base.mkdir(parents=True, exist_ok=True)
    return base / "repodoctor.sqlite"

class DB:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        c = sqlite3.connect(str(self.path), timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys = ON;")
        c.execute("PRAGMA journal_mode = WAL;")
        return c

    def _init(self):
        with _lock, self.connect() as c:
            c.executescript(SCHEMA)

    def exec(self, sql: str, params: Iterable[Any] = ()):
        with _lock, self.connect() as c:
            cur = c.execute(sql, tuple(params))
            return cur.fetchall()

    def execmany(self, sql: str, rows):
        with _lock, self.connect() as c:
            c.executemany(sql, rows)

    def insert(self, sql: str, params) -> int:
        """INSERT and return lastrowid from the SAME connection."""
        with _lock, self.connect() as c:
            cur = c.execute(sql, tuple(params))
            return int(cur.lastrowid)

    # scan helpers
    def create_scan(self, scan_id, target, state, config_json):
        now = time.time()
        self.exec(
            "INSERT INTO scans(id,target,state,created_at,updated_at,config_json) VALUES(?,?,?,?,?,?)",
            (scan_id, target, state, now, now, config_json),
        )

    def set_state(self, scan_id, state, error=None):
        self.exec("UPDATE scans SET state=?, updated_at=?, error=? WHERE id=?",
                  (state, time.time(), error, scan_id))

    def set_summary(self, scan_id, summary_json, score_json):
        self.exec("UPDATE scans SET summary_json=?, score_json=?, updated_at=? WHERE id=?",
                  (summary_json, score_json, time.time(), scan_id))

    def add_event(self, scan_id, stage, status, message=""):
        self.exec("INSERT INTO scan_events(scan_id,ts,stage,status,message) VALUES(?,?,?,?,?)",
                  (scan_id, time.time(), stage, status, message))

    def get_scan(self, scan_id):
        rows = self.exec("SELECT * FROM scans WHERE id=?", (scan_id,))
        return rows[0] if rows else None

    def list_scans(self, limit=50):
        return self.exec("SELECT id,target,state,created_at FROM scans ORDER BY created_at DESC LIMIT ?", (limit,))
