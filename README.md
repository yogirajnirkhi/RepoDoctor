# RepoDoc
Local repository health analyzer. Scans Git bloat, stale branches, code clones, cyclomatic complexity, dependency cycles, and repository footprint without executing repository code.


<div align="center">
  <table border="0" cellpadding="10" cellspacing="0">
    <tr>
      <td align="center" valign="middle">
        <a href="https://github.com/user-attachments/assets/2fdb1137-6874-40f8-a08e-ca0c8585ea03" target="_blank">
          <img src="https://github.com/user-attachments/assets/2fdb1137-6874-40f8-a08e-ca0c8585ea03" alt="Image 1" height="300" />
        </a>
      </td>
      <td align="center" valign="middle">
        <a href="https://github.com/user-attachments/assets/ec0dd0e4-e13f-43f4-b2f8-5b4d7b178bb9" target="_blank">
          <img src="https://github.com/user-attachments/assets/ec0dd0e4-e13f-43f4-b2f8-5b4d7b178bb9" alt="Image 2" height="300" />
        </a>
      </td>
    </tr>
    <tr>
      <td align="center" valign="middle">
        <a href="https://github.com/user-attachments/assets/9d1c4789-4952-41bb-908a-cabb6463775f" target="_blank">
          <img src="https://github.com/user-attachments/assets/9d1c4789-4952-41bb-908a-cabb6463775f" alt="Image 3" height="300" />
        </a>
      </td>
      <td align="center" valign="middle">
        <a href="https://github.com/user-attachments/assets/70a30fbd-a9de-41b0-868d-420a98900971" target="_blank">
          <img src="https://github.com/user-attachments/assets/70a30fbd-a9de-41b0-868d-420a98900971" alt="Image 4" height="300" />
        </a>
      </td>
    </tr>
    <tr>
      <td align="center" valign="middle">
        <a href="https://github.com/user-attachments/assets/724181cd-4155-4920-b417-187e3c00cc28" target="_blank">
          <img src="https://github.com/user-attachments/assets/724181cd-4155-4920-b417-187e3c00cc28" alt="Image 5" height="300" />
        </a>
      </td>
      <td align="center" valign="middle">
        <a href="https://github.com/user-attachments/assets/48396322-1862-4146-b0fb-4f2bc6f05b2f" target="_blank">
          <img src="https://github.com/user-attachments/assets/48396322-1862-4146-b0fb-4f2bc6f05b2f" alt="Image 6" height="300" />
        </a>
      </td>
    </tr>
    <tr>
      <td colspan="2" align="center" valign="middle">
        <a href="https://github.com/user-attachments/assets/45e3ed72-cd98-46d3-b873-6de567b2c2ee" target="_blank">
          <img src="https://github.com/user-attachments/assets/45e3ed72-cd98-46d3-b873-6de567b2c2ee" alt="Image 7" height="300" />
        </a>
      </td>
    </tr>
  </table>
</div>


## 1. Overview

**RepoDoctor** is a local repository health analyzer. It scans Git repositories (local or remote) for code and repository health issues without ever executing repository code. It detects:

- **Git bloat** — large historical blobs and object bloat (deep audit mode)
- **Stale branches** — branches inactive beyond a threshold, merge status, safe-to-delete hints
- **Type-2 structural code clones** — duplicated code across files via tree-sitter parsing
- **Cyclomatic complexity** — per-function McCabe complexity across Python, Go, JS, TS, C, C++
- **Internal dependency cycles** — import/include cycles within the repository
- **Repository footprint** — file/directory size treemap

**Security guarantee:** Never executes repository code. Clones use `--no-checkout`, `--filter=blob:none`, disabled hooks, `GIT_CONFIG_NOSYSTEM`, and `GIT_ASKPASS=echo` for untrusted remotes.

---

## 2. Project Structure

```
repodoctor/
├── pyproject.toml             # Package metadata, dependencies, entry point
├── repodoctor.spec            # PyInstaller spec (standalone EXE build)
├── README.md                  # User-facing install/run docs
├── BUILD_NOTES.md             # Build & run notes (Windows dev)
├── PROJECT_SUMMARY.md         # This file
├── src/repodoctor/            # Source (src-layout)
│   ├── __init__.py            # __version__ = "0.1.0"
│   ├── __main__.py            # PyInstaller entry point (absolute imports)
│   ├── cli.py                 # CLI: serve / scan / version / cleanup-cache
│   ├── models.py              # ScanConfig, ScanState, Severity, Finding, to_jsonable
│   ├── engine.py              # Orchestrates scan pipeline + SQLite persistence
│   ├── git/analyze.py         # Git metadata, branches, deep blob audit
│   ├── ingestion/ingest.py    # Local path validation + remote git clone
│   ├── persistence/db.py      # SQLite schema (WAL) + scan/event/artifact CRUD
│   ├── scoring/score.py       # 0-100 health score (Git 25 / Code 45 / Repo 30)
│   ├── reports/findings.py    # Severity-classified findings per category
│   ├── reports/report.py      # HEALTH.md, analysis.json, git-cleanup.sh writers
│   ├── analysis/
│   │   ├── parsers.py         # tree-sitter language binding + parse
│   │   ├── scan.py            # File collection, ignore filtering, parse records
│   │   ├── complexity.py      # McCabe complexity per function (language-specific)
│   │   ├── clones.py          # Structural clone detection (normalized s-expressions)
│   │   ├── dependencies.py    # Import graph + Tarjan SCC cycle detection
│   │   └── footprint.py       # Directory/file size treemap
│   ├── app/
│   │   ├── server.py          # FastAPI web UI + JSON API + SSE event stream
│   │   ├── templates/         # Jinja2 HTML templates (server-rendered)
│   │   └── static/            # Vendored CSS, JS, ECharts (no CDN/Node required)
│   └── reports/
├── tests/                     # pytest suite (httpx for UI tests)
│   ├── conftest.py            # src path insertion
│   ├── test_clones.py
│   ├── test_complexity.py
│   ├── test_deps.py
│   ├── test_engine_local.py
│   ├── test_ingestion_security.py
│   ├── test_scoring.py
│   ├── test_ui_routes.py
├── build/                     # PyInstaller build intermediates
├── dist/                      # Built artifacts (repodoctor.exe)
├── docs/architecture.md       # Stub: "see spec §3"
```

---

## 3. Interface(CLI/WebUI)

Entry point: `repodoctor = "repodoctor.cli:main"` (also `__main__.py` for PyInstaller)

| Command | Description |
|---------|-------------|
| `repodoctor` | Start web UI (`http://127.0.0.1:8080`) |
| `repodoctor serve [--host H] [--port P]` | Start web UI on host/port |
| `repodoctor scan <target> [--deep-git-audit] [--branch B]` | Scan a local path or Git URL |
| `repodoctor version` | Print version |
| `repodoctor cleanup-cache` | Remove temp clone directories under `/tmp/repodoctor` |

**Default bind:** loopback only (`127.0.0.1`).

---

## 4. Scan Pipeline (Engine)

The `Engine` (`src/repodoctor/engine.py`) runs scans as daemon threads with per-scan SSE event channels and SQLite persistence. Pipeline stages:

1. **VALIDATING** — target validation
2. **INGESTING** — clone/fetch repo (local path or remote `git clone --filter=blob:none --depth=100`)
3. **ANALYZING** — parallel sub-analyses:
   - **Git** — metadata, branches, deep blob audit (optional)
   - **Parsing** — collect source files, tree-sitter parse
   - **Complexity** — McCabe per function
   - **Clones** — structural clone clusters
   - **Dependencies** — import graph + cycle detection
   - **Footprint** — file size treemap
4. **GENERATING_ARTIFACTS** — write HEALTH.md, analysis.json, git-cleanup.sh
5. **COMPLETED / FAILED / CANCELLED**

**Scan limits (ScanConfig):**
- `stale_days`: 90
- `complexity_refactor_threshold`: 10
- `clone_min_tokens`: 20, `clone_min_lines`: 5
- `max_deep_audit_bytes`: 2 GiB
- `max_files`: 50,000
- `max_source_bytes`: 512 MiB
- `max_scan_duration_s`: 1800
- `max_graph_nodes`: 500
- `workers`: 2, `cache_ttl_s`: 3600
- Default ignores: `.git`, `node_modules`, `vendor`, `venv`, `.venv`, `__pycache__`, `dist`, `build`, `target`, `coverage`, `.cache`, `.idea`, `.vscode`

**States:** CREATED, VALIDATING, INGESTING, ANALYZING, GENERATING_ARTIFACTS, COMPLETED, FAILED, CANCELLED

---

## 5. Analysis Modules

### 5.1 Git Analysis (`git/analyze.py`)
- **RepoMeta:** HEAD, default branch, branch count, commit count, repo age, clone latency
- **BranchInfo:** name, last commit, age days, merged state (MERGED/UNMERGED/UNKNOWN/UNKNOWN_DUE_TO_SHALLOW_HISTORY), stale flag, safe-to-delete
- **BlobInfo:** path, blob ID, raw size, disk size, origin commit/date
- **Deep audit:** `git fetch --unshallow`, `cat-file --batch-check`, top-N largest blobs, byte-limit truncation

### 5.2 Ingestion (`ingestion/ingest.py`)
- Remote targets (http/https/git@/ssh://) cloned to `/tmp/repodoctor/<hash>/<uuid>/repo`
- Local paths validated via `canonical_local()` (traversal/read checks)
- `cleanup_cache(max_age_s=0)` removes all temp dirs

### 5.3 Complexity (`analysis/complexity.py`)
McCabe `M` per function. Decision node types per language (python, go, javascript, typescript, c, cpp). Classification: LOW (<=5), MODERATE (<=10), HIGH (<=20), VERY HIGH (>20). Short-circuit `&&`/`||` counted as decisions.

### 5.4 Clones (`analysis/clones.py`)
Type-2 structural clones via normalized s-expressions. Identifiers/literals normalized to type-only. Requires clones across >=2 files, >=2 members. Overlap merging within same file.

### 5.5 Dependencies (`analysis/dependencies.py`)
Import/include graph for Python, Go, JS/TS, C/C++. Cycle detection via Tarjan's strongly connected components (SCC size > 1, plus self-loops).

### 5.6 Footprint (`analysis/footprint.py`)
File-by-file size treemap with percentage of total. Ignores configured patterns.

---

## 6. Scoring (`scoring/score.py`)

0–100 health score, normalized across evaluated components:

| Component | Max Points | Details |
|-----------|-----------|---------|
| Git Object Bloat | 10 | Blobs > 10 MiB penalized |
| Stale Branches | 15 | Ratio of stale branches |
| Cyclomatic Complexity | 20 | Functions > threshold |
| Structural Clones | 15 | Clusters + members count |
| Dependency Cycles | 10 | Cycle count |
| Repository Footprint | 15 | Size tiers (<100 MiB best) |
| File Count | 15 | File count tiers (<1000 best) |

Components not evaluated (e.g., non-Git repos, deep audit disabled) score `None` and are excluded from the denominator.

---

## 7. Findings (`reports/findings.py`)

Severity-classified findings:

| Category | Severity | Trigger |
|----------|----------|---------|
| complexity | MEDIUM/HIGH/CRITICAL | Function complexity > threshold |
| clone | LOW/MEDIUM/HIGH | Structural clone clusters |
| dependency_cycle | HIGH | Any dependency cycle |
| stale_branch | LOW/INFO | Stale branch (merged=LOW, else INFO) |
| git_bloat | LOW/MEDIUM/HIGH | Large historical blobs |

Each finding includes: severity, category, title, path, evidence, threshold, remediation.

---

## 8. Reports & Artifacts

Written to `%USERPROFILE%\.repodoctor\artifacts\<scan_id>\`:

| Artifact | Description |
|----------|-------------|
| `analysis.json` | Full scan payload (config, git, files, functions, clones, deps, treemap, findings, score) |
| `HEALTH.md` | Human-readable Markdown health report |
| `git-cleanup.sh` | Non-destructive bash script using `git-filter-repo` to remove large blobs from history (requires `--execute`) |

---

## 9. Database (`persistence/db.py`)

SQLite (WAL mode) at `%USERPROFILE%\.repodoctor\repodoctor.sqlite` (or `REPODOCTOR_HOME` env override).

Tables: `scans`, `scan_events`, `branches`, `commits`, `files`, `git_objects`, `functions`, `clone_clusters`, `clone_members`, `dependency_nodes`, `dependency_edges`, `dependency_cycles`, `findings`, `artifacts`.

---

## 10. Web UI (`app/server.py` + templates + static)

- **Framework:** FastAPI + Uvicorn
- **Templating:** Jinja2 (server-rendered HTML)
- **Frontend:** HTMX, vendored ECharts (local), no Node.js, no CDN, no external fonts
- **Features:** Sidebar navigation, mobile drawer, keyboard shortcut `N` (new scan), health-score ring, complexity scatter plot, footprint treemap, dependency graph (cycle-only/neighborhood/reset), searchable findings with severity/category filters, real artifact downloads, live scan stages via SSE, persisted execution-log replay

**Routes:**
- `GET /` — scan list
- `GET /new` — new scan form
- `POST /scans` — submit scan (HTMX redirect)
- `GET /scans/{sid}` — scan detail
- `GET /scans/{sid}/pane/{name}` — HTMX panes: overview, git, code, deps, findings, artifacts
- `GET /api/scans/{sid}/events` — SSE event stream
- `GET /api/scans/{sid}/artifacts/{name}` — artifact download (path-traversal protected)

---

## 11. Supported Languages

| Language | Extensions | Complexity | Clones | Dependencies |
|----------|-----------|------------|--------|--------------|
| Python | `.py` | Yes | Yes | Import analysis |
| Go | `.go` | Yes | Yes | go.mod + import blocks |
| JavaScript | `.js`, `.mjs`, `.cjs` | Yes | Yes | import/require |
| TypeScript | `.ts`, `.tsx` | Yes | Yes | import/export |
| C | `.c`, `.h` | Yes | Yes | `#include "..."` |
| C++ | `.cc`, `.cpp`, `.cxx`, `.hpp`, `.hh` | Yes | Yes | `#include "..."` |

---


## 12. Tests

```bash
pip install -e '.[test]'
python -m pytest -q
```

Test files: `test_clones.py`, `test_complexity.py`, `test_deps.py`, `test_engine_local.py`, `test_ingestion_security.py`, `test_scoring.py`, `test_ui_routes.py`

---

## 13. Limitations

- Deep Git audit is not proof that all historical objects were evaluated (byte-limit truncation)
- `analysis.json` contains scan status; inspect it for completeness
- UI changes do not replace or extend the underlying analysis engine
- Shallow clones may yield `UNKNOWN_DUE_TO_SHALLOW_HISTORY` merge states
- `git-cleanup.sh` rewrites history; requires collaborator re-clone and manual force-push
