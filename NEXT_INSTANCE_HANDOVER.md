# Next Instance — Handover Instructions

## Status: Phase 1 complete (3/3), Phase 2 next

### Completed (do not redo)
- **Phase 1.2** ✅ — DuckDB write queue default-on (`config.py`)
- **Phase 1.3** ✅ — Feed circuit breakers (`feeds/runner.py`, `feeds/envelope.py`, `config.py`)
- **Phase 1.1** ✅ — Task watchdog (`lifespan.py`, `routes/health.py`, `config.py`)

### Completed outside plan (2026-06-28)
- **P11 Onion Directory** ✅ — curated legitimate .onion services feed (`backend/onion_directory.py`, `backend/test_onion_directory.py`). Fetches `master.csv` + `securedrop-api.csv` from `alecmuffett/real-world-onion-sites`; ingests as FtM `Domain` entities. Config/manifest/flags/routes wired. **Live verified:** 94 entries, 11 categories, 23 SecureDrop instances. No backend restart needed (Uvicorn reload picked it up). Files changed: `onion_directory.py`, `test_onion_directory.py`, `config.py`, `connector_registry.py`, `features.py`, `routes/registry.py`, `backend/.env`, `AGENTS.md`.

### Next task: Phase 2.1 — RBAC scaffolding + audit log

Read `PLAN_EXTERNAL_ANALYSIS.md` §4 (lines 134–165) for the full spec. Summary:

1. Create `backend/auth/audit.py` — SQLite table `auth_audit` with columns: `timestamp`, `client`, `endpoint`, `tool`, `action`, `success`, `error`. Auto-prune retention (default 90 days).
2. Create `backend/auth/rbac.py` — role constants (`operator`, `node`, `readonly`, `admin`), `require_role(...)` FastAPI dependency factory.
3. Integrate audit hooks into `backend/auth/security.py`.
4. Gate MCP write tools in `backend/mcp_server.py` behind `role=operator` when `rbac_enabled=True`.
5. Add `auth_audit` migration to `backend/sqlite_bootstrap.py`.
6. Config: `rbac_enabled` stays `False` by default. Env: `WORLDBASE_RBAC=0`, `WORLDBASE_AUTH_AUDIT=1`, `WORLDBASE_AUTH_AUDIT_RETENTION_DAYS=90`.
7. Write tests in `backend/test_auth_audit_rbac.py`.
8. Update `AGENTS.md` + `PLAN_EXTERNAL_ANALYSIS.md` (mark 2.1 as ✅ DONE).

### After 2.1: Phase 2.2 — Secret management helpers
See `PLAN_EXTERNAL_ANALYSIS.md` §4 lines 167–195.

### Critical constraints
- **Only the user may start/restart the backend.** Never run `start.ps1`, `start.bat`, `uvicorn`, or any backend launch command.
- **Always use `backend\venv\Scripts\python.exe`** for all Python commands.
- **Fail-soft is mandatory** — every new feature must degrade gracefully when disabled.
- **Tests before implementation** — add/update tests before changing production code.
- **No new files unless necessary** — each file must be justified in the plan.
- **Keep defaults safe** — do not flip flags that break single-operator setups.
- **Pre-commit hooks** — activate venv before `git commit`; never use `--no-verify`.
- **`.gitignore` is sacred** — never `git add -f`.
- **Minimal focused edits** — prefer small targeted changes over rewrites.
- After backend changes: tell user explicitly that restart is needed, which files changed, and that only they may start it.

### Test commands
```powershell
# Run specific test file
& 'D:\MCP Mods\worldbase\backend\venv\Scripts\python.exe' -m pytest backend/test_<name>.py -v --tb=short

# Run all Phase 1 tests (regression check)
& 'D:\MCP Mods\worldbase\backend\venv\Scripts\python.exe' -m pytest backend/test_feed_runner.py backend/test_feed_envelope_contract.py backend/test_duckdb_queue.py backend/test_task_watchdog.py -v --tb=short
```

### Files modified in Phase 1 (for context)
- `backend/config.py` — circuit breaker + watchdog config fields
- `backend/feeds/runner.py` — CircuitBreaker class + FeedConnector integration
- `backend/feeds/envelope.py` — circuit_state/circuit_open_until in HEALTH_META_KEYS
- `backend/lifespan.py` — TaskWatchdog class + register_lifecycle integration
- `backend/routes/health.py` — /api/health/tasks endpoint
- `backend/test_feed_runner.py` — 12 circuit breaker tests
- `backend/test_task_watchdog.py` — 12 watchdog tests (new file)
- `AGENTS.md` — docs for circuit breakers + task watchdog
- `PLAN_EXTERNAL_ANALYSIS.md` — 1.1, 1.2, 1.3 marked done
