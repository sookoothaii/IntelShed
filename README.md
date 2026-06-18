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
| **Edge** | Off-grid Pi pushes sensors → PC fuses → briefing back to Pi |
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

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text   # RAG embeddings
```

**Verify stack:** `.\scripts\smoke-test.ps1` (23 checks — backend, feeds, Vite proxy, Ollama chat, build)

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

Details → [`docs/SETUP.md`](docs/SETUP.md)

---

## What works without keys

Most feeds are **fail-soft** (stale cache or empty payload on upstream errors — never a crashed globe).

| Tag | Layers | Key |
|-----|--------|-----|
| `no-key` | Aircraft (adsb.fi / adsb.lol), USGS, EONET, GDACS, SMARD, IODA outages, pegel, ISS, CelesTrak | — |
| `recommended` | NASA FIRMS wildfires, Cloudflare Radar outages | free signup |
| `optional` | OpenSky OAuth, ENTSO-E EU energy, Blitzortung lightning, AIS, ReliefWeb | varies |
| `required` | Cesium terrain/imagery | [Ion token](https://ion.cesium.com/tokens) |

Full catalog → [`docs/FEEDS.md`](docs/FEEDS.md) · Keys → [`docs/API-KEYS.md`](docs/API-KEYS.md)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  React + CesiumJS (+ MapLibre 2D)          :5176        │
│  Globe · DATA panel · AI chat · OSINT · Situations      │
└───────────────────────────┬─────────────────────────────┘
                            │ /api/*
┌───────────────────────────▼─────────────────────────────┐
│  FastAPI + httpx + SQLite feed_cache         :8002        │
│  TTL cache · /api/globe/snapshot · /api/health            │
└───────────────────────────┬─────────────────────────────┘
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
    USGS · NASA ·      Ollama :11434      Pi :8002/ingest
    GDACS · SMARD …    qwen3 + RAG        (offgrid-raspi)
```

Operator / LLM reference → [`LLM_HANDOFF.md`](LLM_HANDOFF.md)

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [`docs/FEEDS.md`](docs/FEEDS.md) | Every feed: source, endpoint, cache, tags |
| [`docs/API-KEYS.md`](docs/API-KEYS.md) | Optional credentials & `.env` |
| [`docs/SETUP.md`](docs/SETUP.md) | Docker, Pi sync, PMTiles, Flowsint, security |
| [`LLM_HANDOFF.md`](LLM_HANDOFF.md) | Canonical operator + agent handoff |

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
**Canonical sync guide:** [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md) · setup summary → [`docs/SETUP.md`](docs/SETUP.md#pi-edge-sync)

This repo vendors the Pi repo as a **git submodule** at `offgrid-raspi/` (scripts + sync docs). The Pi itself clones `offgrid-raspi` separately; the PC clones `worldbase` and initializes submodules when you work on push/pull scripts.

**PC UI — EDGE dashboard:** In the HUD, open **DATA → EDGE** for live Pi stats (CPU/RAM/disk/load/uptime, room DHT, services, mesh) and 24h sparklines. The header shows **EDGE ONLINE** when `offgrid-pi` has pushed within 5 minutes (`GET /api/nodes`).

---

| Check | Command |
|-------|---------|
| Nodes on PC | `Invoke-RestMethod http://127.0.0.1:8002/api/nodes` |
| Deploy token + HTTP | `.\scripts\sync-pi.ps1` |
| Pi maintenance | `sudo bash pi-disk-maintenance.sh` (on Pi) |
| Smoke test | `.\scripts\smoke-test.ps1` → expect **25/25 PASS** |

---

## License

MIT — see repository terms for WorldBase core code.

Optional features (document intel ingest, external feeds, downloaded models) may pull in **separate third-party licenses**. In particular, **GLiREL relation extraction is disabled by default** because it is CC BY-NC-SA (non-commercial). See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md).
