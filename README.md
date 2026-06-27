# WorldBase

![MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)
![Cesium](https://img.shields.io/badge/Cesium-1.142-6CADDF?style=flat-square)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20qwen3-black?style=flat-square)
![NVIDIA NIM](https://img.shields.io/badge/LLM-NVIDIA%20NIM%20step--3.7--flash-76B900?style=flat-square&logo=nvidia&logoColor=white)

**Spatial intelligence workstation** — live OSINT feeds on a Cesium globe, fusion analytics, and local AI chat.

WorldBase is a thin integration layer: almost everything here rests on libraries, datasets, and tools that other people built and shared. We are grateful to every maintainer whose work makes this project possible.

`FastAPI` · `React` · `Vite` · `SQLite` · `Ollama` · `NVIDIA NIM` · optional `Pi` edge sync

WorldBase is the **PC stack**. It extends the off-grid Pi workshop ([`offgrid-raspi`](https://github.com/sookoothaii/offgrid-raspi)) with heavy fusion, a 24h security briefing, and globe UX. Run WorldBase alone on a PC, or **Pi + PC together** via push/pull sync (see below).

---

## At a glance

| | |
|---|---|
| **Globe** | 30+ live layers — aircraft, quakes, disasters, energy, maritime, transit |
| **MAP** | Offline Protomaps via PMTiles — regional or full planet (~130 GB) |
| **Briefing** | 24h security digest (LOCAL / REGION / GLOBAL), watch items, prediction ledger, agentic loop |
| **Intelligence** | FtM entity graph, OpenSanctions, hybrid RAG (sqlite-vec + FTS5 + RRF + optional BGE rerank) |
| **AI** | Ollama (`qwen3:8b`) + 5 cloud providers; 3-layer anti-hallucination stack (prompt protocol + NIM tweaks + Claim Auditor) |
| **OSINT** | Dark web (P8), ransomware intel, identity enumeration (P9), Telegram SOCMINT, satellite change detection |
| **Entity resolution** | Per-dataset dedupe → cross-dataset link (Splink), dual-pipeline, human-in-the-loop labelling |
| **Multi-agent** | 5-agent orchestrator (Coverage → Retrieval → Spatial → Corroboration → Synthesis), 0 VRAM |
| **Edge** | Off-grid Pi pushes sensors → PC fuses → hardened briefing pull back to Pi |
| **Trust** | Rule-based briefing quality + feed drift + connector provenance (`GET /api/trust`) |
| **MCP** | Cursor/Claude: 13 tools — briefing, nodes, feeds, globe control — [`docs/MCP.md`](docs/MCP.md) |
| **Philosophy** | Positive intelligence — better decisions, not attacks |

Full feature catalog with env vars and setup → [`docs/FEATURES.md`](docs/FEATURES.md)

---

## Quick start

**Prerequisites:** Python 3.11+, Node.js 18+, [Ollama](https://ollama.com/) (`qwen3:8b`, `nomic-embed-text`), free [Cesium Ion](https://ion.cesium.com/tokens) token. Optional: [NVIDIA NIM API key](https://build.nvidia.com/) for cloud reasoning models (free tier incl. `stepfun-ai/step-3.7-flash`). Windows: use `-LiteralPath` when the clone path contains spaces.

### Native (development)

```powershell
git clone https://github.com/sookoothaii/worldbase.git
cd worldbase
git submodule update --init --recursive   # Pi sync scripts in offgrid-raspi/
copy backend\.env.example backend\.env    # optional keys; see GET /api/credentials/status
copy frontend\.env.example frontend\.env  # required: VITE_CESIUM_ION_TOKEN
pip install -r backend\requirements.txt
.\start.ps1
```

| Service | URL |
|---------|-----|
| **UI** | http://localhost:5176 |
| **API** | http://localhost:8002/docs |
| **Health** | http://localhost:8002/api/health |
| **Health (fast)** | http://localhost:8002/api/health/ping |
| **Ollama** | http://127.0.0.1:11434 |

Open **http://localhost:5176** (Vite; binds `127.0.0.1` to avoid IPv6-only fallback). API docs: **http://127.0.0.1:8002/docs**.

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

Restart backend + Vite; add `worldbase` to Cursor MCP (`http://127.0.0.1:8002/api/mcp` + `X-API-Key` if set). Expect **13 tools** when Agent Bus is on.

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text   # RAG embeddings
# Optional Track R reranker (CPU):
pip install sentence-transformers   # when RAG_RERANK=1 in backend/.env
```

**Verify stack:** `.\scripts\smoke-test.ps1` → expect **33 PASS / 0 FAIL / 1 WARN** (health, credentials, connectors, trust probes, live feed envelope contract, STAC, satellite health, Vite proxy, Ollama chat, frontend build). The WARN is the expected intel-ingest auth gate when no API key is set for that check.

`.\start.ps1` waits for `GET /api/health/ping` before starting Vite (avoids proxy `ECONNREFUSED`). ~**6 s** after backend boot, a feed warm-up refreshes GDELT local + **global** pulse, traffic cams, maritime, CAMS haze, air quality, and Bangkok weather.

### Screenshots

| GLOBE | MAP | DATA | SPLIT |
|-------|-----|------|-------|
| ![Globe — Starlink orbits](docs/screenshots/globe-starlink-orbits.png) | ![MAP — PMTiles profile](docs/screenshots/map-pmtiles-profile.png) | ![DATA — quakes feed](docs/screenshots/data-quakes-feed.png) | ![SPLIT — globe + map](docs/screenshots/split-globe-map-sync.png) |

Full set: [`docs/screenshots/`](docs/screenshots/README.md)

### Docker + Pi sync

```powershell
.\scripts\start-docker.ps1    # HTTPS stack + node token
.\scripts\start-flowsint.ps1  # Optional: Flowsint OSINT graph
.\scripts\start-yente.ps1     # Optional: Yente OpenSanctions API
```

Details → [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md) · agent reference → [`AGENTS.md`](AGENTS.md)

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
│  Globe · DATA · AI chat · Agent Bus subscriber          │
└───────────────────────────┬─────────────────────────────┘
                            │ /api/*
┌───────────────────────────▼─────────────────────────────┐
│  FastAPI + SQLite feed_cache                 :8002        │
│  MCP · Agent Bus · hybrid RAG · briefing agentic loop   │
│  briefing quality · /api/trust · claim auditor           │
└───────────────────────────┬─────────────────────────────┘
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
    USGS · NASA ·      Ollama :11434      Pi :8002/ingest
    GDACS · SMARD …    qwen3 + RAG        (offgrid-raspi)
         │       │
         │       └── NVIDIA NIM API (step-3.7-flash, free tier)
         │
         └── Cursor MCP (Streamable HTTP) + optional Docker MCP gateway
```

Agent reference → [`AGENTS.md`](AGENTS.md) · MCP setup → [`docs/MCP.md`](docs/MCP.md)

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [`AGENTS.md`](AGENTS.md) | Runtime, endpoints, key files, troubleshooting |
| [`docs/FEATURES.md`](docs/FEATURES.md) | Optional features — env vars, setup, guardrails |
| [`docs/WORLDBASE_ROADMAP_2026.md`](docs/WORLDBASE_ROADMAP_2026.md) | Full 2026 roadmap — P3–P10, J1–J6, K3–K4 changelog |
| [`docs/MCP.md`](docs/MCP.md) | Cursor MCP tools, Agent Bus, Docker gateway |
| [`docs/FIREWALL.md`](docs/FIREWALL.md) | Slim prompt guard + optional HAK_GAL bridge |
| [`docs/DARKWEB.md`](docs/DARKWEB.md) | Dark Web OSINT (P8) — engines, Tor proxy, OPSEC |
| [`docs/TELEGRAM.md`](docs/TELEGRAM.md) | Telegram SOCMINT (K3) — channels, SEA scoring |
| [`docs/GLOBE.md`](docs/GLOBE.md) | Click-to-detail, layers, INTEL FtM, traffic cams |
| [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md) | Optional document intel ingest (GLiNER) |
| [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) | Optional ML licenses, attribution, lineage |
| [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md) | Pi ↔ PC sync |

---

## Pi + PC (two repos)

| Repo | Role | When you need it |
|------|------|------------------|
| **[worldbase](https://github.com/sookoothaii/worldbase)** (this repo) | Windows/Linux PC — Cesium globe, 30+ feeds, Ollama + NVIDIA NIM briefing, node API `:8002` | Spatial intelligence workstation; fusion and LLM digest |
| **[offgrid-raspi](https://github.com/sookoothaii/offgrid-raspi)** | Raspberry Pi — portal, sensors, mesh, offline services | Edge node that survives without mains; pushes telemetry to the PC |

**Together:** Pi `worldbase_push` → PC `POST /api/node/ingest` · PC briefing → Pi `GET /api/node/pull` (v2: ETag/304, SHA-256, `source: worldbase-pc`, briefing quality) → portal / LCD.  
**Canonical sync guide:** [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md)

This repo vendors the Pi repo as a **git submodule** at `offgrid-raspi/` (scripts + sync docs). The Pi itself clones `offgrid-raspi` separately; the PC clones `worldbase` and initializes submodules when you work on push/pull scripts.

**PC UI — EDGE dashboard:** In the HUD, open **DATA → EDGE** for live Pi stats (CPU/RAM/disk/load/uptime, room DHT, services, mesh) and 24h sparklines. The header shows **EDGE ONLINE** when `offgrid-pi` has pushed within 5 minutes (`GET /api/nodes`).

### Operator checks

| Check | Command |
|-------|---------|
| Nodes on PC | `Invoke-RestMethod http://127.0.0.1:8002/api/nodes` |
| Trust probes | `Invoke-RestMethod http://127.0.0.1:8002/api/trust` |
| PC pull payload (v2) | `GET /api/node/pull` with `X-Node-Token` when `NODE_INGEST_TOKEN` is set |
| Deploy token + HTTP to Pi | `.\scripts\setup-node-security.ps1` then `.\scripts\sync-pi.ps1` |
| Deploy hardened push/pull scripts | `.\scripts\deploy-pi-sync.ps1` |
| Smoke test | `.\scripts\smoke-test.ps1` → expect **33 PASS / 0 FAIL / 1 WARN** |
| Pi disk maintenance | `sudo bash pi-disk-maintenance.sh` (on Pi) |

---

## License

MIT — see repository terms for WorldBase core code.

Optional features (document intel ingest, external feeds, downloaded models) may pull in **separate third-party licenses**. In particular, **GLiREL relation extraction is disabled by default** because it is CC BY-NC-SA (non-commercial). See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md).
