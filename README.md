# WorldBase — Spatial Intelligence Workstation (Windows, Docker-free)

A Windows-native, Docker-free personal data-fusion dashboard inspired by Bilawal Sidhu's WorldView and the offgrid-raspi stack.

## Quick Start (no Docker)

### 1. Prerequisites
- **Python 3.11+** (python.org)
- **Node.js 20+** (nodejs.org)
- **Ollama** (ollama.com/download) — native Windows installer, runs as service on `:11434`

### 2. One-Command Start
```powershell
.\start.ps1
```

This launches:
- Backend (`uvicorn`) on http://localhost:8000
- Frontend (`vite`) on http://localhost:5173
- API docs at http://localhost:8000/docs

### 3. Manual Start (if preferred)

**Backend:**
```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Frontend:**
```powershell
cd frontend
npm install
npm run dev
```

## Architecture

```
Frontend (Vite + React + CesiumJS)
  └─ Globe view (Cesium World Terrain)
  └─ HUD overlay (aircraft, satellites, market feeds)
  └─ Local AI chat (Ollama :11434)

Backend (FastAPI + SQLite)
  └─ /api/aircraft      → OpenSky Network (live ADS-B)
  └─ /api/satellites    → CelesTrak TLE (orbital data)
  └─ /api/world         → Cached world.json (markets, geo)
  └─ /api/chat          → Proxy to local Ollama

Data Store (SQLite)
  └─ aircraft_snapshots
  └─ tle_entries
  └─ feed_cache
```

## Ports

| Service | Port | Note |
|---------|------|------|
| Frontend | 5173 | Vite dev server |
| Backend API | 8000 | FastAPI + auto docs |
| Ollama | 11434 | Local LLM inference (separate install) |

## Ollama Models

After installing Ollama:
```powershell
ollama pull llama3.2
ollama pull qwen2.5
ollama list
```

The frontend chat connects to `http://localhost:11434` automatically.

## Data Sources (no API key required)

- **OpenSky Network** — live aircraft positions
- **CelesTrak** — satellite TLE orbital data
- **Open-Meteo** — weather (optional expansion)

## Vision Modes (planned)

- NVG (Night Vision)
- FLIR (Thermal)
- CRT (Scanlines)
- Anime (Cel-shading)

The shader pipeline is stubbed in `frontend/src/styles/hud.css`.

## License

MIT
