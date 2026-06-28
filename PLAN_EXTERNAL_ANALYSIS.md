# WorldBase — Implementation Plan: External Analysis Response

> Derived from the code-by-code rebuttal of the external architecture review.  
> Focus: fix the **real** gaps, preserve the existing defenses, and avoid rebuilding things that already work.  
> **Validated against 2026 best practices** (see §10 for sources).

---

## 1. Executive Summary

The external analysis identified 14 items. After matching each claim against the actual code:

- **3 items are fully valid** and should be implemented: secret management, Pi sync conflict resolution, and darkweb/OPSEC hardening.
- **3 items are factually wrong** (Ollama fallback, entity-resolution versioning, live contract tests) — no action required.
- **8 items are partially true** — the gaps they identify are real, but the codebase already has partial defenses. These should be hardened, not rewritten.

This plan therefore targets **11 work packages** grouped into 4 phases. All work is designed to fit the existing single-operator workstation architecture (`d:\MCP Mods\worldbase\backend\main.py`, `lifespan.py`, `config.py`) and keeps the current fail-soft philosophy.

---

## 2. What We Will NOT Do

| External claim | Why no action |
|---|---|
| Ollama `qwen3:8b` has no fallback | Chat stack already uses NVIDIA NIM as primary (`chat_proxy.py`, `chat_routing.py`). Briefing intentionally uses Ollama for offline Pi sync and has `format_fallback_protocol()`. |
| Entity resolution has no versioning | `entity_resolution.py` already tracks `_SPLINK_VERSION`, persists models, timestamps `resolution_labels.labeled_at`, and logs run metadata. |
| No live contract tests | `test_health_contract_live`, `test_feed_envelope_contract.py`, and `scripts/smoke-test.ps1` already probe live endpoints. |

---

## 3. Phase 1 — Core Hardening (highest priority)

### 1.1 Process health watchdog ✅ DONE (2026-06-28)

**Gap:** `main.py` runs one Uvicorn process with `reload=True`. Background tasks are crash-isolated but there is no process supervisor or task death-watch.

**2026 best practice:** `asyncio.create_task` is in-memory only — if the process restarts, all tasks are lost. For non-critical tasks a watchdog + strong reference is the recommended lightweight pattern; for critical tasks Celery+Redis is the enterprise standard. WorldBase's tasks are non-critical (fail-soft), so a watchdog is the right choice. **Key asyncio trap:** tasks can be garbage-collected if no strong reference is held — the watchdog must store references. (Source: dev.to/kaushikcoderpy 2026, FastAPI docs)

**Implemented:**
- ✅ `TaskWatchdog` class in `lifespan.py` with `TaskRecord` dataclass.
- ✅ Holds **strong references** to all `asyncio.Task` objects via `_tasks` dict (prevents GC).
- ✅ Monitors each task: detects crashes (`.done()` + `.exception()`), restarts with max 5 retries.
- ✅ Heartbeat tracking: warns when silent for > `interval * timeout_multiplier`.
- ✅ Resource pressure: RSS memory via `psutil`, event-loop lag via 1s sleep delta (fail-soft if psutil missing).
- ✅ `/api/health/tasks` endpoint in `routes/health.py` returns per-task status + resource metrics.
- ✅ `register_lifecycle()` updated: all 11 background tasks now registered with watchdog (or fallback to bare `create_task` when disabled).
- ✅ Config: `task_watchdog_enabled` (default `True`), `task_watchdog_timeout_multiplier` (default `2.5`).
- ✅ Tests: 12/12 `test_task_watchdog.py` passed (registration, start, heartbeat, crash detection, restart, restart limit, status fields, stop/cancel, timeout calc, monitor integration, silent task detection).
- ✅ No regressions: 38/38 feed runner + envelope + duckdb queue tests passed.
- ✅ `AGENTS.md` updated.

**Files changed:**
- `backend/config.py` — 2 new config fields + env parsing.
- `backend/lifespan.py` — `TaskWatchdog`, `TaskRecord` classes + `register_lifecycle()` integration.
- `backend/routes/health.py` — `/api/health/tasks` endpoint.
- `backend/test_task_watchdog.py` — 12 new tests.
- `AGENTS.md` — docs updated.

**Env:**
```bash
WORLDBASE_TASK_WATCHDOG=1                      # default on
WORLDBASE_TASK_WATCHDOG_TIMEOUT_MULTIPLIER=2.5  # default 2.5x interval
```

**Success metric:** ✅ A deliberately broken background task is detected and restarted; `/api/health/tasks` returns all-green under normal load.

---

### 1.2 Enable DuckDB write queue by default ✅ DONE (2026-06-28)

**Gap:** `duckdb_queue.py` exists as a WAL-backed write-through queue with retry + DLQ, but `config.py` sets `duckdb_queue_enabled: bool = False` by default.

**2026 best practice:** DuckDB's official concurrency docs state: one writer process, MVCC within that process. The recommended pattern for FastAPI is a **write-worker** that owns the only write-capable connection. DuckLake v1.0 (April 2026) adds PostgreSQL-catalog multi-process writes, but that is overkill for a single-operator workstation. For SQLite WAL: `PRAGMA busy_timeout=5000`, `PRAGMA synchronous=NORMAL`, `BEGIN IMMEDIATE` for writes. (Sources: DuckDB concurrency docs, cronfeed.work SQLite WAL 2026, pavanrangani.com SQLite production 2026)

**Implemented:**
- ✅ Switched default to `True` in `config.py` (dataclass + `from_env()`).
- ✅ Updated `AGENTS.md` to reflect default-on.
- ✅ Tests: 12/12 `test_duckdb_queue.py` + 27/27 feed tests passed, 0 regressions.
- ✅ Stresstest: 4/4 PASS after change (upsert p95=46.7ms, entity_graph p95=42.1ms).

**Deferred (lower priority, not blocking):**
- ⏳ SQLite WAL PRAGMAs (`busy_timeout=5000`, `synchronous=NORMAL`) — queue already uses WAL mode; PRAGMAs are a tuning refinement.
- ⏳ Queue health metric on `/api/health/tasks` — depends on Phase 1.1 (task watchdog endpoint).
- ⏳ Backup script verification — `scripts/backup.ps1` already uses `VACUUM INTO`; no change needed.
- ✅ Old direct path available via `WORLDBASE_DUCKDB_QUEUE=0`.

**Files changed:**
- `backend/config.py` — default `True`, env default `"1"`.
- `AGENTS.md` — docs updated.

**Env:**
```bash
WORLDBASE_DUCKDB_QUEUE=1  # now the default
```

---

### 1.3 Feed circuit breakers ✅ DONE (2026-06-28)

**Gap:** `feeds/runner.py` has TTL, stale fallback, and envelope validation, but no exponential backoff or circuit breaker after repeated failures.

**2026 best practice:** The standard 3-state pattern (CLOSED → OPEN → HALF_OPEN → CLOSED) is recommended. `pybreaker` is the mature Python library, but for WorldBase's fail-soft feed model a lightweight in-process implementation is sufficient. Key practices: per-service breakers (not global), meaningful reset timeouts, monitor circuit state, always provide fallbacks. (Sources: blog.greeden.me 2026, oneuptime.com 2026, ines-panker.com 2026, pypi circuitbreaker)

**Implemented:**
- ✅ `CircuitBreaker` class in `feeds/runner.py` with 3-state pattern (CLOSED → OPEN → HALF_OPEN).
- ✅ Exponential backoff: 60s → 120s → 240s, capped at `max_backoff_sec` (default 900s).
- ✅ `FeedConnector.run()` skips fetch when OPEN, serves `stale_from_memory()` / `stale_from_disk()`.
- ✅ `record_success()` resets backoff; `record_failure()` trips breaker after threshold.
- ✅ Breaker state exposed via `FeedConnector.circuit_state` / `.circuit_open_until` properties.
- ✅ `circuit_state` + `circuit_open_until` added to `HEALTH_META_KEYS` and `extract_health_feed_meta()` in `envelope.py`.
- ✅ Config: 4 new fields in `config.py`, all default-on.
- ✅ Tests: 19/19 `test_feed_runner.py` (12 new CB tests) + 7/7 envelope contract = 26/26 passed.
- ✅ `AGENTS.md` updated.

**Files changed:**
- `backend/config.py` — 4 new config fields + env parsing.
- `backend/feeds/runner.py` — `CircuitBreaker`, `CircuitState` classes + `FeedConnector` integration.
- `backend/feeds/envelope.py` — `HEALTH_META_KEYS` + `extract_health_feed_meta()` extended.
- `backend/test_feed_runner.py` — 12 new circuit breaker tests.
- `AGENTS.md` — docs updated.

**Env:**
```bash
WORLDBASE_FEED_CIRCUIT_BREAKER=1              # default on
WORLDBASE_FEED_CB_FAILURE_THRESHOLD=5        # default 5
WORLDBASE_FEED_CB_RESET_TIMEOUT_SEC=60       # default 60s
WORLDBASE_FEED_CB_MAX_BACKOFF_SEC=900        # default 900s (15 min)
```

**Success metric:** ✅ A mocked failing feed enters open-circuit state after the threshold and serves stale data; existing tests still pass.

---

## 4. Phase 2 — Auth, Audit, and Secret Hygiene

### 2.1 RBAC scaffolding + audit log

**Gap:** `auth/security.py` has HMAC + replay guard + LAN auth, but `rbac_enabled: bool = False` and there is no audit trail for MCP tool calls or auth events.

**2026 best practice:** FastAPI RBAC via dependency injection is the standard pattern. For MCP specifically, the 2026 ByteBridge guide recommends: gateway-enforced RBAC with per-tool policies, audit logging of all tool calls and policy violations, and retention policies. Minimal roles (operator/node/readonly) are sufficient for single-operator workstations. (Sources: permit.io FastAPI RBAC, bytebridge.medium.com MCP audit 2026, app-generator FastAPI RBAC)

**Plan:**
- Add a minimal `auth/audit.py` that writes to a new SQLite table `auth_audit` (`timestamp`, `client`, `endpoint`, `tool`, `action`, `success`, `error`) with automatic retention pruning.
- Add `auth/rbac.py` with role constants (`operator`, `node`, `readonly`, `admin`) and a `require_role(...)` FastAPI dependency factory.
- Gate MCP write tools (`briefing_generate`, `globe_fly_to`, `darkweb_ingest`) behind `role=operator` when `rbac_enabled=True`.
- Start with two roles: `operator` (full) and `node` (Pi-only, limited to `/api/node/*`).

**Files:**
- `backend/auth/audit.py` (new)
- `backend/auth/rbac.py` (new)
- `backend/auth/security.py` — integrate audit hooks.
- `backend/mcp_server.py` — audit every write tool call and enforce role gate.
- `backend/sqlite_bootstrap.py` — add `auth_audit` migration.
- `backend/config.py` — `rbac_enabled` stays `False` by default to avoid breaking existing single-user setups; set to `True` when an operator token is provisioned.

**Env:**
```bash
WORLDBASE_RBAC=0
WORLDBASE_AUTH_AUDIT=1
WORLDBASE_AUTH_AUDIT_RETENTION_DAYS=90
```

**Success metric:** MCP write calls appear in `auth_audit`; `/api/node/*` calls from a non-node role are rejected; 100% backend tests pass.

---

### 2.2 Secret management helpers

**Gap:** All secrets are read from `os.getenv()` in `config.py`. No rotation, no vault integration, and the Cesium Ion token is inlined into the frontend bundle by Vite.

**Plan:**
- Add a `secrets_manager.py` abstraction that reads in priority order: env var → `.env` → optional Azure Key Vault / AWS Secrets Manager / HashiCorp Vault (lazy-import, fail-soft when not configured).
- Add a `backend/scripts/rotate_api_key.py` helper that generates a new `WORLDBASE_API_KEY`, prints it, and reminds the operator to update `.env` and Pi nodes.
- For the frontend Cesium token: move the token to a backend endpoint `/api/config/cesium` that the frontend fetches at runtime, so the token is no longer baked into the client bundle. Add a short cache (5 min) and LAN auth.
- **Cesium Ion best practice (2026):** Create a token with minimal scopes (`assets:read` only), restrict it to the operator's domain via Cesium's "Allowed URLs" feature, and rotate periodically via the Tokens REST API. Document this in `docs/SECRETS.md`.
- Document the current accepted risk: in single-operator dev mode the token is exposed by design; production deployments should use URL-restricted tokens. (Sources: cesium.com access tokens docs, cesium.com tokens API blog)

**Files:**
- `backend/secrets_manager.py` (new)
- `backend/routes/config.py` (new or extend existing) — add `/api/config/cesium`.
- `frontend/src/lib/cesium.ts` — fetch token from backend instead of `import.meta.env`.
- `backend/scripts/rotate_api_key.py` (new).
- `docs/SECRETS.md` (new).

**Env:**
```bash
# Optional vault mode
WORLDBASE_SECRET_BACKEND=env  # env | azure_keyvault | aws_secretsmanager | hashicorp_vault
WORLDBASE_SECRET_VAULT_URL=
```

**Success metric:** `backend/scripts/rotate_api_key.py` produces a valid key; frontend loads Cesium token from backend; no secret appears in the built `dist/` bundle.

---

## 5. Phase 3 — Edge Sync and OSINT Hardening

### 3.1 Pi sync conflict resolution (last-writer-wins)

**Gap:** `node_briefing.py` has delta sync (`?since=`, ETag, hash), but the Pi is a dumb consumer. If the Pi was offline and has newer local data, the PC overwrites it.

**2026 best practice:** Pure LWW with wall-clock timestamps is explicitly discouraged for offline-first sync (clock skew causes silent data loss). The recommended approach is: version vectors or hybrid logical clocks (HLC) for conflict detection, then operator-driven manual merge for conflicts. ObjectBox Sync (March 2026) uses HLC + developer-controlled precedence. For WorldBase's Pi (dumb consumer, not co-editor), a 409 Conflict + manual merge is the correct pattern — but use a **monotonic counter** instead of wall-clock for version comparison. (Sources: medium.com/@mathankumar LWW 2026, objectbox.io sync 2026, sachith.co.uk offline sync 2026, dev.to/smallstack CRDT 2026)

**Plan:**
- Extend the Pi pull protocol with a `client_version` header (monotonic integer, not wall clock) and a `client_data_hash`.
- On the PC side, compare client version with the latest PC briefing version. If the client is newer, return `409 Conflict` with a human-readable diff instead of overwriting.
- Add a `POST /api/node/push` endpoint so the Pi can send its local state upstream for manual merge (operator-driven, not automatic CRDT).
- Document the operator merge workflow.

**Files:**
- `backend/node_briefing.py` — conflict detection in `GET /api/node/pull`.
- `backend/node_sync.py` — add `POST /api/node/push`.
- `backend/node_ingest.py` — store `client_last_modified`.
- `offgrid-raspi/` — update pull script to send local timestamp and handle 409.
- `docs/PI_SYNC.md` — update.

**Env:**
```bash
WORLDBASE_NODE_CONFLICT_CHECK=1
```

**Success metric:** Simulated newer Pi data triggers a 409 with diff; operator can resolve via new push endpoint; existing delta sync still works.

---

### 3.2 Darkweb OPSEC hardening

**Gap:** `darkweb_bridge.py` already creates fresh Tor `httpx` clients per request, but there is no exit-node rotation, no jurisdiction check, and no compliance documentation.

**2026 best practice:** The Python `stem` library is the standard for Tor control port communication. `SIGNAL NEWNYM` triggers circuit regeneration. Tor enforces a **10-second minimum** between NEWNYM signals — rate-limit accordingly. Fresh `httpx.AsyncClient` per request (already implemented) provides circuit isolation. (Sources: scrapfly.io Tor scraping 2026, codestudy.net NEWNYM, github.com/n1em1nen/signal-newnym)

**Plan:**
- Add a `WORLDBASE_DARKWEB_TOR_ROTATE_IDENTITY=1` option that sends `SIGNAL NEWNYM` to the Tor control port (default 9051) via the `stem` library before each Tor engine batch.
- Rate-limit NEWNYM signals to respect Tor's 10-second minimum (queue rotation requests, no more than 1 per 10s).
- Add `WORLDBASE_DARKWEB_TOR_CONTROL_PASSWORD` for authenticated control port access.
- Add a `DARKWEB_COMPLIANCE.md` doc describing: passive metadata only, no credential stuffing, no leaked-file download, jurisdiction considerations, and that Ahmia/DarkSearch are clearnet by default.
- Add an automatic jurisdiction blocklist: if the resolved exit node country is in `WORLDBASE_DARKWEB_EXIT_BLOCKLIST` (e.g., `CN,RU,IR`), rotate again and warn.
- Keep the existing clearnet-first default; Tor engines remain opt-in.

**Files:**
- `backend/darkweb_bridge.py` — add Tor control-port rotation helper.
- `backend/darkweb_tor.py` (new) — isolate Tor control logic.
- `backend/config.py` — add new env flags.
- `docs/DARKWEB_COMPLIANCE.md` (new).

**Env:**
```bash
WORLDBASE_DARKWEB_TOR_ROTATE_IDENTITY=0
WORLDBASE_DARKWEB_TOR_CONTROL_HOST=127.0.0.1:9051
WORLDBASE_DARKWEB_TOR_CONTROL_PASSWORD=
WORLDBASE_DARKWEB_EXIT_BLOCKLIST=CN,RU,IR
```

**Success metric:** With a local Tor control port, enabling rotation changes the exit IP between requests; unit tests for rotation logic pass without requiring live Tor.

---

## 6. Phase 4 — Ops, Deployment, and Quality

### 4.1 Backend CI job and Linux start script

**Gap:** `.github/workflows/ci.yml` has frontend and backend import checks, but no backend test job. Deployment is PowerShell-only.

**Plan:**
- Extend `ci.yml` with a backend job that installs dependencies, runs the full pytest suite, and runs `ruff` / `mypy` (if clean; if not, mark `continue-on-error` initially).
- Add `scripts/start.sh` and `scripts/start-linux.sh` as POSIX equivalents of `start.ps1`.
- Add `scripts/install-hooks.sh` for Linux pre-commit setup.
- Keep `start.ps1` as the primary Windows path; do not remove it.

**Files:**
- `.github/workflows/ci.yml`
- `scripts/start.sh` (new)
- `scripts/install-hooks.sh` (new)
- `docs/DEPLOYMENT.md` — update with Linux instructions.

**Success metric:** CI backend job passes on Ubuntu; `start.sh` brings up the API on a Linux dev box.

---

### 4.2 Docker Compose for local stack

**Gap:** No containerized local deployment.

**2026 best practice:** Multi-stage Docker builds with non-root user, health check endpoints, and `env_file` for secrets are the standard. Uvicorn should use exec form (`CMD ["uvicorn", ...]`) for graceful shutdown and lifespan events. Docker Compose should include healthcheck directives. (Sources: fastapi.tiangolo.com deployment, fastlaunchapi.dev 2026 guide)

**Plan:**
- Add `Dockerfile.backend` with multi-stage build (build deps → runtime slim), non-root user (`worldbase`), and `HEALTHCHECK CMD curl -f http://localhost:8002/api/health/ping`.
- Use `CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]` (exec form, no `--reload` in production).
- Add `docker-compose.yml` that runs: backend + optional Ollama + optional DuckDB volume.
- Mount `data/` and `worldbase.db` as volumes; use `env_file` for secrets (never bake into image).
- Add a `frontend/Dockerfile` (multi-stage: node build → nginx serve) and Nginx config for the Vite build.
- Document that Docker is optional for local dev; the PowerShell path remains the primary Windows dev workflow.

**Files:**
- `Dockerfile.backend` (new)
- `docker-compose.yml` (new or extend existing)
- `frontend/Dockerfile` (new)
- `frontend/nginx.conf` (new)
- `docs/DOCKER.md` (new).

**Success metric:** `docker compose up` starts the backend and frontend; `/api/health/ping` returns 200.

---

### 4.3 Context budget escalation path (optional)

**Gap:** `context_budget.py` refuses queries when weighted quality < 0.35. This is intentional anti-hallucination behavior, but there is no escalation path for operators who want to force a lower-confidence answer.

**Plan:**
- Add an `escalation` parameter accepted by chat requests: when `escalation=1`, lower the refuse threshold to 0.20 and raise the RAG budget by 50%.
- Log every escalation in `auth_audit` (link to Phase 2.1).
- Keep the default strict path unchanged.

**Files:**
- `backend/context_budget.py` — add escalation multiplier.
- `backend/chat_proxy.py` — accept `escalation` query param.
- `frontend/src/components/ChatPanel.tsx` — add an "expand context" toggle with a warning.

**Env:**
```bash
WORLDBASE_CONTEXT_BUDGET_ESCALATION=1
```

**Success metric:** A low-quality query that previously refused now returns an answer with a visible "expanded context" warning; default behavior is unchanged.

---

### 4.4 MCP per-tool policy

**Gap:** `mcp_server.py` uses a global `WORLDBASE_MCP_WRITE` switch. The firewall gate already exists, but there is no per-tool policy.

**Plan:**
- Add a `MCP_POLICY` dict (env-driven) mapping each tool to a required role (`operator`, `readonly`, `node`, `none`).
- Default: all read tools = `readonly` (or no role if auth is off), write tools = `operator`.
- Enforce the policy inside `_gate_mcp_write()` (rename to `_gate_mcp_tool()`).

**Files:**
- `backend/mcp_server.py`
- `backend/auth/rbac.py` (shared with Phase 2.1)
- `backend/config.py` — add `mcp_policy_json` or prefixed env vars.

**Env:**
```bash
WORLDBASE_MCP_POLICY_briefing_generate=operator
WORLDBASE_MCP_POLICY_globe_fly_to=operator
WORLDBASE_MCP_POLICY_feed_sample=readonly
```

**Success metric:** A readonly token can call `worldbase_feed_sample` but is blocked from `worldbase_briefing_generate`.

---

## 7. Cross-cutting rules

1. **Fail-soft is mandatory.** Every new feature must degrade gracefully when disabled or misconfigured.
2. **Keep defaults safe.** Do not flip flags that would break existing single-operator setups without explicit opt-in.
3. **Tests before implementation.** Add or update tests before changing production code.
4. **No new files unless necessary.** Each proposed file is justified above.
5. **Backend restart required.** Every backend change needs a user-triggered restart (per project rules). This plan will explicitly state that at the end of each merged PR.
6. **Venv only.** All Python commands use `backend\venv\Scripts\python.exe`.

---

## 8. Suggested order of work

1. ~~**Phase 1.2** — enable DuckDB queue by default~~ ✅ DONE (2026-06-28)
2. ~~**Phase 1.3** — feed circuit breakers~~ ✅ DONE (2026-06-28)
3. ~~**Phase 1.1** — task watchdog~~ ✅ DONE (2026-06-28)
4. **Phase 2.1** — auth audit log (needed for 4.4 and 3.2 audit trails).
5. **Phase 2.2** — secret rotation + Cesium token backend fetch.
6. **Phase 3.2** — darkweb OPSEC rotation + compliance doc.
7. **Phase 3.1** — Pi sync conflict detection.
8. **Phase 4.4** — MCP per-tool policy (builds on 2.1).
9. **Phase 4.1** — backend CI + Linux start script.
10. **Phase 4.2** — Docker Compose.
11. **Phase 4.3** — context budget escalation (optional, lowest priority).

---

## 9. Definition of done

- [x] Phase 1.2 — DuckDB write queue enabled by default (2026-06-28).
- [x] Phase 1.3 — Feed circuit breakers implemented (2026-06-28).
- [x] Phase 1.1 — Task watchdog + `/api/health/tasks` (2026-06-28).
- [ ] Phase 2.1 — RBAC scaffolding + audit log.
- [ ] Phase 2.2 — Secret management helpers.
- [ ] Phase 3.1 — Pi sync conflict resolution.
- [ ] Phase 3.2 — Darkweb OPSEC hardening.
- [ ] Phase 4.1 — Backend CI + Linux start script.
- [ ] Phase 4.2 — Docker Compose local stack.
- [ ] Phase 4.3 — Context budget escalation (optional).
- [ ] Phase 4.4 — MCP per-tool policy.
- [ ] All 11 work packages are implemented or explicitly deferred.
- [ ] Full backend test suite passes (`backend\venv\Scripts\python.exe -m pytest backend` with 0 regressions).
- [ ] Smoke test passes (`scripts\smoke-test.ps1`).
- [ ] Each backend change is followed by a user-triggered backend restart.
- [ ] `AGENTS.md` and `docs/WORLDBASE_ROADMAP_2026.md` are updated to reflect new flags and capabilities.
- [ ] No new `.md` files are created beyond what is justified in this plan.

---

## 9. Work Completed Outside This Plan

| Feature | Status | Notes |
|---|---|---|
| **P11 Onion Directory** | ✅ Done 2026-06-28 | Curated legitimate .onion services feed (`backend/onion_directory.py`, `backend/test_onion_directory.py`). Fetches `master.csv` + `securedrop-api.csv` from `alecmuffett/real-world-onion-sites`; 94 live entries ingested as FtM `Domain` entities. Not part of the external-analysis response. |

---

## 10. 2026 Best Practices Sources

| Topic | Source | Key takeaway |
|---|---|---|
| Background tasks | dev.to/kaushikcoderpy 2026, FastAPI docs | `asyncio.create_task` is in-memory only; hold strong refs; watchdog for non-critical tasks |
| DuckDB concurrency | DuckDB official docs, tech-champion.com | Write-worker pattern recommended; single writer process; DuckLake v1.0 for multi-process (overkill here) |
| SQLite WAL | cronfeed.work 2026, pavanrangani.com 2026 | `busy_timeout=5000`, `synchronous=NORMAL`, `BEGIN IMMEDIATE`; WAL is one-writer-at-a-time |
| Circuit breakers | blog.greeden.me 2026, oneuptime.com 2026, ines-panker.com 2026, pypi circuitbreaker | 3-state pattern (CLOSED/OPEN/HALF_OPEN); per-service breakers; always provide fallbacks |
| Cesium Ion tokens | cesium.com access tokens docs, cesium.com tokens API blog | Minimal scopes, URL restrictions, periodic rotation via REST API |
| RBAC + MCP audit | permit.io FastAPI RBAC, bytebridge.medium.com MCP audit 2026 | Dependency injection RBAC; gateway-enforced per-tool policies; audit log with retention |
| Tor exit rotation | scrapfly.io 2026, codestudy.net, stem library | `SIGNAL NEWNYM` via stem; 10s minimum between signals; fresh client per request |
| Offline sync conflicts | medium.com/@mathankumar 2026, objectbox.io 2026, sachith.co.uk 2026, dev.to/smallstack 2026 | LWW with wall clock is discouraged; use HLC/version vectors; 409 + manual merge for non-collaborative edge |
| Docker + FastAPI | fastapi.tiangolo.com, fastlaunchapi.dev 2026 | Multi-stage build, non-root user, exec form CMD, healthcheck, env_file for secrets |

---

*Plan created: 2026-06-28*  
*Source: code-by-code rebuttal of external architecture review + 2026 best practices research.*
