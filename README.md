# WORLDBASE — Spatial Intelligence Workstation

A Windows-native, Docker-free data-fusion dashboard: a CesiumJS 3D globe overlaid with live
real-world feeds (aircraft, satellites, earthquakes, natural events, the ISS), tactical vision
modes, click-to-locate, and a local Ollama AI chat panel. FastAPI backend, React + Vite frontend.

> Inspired by Bilawal Sidhu's WorldView and the offgrid-raspi stack.

---

## Features

- **3D Globe** — Cesium World Terrain with lighting, atmosphere, and fog.
- **Live feeds** (auto-refreshing):
  - Aircraft positions (OpenSky Network)
  - Satellite constellations + orbits (CelesTrak TLE, propagated with `satellite.js`)
  - Earthquakes, magnitude-colored (USGS)
  - Natural events — wildfires, storms, volcanoes, ice (NASA EONET)
  - Live ISS telemetry (wheretheiss.at)
- **DATA panel** — searchable, filterable tables per feed with satellite-group selector.
- **Click-to-locate** — click any event or earthquake in the DATA panel to fly to it on the
  globe with a pulsing marker and a TARGET LOCK info card (incl. source links).
- **Vision modes** — Normal, NVG (night vision), Thermal/FLIR, CRT scanlines, Night — GLSL
  post-processing shaders.
- **Local AI chat** — talks to Ollama on `:11434`, model picker included. Fully offline.
- **HUD aesthetic** — animated boot sequence, live UTC clock, system-status pips,
  glassmorphism, neon glow.

---

## Quick Start (no Docker)

### Prerequisites
- **Python 3.11+**
- **Node.js 20+**
- **Ollama** (optional, for the AI panel) — runs as a service on `:11434`
- A free **Cesium Ion token** — <https://ion.cesium.com/tokens>

### 1. Configure the Cesium token
```powershell
copy frontend\.env.example frontend\.env
# then edit frontend\.env and set VITE_CESIUM_ION_TOKEN=<your token>
```

### 2. One-command start
```powershell
.\start.ps1
```
Launches the backend (`uvicorn` on `:8000`) and frontend (`vite` on `:5173`).

### 3. Manual start

**Backend**
```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend**
```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. API docs live at <http://localhost:8000/docs>.

---

## Architecture

```
Frontend (Vite + React + CesiumJS)
  |- Globe        3D terrain, live entity layers, vision shaders, click-to-locate
  |- DATA panel   searchable tables for every feed
  '- AI chat      local Ollama (:11434)

Backend (FastAPI + SQLite, async httpx with TTL caching)
  |- /api/health        service heartbeat
  |- /api/aircraft      OpenSky live ADS-B states
  |- /api/satellites    CelesTrak TLE (group + limit params)
  |- /api/earthquakes   USGS feed (period + magnitude params)
  |- /api/events        NASA EONET natural events (+ source links)
  |- /api/iss           live ISS position/velocity
  |- /api/world         cached aggregate stub
  |- /api/models        list local Ollama models
  '- /api/chat          proxy to local Ollama

Data store (SQLite): feed_cache, aircraft_snapshots, tle_entries
```

---

## Ports

| Service     | Port  | Note                          |
|-------------|-------|-------------------------------|
| Frontend    | 5173  | Vite dev server               |
| Backend API | 8000  | FastAPI + auto docs (`/docs`) |
| Ollama      | 11434 | Local LLM (separate install)  |

---

## Ollama models

```powershell
ollama pull llama3.2
ollama pull qwen2.5
ollama list
```
The AI panel auto-discovers installed models via `/api/models`.

---

## Data sources (no API key required)

- **OpenSky Network** — live aircraft positions
- **CelesTrak** — satellite TLE orbital data
- **USGS** — earthquake feeds
- **NASA EONET** — natural events
- **wheretheiss.at** — ISS telemetry

The only credential you need is a Cesium Ion token (for terrain/imagery).

---

## Security note

The Cesium Ion token is read from `frontend/.env` (git-ignored) via `VITE_CESIUM_ION_TOKEN`.
It is a client-side token (shipped in the built JS), so restrict it to your domains using the
URL allowlist in the Ion console. Never commit your real `.env`.

---

## License

MIT
