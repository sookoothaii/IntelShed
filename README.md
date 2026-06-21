# WorldBase

![MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)
![Cesium](https://img.shields.io/badge/Cesium-1.142-6CADDF?style=flat-square)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20qwen3-black?style=flat-square)

**Spatial intelligence workstation** — live OSINT feeds on a Cesium globe, fusion analytics, and local AI chat.

`FastAPI` · `React` · `Vite` · `SQLite` · `Ollama` · optional `Pi` edge sync

WorldBase is the **PC stack**. It extends the off-grid Pi workshop ([`offgrid-raspi`](https://github.com/sookoothaii/offgrid-raspi)) with heavy fusion, a 24h security briefing, and globe UX. Run WorldBase alone on a PC, or **Pi + PC together** via push/pull sync (see below).

---

## At a glance

| | |
|---|---|
| **Globe** | 30+ live layers — aircraft, quakes, disasters, energy, maritime, transit |
| **MAP** | Offline Protomaps via PMTiles — regional (`thailand`) or full planet (`planet_full` ~130 GB) |
| **Intelligence** | Situations, correlations, anomalies, OpenSanctions via Yente, fast RAG memory (sqlite-vec) |
| **AI** | Local chat via Ollama (`qwen3:8b` default) |
| **Edge** | Off-grid Pi pushes sensors → PC fuses → hardened briefing pull back to Pi |
| **Trust** | Rule-based briefing quality + field trust score (FULL SITUATION panel; feed drift + connector provenance) |
| **Thailand operator** | CAMS haze, HDX humanitarian, GDELT local, maritime Malacca corridor — enriched LOCAL/REGION briefing blocks |
| **MCP** | Cursor/Claude: 12 tools — briefing, nodes, feeds, generate, optional globe control — [`docs/MCP.md`](docs/MCP.md) |
| **Agent Bus** | MCP/REST → fly globe + toggle layers when HUD open at `:5176` |
| **Philosophy** | Positive intelligence — better decisions, not attacks |

---

## Quick start

### Native (development)

```powershell
Set-Location -LiteralPath 'D:\MCP Mods\worldbase'
copy frontend\.env.example frontend\.env   # set VITE_CESIUM_ION_TOKEN
.\start.ps1
```

| Service | URL |
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

Restart backend + Vite; add `worldbase` to Cursor MCP (`http://127.0.0.1:8002/api/mcp` + `X-API-Key` if set). Expect **12 tools** when Agent Bus is on.

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text   # RAG embeddings
```

**Verify stack:** `.\scripts\smoke-test.ps1` (30 checks — backend, feeds, trust probes, STAC feed items, Vite proxy, Ollama chat, build)

`.\start.ps1` waits for `GET /api/health/ping` before starting Vite so the HUD does not hit proxy `ECONNREFUSED` on first load. After boot, the backend runs a **feed warm-up** (~90 s): GDELT local pulse, traffic cams, maritime, CAMS haze, air quality, Bangkok weather.

### Optional: live maritime AIS (Thailand corridor)

Free key at [aisstream.io](https://aisstream.io) → `backend/.env`:

```env
AISSTREAM_API_KEY=your-key
# WORLDBASE_MARITIME_AISSTREAM=1          # background WebSocket collector (default on when key set)
# WORLDBASE_MARITIME_COLLECT_SEC=30       # one-shot snapshot when collector off
# WORLDBASE_MARITIME_STREAM_STALE_SEC=1800
# WORLDBASE_MARITIME_MAX_VESSELS=800
# WORLDBASE_MARITIME_REGIONS=malacca,laem_chabang,bangkok_port,phuket,singapore  # default when WORLDBASE_OPERATOR_REGION=thailand
```

Restart backend. The API reads a **background AISstream buffer** (non-blocking); JSON includes `stream_connected` and `stream_buffer`. Without the key, `/api/maritime` falls back to MyShipTracking or demo fleet.

**STAC feed items:** `GET /api/stac/feeds/items` exposes connector snapshots with bbox/geometry and registry links. In the HUD: **DATA → FEEDS** — STAC JSON link and ⊕ fly-to per connector.

### Optional: Thailand briefing enrichment (no extra keys)

| Endpoint | Role |
|----------|------|
| `GET /api/cams/haze` | CAMS dust / AOD for Bangkok, Chiang Mai, ASEAN cities |
| `GET /api/humanitarian` | HDX datasets (Myanmar border, displacement) |
| `GET /api/gdelt/pulse/local` | Operator-region GDELT headlines |

These feed the 24h security digest LOCAL / REGION blocks automatically.

### Offline maps (PMTiles)

```powershell
# Regional stack (~500 MB) — default for fast MAP load
.\scripts\download-pmtiles.ps1 -Region stack

# Full planet (~130 GB, resumable BITS)
.\scripts\download-pmtiles.ps1 -Region world-full -Force

# Optional ZXY MVT tiles (experimental Globe MVT layer)
.\scripts\start-pmtiles-serve.ps1   # http://127.0.0.1:8088
```

In **MAP** view, pick the archive in the dropdown. Default is **`thailand`** for speed; select **`planet_full`** for global offline detail when the ~130 GB file is present.

### Split view

**◫ SPLIT** in the HUD shows Globe (left) and Map (right) with linked camera sync.

- Both panes stay **mounted** (no remount on toggle — MapLibre keeps its state).
- CSS **grid** layout (`hud-main--split`) — no overlapping absolute layers over the WebGL canvas.
- On the globe half, heavy chrome (telemetry, controls, timeline) is hidden for a larger interactive area.
- First split open may briefly load PMTiles on the right; later toggles are instant.

Use for tactical overview (3D feeds) + precise 2D basemap side by side.

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
| `optional` | OpenSky OAuth, ENTSO-E EU energy, Blitzortung lightning, AIS, ReliefWeb | varies |
| `required` | Cesium terrain/imagery | [Ion token](https://ion.cesium.com/tokens) |

Feed health → `GET /api/health` · optional keys → `backend/.env.example`

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
│  MCP /api/mcp · Agent Bus /api/agent/* · /api/health    │
└───────────────────────────┬─────────────────────────────┘
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
    USGS · NASA ·      Ollama :11434      Pi :8002/ingest
    GDACS · SMARD …    qwen3 + RAG        (offgrid-raspi)
         │
         └── Cursor MCP (Streamable HTTP) + optional Docker MCP gateway
```

Agent reference → [`AGENTS.md`](AGENTS.md) · MCP setup → [`docs/MCP.md`](docs/MCP.md)

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [`AGENTS.md`](AGENTS.md) | Runtime, endpoints, key files, troubleshooting |
| [`docs/MCP.md`](docs/MCP.md) | Cursor MCP tools, Agent Bus, Docker gateway |
| [`docs/GLOBE.md`](docs/GLOBE.md) | Click-to-detail, layers, INTEL FtM, traffic cams |
| [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md) | Optional document intel ingest (GLiNER) |
| [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md) | Pi ↔ PC sync |

---

## Standing on the shoulders of giants

WorldBase is not a standalone invention. It exists entirely because of the generous, brilliant work of the open-source and open-data communities. We are deeply humbled and profoundly grateful to build upon the foundations laid by others. **To the giants whose shoulders we stand on: Thank you.**

| Inspiration & Foundation | Contribution & Gratitude |
|--------------------------|--------------------------|
| **[Bilawal Sidhu](https://www.youtube.com/watch?v=rXvU7bPJ8n4)** · *WorldView* | The original visionary spark. The tactical globe UX, vision modes (NVG/FLIR/CRT), and the concept of multi-feed fusion on Cesium started here. |
| **[K-AI-STACK/WorldView](https://github.com/K-AI-STACK/WorldView)** | For pioneering the open layer catalog and the Cesium-first OSINT dashboard structure that made this possible. |
| **[kevtoe/worldview](https://github.com/kevtoe/worldview)** | For providing the foundational full-stack proxy pattern, tactical UI tokens, and Resium + Vite references. |
| **[petieclark/worldview](https://github.com/petieclark/worldview)** | For the robust backend key proxying, health endpoint designs, and Docker deployment models. |
| **[Reconurge/Flowsint](https://github.com/reconurge/flowsint)** | For the incredible OSINT graph visualization and making threat intelligence accessible. |
| **[CesiumJS](https://cesium.com/)** & **[MapLibre](https://maplibre.org/)** | For building the stunning 3D/2D rendering engines that power the spatial intelligence core. |
| **[SQLite](https://sqlite.org/)** & **[sqlite-vec](https://github.com/asg017/sqlite-vec)** | For proving that local, offline-first databases can power blazing-fast vector search and RAG memory without cloud lock-in. |
| **[Ollama](https://ollama.com/)** & **[Qwen](https://qwenlm.github.io/)** | For democratizing LLMs and enabling local, private intelligence analysis at the edge. |
| **[OpenSanctions](https://www.opensanctions.org/)** & **[Yente](https://github.com/opensanctions/yente)** | For the tireless work of maintaining public, CC-BY datasets and an enterprise-grade matching API that brings transparency to the world. |
| **Public Civic Data Providers** | USGS, NASA (EONET/FIRMS/GIBS), NOAA SWPC, GDACS, SMARD, IODA, Open-Meteo, CelesTrak, adsb.lol/adsb.fi, Element84, Pegelonline, and every single engineer maintaining free civic APIs. You are the lifeblood of this project. |

---

## Pi + PC (two repos)

| Repo | Role | When you need it |
|------|------|------------------|
| **[worldbase](https://github.com/sookoothaii/worldbase)** (this repo) | Windows/Linux PC — Cesium globe, 30+ feeds, Ollama briefing, node API `:8002` | Spatial intelligence workstation; fusion and LLM digest |
| **[offgrid-raspi](https://github.com/sookoothaii/offgrid-raspi)** | Raspberry Pi — portal, sensors, mesh, offline services | Edge node that survives without mains; pushes telemetry to the PC |

**Together:** Pi `worldbase_push` → PC `POST /api/node/ingest` · PC briefing → Pi `GET /api/node/pull` → portal / LCD.  
**Canonical sync guide:** [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md)

This repo vendors the Pi repo as a **git submodule** at `offgrid-raspi/` (scripts + sync docs). The Pi itself clones `offgrid-raspi` separately; the PC clones `worldbase` and initializes submodules when you work on push/pull scripts.

**PC UI — EDGE dashboard:** In the HUD, open **DATA → EDGE** for live Pi stats (CPU/RAM/disk/load/uptime, room DHT, services, mesh) and 24h sparklines. The header shows **EDGE ONLINE** when `offgrid-pi` has pushed within 5 minutes (`GET /api/nodes`).

---

| Check | Command |
|-------|---------|
| Nodes on PC | `Invoke-RestMethod http://127.0.0.1:8002/api/nodes` |
| Deploy token + HTTP | `.\scripts\sync-pi.ps1` |
| Pi maintenance | `sudo bash pi-disk-maintenance.sh` (on Pi) |
| Smoke test | `.\scripts\smoke-test.ps1` → expect **27/27 PASS** |

---

## License

MIT — see repository terms for WorldBase core code.

Optional features (document intel ingest, external feeds, downloaded models) may pull in **separate third-party licenses**. In particular, **GLiREL relation extraction is disabled by default** because it is CC BY-NC-SA (non-commercial). See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md).
