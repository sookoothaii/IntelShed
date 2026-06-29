# WorldBase

![MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)
![Cesium](https://img.shields.io/badge/Cesium-1.142-6CADDF?style=flat-square)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20qwen3-black?style=flat-square)
![NVIDIA NIM](https://img.shields.io/badge/LLM-NVIDIA%20NIM%20step--3.7--flash-76B900?style=flat-square&logo=nvidia&logoColor=white)

**Spatial intelligence workstation** — live OSINT feeds on a Cesium globe, fusion analytics, and local AI chat.

WorldBase is a thin integration layer: almost everything here rests on libraries, datasets, and tools that other people built and shared. We are grateful to every maintainer whose work makes this project possible.

`FastAPI` · `React` · `Vite` · `SQLite` · `DuckDB` · `Ollama` · `NVIDIA NIM` · `Docker` · optional `Pi` edge sync

WorldBase is the **PC stack**. It extends the off-grid Pi workshop ([`offgrid-raspi`](https://github.com/sookoothaii/offgrid-raspi)) with heavy fusion, a 24h security briefing, and globe UX. Run WorldBase alone on a PC, or **Pi + PC together** via push/pull sync (see below).

---

## At a glance

| | |
|---|---|
| **Globe** | 30+ live layers — aircraft, quakes, disasters, energy, maritime, transit, dark web |
| **MAP** | Offline Protomaps via PMTiles — regional or full planet (~130 GB) |
| **Briefing** | 24h security digest (LOCAL / REGION / GLOBAL), watch items, prediction ledger, agentic loop, two-pass critique-refine |
| **Intelligence** | FtM entity graph (45k+ entities), OpenSanctions, hybrid RAG (sqlite-vec + FTS5 + RRF + BGE rerank), GraphRAG-lite |
| **AI** | Ollama (`qwen3:8b`) + 6 cloud providers (NVIDIA NIM, Groq, OpenRouter, Cerebras, SambaNova, DeepSeek); 4-layer anti-hallucination stack |
| **OSINT** | Dark web (P8, 8 search engines + Tor), ransomware intel, identity enumeration (P9, 83 platforms), Telegram SOCMINT, satellite change detection |
| **Entity resolution** | Per-dataset dedupe → cross-dataset link (Splink), dual-pipeline, human-in-the-loop labelling, FtM 4.0 StatementEntity |
| **Multi-agent** | 5-agent orchestrator (Coverage → Retrieval → Spatial → Corroboration → Synthesis) + blackboard + evidence chains, 0 VRAM |
| **Anomaly detection** | Isolation Forest on 8 feed time series (V4-23), River HalfSpaceTrees on live streams, CPU-only |
| **Predictive** | LightGBM forecasting on snapshot time series (V4-19), 24h entity count forecast |
| **Edge** | Off-grid Pi pushes sensors → PC fuses → hardened briefing pull back to Pi (delta sync + conflict detection) |
| **Trust** | Rule-based briefing quality + feed drift + connector provenance + route outcome ledger (`GET /api/trust`) |
| **MCP** | Cursor/Claude: 13 tools — briefing, nodes, feeds, globe control — [`docs/MCP.md`](docs/MCP.md) |
| **Docker** | Full stack: backend + Caddy (TLS) + Redis + Celery worker/beat + Flower — `docker compose up -d --build` |
| **Philosophy** | Positive intelligence — better decisions, not attacks |

Full feature catalog with env vars and setup → [`docs/FEATURES.md`](docs/FEATURES.md)

---

## Quick start

**Prerequisites:** Python 3.12+, Node.js 20+, [Ollama](https://ollama.com/) (`qwen3:8b`, `nomic-embed-text`), free [Cesium Ion](https://ion.cesium.com/tokens) token. Optional: [NVIDIA NIM API key](https://build.nvidia.com/) for cloud reasoning models (free tier incl. `stepfun-ai/step-3.7-flash`). Docker for containerized deployment.

### Docker (recommended)

```bash
git clone https://github.com/sookoothaii/worldbase.git
cd worldbase
git submodule update --init --recursive   # Pi sync scripts in offgrid-raspi/
cp backend/.env.example backend/.env      # API keys, feature flags
cp frontend/.env.example frontend/.env    # required: VITE_CESIUM_ION_TOKEN
docker compose up -d --build
```

| Service | URL |
|---------|-----|
| **UI** | https://localhost (accept self-signed cert) |
| **API** | https://localhost/api/docs |
| **Health** | https://localhost/api/health/ping |
| **Flower** | http://localhost:5555 (Celery dashboard) |

### Native (development)

```bash
git clone https://github.com/sookoothaii/worldbase.git
cd worldbase
git submodule update --init --recursive
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
python -m venv backend/venv
source backend/venv/bin/activate          # Linux/macOS
# backend\venv\Scripts\activate            # Windows
pip install -r backend/requirements.txt
# Start backend + frontend (see start.sh or start.ps1)
```

| Service | URL (venv mode) |
|---------|-----|
| **UI** | http://localhost:5176 |
| **API** | http://localhost:8002/docs |
| **Health** | http://localhost:8002/api/health |
| **Health (fast)** | http://localhost:8002/api/health/ping |
| **Ollama** | http://127.0.0.1:11434 |

Open **http://localhost:5176** (Vite). API docs: **http://127.0.0.1:8002/docs**.

### MCP + Agent Bus (optional)

For Cursor / Claude automation — full guide: [`docs/MCP.md`](docs/MCP.md).

```powershell
# backend/.env
WORLDBASE_MCP=1
WORLDBASE_MCP_WRITE=1
WORLDBASE_AGENT_BUS=1          # globe fly_to / layer toggle via MCP

# frontend/.env
VITE_WORLDBASE_AGENT_BUS=1     # HUD must be open at :5176
```

Restart backend + Vite; add `worldbase` to Cursor MCP (`http://127.0.0.1:8002/api/mcp` + `X-API-Key` if set). Expect **13 tools** when Agent Bus is on. Per-tool RBAC policy enforced (read tools → `readonly`, write tools → `operator`).

```bash
ollama pull qwen3:8b
ollama pull nomic-embed-text   # RAG embeddings
# Optional BGE reranker (CPU or GPU):
pip install sentence-transformers   # when RAG_RERANK=1 in backend/.env
# Optional anomaly detection (Isolation Forest):
pip install scikit-learn            # when WORLDBASE_ANOMALY_DETECTION=1
# Optional predictive analytics (LightGBM):
pip install lightgbm numpy          # when WORLDBASE_PREDICTIVE=1
```

**Verify stack:** `./scripts/smoke-test.ps1` (Windows) or `./scripts/smoke-test.sh` (Linux) → expect **33 PASS / 0 FAIL / 1 WARN**.

The start script waits for `GET /api/health/ping` before starting Vite (avoids proxy `ECONNREFUSED`). ~**6 s** after backend boot, a feed warm-up refreshes GDELT local + global pulse, traffic cams, maritime, CAMS haze, air quality, and Bangkok weather.

### Screenshots

| GLOBE | MAP | DATA | SPLIT |
|-------|-----|------|-------|
| ![Globe — Starlink orbits](docs/screenshots/globe-starlink-orbits.png) | ![MAP — PMTiles profile](docs/screenshots/map-pmtiles-profile.png) | ![DATA — quakes feed](docs/screenshots/data-quakes-feed.png) | ![SPLIT — globe + map](docs/screenshots/split-globe-map-sync.png) |

Full set: [`docs/screenshots/`](docs/screenshots/README.md)

### Pi sync

```bash
./scripts/start-docker.sh     # Linux: HTTPS stack + node token + LAN auto-detect
# .\scripts\start-docker.ps1  # Windows: same
```

Details → [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md) · agent reference → [`AGENTS.md`](AGENTS.md) · Linux migration → [`docs/LINUX_MIGRATION_PLAN.md`](docs/LINUX_MIGRATION_PLAN.md)

---

## What works without keys

Most feeds are **fail-soft** (stale cache or empty payload on upstream errors — never a crashed globe).

| Tag | Layers | Key |
|-----|--------|-----|
| `no-key` | Aircraft (adsb.fi / adsb.lol), USGS, EONET, GDACS, SMARD, IODA outages, pegel, ISS, CelesTrak | — |
| `recommended` | NASA FIRMS wildfires, Cloudflare Radar outages | free signup |
| `optional` | OpenSky OAuth (recommended for full ADS-B), ENTSO-E EU energy, Blitzortung lightning, AISstream, ReliefWeb | varies |
| `required` | Cesium terrain/imagery | [Ion token](https://ion.cesium.com/tokens) |

Feed health → `GET /api/health` · trust score → `GET /api/trust` · key catalog (no secrets) → `GET /api/credentials/status` · templates → `backend/.env.example`, `frontend/.env.example`

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  React + CesiumJS (+ MapLibre 2D)          :5176        │
│  Globe · DATA · AI chat · Agent Bus · Agent Swarm       │
└───────────────────────────┬─────────────────────────────┘
                            │ /api/*
┌───────────────────────────▼─────────────────────────────┐
│  FastAPI + SQLite + DuckDB                  :8002        │
│  MCP · Agent Bus · hybrid RAG · briefing agentic loop   │
│  5-agent orchestrator · anomaly detection · predictive  │
│  4-layer anti-hallucination · /api/trust · provenance   │
│  Celery worker + beat (Docker) · Redis cache/pubsub     │
└───────────────────────────┬─────────────────────────────┘
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
    USGS · NASA ·      Ollama :11434      Pi :443/ingest
    GDACS · SMARD …    qwen3 + RAG        (offgrid-raspi)
    30+ feeds          6 cloud providers   delta sync
         │       │       │
         │       │       └── NVIDIA NIM · Groq · OpenRouter · Cerebras · SambaNova · DeepSeek
         │       │
         │       └── Cursor MCP (Streamable HTTP) + Docker MCP gateway
         │
         └── Caddy TLS (Docker) → https://localhost
```

Agent reference → [`AGENTS.md`](AGENTS.md) · MCP setup → [`docs/MCP.md`](docs/MCP.md)

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [`AGENTS.md`](AGENTS.md) | Runtime, endpoints, key files, architecture notes, troubleshooting |
| [`docs/FEATURES.md`](docs/FEATURES.md) | Optional features — env vars, setup, guardrails |
| [`docs/WORLDBASE_ROADMAP_V4.md`](docs/WORLDBASE_ROADMAP_V4.md) | V4 roadmap — sprints, ADRs, shipped features |
| [`docs/WORLDBASE_ROADMAP_V2.md`](docs/WORLDBASE_ROADMAP_V2.md) | Compact roadmap — shipped items reference + open work |
| [`docs/LINUX_MIGRATION_PLAN.md`](docs/LINUX_MIGRATION_PLAN.md) | Migrate WorldBase from Windows to Linux |
| [`docs/MCP.md`](docs/MCP.md) | Cursor MCP tools, Agent Bus, Docker gateway |
| [`docs/FIREWALL.md`](docs/FIREWALL.md) | Slim prompt guard + optional HAK_GAL bridge |
| [`docs/DARKWEB.md`](docs/DARKWEB.md) | Dark Web OSINT (P8) — engines, Tor proxy, OPSEC |
| [`docs/TELEGRAM.md`](docs/TELEGRAM.md) | Telegram SOCMINT (K3) — channels, SEA scoring |
| [`docs/GLOBE.md`](docs/GLOBE.md) | Click-to-detail, layers, INTEL FtM, traffic cams |
| [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md) | Optional document intel ingest (GLiNER) |
| [`docs/DOCKER.md`](docs/DOCKER.md) | Docker stack operations, troubleshooting |
| [`docs/SECRETS.md`](docs/SECRETS.md) | Secret management — env, vault, Cesium token |
| [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) | Optional ML licenses, attribution, lineage |
| [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md) | Pi ↔ PC sync |

---

## Pi + PC (two repos)

| Repo | Role | When you need it |
|------|------|------------------|
| **[worldbase](https://github.com/sookoothaii/worldbase)** (this repo) | Windows/Linux PC — Cesium globe, 30+ feeds, Ollama + NVIDIA NIM briefing, node API `:8002` | Spatial intelligence workstation; fusion and LLM digest |
| **[offgrid-raspi](https://github.com/sookoothaii/offgrid-raspi)** | Raspberry Pi — portal, sensors, mesh, offline services | Edge node that survives without mains; pushes telemetry to the PC |

**Together:** Pi `worldbase_push` → PC `POST /api/node/ingest` · PC briefing → Pi `GET /api/node/pull` (v3: ETag/304, SHA-256, conflict detection, `source: worldbase-pc`, briefing quality) → portal / LCD.  
**Canonical sync guide:** [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md)

This repo vendors the Pi repo as a **git submodule** at `offgrid-raspi/` (scripts + sync docs). The Pi itself clones `offgrid-raspi` separately; the PC clones `worldbase` and initializes submodules when you work on push/pull scripts.

**PC UI — EDGE dashboard:** In the HUD, open **DATA → EDGE** for live Pi stats (CPU/RAM/disk/load/uptime, room DHT, services, mesh) and 24h sparklines. The header shows **EDGE ONLINE** when `offgrid-pi` has pushed within 5 minutes (`GET /api/nodes`).

### Operator checks

| Check | Command |
|-------|---------|
| Nodes on PC | `curl -s http://127.0.0.1:8002/api/nodes` |
| Trust probes | `curl -s http://127.0.0.1:8002/api/trust` |
| Anomaly status | `curl -s http://127.0.0.1:8002/api/anomalies/iso/status` |
| PC pull payload (v3) | `GET /api/node/pull` with `X-Node-Token` when `NODE_INGEST_TOKEN` is set |
| Deploy hardened push/pull scripts | `./scripts/deploy-pi-sync.ps1` (Windows) |
| Smoke test | `./scripts/smoke-test.ps1` → expect **33 PASS / 0 FAIL / 1 WARN** |
| Pi disk maintenance | `sudo bash pi-disk-maintenance.sh` (on Pi) |

---

## License

MIT — see repository terms for WorldBase core code.

Optional features (document intel ingest, external feeds, downloaded models) may pull in **separate third-party licenses**. In particular, **GLiREL relation extraction is disabled by default** because it is CC BY-NC-SA (non-commercial). See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md).
