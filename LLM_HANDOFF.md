# LLM Handoff — WorldBase

> **Operator + agent reference.** Agent quick start: [`AGENTS.md`](AGENTS.md) · User docs: [`README.md`](README.md) · [`docs/FEEDS.md`](docs/FEEDS.md) · [`docs/API-KEYS.md`](docs/API-KEYS.md) · [`docs/SETUP.md`](docs/SETUP.md)  
> Last updated: 2026-06-15 (late evening) | Stack: qwen3:8b, main, Pi sync live, SD ~64%, smoke 23/23

## Project Overview

WorldBase is a spatial intelligence dashboard: React + CesiumJS globe, FastAPI backend with 30+ feeds. **Fail-soft** — upstream errors → stale cache or `{ count: 0, error }`, not HTTP 500.

**Philosophy**: Positive intelligence — help make better decisions, not attack.

**Inspiration**: Bilawal Sidhu *WorldView*, [K-AI-STACK/WorldView](https://github.com/K-AI-STACK/WorldView), [kevtoe/worldview](https://github.com/kevtoe/worldview), [petieclark/worldview](https://github.com/petieclark/worldview), offgrid-raspi.

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
| LLM | Ollama (**qwen3:8b** default) + **nomic-embed-text** RAG via `/api/chat` |

---

## Project Structure

```
worldbase/
├── backend/
│   ├── main.py              # FastAPI app, /api/chat (SSE streaming), /api/health, /api/health/ping
│   ├── feeds_extra.py       # Extended feeds (async SQLite via asyncio.to_thread + WAL)
│   ├── feed_registry.py     # Shared feed_cache writes for /api/health provenance
│   ├── globe_snapshot.py    # GET /api/globe/snapshot — bundled parallel feed fetch (15s cache)
│   ├── firewall_bridge.py   # Optional HAK_GAL LLM firewall on :8001
│   ├── node_sync.py         # Pi↔PC sync, sensor alerts, HMAC auth, mesh briefing
│   ├── osint_tools.py       # IP/Domain/Username/Email/Reverse-geocode
│   ├── rag_memory.py        # Ollama nomic-embed + SQLite cosine RAG (via sqlite-vec)
│   └── worldbase.db         # SQLite (node_state, briefings, sensor_alerts, feed_cache, rag_chunks)
├── frontend/
│   ├── src/
│   │   ├── App.tsx          # Views: Globe, MAP, DATA, AI, FIREWALL, OSINT; split grid layout
│   │   ├── hooks/layers/    # 21 use*Layer hooks + GlobeLayerManager + layerUtils.ts
│   │   ├── styles/hud.css   # HUD, telemetry, split grid, map mode bar
│   │   ├── lib/mapView.ts   # Shared basemap + 2D/3D mode state
│   │   └── components/
│   │       ├── Globe.tsx    # Cesium 3D, viewer state, basemap, vision modes
│   │       ├── MapPanel.tsx # MapLibre 2D PMTiles (persistent instance)
│   │       └── MapModeBar.tsx  # KARTE/SATELLIT/HYBRID/GELÄNDE + 2D/3D toggle
│   └── public/favicon.svg
├── data/pmtiles/            # Offline archives (gitignored blobs; see download script)
└── offgrid-raspi/           # Pi scripts (submodule)
```

---

## API Endpoints (All under `/api`)

### Core Feeds
| Endpoint | What | Cache TTL | Source |
|----------|------|-----------|--------|
| `/aircraft` | Live aircraft (OpenSky → adsb.fi / adsb.lol) | 45s | adsb.fi + adsb.lol |
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
| `/gdacs` | Humanitarian alerts (red/orange) | 900s | gdacs.org JSON API |
| `/pegel` | German river gauges (Pegelonline) | 900s | pegelonline.wsv.de |

### Intelligence Engine
| Endpoint | What |
|----------|------|
| `/anomalies` | Aircraft anomaly detection (6 patterns) |
| `/anomalies/river` | Online River HalfSpaceTrees / z-score per feed |
| `/correlations` | Cross-feed correlation (nuclear-quake, military-surge, seismic-cluster) |
| `/briefing` | Latest LLM-generated situation briefing |
| `/briefing/generate` | Force new briefing generation |
| `/situations` | Unified situation board (parallel fetch) |
| `/fusion/heatmap` | **Killer-Feature**: 8-feed signal aggregation onto lat/lon grid |
| `/memory/{search,stats,index/pulse}` | Fast vector RAG over briefings + GDELT + hazards + situations + volcanoes + STAC + sanctions (`sqlite-vec`) |

### Imagery & Maps
| Endpoint | What | Source |
|----------|------|--------|
| `/stac/collections` | STAC catalog + region presets | static |
| `/stac/search` | Sentinel-2 / Landsat search (bbox + date + cloud) | Element84 EarthSearch (free) |
| `/stac/item/{id}` | STAC item detail | Element84 |
| `/stac/thumbnail?id=...` | CORS-safe thumbnail proxy | Element84 |
| `/pmtiles/{status,file/{name}}` | Local Protomaps PMTiles serve | local |
| `/gibs/{layers,latest}` | NASA GIBS WMTS catalog + token | NASA |

### Maritime intelligence
| Endpoint | What |
|----------|------|
| `/maritime` | Live AIS vessel positions (port regions) |
| `/maritime/ports` | Tracked port bbox list |
| `/sanctions/status` | Yente/CSV freshness + index size |
| `/sanctions/refresh` | Force re-download of OpenSanctions default CSV (if local) |
| `/sanctions/search?q=` | Yente fallback to local fuzzy match (Person/Company/Vessel) |
| `/sanctions/screen/vessels` | AIS ↔ OpenSanctions cross-match (Yente-accelerated) |

### Aircraft trails
| Endpoint | What |
|----------|------|
| `/aircraft/trails?icao24=...&minutes=30` | Persisted 30 min trail per ICAO24 |
| `/aircraft/trails/stats` | Row count, distinct aircraft, oldest/newest |
| `/aircraft/trails/snapshot` | Manual trigger (rate-limited) |

### Pegel sparklines
| Endpoint | What |
|----------|------|
| `/pegel/{uuid}/history?hours=24` | Time series for SVG sparkline rendering |

### Pi↔PC Sync (`node_sync.py`)
| Endpoint | What |
|----------|------|
| `/node/ingest` | POST Pi telemetry. **HMAC** body → `X-Node-Token` when `NODE_INGEST_TOKEN` set |
| `/nodes` | GET all nodes (public read) |
| `/node/pull` | GET briefing + alerts. Requires `X-Node-Token` when token set |
| `/node/pull/mesh` | LoRa payload <230 B; same auth as pull |
| `/node/{id}/command` | POST queue command (PC). Requires `X-Admin-Token` |
| `/node/{id}/commands` | GET pending commands (Pi). Requires `X-Node-Token` |
| `/alerts` | GET sensor alerts (threshold-based) |

**Pi scripts:** `offgrid-raspi/scripts/worldbase_push.py`, `worldbase_pull.py` — deploy + token: `scripts/setup-node-security.ps1`, `scripts/sync-pi.ps1`, `offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`.

**Pi state files (push reads):** `esp32_state.json` (DHT USB), `mesh_state.json`, `gps_location.json` — **not** legacy `sensor_data.json` / `mesh_nodes.json` / `gps.json`. Portal briefing: `/var/lib/offgrid/briefing_latest.json` (PC first).

### Flowsint & Yente (local Docker)
| Item | Detail |
|------|--------|
| Upstream | https://github.com/reconurge/flowsint, https://github.com/opensanctions/yente |
| Setup | `scripts/setup-flowsint.ps1`, `scripts/setup-yente.ps1` |
| UI/API | Flowsint UI: http://localhost:5173, Yente API: http://localhost:8003 |
| Health | `GET /api/flowsint/health`, `GET /api/sanctions/status` |
| Setup | `scripts/setup-flowsint.ps1`, `scripts/start-flowsint.ps1` |

### OSINT (`osint_tools.py`)
| Endpoint | What | Source |
|----------|------|--------|
| `/osint/ip/{ip}` | IP geolocation | ip-api.com |
| `/osint/domain/{domain}` | DNS A/MX records | Local DNS resolver |
| `/osint/username/{username}` | GitHub/Reddit presence check | Platform APIs |
| `/osint/email/{email}` | Disposable domain + MX check | Local |
| `/osint/reverse-geocode` | Lat/lon → location name | BigDataCloud |

### Firewall (`firewall_bridge.py`)
| Endpoint | What |
|----------|------|
| `/firewall/status` | HAK_GAL reachability + `enabled` (requires `FIREWALL_HOST` in `.env`) |
| `/firewall/test` | POST `{"query":"..."}` — direct firewall scan |
| `/chat` + `firewall: true` | User message scanned before Ollama; blocks on `risk_score > 0.7` |

### System
| Endpoint | What |
|----------|------|
| `/health` | Status + per-feed freshness, count, source, error (SQLite `feed_cache` + `feed_registry.py`) |
| `/health/ping` | Fast liveness probe for HUD status bar (no feed parsing) |
| `/globe/snapshot?layers=...` | Parallel bundle of slow globe feeds (30s cache, refresh lock) |
| `/chat` | SSE streaming LLM chat with web search + optional firewall scan |

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
- Cesium viewer init, basemap (`applyGlobeMapMode`), vision shaders, timeline, HUD chrome
- **Layer rendering** via `hooks/layers/GlobeLayerManager.tsx` (21 `use*Layer` hooks)
- `layerUtils.ts`: safe `attachDataSource` / `detachDataSource` (split teardown)
- `viewer` React state — hooks re-run after async Cesium init
- Pauses render loop when hidden; `resolutionScale` 1.0 in split, 1.5 full-screen
- **LIVE TELEMETRY** panel: grouped feeds, health dots, presets
- Emergency squawk ring (7500/7600/7700); time slider (quakes + events)

### Split view (`App.tsx` + `hud.css`) — current (2026-06-15)
- **◫ SPLIT** — CSS grid (`hud-main--split`): globe col 1, map col 2
- **Globe + MapPanel always mounted** — toggle = CSS only (no MapLibre remount)
- **No empty `view-fade` on GLOBE** — overlay blocked scroll/wheel (fixed)
- Camera sync with **500 ms suppress** after programmatic jumps
- Resize at 0 / 120 / 350 ms on layout change; split hides heavy globe chrome

---

## Data Structures (Critical for Frontend)

### CoinGecko Crypto Response
```json
{"bitcoin": {"usd": 71131, "usd_24h_change": -3.37}}
```
Frontend uses `v.usd ?? v.price` and `v.usd_24h_change ?? v.change_24h`.

### Node object (from `/api/nodes`) — 2026-06-15 live
```json
{
  "node_id": "offgrid-pi",
  "online": true,
  "lat": 9.55,
  "lon": 100.05,
  "sensors": {"temp_c": 27.8, "humidity_pct": 38, "node_id": "esp32_dht_usb"},
  "mesh": [{"id": "d9b0", "lat": 9.55, "lon": 100.05, "sats": 22}],
  "health": {
    "cpu_temp_c": 48.7,
    "ram_pct": 72.6,
    "disk_pct": 72,
    "services": {"offgrid-mesh": "active", "offgrid-sensor-ingest": "active"}
  }
}
```
**IMPORTANT:** Room DHT is `sensors.temp_c` / `sensors.humidity_pct`. Pi CPU is `health.cpu_temp_c` — not `sensors.cpu_temp`.

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
5. **Port confusion (2026-06-03 audit)**: Canonical dev ports are **Frontend 5176**, **Backend 8002** (`start.ps1`, `vite.config.ts`). Pi `worldbase_push`/`pull` must use **8002** (`fix-worldbase-port-8002.sh`). PC port **8000** is another local service, not WorldBase.
6. **Pi `/mnt/usb`**: Name suggests USB stick; on this Pi it was **Borg on root** (`/dev/sda2`). Removed 2026-06-03 (~5.4 GB). See `offgrid-raspi/docs/pi-storage-layout.md`. Sneakernet: `mkdir -p /mnt/usb` when needed.
7. **Stuck `borg`**: `pgrep -a borg` then `kill` before `borg break-lock`; interactive `borg list` without `BORG_PASSPHRASE` can hold the lock for hours.

---

## Build & Deploy

```bash
# Backend
cd backend
.\venv\Scripts\python.exe main.py   # or uvicorn main:app --reload

# Frontend (dev)
cd frontend
npm run dev                          # http://localhost:5176 (Vite proxy → :8002)

# Frontend (production build)
npm run build                      # outputs dist/

# Automated smoke test (backend APIs, Ollama chat, Vite proxy, build)
.\scripts\smoke-test.ps1           # expect FAIL 0 after .\start.ps1
```

### Docker (optional — Pi HTTPS sync)

```powershell
.\scripts\start-docker.ps1   # Caddy :443 TLS + backend on 127.0.0.1:8002
```

Stack: `docker-compose.yml` — `web` (Caddy SPA + `/api` proxy), `backend` (FastAPI, SQLite volume). Pi synct über HTTPS mit gleichem `NODE_INGEST_TOKEN`. Secure-by-default: `WORLDBASE_REQUIRE_NODE_TOKEN=1`.

---

## Environment Variables

| Var | Default | Purpose |
|-----|---------|---------|
| `OLLAMA_HOST` | **127.0.0.1:11434** | Ollama host(s), comma-separated. **Windows:** `127.0.0.1` zuverlässiger als `localhost` (IPv6). Backend probiert beide automatisch. |
| `OLLAMA_MODEL` | qwen3:8b | Default chat model (`/api/models` filtert Embed-Modelle raus) |
| `OLLAMA_EMBED_MODEL` | nomic-embed-text | RAG embeddings only — nicht im Chat-Dropdown |
| `OLLAMA_KEEP_ALIVE` | `1m` | `0` = Modell sofort aus VRAM; `5m` war früher Default (zu aggressiv mit Globe) |
| `WORLDBASE_BRIEFING_AUTOPILOT` | `1` | `0` = kein Hintergrund-Briefing (spart VRAM) |
| `WORLDBASE_RAG_AUTOPILOT` | `1` | `0` = kein Hintergrund-RAG-Embed |
| `WORLDBASE_OPERATOR_REGION` | `thailand` | Home region for 24h security protocol (STAC bbox presets) |
| `WORLDBASE_BRIEFING_LANG` | `en` | Briefing language (`en` = security digest default, `de` = Lageprotokoll) |
| `FIREWALL_HOST` | `localhost:8001` | leer = HAK_GAL Firewall aus |
| `NODE_INGEST_TOKEN` | "" (empty) | HMAC + shared secret for ingest/pull/commands |
| `NODE_ADMIN_TOKEN` | (falls back to ingest) | `X-Admin-Token` for `/node/{id}/command` |
| `WORLDBASE_BIND_HOST` | `127.0.0.1` | Uvicorn bind; `0.0.0.0` when Pi on LAN **with** token |
| `WORLDBASE_BRIEFING_INTERVAL` | 21600 | Autopilot briefing interval (seconds); 6 h default |
| `WORLDBASE_SELF` | http://localhost:8002 | Self-referential URL for briefing |
| `ADSB_PRIMARY` | `auto` | `adsb.fi`, `adsb.lol`, or `auto` (parallel lol + sequential fi) |
| `ADSB_TOTAL_TIMEOUT` | `14` | Regional fetch budget (seconds) |
| `ADSB_NODE_TIMEOUT` | `6` | Per-region HTTP timeout (seconds) |
| `WORLDBASE_PORT` (Pi) | 8002 | Pi push/pull target |

---

## Done (2026-06-15) — merge, Pi organism, repo hygiene

### Git / CI
- **PR #1 merged** — `feature/cesium-1.142-eval` → `main` (CI green, smoke 23/23)
- `.gitignore`: `*.db-shm`, `*.db-wal`; `ADSB_PRIMARY` in `backend/.env.example`
- Submodule `offgrid-raspi` @ `91683d8`

### Pi ↔ PC sync (live)
- **`worldbase_push.py`**: reads OGN paths (`esp32_state.json`, `mesh_state.json`, `gps_location.json`)
- **Buffer fix**: no replay after successful push (stale empty samples overwrote good ingest)
- **`offgrid-portal`**: PC `briefing_latest.json` first (`brief.source = worldbase-pc`), local `world_brief` fallback
- Stale `test` node removed from `node_state`
- Pi root disk **72%** after maintenance; SD **89%** (ZIM + arduino cache — expected)

### Deploy note
- SCP from Windows → **LF-encode** Python scripts before Pi install (CRLF breaks `#!/usr/bin/env python3`)

### Verified
- `/api/nodes`: DHT + 2 mesh nodes + GPS
- Push log: `sensors=3 mesh=2 gps=yes`
- Portal `/api/status`: `"source": "worldbase-pc"`

---

## Done (2026-06-15) — Globe stability, split view, aircraft

### Frontend
- Layer refactor → `frontend/src/hooks/layers/` (21 hooks + `GlobeLayerManager`)
- Globe overlay fix (empty `view-fade` blocked interaction)
- Split: CSS grid, persistent `MapPanel`, resize + camera-sync debounce
- Esri basemap before Ion 3D buildings; aircraft poll 45 s

### Backend
- `adsb_client.py`: adsb.fi fallback, sequential regional fetch, `ADSB_PRIMARY`
- `/api/aircraft`: stale-while-revalidate, 45 s cache; `globe_snapshot` 30 s TTL

### Verified
- Operator UI **localhost:5176** — globe + split OK
- Backend **:8002** — aircraft ~300 states via **adsb.fi**; `npm run build` green

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

## Ecosystem (2026-06-15)

| Component | Location | Status |
|-----------|----------|--------|
| WorldBase PC | `192.168.1.111:8002` API, `:5176` UI | **main** @ `217a485`, smoke 23/23 |
| HAK_GAL Firewall | `localhost:8001` | Manual start; fail-open when down |
| Flowsint Docker | `:5173` UI, `:5001` API | Embed in OSINT tab |
| Off-Grid Pi | `192.168.1.121`, SSH `~/.ssh/offgrid-pi` | push/pull OK; DHT+mesh+GPS live |
| Pi portal | `:8093` | PC briefing primary in GEOPOL |
| Borg (Pi) | `/mnt/sdcard/borg-repo` | ~1.7 GB on SD |
| Project backup (Pi) | `/mnt/sdcard/offgrid-project-backup/` | Daily 03:30; **keep 14** (maintenance script) |

**Pi ops (from Windows PC):**
```powershell
& "$env:WINDIR\System32\OpenSSH\ssh.exe" -i "$env:USERPROFILE\.ssh\offgrid-pi" user0@192.168.1.121
```
```bash
sudo offgrid security-harden
journalctl -u worldbase_push -n 3 --no-pager
```

**PC fallback (Admin PowerShell):** `scripts/pc-portproxy-for-pi.ps1` forwards `:8000` → `:8002`.

### Pi storage (canonical doc)

Full detail: **`offgrid-raspi/docs/pi-storage-layout.md`**

| Volume | Mount | 2026-06-15 |
|--------|-------|------------|
| USB root SSD | `/` (`sda2` ~28G) | **~72%** used, ~7.5G free |
| SD card | `/mnt/sdcard` (`mmcblk0p1` ~30G) | **~64%** used (~11G free); ZIM ~14G, models ~1.7G; `.arduino15` removed 2026-06-15 |

- **ZIM/maps/models** already symlinked to SD — not on root.
- **Borg** on SD: `/mnt/sdcard/borg-repo` (live 2026-06-04). Old `/mnt/usb` on root **deleted** — `borg list /mnt/usb` → repo does not exist.
- **Do not** SSH with `offgrid-pi` key *from* the Pi — key is on Windows only.

## 2026-06-03 session (continued)

- Pi port fix verified (`WORLDBASE_PORT=8002`) — push/pull `Ingest OK` / `Pull OK`
- Pi disk: removed root Borg repo `/mnt/usb` (~5.4G); `offgrid-borg.timer` disabled; docs `pi-storage-layout.md`
- Globe: transit city selector, GDACS + air quality + **OSINT pins** (mint markers, max 24, clear button)
- Backend: `/api/cve` (CISA KEV), briefing fusion includes CVE + nodes + GDACS
- AI chat `build_chat_context` injects CISA KEV list
- OSINT: IP + reverse-geocode auto-pin on search; counter in OSINT panel header
- `/api/health`: per-feed `ttl_sec`, `status` (fresh|warn|stale); FULL SITUATION feed grid sorted by age
- Pi: `disk_pct`/`ram_pct` sensor alerts; briefing alerts if disk >= 85%
- Pi maintenance: `offgrid-raspi/scripts/pi-disk-maintenance.sh` (warns if Borg returns to `/mnt/usb`)
- **Pegel:** `backend/pegel_bridge.py`, globe layer + DATA tab `pegel`; OSINT pins persist in `localStorage` (`worldbase_osint_pins_v1`)

## Next Steps (Ideas)

**Backlog:** see section *Backlog (next session)* below.

**Done (2026-06-04) — Phase A “Positive Palantir”:**
- `POST /api/osint/pins/import` + Flowsint JSON paste in OSINT tab → `osintPins` / globe
- Unified **SITUATIONS** board: `GET /api/situations` + overlay (correlations, anomalies, GDACS, pegel, Pi sensors, local pins)
- Entity graph: `entities` / `entity_links`, `GET /api/entity/{id}/context`
- Chat tools (Ollama `use_tools`): `osint_ip`, `osint_domain`, `list_correlations`, `list_situations`, `entity_context`, `focus_globe`, `generate_briefing`

**Done (2026-06-04) — Phase B partial:**
- SMARD API fix (index+timestamp URLs) + `/api/energy/de/globe` + ENERGY layer on globe
- GTFS defaults (VBB Berlin URL, gtfs.de aggregate HH/MUC with bbox); `gtfs-realtime-bindings` in venv
- Pegel+rain correlation in `/api/correlations`; situations parallel + 45s cache
- Browser push for negative DE power price

**Done (2026-06-04) — Phase B close + Phase C start:**
- **Time slider** on globe (quakes + EONET events, 6/12/24h scrub, cumulative filter)
- **OpenSky** shared `opensky_client.py` — aircraft, anomalies, correlations use OAuth when `backend/.env` has credentials
- **Pi sensor sparklines** in globe target panel (`SensorSparklines.tsx`)

**Done (2026-06-04) — Power stack (free feeds, no Palantir budget):**
- **`aircraft_provider.py`** + **`adsb_client.py`** — `/api/aircraft` uses OpenSky if configured, else **adsb.lol** global grid (ODbL, no key); response includes `source`
- **`/api/anomalies`** + correlations use same aircraft provider (no more anonymous-OpenSky-only failures)
- **CRISES layer** — `/api/geopolitics` rebuilt: **GDACS** RSS with `geo_centroids.py` geocoding (ReliefWeb **v1 decommissioned**); optional **ReliefWeb v2** via `RELIEFWEB_APPNAME` in `backend/.env`
- **`gdelt_bridge.py`** — `GET /api/gdelt/pulse` (GDELT DOC headlines, 10 min cache, rate-limit aware)
- **`gdelt_bridge.py`** — `GET /api/gdelt/pulse/local` + `/geo/local` (operator region for briefing LOCAL block)
- **`POST /api/flowsint/export-investigation`** — export globe pins for Flowsint workflow
- Military feed: **adsb.fi** with **adsb.lol `/v2/mil`** fallback

**Done (2026-06-04–06) — Gold canvas Phase 1+2 (all free / no purchase):**
- **Ollama:** `OLLAMA_MODEL=qwen3:8b`, `OLLAMA_EMBED_MODEL=nomic-embed-text` in `backend/.env.example`; `/api/models` returns `default`
- **`cap_bridge.py`** — `GET /api/hazards` (NWS GeoJSON + Meteoalarm); Globe **HAZARDS** + GDELT GEO
- **`anomaly_river.py`** — `GET /api/anomalies/river` (River HalfSpaceTrees, z-score fallback); in Situation Board + briefing
- **`rag_memory.py`** — `GET /api/memory/search`, autopilot indexes briefings + GDELT; chat tool **`search_memory`**
- **`gdelt_bridge.py`** — `GET /api/gdelt/geo` (GEO 2.0 points)
- **`gibs_bridge.py`** — `GET /api/gibs/layers`, `/latest`; Globe NASA GIBS toggle (FIRES/GOES/VIIRS)
- **`outages_bridge.py`** — `GET /api/outages` (IODA; optional Cloudflare via `CLOUDFLARE_API_TOKEN`)
- **`volcano_bridge.py`** — `GET /api/volcanoes` (Smithsonian GVP WFS proxy)
- **`duckdb_fusion.py`** — `GET /api/fusion/status`, `/sample`
- **`pmtiles_bridge.py`** + **`scripts/download-pmtiles.ps1`** + **`scripts/start-pmtiles-serve.ps1`**
  - Stack: `planet_z6.pmtiles` (~42 MB world) + `thailand.pmtiles` (~427 MB detail)
  - Regions: `stack`, `thailand`, `world-z10`, `world-full -Force`, `asean`
  - Serve: `http://127.0.0.1:8088` — MapLibre ZXY MVT (not yet wired into Cesium globe)
- **Docker** (optional): `docker-compose.yml`, `scripts/start-docker.ps1`

**Done (2026-06-06) — Stufe B: RAG, Entity-Card, Cesium Eval & Split-View:**
- **RAG Erweiterung**: `rag_memory.py` indexiert `hazards`, `situations` und `volcanoes` automatisch. SQLite Ringbuffer (2000 Chunks) statt `sqlite-vec` für O(n) Cosine-Search.
- **Entity-Context-Card**: Globe-Clicks zeigen verbundene Datensätze (`GET /api/entity/{id}/context`) im `Globe.tsx` Target-Panel an (`EntityContextCard`).
- **Cesium 1.142 Eval**: Update auf `cesium@1.142.0` auf Branch `feature/cesium-1.142-eval` und Einbau des nativen `MVTDataProvider` als experimentellen Globe-Layer.
- **Split-View**: GLOBE und MAP können nun nebeneinander angezeigt werden, inklusive asynchronem, bidirektionalem Camera-Sync.

**Done (2026-06-06) — Stufe C: Phase 2 Fusion komplett:**
- **CRITICAL BUGFIX `rag_memory.py`**: 5 Funktionen waren versehentlich um 4 Spaces eingerückt → Modul-Level fehlte, ganzer RAG-Stack hätte zur Laufzeit `AttributeError` geworfen. Korrigiert. Außerdem `cap_bridge.get_hazards` / `volcano_bridge.get_volcanoes` durch echte Funktionsnamen (`hazards_active`, `holocene_volcanoes`) ersetzt. **Phase B war ohne diesen Fix nicht funktional.**
- **STAC / Sentinel-2** (`backend/stac_bridge.py`): Element84 EarthSearch (kostenlos, kein Key). Endpoints: `/api/stac/{collections,search,item/{id},thumbnail}`. Region-Presets: `thailand`, `bangkok`, `phuket`, `mekong-delta`, `germany`, `rhein`. Range-aware Thumbnail-Proxy mit ETag. Optional `TITILER_URL` → echte NDVI/True-Color Kacheln. Bridge cached intern (5 min search, 10 min thumbnails).
- **OpenSanctions** (`backend/sanctions_bridge.py`): Lokal-first ohne paid API. Lädt CC-BY `default/targets.simple.csv` (~450 MB) einmal pro 24 h, parst in In-Memory Index (by_name + by_id_token), Jaccard+Substring Fuzzy-Match, IMO/MMSI Identifier-Lookup. Endpoints: `/api/sanctions/{status,refresh,search,screen/vessels}`. Fallback auf self-hosted `yente` (`OPENSANCTIONS_YENTE_URL`) wenn gesetzt. Background ingest in RAG.
- **Aircraft Trails** (`backend/aircraft_trails.py`): Background-Snapshot alle 30 s aus `aircraft_provider`. SQLite `aircraft_trail` Tabelle mit (icao24, lat, lon, alt, speed, heading, t). Auto-Prune ≥ 6 h, Hard-Cap 200 k Rows. Endpoints: `/api/aircraft/{trails,trails/stats,trails/snapshot}`.
- **Pegel Sparklines** (`backend/pegel_bridge.py`): Neuer Endpoint `/api/pegel/{uuid}/history?hours=24` über pegelonline `measurements.json`. Frontend `frontend/src/components/PegelSparkline.tsx` ist ein dependency-freier SVG-Renderer.
- **FUSION HEATMAP** (`backend/fusion_heatmap.py`, neu, **Killer-Feature**): aggregiert quakes + GDACS + hazards + volcanoes + aircraft-anomalies + outages + pegel + aircraft-density auf konfigurierbares Lat/Lon-Grid. Endpoint: `/api/fusion/heatmap?cell_deg=2&top=60&include_geojson=0|1`. Globe-Layer mit Rectangle-Entities + HSL-Plasma-Skala + Legende.
- **Situation Board First-Load**: Startup pre-warms River + Situations + Fusion-Heatmap, sodass der erste Klick instant ist.
- **Frontend DATA-Tabs**: `stac` und `sanctions` neu hinzugekommen (siehe `frontend/src/components/{StacPanel,SanctionsPanel}.tsx`). Pegel-Tab als Card-Grid mit eingebetteten Sparklines.
- **Globe-Layer**: AIRCRAFT TRAILS Toggle, FUSION HEATMAP Toggle, sanktionierte Vessels rot mit ⚠-Outline + Watchlist-Counter im Layer-Block.

**Done (2026-06-06) — HAK_GAL Firewall + Joint-Stack-Test (WorldBase + Firewall):**
- **`backend/.env`**: `FIREWALL_HOST=localhost:8001` gesetzt → `/api/firewall/status` meldet `enabled: true`
- **Firewall-Reparatur (PC)**: kaputte `scipy`/`scikit-learn`-Installation (Import `compose_quat`) behoben via `pip install --no-cache-dir scipy==1.15.3 scikit-learn==1.7.2`
- **Smoke-Test** `.\scripts\smoke-test.ps1`: **17/17 PASS** (Backend, Fusion, Feeds, Vite-Proxy, Ollama-Chat, Frontend-Build)
- **Firewall-Integration**: `/api/firewall/status` → `healthy`; `/api/firewall/test` harmlos → erlaubt; Jailbreak-Prompt → `blocked: true`, `risk_score: 1.0`
- **Chat mit `firewall: true`**: harmloser Prompt → Ollama antwortet; Jailbreak → **FIREWALL BLOCK** (kein LLM-Aufruf)
- **VRAM (RTX 3080 Ti)**: ~11–13 GB mit Firewall-Modellen + `nomic-embed-text`; `OLLAMA_KEEP_ALIVE=1m`, `WORLDBASE_BRIEFING_INTERVAL=1800` in `.env`
- **Start Firewall**: `D:\MCP Mods\HAK_GAL_HEXAGONAL\standalone_packages\llm-security-firewall\detectors\orchestrator\start.ps1`

**Done (2026-06-06) — Stufe D: Google-Maps-Modus + Ollama-Zuverlässigkeit:**
- **`MapModeBar`** (`frontend/src/components/MapModeBar.tsx`): Globale Leiste unten rechts — **KARTE / SATELLIT / HYBRID / GELÄNDE**, **2D / 3D**, **GEBÄUDE**, optional **PHOTO 3D** (Cesium Ion Google Photorealistic Tiles, Asset 2275207).
- **`mapView.ts`**: Shared State zwischen Globe (Cesium) und MapPanel (MapLibre); Esri World Imagery + Hillshade (kostenlos, kein Key).
- **Globe**: OSM 3D-Gebäude (`createOsmBuildingsAsync`), GPU-Tuning (`maximumScreenSpaceError`, FXAA, `resolutionScale`), Basemap-Umschalter ersetzt Cesium `baseLayerPicker`.
- **MapPanel**: Satellit/Hybrid/Gelände-Raster, `fill-extrusion` Gebäude aus PMTiles, Pitch 60° im 3D-Modus, Kamera-Sync inkl. Pitch.
- **Ollama-Fix**: `OLLAMA_HOST=127.0.0.1:11434`, Host-Fallbacks, `/api/models` Timeout 12 s + 20 s Cache, Embed-Modelle aus Chat-Liste gefiltert, Vite-Proxy → `127.0.0.1:8002` (120 s Timeout). AI-Tab: deutsche Fehler + **↻ ERNEUT PRÜFEN**.
- **Start**: immer `.\start.ps1` → Frontend **:5176** (nicht direkt :8002 — dort gibt es keine UI).

**Done (2026-06-08) — Performance, offline planet, operator UI (`34975b4`):**
- **`feeds_extra.py`**: SQLite reads/writes via `asyncio.to_thread` + WAL — no longer blocks the event loop
- **`globe_snapshot.py`**: `GET /api/globe/snapshot` — parallel feed bundle, 15s cache, refresh lock
- **`ais_bridge.py`**: parallel upstream fetch, 6s timeout, stale cache, refresh lock
- **`main.py`**: `/api/health/ping`; aircraft cache 30s; WAL in `init_db`
- **`feed_registry.py`**: shared `feed_cache` persistence for health provenance
- **Globe**: `visibleRef` pauses render + polling when hidden; snapshot replaces ~15 parallel fetches; lighter default layers
- **Split view**: restored git-style `split-view` / `split-pane` layout (stable pan/zoom + events)
- **Telemetry HUD**: grouped LIVE TELEMETRY, feed health dots, ACTIVE/ALL filter, hover tooltips (incl. dynamic Kp text)
- **MapPanel**: Protomaps sprites from `basemaps-assets` + `styleimagemissing` fallback
- **PMTiles**: `planet_full.pmtiles` ~**130 GB** downloaded (`.\scripts\download-pmtiles.ps1 -Region world-full -Force`); MAP archive dropdown defaults to **`thailand`** for fast load — select **`planet_full`** manually for global basemap
- **Smoke test**: `.\scripts\smoke-test.ps1` → **23/23 PASS** (verified after restart)

**Architecture notes (2026-06-08):**
- **Turbopuffer**: not used — stay local/offline-first for RAG (`rag_memory.py`) and firewall (HAK_GAL centroids). Next RAG step: `sqlite-vec` locally, not cloud vector DB.
- **Firewall**: HAK_GAL v6 semantic-first (`all-MiniLM-L6-v2` centroids). WorldBase passes `session_id: worldbase` only; optional future: WorldBase context in scan payload.

**Backlog (next session):**
1. **Firewall autostart** — optional flag in `start.ps1` or header status dot when `:8001` down
2. **`sqlite-vec`** spike in `rag_memory.py`
3. **TiTiler** + **yente** self-host

**Removed from backlog (done 2026-06-15 late):**
- ~~Telemetry presets~~ — Overview / DE Infra / OSINT quick bar; split auto-overview + `globe-split-bar`
- ~~Heatmap → Briefing~~ — `top_hotspots_for_llm()` in briefing, chat context, `/api/briefing` + `/api/node/pull`
- ~~Pi SD `.arduino15`~~ — removed (~7 GB); SD 89% → 64%
- ~~LF deploy helper~~ — `scripts/deploy-pi-sync.ps1` (push/pull/portal, `-TrimArduino`, `-Portal`)
- ~~Split globe camera~~ — `mapPitchToCesiumDeg` / `cesiumPitchToMapDeg` in `cameraSync.ts`

**Removed from backlog (done earlier):**
- ~~PR `feature/cesium-1.142-eval` → `main`~~ — merged PR #1
- ~~Pi push empty sensors/mesh~~ — OGN path fix + buffer replay fix
- ~~Portal dual briefing~~ — PC `briefing_latest.json` primary
- ~~`world-full` download~~ — `planet_full.pmtiles` on disk (~130 GB)

**Done (2026-06-15 late) — Ops + intelligence UX:**
- **`scripts/deploy-pi-sync.ps1`**: LF-safe SCP of `worldbase_push.py`, `worldbase_pull.py`, optional `-Portal`, `-TrimArduino`; clears push buffer; restarts systemd
- **Pi SD**: removed `/mnt/sdcard/.arduino15` (~6.9 GB); SD ~64% used, ~11 GB free
- **Fusion → briefing**: `fusion_heatmap.top_hotspots_for_llm()`; top-3 cells in LLM prompt, SQLite `sources.fusion_hotspots`, `/api/node/pull`, `build_chat_context()`
- **Telemetry presets**: OVERVIEW / DE INFRA / OSINT quick buttons; Overview enables fusion heatmap; split auto-overview + compact `globe-split-bar`
- **Split camera sync**: MapLibre pitch 0° (down) ↔ Cesium −90°; fixes globe staring into space on split

**Done (2026-06-15 night) — Security advisor briefing (Thailand home):**
- **`operator_briefing.py`**: 24h digest buckets LOKAL / REGION / GLOBAL + cyber/infra; Thailand bbox + ASEAN keywords
- Autopilot + `POST /api/briefing/generate`: German **Lageprotokoll** (LOKAL, REGION, GLOBAL, CYBER & INFRA, EMPFEHLUNG)
- Feeds: + GDELT pulse headlines, Bangkok air quality; fusion top-3 retained
- Env: `WORLDBASE_OPERATOR_REGION=thailand`, `WORLDBASE_BRIEFING_LANG=de`, interval default 6 h

**Done (2026-06-03):** Flowsint embed; `/api/flowsint/health`. OSINT pins + localStorage; `/api/pegel`; Ollama `keep_alive: 5m`.

## 2026-06-04 session

- **Security:** `NODE_INGEST_TOKEN` + protected node APIs; `scripts/setup-node-security.ps1`, `scripts/pc-security-audit.ps1`; Pi: `offgrid security-harden`, UFW, Portal-Auth optional
- **Pi (SSH):** token overrides, HMAC push/pull scripts, `offgrid security-harden`, llama `127.0.0.1`, Borg → `/mnt/sdcard/borg-repo`
- **Flowsint:** Docker prod stack; CRLF fix in `setup-flowsint.ps1` for `entrypoint.sh`; iframe embed OK in WorldBase
- **start.ps1:** paths with spaces (`D:\MCP Mods\worldbase`) via `-LiteralPath`
- **UFW Pi:** admin port **8084** (HAK_GAL), not 8081; passepartout no broad `10.42.0.0/16` allow
- **Hotspot:** no default PSK in `01_wifi_ap.sh` — generated to `/etc/offgrid/wifi-ap.env`

---


## Quick Reference: If Something Breaks

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `toFixed is not a function` | `a.alt` is string | `Number(a.alt).toFixed(0)` with `isNaN` guard |
| Node shows `CPU: —` | Wrong field path | Use `n.health.cpu_temp_c` |
| Crypto shows `$—` | Wrong field names | Use `v.usd` / `v.usd_24h_change` |
| Spaceweather `—` | Fields don't exist | Use `aurora_visible_midlat` / `hf_radio_impact` |
| Website not reachable | Backend not running | `.\start.ps1` (use **LiteralPath** if path has spaces) |
| Frontend OK on `localhost:5176` but not `127.0.0.1` | Vite binds IPv6 (`::1`) | Use **http://localhost:5176** in browser |
| Pi `Ingest FAILED` HTTP 403 | Token mismatch | `setup-node-security.ps1` on PC + Pi override from `pi-node-token.conf` |
| `borg list /mnt/usb` fails | Repo removed 2026-06-03 | Use `/mnt/sdcard/borg-repo`; tar backups on SD |
| Pi disk alert in UI | Root was >85% | See `offgrid-raspi/docs/pi-storage-layout.md`; run `pi-disk-maintenance.sh` |
| `borg` lock timeout on Pi | Stuck `borg list`/`check` | `pgrep -a borg`; `kill`; `borg break-lock $BORG_REPO` |
| Split: black right pane / reload every toggle | MapPanel remounted on toggle (old) | Fixed — single MapPanel instance; CSS grid only |
| Split: globe jitter when panning | Camera sync feedback loop | Fixed — 500 ms suppress after programmatic sync |
| Globe: no scroll / no map tiles | Empty `view-fade` over canvas | Fixed — no overlay when `view === 'globe'` |
| AIRCRAFT = 0, slow timeout | adsb.lol unreachable from network | **adsb.fi** fallback; optional `ADSB_PRIMARY=adsb.fi` |
| HUD shows `adsb.fi` under AIRCRAFT | Working as designed | adsb.lol empty/slow — fi regional grid active |
| CRISES at 0,0 or empty | ReliefWeb v1 dead (410) | GDACS + geocoding; optional `RELIEFWEB_APPNAME` |
| MAP shows Thailand not world | Default archive for speed | Select **planet_full** in dropdown (~130 GB) |
| Pi `sensors`/`mesh` empty on PC | Old push paths or stale buffer replay | Deploy `worldbase_push.py` @ `91683d8+`; `rm worldbase_push_buffer.jsonl`; see `WORLDBASE_PI_SYNC.md` |
| Portal `env: python3\r` after deploy | CRLF from Windows SCP | LF-encode before scp; **never** `tr -d '\r'` (corrupts shebang) |
| Portal GEOPOL shows local brief only | Old portal or pull down | `briefing_latest.json` present; portal `brief.source` should be `worldbase-pc` |
| 🛡️ firewall inactive | HAK_GAL not on :8001 | Start orchestrator; `FIREWALL_HOST=localhost:8001` |

---

## File Paths (Absolute)

- Main app: `D:\MCP Mods\worldbase\frontend\src\App.tsx`
- Globe: `D:\MCP Mods\worldbase\frontend\src\components\Globe.tsx`
- Layer hooks: `D:\MCP Mods\worldbase\frontend\src\hooks\layers\`
- Styles: `D:\MCP Mods\worldbase\frontend\src\styles\hud.css`
- Backend feeds: `D:\MCP Mods\worldbase\backend\feeds_extra.py`
- Node sync: `D:\MCP Mods\worldbase\backend\node_sync.py`
- OSINT: `D:\MCP Mods\worldbase\backend\osint_tools.py`
- Main backend: `D:\MCP Mods\worldbase\backend\main.py`
- Aircraft: `backend/aircraft_provider.py`, `backend/adsb_client.py`, `backend/opensky_client.py`
- Crises geo: `backend/geo_centroids.py`
- GDELT: `backend/gdelt_bridge.py` (pulse + geo)
- Phase 1+2 bridges: see *Done (2026-06-04–06)* sections above
- PMTiles backend: `backend/pmtiles_bridge.py` (status + Range-aware file endpoint)
- PMTiles frontend: `frontend/src/components/MapPanel.tsx`
- PMTiles data: `data/pmtiles/planet_full.pmtiles` (~130 GB), `thailand.pmtiles`, `planet_z6.pmtiles`
- PMTiles tooling: `scripts/download-pmtiles.ps1`, `scripts/start-pmtiles-serve.ps1` (optional ZXY on :8088)
- Performance: `backend/globe_snapshot.py`, `backend/feed_registry.py`, `backend/ais_bridge.py` (parallel)
- Bridges: `cap_bridge.py`, `anomaly_river.py`, `rag_memory.py`, `outages_bridge.py`, `volcano_bridge.py`, `gibs_bridge.py`, `duckdb_fusion.py`
- Phase 2: `backend/stac_bridge.py`, `sanctions_bridge.py`, `aircraft_trails.py`, `fusion_heatmap.py`
- Frontend Phase 2 components: `frontend/src/components/{PegelSparkline,StacPanel,SanctionsPanel}.tsx`
- Pi sync doc: `offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`
- Pi push: `offgrid-raspi/scripts/worldbase_push.py` → `/usr/local/bin/` on Pi
- Pi portal: `offgrid-raspi/offgrid/bin/offgrid-portal` → windsurf project on Pi
- Pi maintenance: `offgrid-raspi/scripts/pi-disk-maintenance.sh`
- DB: `D:\MCP Mods\worldbase\backend\worldbase.db`
- Sanctions CSV cache: `D:\MCP Mods\worldbase\data\sanctions\targets.simple.csv` (~450 MB, CC-BY, auto-refresh 24 h)
