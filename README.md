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
| **Intelligence** | Situations, correlations, anomalies, sanctions screening, RAG memory |
| **AI** | Local chat via Ollama (`qwen3:8b` default), optional cloud providers |
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
| **Ollama** | http://127.0.0.1:11434 |

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text   # RAG embeddings
```

Smoke test: `.\scripts\smoke-test.ps1`

### Docker + Pi sync

```powershell
.\scripts\start-docker.ps1    # HTTPS stack + node token
```

Details → [`docs/SETUP.md`](docs/SETUP.md)

---

## What works without keys

Most feeds are **fail-soft** (stale cache or empty payload on upstream errors — never a crashed globe).

| Tag | Layers | Key |
|-----|--------|-----|
| `no-key` | Aircraft (adsb.lol), USGS, EONET, GDACS, SMARD, IODA outages, pegel, ISS, CelesTrak | — |
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
│  TTL cache · provenance · /api/health dashboard         │
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

`offgrid-raspi/` — sync docs: [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md)

---

## License

MIT
