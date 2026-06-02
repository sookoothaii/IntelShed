# LLM Handoff — WorldBase
> Last updated: 2026-06-02 | Session: Phase 1+2+3 + FULL SITUATION button

## Project Overview
WorldBase is a spatial intelligence dashboard: React + CesiumJS globe on the frontend, FastAPI backend with 20+ data feeds. No API keys required for any source. All feeds are fail-soft (serve stale cache or empty payload on upstream error).

**Philosophy**: Positive intelligence — help make better decisions, not attack.

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Frontend | React 18 + TypeScript + Vite |
| Globe | CesiumJS (Viewer, CustomDataSource, Entity) |
| Styling | Vanilla CSS (`src/styles/hud.css`) — no Tailwind |
| Backend | FastAPI + uvicorn |
| HTTP Client | httpx (async) |
| Cache | In-memory + SQLite `feed_cache` table |
| DB | SQLite (`worldbase.db`) |
| LLM | Ollama (qwen2.5:14b default) via `/api/chat` |

---

## Project Structure

```
worldbase/
├── backend/
│   ├── main.py              # FastAPI app, /api/chat (SSE streaming), /api/health
│   ├── feeds_extra.py       # 13 feed endpoints + anomaly/correlation detection
│   ├── node_sync.py         # Pi↔PC sync, sensor alerts, HMAC auth, mesh briefing
│   ├── osint_tools.py       # NEW: IP/Domain/Username/Email/Reverse-geocode
│   ├── requirements.txt     # dnspython added for DNS lookups
│   └── worldbase.db         # SQLite (node_state, briefings, sensor_alerts, feed_cache)
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # Main app: DATA panel (12 tabs), ChatPanel, FullAnalysisOverlay
│   │   ├── styles/hud.css   # ALL styles including new analysis overlay
│   │   └── components/
│   │       └── Globe.tsx    # CesiumJS: 9 DataSources, entity rendering, Ask AI
│   └── dist/                # Built frontend (served by backend)
└── offgrid-raspi/           # Pi scripts (not in this workspace)
```

---

## API Endpoints (All under `/api`)

### Core Feeds
| Endpoint | What | Cache TTL | Source |
|----------|------|-----------|--------|
| `/aircraft` | Live aircraft (OpenSky) | 15s | OpenSky |
| `/satellites` | ISS + others (CelesTrak) | 60s | CelesTrak |
| `/earthquakes` | USGS seismic | 60s | USGS |
| `/events` | Natural events (NASA EONET) | 300s | EONET |
| `/iss` | ISS position | 5s | WhereIsISS |

### Extended Feeds (`feeds_extra.py`)
| Endpoint | What | Cache TTL | Source |
|----------|------|-----------|--------|
| `/spaceweather` | Kp index, scale, aurora, HF impact | 300s | NOAA SWPC |
| `/geopolitics` | ReliefWeb crises | 300s | ReliefWeb |
| `/markets` | Crypto (CoinGecko) + Forex | 60s | CoinGecko + Frankfurter |
| `/military` | Military aircraft (adsb.fi) | 20s | adsb.fi |
| `/nodes` | Pi node telemetry | DB | Local |
| `/airquality` | PM2.5/PM10 (6 cities) | 3600s | Open-Meteo |
| `/gdacs` | Humanitarian alerts | 900s | GDACS RSS |

### Intelligence Engine
| Endpoint | What |
|----------|------|
| `/anomalies` | Aircraft anomaly detection (6 patterns) |
| `/correlations` | Cross-feed correlation (nuclear-quake, military-surge, seismic-cluster) |
| `/briefing` | Latest LLM-generated situation briefing |
| `/briefing/generate` | Force new briefing generation |

### Pi↔PC Sync (`node_sync.py`)
| Endpoint | What |
|----------|------|
| `/node/ingest` | POST Pi telemetry. Optional HMAC via `X-Node-Token` header |
| `/nodes` | GET all nodes |
| `/node/pull` | GET briefing + alerts for Pi. `?mesh=1` for <230 byte payload |
| `/node/pull/mesh` | Dedicated LoRa endpoint |
| `/alerts` | GET sensor alerts (threshold-based) |

### OSINT (`osint_tools.py`) — NEW
| Endpoint | What | Source |
|----------|------|--------|
| `/osint/ip/{ip}` | IP geolocation | ip-api.com |
| `/osint/domain/{domain}` | DNS A/MX records | Local DNS resolver |
| `/osint/username/{username}` | GitHub/Reddit presence check | Platform APIs |
| `/osint/email/{email}` | Disposable domain + MX check | Local |
| `/osint/reverse-geocode` | Lat/lon → location name | BigDataCloud |

### System
| Endpoint | What |
|----------|------|
| `/health` | Status + per-feed freshness timestamps |
| `/chat` | SSE streaming LLM chat with web search |

---

## Database Schema

```sql
CREATE TABLE node_state (node_id TEXT PRIMARY KEY, name, lat, lon, updated_at, payload TEXT);
CREATE TABLE briefings (id INTEGER PRIMARY KEY, created_at, text, sources TEXT);
CREATE TABLE sensor_alerts (id INTEGER PRIMARY KEY, node_id, sensor, severity, value, threshold, message, created_at);
CREATE TABLE feed_cache (key TEXT PRIMARY KEY, value TEXT, cached_at TEXT);
```

---

## Key Frontend Components

### `App.tsx`
- **DATA panel**: 12 tabs — aircraft, satellites, seismic, events, iss, spaceweather, geopolitics, markets, nodes, military, situations, health
- **ChatPanel**: Streaming SSE, model selector, web search toggle, Ask AI injection
- **FullAnalysisOverlay**: The big red "FULL SITUATION" button. Fetches ALL 13 feeds in parallel, 2-column layout, auto-refresh 30s toggle.

### `Globe.tsx`
- 9 CustomDataSources: aircraft, satellites, seismic, events, iss, military, spaceweather, geopolitics, nodes
- Emergency squawk pulsating ring (7500/7600/7700 = red)
- Kp-based aurora oval rings
- Ask AI button in target panel
- HUD stats overlay

---

## Data Structures (Critical for Frontend)

### CoinGecko Crypto Response
```json
{"bitcoin": {"usd": 71131, "usd_24h_change": -3.37}}
```
Frontend uses `v.usd ?? v.price` and `v.usd_24h_change ?? v.change_24h`.

### Node Health Object (from `/api/nodes`)
```json
{
  "health": {
    "cpu_temp_c": 43.8,
    "load_1m": 0.52,
    "ram_pct": 69.0,
    "disk_pct": 91,
    "services": {...}
  },
  "sensors": {}  // often empty from Pi
}
```
**IMPORTANT**: CPU temp is at `health.cpu_temp_c`, NOT `sensors.temp_c` or `sensors.cpu_temp`.

### Military Aircraft (`/api/military`)
```json
{
  "aircraft": [
    {"hex": "ae63e2", "flight": null, "type": "T38", "lat": ..., "lon": ..., "alt": 400, "speed": 1, "squawk": null}
  ]
}
```
`alt` and `speed` can be strings — always `Number(val)` before `.toFixed()`.

### Spaceweather (`/api/spaceweather`)
```json
{
  "kp_index": 1.33,
  "scale": "quiet",
  "aurora_visible_midlat": false,
  "hf_radio_impact": false,
  "history": [{"time": "...", "kp": 1.33}]
}
```
**NO** `bt`, `speed`, `density`, `aurora_probability` fields exist.

---

## Known Bugs / Gotchas

1. **Military alt/speed strings**: `a.alt` from adsb.fi can be a string. Always `Number(a.alt).toFixed(0)` with `!isNaN()` guard.
2. **Node sensors empty**: `n.sensors` is `{}`. Read from `n.health.cpu_temp_c`, `n.health.ram_pct`, etc.
3. **CoinGecko fields**: Use `v.usd` and `v.usd_24h_change`, not `v.price`/`v.change_24h`.
4. **Build**: `npm run build` in `frontend/` → outputs to `dist/`. Backend serves `dist/` at `/`.
5. **Port confusion**: Frontend dev server runs on 5173. Backend API on 8000. User sometimes tries random ports like 56649.

---

## Build & Deploy

```bash
# Backend
cd backend
.\venv\Scripts\python.exe main.py   # or uvicorn main:app --reload

# Frontend (dev)
cd frontend
npm run dev                          # http://localhost:5173

# Frontend (production build)
npm run build                      # outputs dist/
```

---

## Environment Variables

| Var | Default | Purpose |
|-----|---------|---------|
| `OLLAMA_HOST` | localhost:11434 | Ollama host(s), comma-separated |
| `OLLAMA_MODEL` | qwen2.5:14b | Default LLM model |
| `NODE_INGEST_TOKEN` | "" (empty) | HMAC secret for `/node/ingest` |
| `WORLDBASE_BRIEFING_INTERVAL` | 600 | Autopilot briefing interval (seconds) |
| `WORLDBASE_SELF` | http://localhost:8000 | Self-referential URL for briefing |

---

## What Was Built in This Session

### Phase 1: Globe + Intelligence (12 features)
- 5 new DATA tabs (spaceweather, geopolitics, markets, nodes, military)
- 3 new globe layers (military aircraft, spaceweather Kp-ring, geopolitics pins)
- Aircraft anomaly detection (`/api/anomalies`)
- Cross-feed correlation engine (`/api/correlations`)
- Situations tab in DATA panel
- Globe click → Ask AI (entity context to chat)
- Feed cache persistence to SQLite

### Phase 2: Pi↔PC Organismus (3 features)
- Sensor alert thresholds (temp, battery, CO2, radiation, PM2.5)
- Optional HMAC auth on `/api/node/ingest`
- Mesh briefing compression (<230 bytes for LoRa)

### Phase 3: OSINT + New Feeds (3 features)
- OSINT tools (IP, domain, username, email, reverse-geocode)
- Air quality feed (Open-Meteo)
- GDACS humanitarian alerts
- `/api/health` with per-feed freshness

### The Button
- **FULL SITUATION** button in HUD header
- 2-column overlay, 13 feeds parallel fetch
- Auto-refresh toggle (30s)
- All data null-safe with proper fallbacks

---

## Next Steps (Ideas)

1. **OSINT → Globe**: Render OSINT results as globe markers with geolocation
2. **Air Quality + GDACS Tabs**: Add to DATA panel (APIs exist, UI missing)
3. **Ollama keep_alive**: Send `{"keep_alive": "5m"}` in chat requests to prevent cold-load
4. **Frontend Tests**: Add Playwright smoke tests
5. **Offline Mode**: Cache all feeds in IndexedDB for offline globe viewing
6. **Alert Notifications**: Browser push notifications for critical alerts
7. **Time Slider**: Scrub through historical feed data on the globe

---

## Quick Reference: If Something Breaks

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `toFixed is not a function` | `a.alt` is string | `Number(a.alt).toFixed(0)` with `isNaN` guard |
| Node shows `CPU: —` | Wrong field path | Use `n.health.cpu_temp_c` |
| Crypto shows `$—` | Wrong field names | Use `v.usd` / `v.usd_24h_change` |
| Spaceweather `—` | Fields don't exist | Use `aurora_visible_midlat` / `hf_radio_impact` |
| Website not reachable | Backend not running | Start `python main.py` on port 8000 |

---

## File Paths (Absolute)

- Main app: `D:\MCP Mods\worldbase\frontend\src\App.tsx`
- Globe: `D:\MCP Mods\worldbase\frontend\src\components\Globe.tsx`
- Styles: `D:\MCP Mods\worldbase\frontend\src\styles\hud.css`
- Backend feeds: `D:\MCP Mods\worldbase\backend\feeds_extra.py`
- Node sync: `D:\MCP Mods\worldbase\backend\node_sync.py`
- OSINT: `D:\MCP Mods\worldbase\backend\osint_tools.py`
- Main backend: `D:\MCP Mods\worldbase\backend\main.py`
- DB: `D:\MCP Mods\worldbase\backend\worldbase.db`
