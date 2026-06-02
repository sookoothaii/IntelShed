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
  - Space weather — planetary K-index, aurora/HF-radio impact (NOAA SWPC)
  - Wildfire thermal anomalies, confidence-colored (NASA FIRMS MODIS + VIIRS)
  - Lightning strikes worldwide, 10-minute fade (Blitzortung.org)
  - German power grid — generation mix, CO₂ intensity, day-ahead price (SMARD / Bundesnetzagentur)
  - EU electricity — Day Ahead prices + generation mix by source (ENTSO-E Transparency Platform, 14 bidding zones)
  - Stock markets — DAX, S&P 500, NASDAQ, Nikkei, Gold, Oil, BTC, ETH (Yahoo Finance)
  - GTFS-Realtime public transit — live vehicle positions (Helsinki HSL, Boston MBTA, Berlin VBB, Hamburg HVV, Munich MVV)
  - Maritime AIS — live vessel positions by type, port-region tracking (MyShipTracking / AISHub)
  - Air quality — PM2.5 / PM10 for major cities (Open-Meteo)
  - GDACS alerts — tsunami, cyclone, flood, drought, volcano (GDACS / UN)
  - Markets — crypto (CoinGecko) + ECB forex (Frankfurter)
  - Military / interesting aircraft (adsb.fi open data)
  - Point weather for any coordinate (Open-Meteo)
  - Humanitarian disasters worldwide (ReliefWeb / UN OCHA)
- **DATA panel** — searchable, filterable tables per feed with satellite-group selector.
- **Click-to-locate** — click any event or earthquake in the DATA panel to fly to it on the
  globe with a pulsing marker and a TARGET LOCK info card (incl. source links).
- **Vision modes** — Normal, NVG (night vision), Thermal/FLIR, CRT scanlines, Night — GLSL
  post-processing shaders.
- **Multi-Provider AI chat** — primary: local Ollama (`:11434`). Optional: OpenAI,
  Anthropic, Groq, OpenRouter — switchable via provider dropdown. Streaming for all.
  Zuschaltbare LLM-Security-Firewall integration (HAK_GAL) scans prompts before
  reaching any provider.
- **Public webcam feeds** — curated traffic, nature, space, and city webcams
  (NASA ISS HDEV, traffic cams, weather stations, cityscapes). Grid view + fullscreen.
- **OSINT console** — a peer tab alongside AI that embeds the OpenOSINT toolset
  (username/email/IP enumeration, etc.) running on the off-grid Pi.
- **PC ↔ Pi node sync** — the off-grid Pi pushes its edge telemetry (CPU temp, sensors,
  mesh nodes, Pi-hole, systemd health) into WorldBase every 45 s via a systemd daemon;
  the PC fuses all feeds with the local LLM into a world-situation briefing the Pi pulls
  back every 5 min for offline display. One organism.
- **Bidirectional Pi control** — send commands from WorldBase UI to any Pi node:
  reboot, shutdown, restart service, custom exec. Command queue with ACK tracking.
- **Sensor time-series** — historical sensor data stored per Pi node for graphing.
- **Mesh node visualization** — Meshtastic mesh nodes rendered on globe with
  connection lines and SNR info.
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
  |- /api/spaceweather  NOAA SWPC planetary K-index + impact flags
  |- /api/markets       crypto (CoinGecko) + forex (Frankfurter/ECB)
  |- /api/military      military/interesting aircraft (adsb.fi)
  |- /api/weather       point weather for any lat/lon (Open-Meteo)
  |- /api/airquality    PM2.5 / PM10 for monitored cities (Open-Meteo)
  |- /api/gdacs         GDACS disaster alerts with geo coordinates
  |- /api/geopolitics   active disasters worldwide (ReliefWeb)
  |- /api/wildfires     NASA FIRMS thermal anomalies with confidence
  |- /api/lightning     Blitzortung.org live strikes (~10 min window)
  |- /api/energy/de     German power generation mix + CO₂ + price (SMARD)
  |- /api/eu-energy/price/{country}   EU Day Ahead electricity prices (ENTSO-E)
  |- /api/eu-energy/generation/{country}   EU generation mix by source (ENTSO-E)
  |- /api/stocks        Stock indices + commodities + crypto (Yahoo Finance)
  |- /api/transit/{city} GTFS-Realtime vehicle positions
  |- /api/maritime      AIS vessel positions (port regions + demo fallback)
  |- /api/world         cached aggregate stub
  |- /api/models        list local Ollama models
  |- /api/chat          proxy to Ollama / OpenAI / Anthropic / Groq / OpenRouter
  |- /api/providers     available LLM providers based on configured API keys
  |- /api/models        list local Ollama models
  |
  |- /api/webcams         public webcam feeds (traffic, nature, space, city)
  |- /api/webcams/categories
  |
  |- /api/firewall/status  LLM-Security-Firewall health check
  |
  |  -- node sync (PC brain <-> Pi edge) --
  |- /api/node/ingest   (POST) Pi pushes sensors/mesh/pihole/health/GPS
  |- /api/nodes         live node registry for globe entities
  |- /api/briefing      latest fused LLM world-situation briefing
  |- /api/briefing/generate  (POST) fuse feeds + write briefing via LLM
  |- /api/node/pull     Pi pulls briefing + critical alerts (offline display)
  |- /api/node/{id}/command       queue command for Pi
  |- /api/node/{id}/commands      Pi polls pending commands
  |- /api/node/command/{id}/ack   Pi acks command execution
  |- /api/node/{id}/command-history  view command log
  |- /api/node/{id}/sensors/history  time-series sensor data (24h)
  |- /api/node/{id}/sensors/latest   latest sensor values
  |- /api/mesh/nodes    all mesh nodes from all Pis for globe rendering

Data store (SQLite): feed_cache, aircraft_snapshots, tle_entries, node_state, briefings
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
- **NASA FIRMS** — wildfire thermal anomalies (MODIS + VIIRS)
- **Blitzortung.org** — real-time lightning strikes
- **SMARD (Bundesnetzagentur)** — German power grid data
- **ENTSO-E Transparency Platform** — EU Day Ahead prices + generation mix (free registration)
- **Yahoo Finance** — stock indices, commodities, crypto
- **GTFS-Realtime** — public transit vehicle positions ( TransitFeeds / agency feeds )
- **MyShipTracking / AISHub** — AIS vessel positions (free tier, port regions)
- **wheretheiss.at** — ISS telemetry
- **NOAA SWPC** — space weather (planetary K-index)
- **CoinGecko** — crypto prices
- **Frankfurter / ECB** — forex rates
- **adsb.fi** — military / interesting aircraft (open data, no rate wall)
- **Open-Meteo** — point weather + air quality forecast
- **GDACS** — global disaster alert and coordination system
- **ReliefWeb (UN OCHA)** — active humanitarian disasters
- **Public webcam feeds** — traffic agencies, weather services, NASA, city tourism
- **OpenAI / Anthropic / Groq / OpenRouter** — optional cloud LLM providers

The only credential you need is a Cesium Ion token (for terrain/imagery).

---

## Security note

The Cesium Ion token is read from `frontend/.env` (git-ignored) via `VITE_CESIUM_ION_TOKEN`.
It is a client-side token (shipped in the built JS), so restrict it to your domains using the
URL allowlist in the Ion console. Never commit your real `.env`.

---

## License

MIT
