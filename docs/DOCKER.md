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
| **redis** | `redis:7-alpine` | 6379 (internal) | Rate-limit storage (in-memory, no persistence) |

The backend is **not** published to the host by default — Caddy proxies it. This is the most locked-down posture. To expose it directly, copy `docker-compose.override.example.yml` to `docker-compose.override.yml`.

## Architecture

```
Browser ──https──→ Caddy (:443) ──→ backend:8002 (internal)
                         │
                         └──→ SPA static files (/srv)
                         
backend ──→ redis:6379 (rate limits)
backend ──→ host.docker.internal:11434 (Ollama on host)
```

### Backend Dockerfile

Multi-stage build:
1. **Builder stage**: `python:3.12-slim` + `build-essential`, `libicu-dev`, `pkg-config` → pip installs to `/install` (core + optional deps including torch CPU, splink, gliner)
2. **Runtime stage**: `python:3.12-slim` + `libicu76` (runtime only, Debian Trixie) + `libgomp1` (OpenMP for torch/onnxruntime) + `curl` (healthcheck) → copies `/install`, runs as non-root `worldbase` user

Exec-form CMD: `CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]` (graceful shutdown, lifespan events).

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

The Pi reaches the backend via Caddy's HTTPS endpoint:

```bash
# On the Pi:
export WORLDBASE_PC=<pc-lan-ip>
export WORLDBASE_SCHEME=https
export WORLDBASE_VERIFY_TLS=0   # internal CA cert
curl https://$WORLDBASE_PC/api/node/pull -H "X-Node-Token: <token>"
```

`start-docker.ps1` auto-detects the LAN IP and prints the exact Pi sync target.

## Troubleshooting

- **`followthemoney` install fails**: The builder stage installs `libicu-dev` + `pkg-config` for `pyicu`. If you see ICU errors, ensure the builder stage ran correctly.
- **Optional deps (torch, splink, gliner, etc.)**: The Dockerfile installs these in a second pip layer (CPU-only torch from `download.pytorch.org/whl/cpu`). If a specific optional package fails to build, check the builder stage logs. The backend lazy-imports all optional packages and runs without them, but entity resolution, NER, and RAG reranking will be disabled.
- **`psycopg2-binary`, `protobuf`, `river` not in venv**: These are listed in `requirements.txt` but may be missing from the local venv if it was created before they were added. Run `pip install psycopg2-binary protobuf river` in the venv to fix.
- **`libgomp1` missing at runtime**: The runtime stage installs `libgomp1` for OpenMP support (torch/onnxruntime CPU mode). If you see `libgomp.so.1: cannot open shared object file`, ensure the runtime stage installed it correctly.
- **Windows port 8002 conflict**: `net stop winnat; net start winnat` (elevated), or use `docker-compose.override.example.yml` with a different port.
- **Caddy TLS warning**: Browser will warn about the internal CA cert — accept once. This is expected for local dev.
