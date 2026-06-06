# WORLDBASE — Spatial Intelligence Workstation

A Windows-native data-fusion dashboard: a CesiumJS 3D globe overlaid with live
real-world feeds (aircraft, satellites, earthquakes, natural events, the ISS), tactical vision
modes, click-to-locate, and a local Ollama AI chat panel. FastAPI backend, React + Vite frontend.

Runs two ways: **natively** (venv + Vite, `start.ps1`) for development, or as a fully
**containerized stack** (`docker compose`) where the PC and the off-grid Pi connect over
**HTTPS with token-authenticated sync** — see [`docs/DOCKER_DEPLOY.md`](docs/DOCKER_DEPLOY.md).

> Inspired by Bilawal Sidhu's WorldView and the offgrid-raspi stack.

---

## Features

- **3D Globe** — Cesium World Terrain with lighting, atmosphere, and fog.
- **Live feeds** (auto-refreshing):
  - Aircraft positions — **OpenSky** (optional OAuth) or **adsb.lol** global grid (free, no key)
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
  - Humanitarian crises on globe — **GDACS** alerts (geocoded); optional **ReliefWeb v2** (`RELIEFWEB_APPNAME`)
  - Timeline scrub — earthquakes + EONET events (6/12/24h window on globe)
  - Situation Board — fused correlations, anomalies, GDACS, pegel, Pi sensors (`GET /api/situations`)
  - GDELT news pulse — global headline themes (`GET /api/gdelt/pulse`, no key)
  - NWS/Meteoalarm hazards + GDELT GEO on globe (`GET /api/hazards`, `GET /api/gdelt/geo`)
  - River feed anomalies + RAG memory (`GET /api/anomalies/river`, `GET /api/memory/search`)
  - Internet outages (IODA) + volcanoes (Smithsonian) + NASA GIBS imagery toggle on globe
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
- **OSINT console** — quick lookups (IP, domain, email, …) plus **[Flowsint](https://github.com/reconurge/flowsint)** graph investigations (Docker on PC; see `docs/FLOWSINT_INTEGRATION.md`). OpenOSINT remains on the off-grid Pi.
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

## Quick Start (Docker — recommended)

Docker 24+ with Compose. Brings up the backend (FastAPI), the SPA, and a Caddy
reverse proxy with **internal-CA TLS** in one command:

```powershell
Set-Location -LiteralPath 'D:\MCP Mods\worldbase'
.\scripts\start-docker.ps1     # generates a node token, detects LAN IP, builds + runs
```

Open **https://localhost** (accept the internal-CA warning once). The Pi reaches
the PC at `https://<pc-lan-ip>/api/node/ingest`. Stop with `.\scripts\stop-docker.ps1`.
Full guide + security model: [`docs/DOCKER_DEPLOY.md`](docs/DOCKER_DEPLOY.md).

---

## Quick Start (native, no Docker)

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
Set-Location -LiteralPath 'D:\MCP Mods\worldbase'   # adjust path
.\start.ps1
```
Launches the backend (`uvicorn` on **:8002**) and frontend (Vite on **:5176**).

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
  |- /api/aircraft      ADS-B states (OpenSky OAuth or adsb.lol fallback; field `source`)
  |- /api/anomalies     aircraft anomaly scan (same provider)
  |- /api/situations    fused situation board (correlations, GDACS, pegel, nodes)
  |- /api/gdelt/pulse   GDELT headline themes (cached, no key)
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
  |- /api/geopolitics   GDACS crises (geocoded) + optional ReliefWeb v2
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
| Frontend    | 5176  | Vite dev server (`start.ps1`) |
| Backend API | 8002  | FastAPI + auto docs (`/docs`) |
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

- **adsb.lol** — global ADS-B grid (free, no key; default when OpenSky not configured)
- **OpenSky Network** — optional OAuth for higher aircraft rate limits
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
- **ReliefWeb v2 (UN OCHA)** — optional disasters on CRISES layer (`RELIEFWEB_APPNAME`)
- **GDELT DOC** — news pulse API (rate-limited; backend caches 10 min)
- **Public webcam feeds** — traffic agencies, weather services, NASA, city tourism
- **OpenAI / Anthropic / Groq / OpenRouter** — optional cloud LLM providers

The only credential you need is a Cesium Ion token (for terrain/imagery).

---

## Security note

The Cesium Ion token is read from `frontend/.env` (git-ignored) via `VITE_CESIUM_ION_TOKEN`.
It is a client-side token (shipped in the built JS), so restrict it to your domains using the
URL allowlist in the Ion console. Never commit your real `.env`.

**Pi sync:** set `NODE_INGEST_TOKEN` via `.\scripts\setup-node-security.ps1` and deploy to the Pi (`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`).

**Start on Windows** (paths with spaces):

```powershell
Set-Location -LiteralPath 'D:\MCP Mods\worldbase'
.\start.ps1
```

Use `http://localhost:5176` for the UI (Vite may listen on IPv6 `::1` only).

---

## Off-grid Pi (submodule)

Submodule: `offgrid-raspi/`. Edge node at `192.168.1.121`, sync to WorldBase on **port 8002**.

| Topic | Doc |
|-------|-----|
| Pi ↔ WorldBase sync + token | [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md) |
| Storage (root vs SD, Borg) | [`offgrid-raspi/docs/pi-storage-layout.md`](offgrid-raspi/docs/pi-storage-layout.md) |
| Security ops (PC + Pi) | [`docs/SECURITY_OPERATIONS.md`](docs/SECURITY_OPERATIONS.md) |
| Operator status | [`offgrid-raspi/OFFGRID_STATUS.md`](offgrid-raspi/OFFGRID_STATUS.md) |
| LLM / WorldBase integration | [`LLM_HANDOFF.md`](LLM_HANDOFF.md) |
| Next mission / backlog | [`docs/NEXT_LLM_MISSION.md`](docs/NEXT_LLM_MISSION.md) |
| Flowsint (graph OSINT) | [`docs/FLOWSINT_INTEGRATION.md`](docs/FLOWSINT_INTEGRATION.md) |

SSH from Windows:

```powershell
& "$env:WINDIR\System32\OpenSSH\ssh.exe" -i "$env:USERPROFILE\.ssh\offgrid-pi" user0@192.168.1.121
```

**Flowsint on PC:** `.\scripts\setup-flowsint.ps1` then `.\scripts\start-flowsint.ps1 -Build` — embed in WorldBase OSINT tab.

**Security (PC + Pi):** [`docs/SECURITY_OPERATIONS.md`](docs/SECURITY_OPERATIONS.md) — `.\scripts\setup-node-security.ps1`, `.\scripts\pc-security-audit.ps1`

---

## License

MIT
