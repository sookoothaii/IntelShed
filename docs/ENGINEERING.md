# Engineering Hygiene — Track E

> **Track E** brings WorldBase's engineering discipline to WorldMonitor parity.
> Sessions E1–E3 run parallel to the fachlichen Sessions 4–16.

---

## Session E1 — Pre-push Hooks + Rate Limiting + CSP

### E-01: Pre-push Hooks

**File:** `.husky/pre-push`
**Config:** `.pre-commit-config.yaml` (stages: `[pre-push]`)

The pre-push hook runs four quality gates (fail-fast):

| # | Check | Scope | Failure |
|---|-------|-------|---------|
| 1 | `ruff check backend/` | Backend lint | Non-zero exit |
| 2 | `pytest --collect-only -q` | Backend syntax + import | Collection error |
| 3 | `npx tsc --noEmit` | Frontend type check | Type error |
| 4 | Secret guard | Staging area | `.env` file staged |

**Install:**
```bash
# If husky is not yet set up:
npx husky install
# The hook is already at .husky/pre-push
```

**Manual verification:**
```bash
bash .husky/pre-push
```

**Bypass (emergency only):**
```bash
git push --no-verify
```

### E-02: Rate Limiting (Sliding Window)

**File:** `backend/middleware/rate_limit.py`
**Config:** `backend/config.py` + `backend/.env.example`

Two-layer rate limiting:

1. **slowapi per-endpoint decorators** (fixed-window) — existing, unchanged:
   - `@rate_limit_node_ingest()` — 100/min per node
   - `@rate_limit_node_pull()` — 20/min per node
   - `@rate_limit_node_command()` — 10/min per admin
   - `@rate_limit_general()` — 1000/hour per IP

2. **SlidingWindowLimiter** (new) — global middleware, per-IP sliding window:
   - Redis ZSET backend with in-memory deque fallback
   - API-key requests exempt (`X-API-Key` matching `WORLDBASE_API_KEY`)
   - Node-token requests exempt (`X-Node-Token` matching `NODE_INGEST_TOKEN`)
   - `/api/health/*` always exempt
   - Per-endpoint RPM overrides via `WORLDBASE_RATE_LIMIT_OVERRIDES`

**Environment Variables:**

| Var | Default | Description |
|-----|---------|-------------|
| `WORLDBASE_RATE_LIMIT` | `1` | Enable sliding window (on/off) |
| `WORLDBASE_RATE_LIMIT_RPM` | `60` | Requests per minute per IP |
| `WORLDBASE_RATE_LIMIT_WINDOW_SEC` | `60` | Sliding window size (seconds) |
| `WORLDBASE_RATE_LIMIT_OVERRIDES` | (empty) | Per-endpoint: `/api/chat:30,/api/briefing:10` |
| `RATE_LIMIT_STORAGE` | `memory` | `redis` or `memory` |
| `RATE_LIMIT_REDIS_URL` | (empty) | Redis connection URL |

**429 Response:**
```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Sliding window rate limit exceeded.",
    "details": {
      "retry_after_seconds": 60,
      "limit": "60/minute"
    }
  }
}
```
Headers: `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`

**Tests:** `backend/tests/test_rate_limiter.py` (16 tests)

### E-07: CSP Hardening

Three synchronized CSP sources:

| Source | File | Scope |
|--------|------|-------|
| Meta tag | `frontend/index.html` | Dev mode (Vite :5176) |
| HTTP header | `backend/middleware/security_headers.py` | Backend responses (venv mode) |
| Caddy header | `Caddyfile` | Docker mode (Caddy proxy) |

**CSP Policy:**
```
default-src 'self';
script-src 'self' 'unsafe-inline' 'unsafe-eval';
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
font-src 'self' https://fonts.gstatic.com data:;
img-src 'self' data: blob: https:;
connect-src 'self' https://api.cesium.com wss: ws:;
worker-src 'self' blob:;
object-src 'none';
frame-ancestors 'self';
base-uri 'self';
form-action 'self';
```

**Notes:**
- `'unsafe-inline'` and `'unsafe-eval'` required for Vite dev mode and Cesium web workers
- `blob:` in `worker-src` and `img-src` for Cesium terrain tiles and dynamic imagery
- `https://api.cesium.com` in `connect-src` for Cesium Ion token API
- `wss:` and `ws:` for WebSocket connections (AIS streams, chat SSE fallback)

**Sync verification:** `test_rate_limiter.py::TestCSPHeaders::test_csp_sync_across_sources`

---

## Session E2 — CI Workflows + Cache Stampede Protection

### E-03: CI-Workflows erweitern

**Files:** `.github/workflows/security-audit.yml`, `feed-validation.yml`, `typecheck.yml`, `deploy-gate.yml`

Four new GitHub Actions workflows complement the existing `ci.yml`:

| Workflow | Trigger | Jobs | Purpose |
|----------|---------|------|---------|
| `security-audit.yml` | PR + daily schedule | `pip-audit`, `npm-audit` | Dependency vulnerability scanning (Python + npm) |
| `feed-validation.yml` | PR (bridge paths) + daily | `feed-smoke` | Import all feed bridges, validate FeedEnvelope, run mapping validator |
| `typecheck.yml` | PR (backend/frontend paths) | `mypy`, `tsc` | Static type checking (mypy non-blocking, tsc blocking) |
| `deploy-gate.yml` | PR | Aggregate + 8 re-declared jobs | Single required status check for branch protection |

**Deploy Gate** aggregates all CI jobs (`frontend`, `frontend-test`, `backend`, `backend-tests`, `pre-commit`, `typecheck`, `security-audit`, `feed-validation`) into one `deploy-gate` job. Configure branch protection to require this single check instead of individual jobs.

**Path filters** — `feed-validation.yml` only triggers on changes to `backend/feeds/**`, `backend/*_bridge.py`, and related files. `typecheck.yml` triggers on `backend/**/*.py` and `frontend/src/**`.

**Tests:** `backend/tests/test_ci_workflows.py` (16 tests — YAML structure validation, job existence, trigger configuration)

### E-04: Cache Stampede Protection

**File:** `backend/cache_coalesce.py`
**Config:** `WORLDBASE_CACHE_COALESCE=1` (default on)

When multiple concurrent requests miss the cache for the same key, only the first request ("leader") triggers the upstream fetch. All concurrent waiters share the same `asyncio.Future` and receive the identical result.

**Architecture:**

```
Request A ─┐
Request B ──┼──→ cached_fetch_json("iss", ttl=4) ──→ 1 upstream fetch
Request C ──┘         │                                (not 3)
                      ├─ Cache hit? → return immediately
                      ├─ In-flight? → await shared Future
                      └─ Cache miss → become leader, fetch, cache, resolve Future
```

**Integration points:**
- `backend/routes/core_feeds.py` — `/api/iss` endpoint (4s TTL, most stampede-prone)
- `backend/runtime_cache.py` — `cache_invalidate()` added for manual cache eviction
- `backend/config.py` — `cache_coalesce_enabled` field in `WorldBaseConfig`

**Usage:**
```python
from cache_coalesce import cached_fetch_json

data = await cached_fetch_json(
    key="eonet",
    ttl=300,
    fetcher=lambda: _fetch_eonet(),
    persist=True,  # optional: also write to feed_registry (SQLite)
)
```

**Environment Variables:**

| Var | Default | Description |
|-----|---------|-------------|
| `WORLDBASE_CACHE_COALESCE` | `1` | Enable coalescing (set `0` for pass-through mode) |

**Tests:** `backend/tests/test_cache_coalesce.py` (16 tests — single fetch, concurrent coalescing, TTL expiry, exception propagation, persist, disabled mode, large batch)

---

## Remaining Items (identified, not yet implemented)

### E-08: Cesium Memory Cap
- `releaseGeometryInstances` on Primitive-based layers
- `maximumMemoryUsage` on 3D Tilesets
- Heap monitor (`performance.memory.usedJSHeapSize`, 800MB threshold, 30s interval)
- LRU layer eviction (not `primitives.removeAll()`)

### E-09: CSP Single Source of Truth
- `backend/csp_policy.py` — `CSPPolicy` class with `to_header()`, `to_meta_tag()`, `to_caddyfile()`
- Vite plugin to auto-sync `index.html` + `Caddyfile` at build time
- `security_headers.py` imports from `csp_policy` instead of hardcoded string

### E-10: Golden Queries Expansion (15 → 50+)
- "Critical Pairs" method: Spatial+Live, Temporal+Graph, Multi-Hypothesis+Prognostic, Agentic+Low-Provenance, Empty-Results
- Languages: EN + TH (operator region)
- Agentic modes: Off (default) + 5-Agent (most complex)
- Each route covered at least once

---

## Verification

```powershell
# Run rate limiter + CSP tests
cd backend
venv\Scripts\python.exe -m pytest tests/test_rate_limiter.py -v

# Run cache coalesce tests
venv\Scripts\python.exe -m pytest tests/test_cache_coalesce.py -v

# Run CI workflow structure tests
venv\Scripts\python.exe -m pytest tests/test_ci_workflows.py -v

# Run full test suite
venv\Scripts\python.exe -m pytest -v --tb=short --maxfail=50 -q

# Smoke test (requires API running)
.\scripts\smoke-test.ps1
```
