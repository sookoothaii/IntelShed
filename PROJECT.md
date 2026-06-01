# WorldBase — Spatial Intelligence Workstation

> A Docker-free, Windows-native personal data-fusion dashboard inspired by [Bilawal Sidhu](https://bilawal.ai/)'s spatial intelligence thesis and the [offgrid-raspi](https://github.com/sookoothaii/offgrid-raspi) offline-node philosophy.

---

## Table of Contents

1. [Core Idea](#core-idea)
2. [What This Is](#what-this-is)
3. [What This Is Not](#what-this-is-not)
4. [Architecture](#architecture)
5. [Technology Stack](#technology-stack)
6. [Getting Started](#getting-started)
7. [Features](#features)
8. [API Reference](#api-reference)
9. [Data Sources](#data-sources)
10. [Expansion Roadmap](#expansion-roadmap)
11. [Credits & Inspiration](#credits--inspiration)
12. [License](#license)

---

## Core Idea

The thesis is simple: **the physical world is becoming queryable and programmable**. Satellite orbits, aircraft transponders, weather patterns, financial flows, geopolitical events — all of these are data streams that can be fused into a single, navigable spatial model.

WorldBase is a local-first implementation of that thesis. It does not require classified clearances, cloud subscriptions, or expensive infrastructure. It runs on a standard Windows PC with Python, Node.js, and a Cesium ion free-tier token. The entire stack is offline-capable once data is cached.

**Key principles:**

- **Local-first**: SQLite cache, local LLM inference (Ollama), no mandatory cloud.
- **Docker-free**: No containerization complexity. Direct venv + npm.
- **Extensible**: FastAPI backend makes adding new data feeds trivial.
- **Aesthetic**: Military-HUD green-on-black UI. Information density over decoration.

---

## What This Is

A personal spatial intelligence workstation with four pillars:

1. **Globe** — A CesiumJS 3D globe with real terrain, orbital mechanics, and live entity tracking.
2. **Feeds** — Aggregated live data: aircraft (ADS-B), satellites (TLE), world status (markets, geo, news).
3. **Local AI** — Chat interface proxying to a local Ollama instance. No data leaves your machine.
4. **Health** — System monitoring of all backend services and data pipelines.

The reference build assumes a modern Windows PC with enough RAM to run both the web stack and a local LLM (4–8 GB for the LLM, depending on model size).

---

## What This Is Not

- **Not a competitor to Palantir, Google Earth Enterprise, or ESRI ArcGIS.** Those are billion-dollar platforms. This is a personal workshop node.
- **Not a replacement for Ollama, CesiumJS, or OpenSky.** We integrate them.
- **Not guaranteed real-time for critical decisions.** OpenSky has ~10-second latency; CelesTrak TLEs are updated a few times per day. This is situational awareness, not air-traffic control.
- **Not a mesh/off-grid node.** The offgrid-raspi project handles LoRa, Meshtastic, and battery-powered field nodes. WorldBase is grid-tied and desk-bound by design.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  FRONTEND  (Vite + React + TypeScript + CesiumJS)                          │
│  ├─ Globe View        → 3D terrain, entity tracking, vision modes          │
│  ├─ Data Panel        → Aircraft, satellites, world status, health          │
│  ├─ AI Chat           → Local LLM chat (Ollama proxy)                       │
│  └─ HUD Aesthetic     → Military terminal green-on-black theme              │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼ WebSocket / REST (:5173 → :8000 proxy)
┌─────────────────────────────────────────────────────────────────────────────┐
│  BACKEND  (FastAPI + SQLite + httpx)                                         │
│  ├─ /api/health       → System status                                        │
│  ├─ /api/aircraft     → OpenSky Network (live ADS-B positions)             │
│  ├─ /api/satellites   → CelesTrak TLE (orbital data)                       │
│  ├─ /api/world        → Cached world.json (markets, geo, news)             │
│  └─ /api/chat         → Proxy to local Ollama (:11434)                      │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼  (optional, separate install)
┌─────────────────────────────────────────────────────────────────────────────┐
│  OLLAMA  (Native Windows Service)                                            │
│  ├─ Port :11434                                                          │
│  ├─ Models: llama3.2, qwen2.5, deepseek-coder, etc.                        │
│  └─ GPU acceleration via CUDA/ROCm (if available)                            │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. User opens browser → Vite dev server (`:5173`) serves React app.
2. React app proxies `/api/*` requests to FastAPI backend (`:8000`).
3. FastAPI either serves from SQLite cache or fetches live from external APIs (OpenSky, CelesTrak).
4. AI chat requests are forwarded to Ollama (`:11434`) running as a native Windows service.

---

## Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **3D Engine** | CesiumJS | De-facto standard for WebGL globes; used by Bilawal Sidhu's WorldView. |
| **Frontend Framework** | React 18 + TypeScript | Component model + type safety for a dashboard with many data views. |
| **Build Tool** | Vite | Faster than Webpack; `vite-plugin-cesium` handles Cesium asset bundling. |
| **Backend** | FastAPI (Python) | Async by default, auto-generated OpenAPI docs, trivial to add endpoints. |
| **HTTP Client** | httpx | Async HTTP for external API calls (OpenSky, CelesTrak). |
| **Database** | SQLite | Zero-config, sufficient for feed cache and small-scale storage. |
| **LLM Runtime** | Ollama | Simplest local LLM hosting on Windows; CUDA support out of the box. |
| **Styling** | Pure CSS | No Tailwind/Bootstrap dependency; HUD aesthetic is custom anyway. |

---

## Getting Started

### Prerequisites

| Dependency | Minimum Version | Download |
|-----------|-----------------|----------|
| Python | 3.11 | https://python.org |
| Node.js | 20 | https://nodejs.org |
| Ollama | latest | https://ollama.com/download |
| Cesium ion token | free tier | https://ion.cesium.com |

### One-Command Start

Open PowerShell and run:

```powershell
cd "D:\MCP Mods\worldbase"
.\start.ps1
```

This script will:
1. Check Python and Node.js availability.
2. Check if Ollama is running.
3. Create a Python venv in `backend/venv` (if missing).
4. Install Python dependencies from `requirements.txt`.
5. Initialize the SQLite database (`worldbase.db`) if missing.
6. Start the FastAPI backend in a new terminal window.
7. Run `npm install` in `frontend/` (if `node_modules` is missing).
8. Start the Vite dev server in a new terminal window.

### Manual Start (if preferred)

**Terminal 1 — Backend:**
```powershell
cd "D:\MCP Mods\worldbase\backend"
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Frontend:**
```powershell
cd "D:\MCP Mods\worldbase\frontend"
npm install
npm run dev
```

**Terminal 3 — Ollama (if not already running as a service):**
```powershell
ollama serve
```

### After Start

Open your browser:

| URL | What you get |
|-----|-------------|
| `http://localhost:5173` | WorldBase dashboard (Globe / Data / AI) |
| `http://localhost:8000/docs` | Auto-generated FastAPI Swagger docs |
| `http://localhost:8000/redoc` | Alternative ReDoc API docs |

### Pull a Local Model

```powershell
ollama pull llama3.2
ollama pull qwen2.5
ollama list
```

The AI chat tab defaults to `llama3.2`. Change the model string in `App.tsx` or make it user-selectable.

---

## Features

### 1. Globe View

A full CesiumJS 3D globe with:

- **Cesium World Terrain** — Real elevation data (requires free ion token).
- **Base Layer Picker** — Switch between Bing, OSM, and other imagery providers.
- **Geocoder** — Search for locations by name.
- **Scene Mode Picker** — 3D globe, 2D map, or Columbus view.
- **Entity Markers** — Test marker over Berlin (customizable to any coordinate).

**Planned additions:**
- Live aircraft as entity points (OpenSky → Cesium `SampledPositionProperty`).
- Satellite orbit visualization (TLE → SGP4 propagation → Cesium path).
- Vision modes: NVG (night vision), FLIR (thermal), CRT (scanlines), Anime (cel-shading).

### 2. Data Panel

Four sub-tabs for different data domains:

#### Aircraft (OpenSky Network)
- Live ADS-B positions of commercial and general aviation aircraft.
- Columns: ICAO24, Callsign, Country, Latitude, Longitude, Altitude, Velocity, Heading.
- Fetched directly from `opensky-network.org/api/states/all`.
- 30-row display with count badge.

#### Satellites (CelesTrak)
- Two-Line Element (TLE) sets for ~100 active satellites.
- Parsed fields: Name, NORAD ID, Inclination, Orbital Period.
- Fetched from `celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle`.

#### World Status
- Stub for aggregated world data: markets, crypto, geopolitical events, weather.
- Currently returns cached `world.json` or an empty placeholder.
- Designed for a future `world-sync` cron job to populate the cache.

#### Health
- Backend liveness probe (`/api/health`).
- Displays `OK` + ISO timestamp if the FastAPI server is responsive.

### 3. Local AI Chat

- Proxies to Ollama's `/api/chat` endpoint.
- No streaming yet (single-response mode).
- Message history stored in React state (lost on page refresh; persistence is a future enhancement).
- Graceful fallback if Ollama is not running.

### 4. HUD Aesthetic

Custom CSS inspired by military terminal interfaces:
- `#060a12` deep navy background.
- `#00e5a0` phosphor-green primary color.
- Monospace font stack (`Courier New`).
- Glow effects on active buttons and status indicators.
- No external UI framework — total visual control.

---

## API Reference

All endpoints are prefixed with `/api` and served by the FastAPI backend.

### `GET /api/health`

**Response:**
```json
{
  "status": "ok",
  "time": "2026-06-01T00:15:42+00:00"
}
```

### `GET /api/aircraft`

Fetches live aircraft positions from OpenSky Network.

**Response:**
```json
{
  "count": 8234,
  "timestamp": 1752528942,
  "states": [
    ["4b1902", "SWR123  ", "Switzerland", 1717481345, 1717481345, 8.55, 47.45, 10668, false, 245.3, 92.5, null, null, null, false, 0],
    ...
  ]
}
```

OpenSky state vector format (array indices):
| Index | Field |
|-------|-------|
| 0 | ICAO24 |
| 1 | Callsign |
| 2 | Origin country |
| 5 | Longitude |
| 6 | Latitude |
| 7 | Barometric altitude (m) |
| 9 | Velocity (m/s) |
| 10 | True track (degrees) |

### `GET /api/satellites`

Fetches active satellite TLEs from CelesTrak.

**Response:**
```json
{
  "count": 100,
  "satellites": [
    {
      "name": "ISS (ZARYA)",
      "tle1": "1 25544U 98067A   25152.51782519  .00017180  00000+0  30706-3 0  9991",
      "tle2": "2 25544  51.6378  63.0440 0006741  33.2676  78.5155 15.50995519372209"
    }
  ]
}
```

### `GET /api/world`

Returns cached world status or a placeholder.

**Response (empty):**
```json
{
  "status": "empty",
  "message": "Run world-sync to populate.",
  "currencies": {},
  "geo": {},
  "news": []
}
```

### `POST /api/chat`

Proxies chat requests to local Ollama.

**Request:**
```json
{
  "model": "llama3.2",
  "messages": [{"role": "user", "content": "What is the capital of France?"}]
}
```

**Response:** Ollama's native JSON response (mirrored).

---

### Extended Feeds (no API key)

Implemented in `backend/feeds_extra.py`. Every feed is fail-soft: on upstream error it
returns the last good cached value or an empty payload.

| Endpoint | Source | Notes |
|----------|--------|-------|
| `GET /api/spaceweather` | NOAA SWPC | Planetary K-index, storm scale, aurora/HF-radio impact flags, 24-sample history. |
| `GET /api/markets` | CoinGecko + Frankfurter | Crypto (BTC/ETH/XMR/SOL) in USD/EUR with 24h change + ECB forex. |
| `GET /api/military` | adsb.fi open data | Military/interesting aircraft worldwide, no rate wall. |
| `GET /api/weather?lat=&lon=` | Open-Meteo | Current conditions + 24h outlook for any coordinate. |
| `GET /api/geopolitics` | ReliefWeb (UN OCHA) | Active humanitarian disasters/crises worldwide. |

### Node Sync — "One Organism" (PC brain ↔ Pi edge)

Implemented in `backend/node_sync.py`. SQLite tables: `node_state`, `briefings`.

| Endpoint | Direction | Purpose |
|----------|-----------|---------|
| `POST /api/node/ingest` | Pi → PC | Upsert a node's live state: `{node_id, name, lat, lon, sensors, mesh[], pihole, health}`. |
| `GET /api/nodes` | read | Live node registry (online if updated < 300 s ago) for globe entities + UI. |
| `POST /api/briefing/generate` | PC | Fuse feeds (`_gather_snapshot`) → ranked alerts (`_compile_alerts`) → local LLM writes a ≤150-word situation briefing → store. |
| `GET /api/briefing` | read | Latest stored briefing + alerts. |
| `GET /api/node/pull` | PC → Pi | Single payload (briefing + fresh critical alerts) the off-grid Pi displays even without its own upstream internet. |

**Data flow of the organism:** the Pi POSTs edge telemetry → WorldBase renders it as a live
entity and fuses it with global feeds → the local 14B LLM writes a narrative briefing → the Pi
pulls that briefing back. The strong PC *thinks*; the small Pi *senses and shows*.

### OSINT integration

The frontend (`frontend/src/App.tsx`) exposes **OSINT** as a peer nav item next to GLOBE / DATA /
AI. It embeds the OpenOSINT console (running on the Pi) via an `<iframe>`; the URL is configurable
through `VITE_OSINT_URL` (default `http://localhost:15000`, the SSH tunnel to the Pi).

---

## Data Sources

| Source | URL | Data | Rate Limit |
|--------|-----|------|-----------|
| **OpenSky Network** | `opensky-network.org/api/states/all` | Live ADS-B aircraft positions | Anonymous: ~10s refresh |
| **CelesTrak** | `celestrak.org/NORAD/elements/gp.php` | Satellite TLE orbital data | No limit (public domain) |
| **Cesium ion** | `api.cesium.com` | World terrain, imagery | Free tier: generous |
| **Ollama** | `localhost:11434` | Local LLM inference | Unlimited (local) |

All external APIs are free and do not require paid keys for basic usage. Cesium ion requires a free account token for world terrain.

---

## Expansion Roadmap

### Phase 1 — Core Stability

- [ ] **Aircraft on Globe**: Render OpenSky positions as Cesium `PointPrimitive` or `Entity` points, updated every 10 seconds.
- [ ] **Satellite Orbits**: Parse TLE → SGP4 (via `satellite.js` or pure Python) → Cesium `SampledPositionProperty` with 1-minute resolution paths.
- [ ] **Vision Modes**: Canvas2D post-processing shaders (NVG green phosphor, FLIR thermal palette, CRT scanlines, Anime cel-shading).
- [ ] **Persistent Chat**: Store chat history in SQLite or `localStorage`.

### Phase 2 — Data Richness

- [ ] **World Sync Service**: Python cron script that fetches:
  - Crypto prices (CoinGecko free API)
  - Forex / macro indicators (FRED, ECB)
  - Weather alerts (Open-Meteo)
  - Geopolitical news (RSS aggregators)
- [ ] **Feed Cache TTL**: Add `expires_at` to `feed_cache` table; stale entries auto-refresh.
- [ ] **Data Export**: JSON/CSV download buttons for aircraft and satellite tables.

### Phase 3 — Intelligence Layer

- [ ] **RAG Pipeline**: Ollama chat with retrieval-augmented generation over local documents (PDFs, notes, Wikipedia dumps).
- [ ] **Anomaly Detection**: Flag aircraft with unusual patterns (no callsign, military transponder codes, erratic altitude changes).
- [ ] **Semantic Search**: "Show me all cargo flights over Europe above 30,000 ft" — parsed by LLM, translated to SQL/OpenSky query.
- [ ] **Alerting**: WebSocket push for configurable triggers (e.g., "alert when ISS is overhead").

### Phase 4 — Sousveillance Aesthetics

- [ ] **CCTV Integration**: Public traffic camera feeds draped onto 3D buildings (Bilawal Sidhu's signature feature).
- [ ] **Custom Overlays**: User-uploaded GeoJSON, KML, or shapefiles.
- [ ] **Time Slider**: Replay historical aircraft or satellite positions from SQLite cache.
- [ ] **Screenshot/Share**: Export globe view as PNG with HUD overlay.

### Phase 5 — Desktop Packaging

- [ ] **Electron or Tauri Wrapper**: Standalone `.exe` instead of browser + two terminals.
- [ ] **System Tray Icon**: Minimize to tray, background data sync.
- [ ] **Auto-Start**: Launch backend + frontend on Windows boot.

---

## Future Vision & Agent Handoff

> This section is written for the **next AI agent** (or human) who picks up WorldBase. It
> describes the current reality, the mental model, the exact places to touch, and a deliberately
> ambitious set of expansion ideas. Read it before writing code. Be bold, but keep the
> fail-soft, no-key, local-first philosophy intact.

### Current state (as of June 2026)

What is real and tested today:

- **Backend** (`backend/main.py` + `backend/feeds_extra.py` + `backend/node_sync.py`): all feeds
  in the API reference above are live and fail-soft. SQLite at `backend/worldbase.db`.
- **Node sync**: `POST /api/node/ingest` accepts Pi telemetry from the live push daemon;
  `GET /api/nodes` returns it (Pi currently online, 49°C, 7 services reporting);
  `POST /api/briefing/generate` fuses feeds and calls the local LLM; `GET /api/node/pull` is the
  Pi's offline payload. Verified end-to-end with a **live** Pi node.
- **Frontend** (`frontend/src/App.tsx`): GLOBE / DATA / AI / **OSINT** nav. The OSINT tab embeds
  the OpenOSINT console (`VITE_OSINT_URL`). The Cesium globe lives in `components/Globe.tsx`.
- **The two machines**: a strong **on-grid PC** runs WorldBase + Ollama (14B). A small
  **off-grid Raspberry Pi** runs the OpenOSINT stack, Pi-hole, Kiwix, Meshtastic/LoRa, sensors.
  They are reachable to each other over LAN / SSH tunnel (`localhost:15000` → Pi `:5000`).

### Mental model: one organism

```
        PC (brain, on-grid)                         Pi (senses, off-grid)
   ┌───────────────────────────┐             ┌──────────────────────────────┐
   │ WorldBase globe + feeds    │  ingest →   │ sensors, mesh, Pi-hole, GPS   │
   │ Ollama 14B (fusion/LLM)    │ ← pull      │ OpenOSINT tools, Kiwix, LoRa  │
   │ situation briefing writer  │             │ portal (offline display)      │
   └───────────────────────────┘             └──────────────────────────────┘
```

The PC has compute and the wide view; the Pi has presence in the physical world and survives
without grid power or internet. The sync layer is the nervous system between them. **Every new
feature should ask: does this strengthen the brain, the senses, or the nerve between them?**

### What is NOT done yet (honest gaps)

- The new feeds (`/api/military`, `/api/spaceweather`, `/api/markets`, `/api/geopolitics`,
  `/api/nodes`) are **not yet rendered on the globe** — only the backend exists. Frontend wiring
  is the obvious next step (`components/Globe.tsx` + new DATA sub-tabs).
- ~~There is no real Pi-push script yet.~~ **DONE**: `worldbase_push.py` + `worldbase_pull.py`
  are installed as systemd services on the Pi. Push every 45 s; pull every 5 min.
- **Briefing generation is manual** (`POST /api/briefing/generate`). It should run on a schedule
  (APScheduler or a simple asyncio loop) every 10–15 min so the Pi always has fresh data.
- The chat proxy in `main.py` is still **non-streaming** (`stream: False`). The OpenOSINT chat we
  fixed *does* stream; WorldBase's own AI chat does not yet.
- No auth on `/api/node/ingest` — fine on a trusted LAN, but add a shared token before exposing.

### Expansion ideas (be creative — pick a thread and pull)

**A. Make the globe a living situation display.**
1. Render `/api/nodes` as pulsing entities at the Pi's real coordinates, with the mesh nodes as
   linked points and SNR-weighted connection lines (a literal picture of the LoRa network).
2. Plot `/api/military` aircraft with distinct icons and squawk-based coloring (7500/7600/7700
   emergency codes glow red). Draw `/api/geopolitics` disasters and `/api/spaceweather` aurora
   ovals (NOAA OVATION) as overlays.
3. A **"briefing mode"**: clicking the situation briefing highlights every alert's coordinate on
   the globe in sequence — a guided tour of the world's current state.

**B. Turn feeds into intelligence, not just dots.**
4. **Aircraft anomaly detection**: flag no-callsign, military transponders, circling/loitering
   patterns, sudden altitude changes. Feed candidates to the LLM for a one-line assessment.
5. **Cross-feed correlation**: earthquake near a nuclear site + ReliefWeb disaster + aircraft
   surge in the region → a synthesized "developing situation" card.
6. **RAG over the Pi's Kiwix/Wikipedia dump**: the briefing LLM cites offline encyclopedic
   context (e.g., what is at the quake's epicenter) without touching the internet.

**C. Deepen the PC↔Pi organism.**
7. **Bidirectional, signed sync**: HMAC-token on ingest; the Pi mirrors a compressed feed
   snapshot so its portal shows the globe's data even when its own uplink is down.
8. **Mesh-relayed briefings**: shrink the situation briefing to <230 bytes and TX it over
   Meshtastic/LoRa so other field nodes receive world awareness with no internet at all.
9. **Sensor-driven alerts**: if the Pi's battery voltage drops or a Geiger/AQ sensor spikes, the
   PC escalates it into the briefing and (optionally) into a push notification.
10. **Failover roles**: if the PC is offline, the Pi runs a tiny local model (e.g., a 1–3B Ollama
    model already present) to keep producing a degraded-but-useful briefing.

**D. Make OSINT a first-class, fused capability (not just an iframe).**
11. Give WorldBase's *own* AI chat the OpenOSINT tools (function-calling) so one chat can both
    reason and run `search_ip` / `search_username` / `sherlock`. Proxy tools through the backend.
12. **OSINT → globe**: geolocate IP/WHOIS/EXIF results and drop them as markers with a TARGET
    LOCK card, unifying the OSINT and spatial views.

**E. New no-key data layers worth adding** (keep the fail-soft pattern in `feeds_extra.py`):
13. Maritime AIS (free tiers / aishub), submarine cable map (TeleGeography static), internet
    outages (IODA), air quality (OpenAQ), radiation (Safecast), lightning, NOAA tsunami/cyclone
    GIS, GDELT geopolitical news volume, APRS amateur-radio positions, aurora oval, FIRMS fires.

**F. Operability (make it boringly reliable).**
14. ~~systemd units for Pi-push/pull daemons on the Pi~~ **DONE**.
    systemd units for backend + frontend on the PC; Ollama `keep_alive` so the 14B model
    never cold-loads mid-query.
15. Persist feed cache to SQLite with TTL (`feed_cache` table already exists) so a restart keeps
    the last good world state. Add a `/api/health` that reports each feed's freshness.
16. Package the PC side as a Tauri/Electron app with a tray icon and auto-start.

### Conventions to preserve

- **No API keys** for data feeds; if a source needs one, make it optional and degrade gracefully.
- **Fail-soft everywhere**: never let one dead upstream break the globe. Return stale or empty.
- **Local-first**: nothing should *require* the cloud. The Pi must stay useful fully offline.
- **HUD aesthetic**: green-on-black, monospace, information density over decoration.
- Add new feeds as small `APIRouter` modules and `include_router` them in `main.py`.

---

## Credits & Inspiration

- **Bilawal Sidhu** — For the [WorldView](https://www.spatialintelligence.ai/p/i-built-a-spy-satellite-simulator) demo and the "spatial intelligence" thesis. The thesis: "we're building AI that understands the physical world the way it understands text."
- **offgrid-raspi** — For the idempotent-setup philosophy, the honest documentation style, and the workshop-node mindset.
- **CesiumJS** — The open-source WebGL globe engine that powers everything from NASA to Google Earth.
- **OpenSky Network** — The crowdsourced ADS-B aggregation project that makes live aircraft tracking accessible to anyone.
- **CelesTrak** — Dr. T.S. Kelso's public-domain orbital data service, running since the 1980s.

---

## License

MIT — See [LICENSE](LICENSE).

Fork for the code, the docs, or both.
