# Docker — WorldBase Containerized Stack

WorldBase ships with a Docker Compose stack for containerized deployment. This is optional — the primary dev workflow is `start.ps1` (Windows) or `start.sh` (Linux).

## Quick start

### Windows (PowerShell)

```powershell
.\scripts\start-docker.ps1
```

This auto-detects your LAN IP, generates a root `.env`, and runs `docker compose up -d --build`.

### Linux / macOS

```bash
# 1. Copy env files
cp backend/.env.example backend/.env       # fill in API keys
cp frontend/.env.example frontend/.env     # Cesium Ion token
cp .env.docker.example .env               # adjust LAN IP

# 2. Build + start
docker compose up -d --build
```

## What runs

| Service | Image | Port | Notes |
|---------|-------|------|-------|
| **backend** | `worldbase-backend:local` | 8002 (internal) | FastAPI, non-root user (uid 10001), healthcheck on `/api/health/ping` |
| **web** | `worldbase-web:local` | 80, 443 | Caddy: TLS termination, SPA serve, `/api` reverse proxy |
| **redis** | `redis:7-alpine` | 6379 (internal) | Rate-limit storage, Celery broker (in-memory, no persistence) |
| **celery-worker** | `worldbase-backend:local` | — | Feed ingest, briefing generation, entity resolution (delegates to backend API) |
| **celery-beat** | `worldbase-backend:local` | — | Periodic task scheduler (feed ingest, briefing autopilot) |
| **flower** | `mher/flower:2.0` | 5555 (internal) | Celery monitoring dashboard (proxied via Caddy at `/flower/`) |

The backend is **not** published to the host by default — Caddy proxies it. This is the most locked-down posture. To expose it directly, copy `docker-compose.override.example.yml` to `docker-compose.override.yml`.

## Architecture

```
Browser ──https──→ Caddy (:443) ──→ backend:8002 (internal)
                         │
                         └──→ SPA static files (/srv)
                         
backend ──→ redis:6379 (rate limits + Celery broker)
backend ──→ host.docker.internal:11434 (Ollama on host)

celery-beat ──→ redis:6379 (schedule)
celery-worker ──→ redis:6379 (tasks)
celery-worker ──→ backend:8002 (API calls for feed ingest, briefing)
flower ──→ redis:6379 (monitoring)
```

### Backend Dockerfile

Multi-stage build:
1. **Builder stage**: `python:3.12-slim` + `build-essential`, `libicu-dev`, `pkg-config` → pip installs to `/install` (core + optional deps including torch CPU, splink, gliner)
2. **Runtime stage**: `python:3.12-slim` + `libicu76` (runtime only, Debian Trixie) + `libgomp1` (OpenMP for torch/onnxruntime) + `curl` (healthcheck) → copies `/install`, runs as non-root `worldbase` user

Exec-form CMD: `CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]` — uses `python -m` because `pip install --target=/install` puts console scripts in `/install/bin` which is not on `$PATH`.

### Frontend Dockerfile

Multi-stage build:
1. **Build stage**: `node:20-alpine` → `npm run build` (Vite production build)
2. **Serve stage**: `caddy:2-alpine` → serves `dist/` as SPA, reverse-proxies `/api` to backend

The `Caddyfile` is mounted at runtime (not baked into the image), so you can edit it without rebuilding.

## Volumes

| Volume | Mount | Purpose |
|--------|-------|---------|
| `worldbase-db` | `/data` | Persistent SQLite (`worldbase.db`) |
| `caddy-data` | `/data` (Caddy) | TLS certificate store |
| `caddy-config` | `/config` (Caddy) | Caddy autosave config |

## Environment

### `backend/.env` (via `env_file`)

All backend env vars (API keys, feature flags, etc.). See `backend/.env.example`. This file is git-ignored — never bake secrets into the image.

### Root `.env` (compose-level)

Consumed by `docker-compose.yml`. See `.env.docker.example`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_CESIUM_ION_TOKEN` | (empty) | Baked into frontend build |
| `WORLDBASE_LAN` | `127.0.0.1` | LAN IP for Caddy TLS cert (Pi access) |
| `WORLDBASE_CORS_ORIGINS` | (empty) | Extra allowed origins |
| `WORLDBASE_REQUIRE_NODE_TOKEN` | `1` | Refuse LAN exposure without token |
| `OLLAMA_HOST` | `host.docker.internal:11434` | Reach host's Ollama from container |

## Health checks

```bash
# Backend (from host, if exposed via override)
curl http://127.0.0.1:8002/api/health/ping

# Backend (from inside the compose network)
docker compose exec backend curl -s localhost:8002/api/health/ping

# Caddy (HTTPS)
curl -k https://localhost/api/health/ping
```

## Stop

```bash
docker compose down           # stop + remove containers
docker compose down -v        # also remove volumes (deletes DB!)
```

## Pi sync over LAN

The Pi reaches the backend via Caddy's HTTPS endpoint (port 443), **not** port 8002:

```bash
# On the Pi — worldbase_push.service drop-in config:
# /etc/systemd/system/worldbase_push.service.d/http-lan.conf
[Service]
Environment=WORLDBASE_SCHEME=https
Environment=WORLDBASE_PORT=443
Environment=WORLDBASE_PC=<pc-lan-ip>
Environment=WORLDBASE_VERIFY_TLS=0   # internal CA cert

# Also fix port.conf drop-in:
# /etc/systemd/system/worldbase_push.service.d/port.conf
[Service]
Environment="WORLDBASE_PORT=443"

# Apply:
sudo systemctl daemon-reload
sudo systemctl restart worldbase_push.service
```

`start-docker.ps1` auto-detects the LAN IP and prints the exact Pi sync target.

**Important:** The Pi's `worldbase_push.service` has multiple drop-in files. Both `http-lan.conf` and `port.conf` must agree on `WORLDBASE_PORT=443`. The main service file defaults to port 8002 — drop-ins override it.

## Stack verification (post-start health check)

After `docker compose up -d --build`, verify the stack is fully operational:

### 1. Container status

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

Expected: `worldbase-backend-1`, `worldbase-web-1`, `worldbase-redis-1` all `Up` and `healthy`. Celery worker/beat/flower may show `starting` for the first 30–60 s.

### 2. Backend health (from inside the compose network)

```bash
# Fast ping
docker compose exec backend curl -s http://127.0.0.1:8002/api/health/ping
# → {"status":"ok","time":"..."}

# Full health (feed freshness, FtM, DuckDB)
docker compose exec backend curl -s http://127.0.0.1:8002/api/health
```

### 3. Caddy proxy (TLS termination)

```bash
# From inside the web container — verifies Caddy → backend proxy
docker compose exec web wget -qO- --no-check-certificate https://localhost/api/health/ping
```

> **Windows host caveat:** `curl -sk https://localhost/api/health/ping` from PowerShell may return empty (Windows curl SSL issue). Open `https://localhost` in a browser instead — accept the self-signed cert once.

### 4. API key

The backend reads `WORLDBASE_API_KEY` from `backend/.env` (via `env_file` in docker-compose). To find the key at runtime:

```bash
docker compose exec backend python -c "import os; print(os.getenv('WORLDBASE_API_KEY','NOT_SET'))"
```

Use this key as `X-API-Key` header for authenticated endpoints:

```bash
docker compose exec backend curl -s -H "X-API-Key: <key>" http://127.0.0.1:8002/api/briefing
```

### 5. Key endpoints to verify

| Endpoint | Expected | Notes |
|----------|----------|-------|
| `GET /api/health/ping` | `{"status":"ok"}` | No auth required |
| `GET /api/health` | Feed counts, FtM ready, DuckDB | No auth required |
| `GET /api/trust` | Score 0–4, feed drift | No auth required |
| `GET /api/briefing` | quality, insights, watch_items, agentic | Requires `X-API-Key` |
| `GET /api/intel/graph/stats` | entities, statements, edges counts | Requires `X-API-Key` |
| `GET /api/anomalies/iso/status` | enabled, model_trained, metrics count | Requires `X-API-Key` |
| `GET /api/agent/status` | phases, blackboard, two_pass, layers | Requires `X-API-Key` |
| `GET /api/memory/stats` | chunks, vec_chunks, search_mode | Requires `X-API-Key` |
| `GET /api/darkweb/status` | engines, modes, tor_proxy | Requires `X-API-Key` |
| `GET /api/admin/flags` | All feature flags with enabled state | Requires `X-API-Key` |
| `GET /openapi.json` | Full route list (281+ routes) | No auth required |

### 6. Feature flags gotcha (Docker)

`GET /api/admin/flags` shows many flags as `enabled: false` with `source: "env"` — e.g. `query_router`, `provenance`, `briefing_autopilot`, `briefing_intel`, `rag_rerank`, `rag_feed_ingest`, `feed_ingest_autopilot`, `briefing_agentic_loop`, `ftm_statements`.

**This is expected.** These flags are not explicitly set in `backend/.env`, so the admin flags endpoint reads them as `false`. However, the **code defaults** in `config.py` / `features.py` apply at runtime — e.g. `WORLDBASE_QUERY_ROUTER` defaults to `"1"` (on), `WORLDBASE_PROVENANCE` defaults to `"1"` (on), `WORLDBASE_BRIEFING_AUTOPILOT` defaults to `"1"` (on). The briefing will still run agentic loops, feed ingest autopilot will still run, RAG rerank will still work.

To explicitly enable a flag in Docker, add it to `backend/.env` and rebuild: `docker compose up -d --build`.

### 7. Celery worker activity

Feed ingest runs via Celery workers, not in-process. Check worker logs:

```bash
docker logs worldbase-celery-worker-1 --tail 20
```

Expected: `Task tasks.feeds.ingest_feed[...] succeeded in Ns` with entity/edge counts. Beat scheduler:

```bash
docker logs worldbase-celery-beat-1 --tail 10
# → celery beat v5.x is starting... beat: Starting...
```

### 8. Anomaly detection cold start

`GET /api/anomalies/iso/status` will show `model_trained: false, total_metrics: 0` on a fresh Docker DB. This is expected — the Isolation Forest needs ≥14 samples (feed metrics collected over time) before training. The autopilot background loop collects metrics hourly and trains daily. After ~14 hours of operation, the model will auto-train.

### 9. Route path reference

Common endpoint paths (some are non-obvious):

| What | Correct path | Wrong path |
|------|-------------|------------|
| FtM graph stats | `/api/intel/graph/stats` | ~~`/api/ftm/stats`~~ |
| FtM entities | `/api/intel/entities` | ~~`/api/ftm/entities`~~ |
| Entity by ID | `/api/entity/{id}` | ~~`/api/ftm/entity/{id}`~~ |
| Feed status | `/api/intel/feeds/status` | ~~`/api/feeds`~~ |
| Briefing | `/api/briefing` | — |
| Anomaly status | `/api/anomalies/iso/status` | — |
| Agent status | `/api/agent/status` | — |
| Memory stats | `/api/memory/stats` | — |
| Darkweb status | `/api/darkweb/status` | — |
| Admin flags | `/api/admin/flags` | — |
| Connectors | `/api/connectors` | — |
| Credentials | `/api/credentials/status` | — |

### 10. DuckDB spatial in Docker

- R-Tree index **disabled** by default (DuckDB 1.5.x bug — `duckdb-spatial #769` FATAL "flat vector" error on writes)
- `geom GEOMETRY` column still created and synced via `ST_MakePoint` on upsert (safe without R-Tree)
- `ST_Within` queries use full scan (no R-Tree) — works but slower
- Runtime fallback: `ST_Within` → `lat/lon BETWEEN` if "flat vector" error occurs
- `_drop_rtree_index_if_present()` runs on startup to clean up indexes from prior runs
- To force-enable R-Tree (testing/future DuckDB): set `WORLDBASE_DUCKDB_RTREE=1` in `backend/.env`
- DuckDB dead letters in `/api/admin/dlq` may show historical count from prior venv runs — no new dead letters in Docker mode

## Troubleshooting

- **CRITICAL — Never run venv backend and Docker stack simultaneously**: The venv backend (`start.ps1`) binds `0.0.0.0:8002` with a local `worldbase.db`. The Docker backend runs inside a container with its own `/data/worldbase.db` volume. Running both creates two separate databases — Pi heartbeats, briefings, and entity data will diverge. If Docker is running, stop the venv backend first (`Ctrl+C` in the `start.ps1` terminal or `Stop-Process` on the PID listening on 8002). Check with `netstat -ano | findstr :8002` — if it shows `LISTENING` while `docker ps` shows `worldbase-backend-1`, you have a dual-backend conflict.
- **DuckDB `entities.duckdb` invalid (0 bytes)**: If `/app/data/entities.duckdb` is a 0-byte file, DuckDB cannot open it and FTM will report `ready: false`. Fix: `docker exec worldbase-backend-1 rm -f /app/data/entities.duckdb /app/data/entities.duckdb.wal` then `docker restart worldbase-backend-1`. DuckDB will recreate the file with schema on startup.
- **Pi shows offline after PC reboot**: The Pi's `worldbase_push.service` may still point to `http://<pc-ip>:8002` (venv backend). After switching to Docker, update the Pi's drop-in configs to `https` + port `443` (see Pi sync section above). Verify with `journalctl -u worldbase_push.service -n 5` on the Pi.
- **`followthemoney` install fails**: The builder stage installs `libicu-dev` + `pkg-config` for `pyicu`. If you see ICU errors, ensure the builder stage ran correctly.
- **Optional deps (torch, splink, gliner, etc.)**: The Dockerfile installs these in a second pip layer (CPU-only torch from `download.pytorch.org/whl/cpu`). If a specific optional package fails to build, check the builder stage logs. The backend lazy-imports all optional packages and runs without them, but entity resolution, NER, and RAG reranking will be disabled.
- **`psycopg2-binary`, `protobuf`, `river` not in venv**: These are listed in `requirements.txt` but may be missing from the local venv if it was created before they were added. Run `pip install psycopg2-binary protobuf river` in the venv to fix.
- **`libgomp1` missing at runtime**: The runtime stage installs `libgomp1` for OpenMP support (torch/onnxruntime CPU mode). If you see `libgomp.so.1: cannot open shared object file`, ensure the runtime stage installed it correctly.
- **Windows port 8002 conflict**: `net stop winnat; net start winnat` (elevated), or use `docker-compose.override.example.yml` with a different port.
- **Caddy TLS warning**: Browser will warn about the internal CA cert — accept once. This is expected for local dev.
