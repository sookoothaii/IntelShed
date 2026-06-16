# WorldBase

![MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)
![Cesium](https://img.shields.io/badge/Cesium-1.142-6CADDF?style=flat-square)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20qwen3-black?style=flat-square)

**Spatial intelligence workstation** — live OSINT feeds on a Cesium globe, fusion analytics, and local AI chat.

`FastAPI` · `React` · `Vite` · `SQLite` · `Ollama` · optional `Pi` edge sync

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

WorldBase builds on ideas and patterns from the open geospatial OSINT community. **Thank you:**

| Inspiration | Contribution |
|-------------|--------------|
| **[Bilawal Sidhu](https://www.youtube.com/watch?v=rXvU7bPJ8n4)** · *WorldView* | Tactical globe UX, vision modes (NVG/FLIR/CRT), multi-feed fusion on Cesium |
| **[K-AI-STACK/WorldView](https://github.com/K-AI-STACK/WorldView)** | Open layer catalog & Cesium-first OSINT dashboard structure |
| **[kevtoe/worldview](https://github.com/kevtoe/worldview)** | Full-stack proxy pattern, tactical UI tokens, Resium + Vite reference |
| **[petieclark/worldview](https://github.com/petieclark/worldview)** | Backend key proxying, health endpoint, Docker deployment model |
| **[CesiumJS](https://cesium.com/)** · **[satellite.js](https://github.com/shashwatak/satellite-js)** | 3D globe & SGP4 orbit propagation |
| **offgrid-raspi** (submodule) | Edge node, mesh, Pi ↔ PC sync architecture |
| **Public data providers** | USGS, NASA (EONET/FIRMS/GIBS), NOAA SWPC, GDACS, SMARD, IODA, Open-Meteo, CelesTrak, adsb.lol, OpenSanctions CC-BY, and everyone maintaining free civic APIs |

---

## Pi edge (submodule)

`offgrid-raspi/` @ `91683d8` — full sync guide: [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md)

| Check | Command |
|-------|---------|
| Nodes on PC | `Invoke-RestMethod http://127.0.0.1:8002/api/nodes` |
| Deploy token + HTTP | `.\scripts\sync-pi.ps1` |
| Pi maintenance | `sudo bash pi-disk-maintenance.sh` (on Pi) |
| Smoke test | `.\scripts\smoke-test.ps1` → expect **23/23 PASS** |

---

## License

MIT
