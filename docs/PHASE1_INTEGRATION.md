# Phase 1 integration (no purchase required)

Implemented 2026-06-04 — quick wins from the Gold canvas.

## Backend endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/hazards` | NWS GeoJSON + Meteoalarm CAP (5 min cache) |
| `GET /api/anomalies/river` | River HalfSpaceTrees per feed (60s cache; z-score if `river` missing) |
| `GET /api/memory/search?q=` | RAG over briefings + GDELT (Ollama `nomic-embed-text`) |
| `POST /api/memory/index/pulse` | Manual GDELT pulse re-index |
| `GET /api/memory/stats` | Chunk counts by source |
| `GET /api/gdelt/geo` | GDELT GEO 2.0 points (15 min cache) |
| `GET /api/gibs/layers` | NASA GIBS WMTS catalog (for future imagery toggle) |
| `GET /api/fusion/status` | DuckDB spatial readiness |
| `GET /api/fusion/sample` | Demo query (entities or `FUSION_GEOPARQUET`) |

## Ollama setup (PC)

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text
```

Copy `backend/.env.example` → `backend/.env` and set `OLLAMA_MODEL=qwen3:8b`.

## Python deps

```powershell
cd backend
pip install -r requirements.txt
```

Optional: `river` enables HalfSpaceTrees; without it, z-score fallback runs.

## Globe

- **HAZARDS** layer: NWS/Meteoalarm + GDELT GEO points (purple).
- Situation Board includes River feed anomalies.

## Chat tools

- `search_memory` — semantic recall for citable briefings.

## Phase 2 additions (still free, 2026-06-05)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/outages` | IODA alerts/events (no key); + Cloudflare Radar if `CLOUDFLARE_API_TOKEN` |
| `GET /api/volcanoes` | Smithsonian GVP holocene volcanoes (WFS proxy) |
| `GET /api/pmtiles/status` | Local `.pmtiles` basemap readiness |
| `GET /api/gibs/latest` | WMTS date token for imagery overlay |

Globe layers: **OUTAGES**, **VOLCANOES**, **NASA GIBS** imagery toggle (FIRES/GOES/VIIRS).

```powershell
# Quick test file (~20 MB, US zip codes — validates pipeline)
.\scripts\download-pmtiles.ps1 -Region sample

# Better for WorldBase / DE (~60 MB world overview, or Germany bbox — auto-installs pmtiles CLI)
.\scripts\download-pmtiles.ps1 -Region z6
.\scripts\download-pmtiles.ps1 -Region germany

# Then in backend/.env:
# PMTILES_PATH=D:/MCP Mods/worldbase/data/pmtiles/germany.pmtiles
```

Note: `r2-public.protomaps.com/protomaps-sample.pmtiles` was removed (404). Use regions above.

## Phase A done (2026-06-06) — PMTiles in UI

| Endpoint / Component | Purpose |
|----------------------|---------|
| `GET /api/pmtiles/file/{name}` | Range-aware stream (200/206), HEAD probe, ETag — replaces external `pmtiles serve` |
| `frontend/src/components/MapPanel.tsx` | MapLibre + `pmtiles://` protocol + `@protomaps/basemaps` style |
| App nav **MAP** tab | Tactical 2D companion to Cesium globe; focus sync via `focusOnMap` |

```powershell
# No separate pmtiles serve process required:
.\start.ps1
# Open http://localhost:5176 → click MAP tab
```

Optional: `scripts/start-pmtiles-serve.ps1` still works on port 8088 for ZXY/MVT
testing or non-MapLibre clients.

## Phase B done (2026-06-06) — RAG, Entity-Card, Cesium Eval & Split-View

| Endpoint / Component | Purpose |
|----------------------|---------|
| `backend/rag_memory.py` | RAG erweitert auf Hazards, Situations, Volcanoes. Ringbuffer (2000 chunks) |
| `frontend/src/components/Globe.tsx` | EntityContextCard bei Klick auf Entities (zeigt Fusion Graph) |
| `frontend/src/components/Globe.tsx` | MVTDataProvider Toggle (Cesium 1.142 Eval-Branch) |
| `frontend/src/App.tsx` | Split-View (Globe + MapPanel) mit bidirektionalem Camera-Sync |

> **Bugfix (2026-06-06):** `backend/rag_memory.py` hatte 5 Funktionen versehentlich
> auf Funktions- statt Modul-Ebene eingerückt (`upsert_chunk`, `ingest_pulse`,
> `ingest_hazards`, `ingest_volcanoes`, `ingest_situations`). Der ganze
> Phase-B RAG-Stack wäre zur Laufzeit mit `AttributeError` gebrochen.
> Außerdem wurden `cap_bridge.get_hazards` / `volcano_bridge.get_volcanoes`
> verwendet, die nicht existieren — korrigiert auf `hazards_active` /
> `holocene_volcanoes`.

## Phase 2 done (2026-06-06) — Fusion, Imagery, Sanctions, Polish

| Endpoint / Component | Purpose |
|----------------------|---------|
| `backend/stac_bridge.py` | Element84 EarthSearch (Sentinel-2 L2A, Landsat C2 L2) — `/api/stac/{collections,search,item,thumbnail}` mit Region-Presets (Thailand, Mekong, Bangkok, Phuket, Germany, Rhein), Range-aware Thumbnail-Proxy. Optional `TITILER_URL` → echte True-Color/NDVI Kacheln. |
| `backend/sanctions_bridge.py` | OpenSanctions ohne kostenpflichtige API: lädt CC-BY `default/targets.simple.csv` (~450 MB) einmal pro 24 h, in-memory Token-Index, Name + Identifier (IMO/MMSI) Lookup. Endpoints: `/api/sanctions/{status,refresh,search,screen/vessels}`. Fällt auf self-hosted `yente` (`OPENSANCTIONS_YENTE_URL`) zurück, wenn gesetzt. |
| `backend/aircraft_trails.py` | Persistiert ADS-B Positionen alle 30 s in SQLite (`aircraft_trail`). Hard-Cap 200 k Rows, Auto-Prune ≥ 6 h. Endpoints: `/api/aircraft/trails`, `/api/aircraft/trails/stats`, `/api/aircraft/trails/snapshot`. |
| `backend/pegel_bridge.py` | Neu: `GET /api/pegel/{uuid}/history?hours=24` für SVG-Sparklines im Frontend. |
| `backend/fusion_heatmap.py` | **Killer-Feature**: aggregiert quakes + GDACS + hazards + volcanoes + aircraft-anomalies + outages + pegel + aircraft-density auf ein Lat/Lon-Grid (default 2°). Liefert ranked cells + optionales GeoJSON. Endpoint: `/api/fusion/heatmap`. |
| `backend/main.py` | Startup-Pre-warm für Situations + River + Fusion (instant first-load), Aircraft-Trail Background-Loop, RAG ingest erweitert um STAC + Sanctions. |
| `frontend/src/components/PegelSparkline.tsx` | Dependency-freie SVG-Sparkline (Gradient-Fill + Endpunkt-Highlight), reused im DATA-Pegel-Grid + Globe Target-Panel. |
| `frontend/src/components/StacPanel.tsx` | DATA-Tab **STAC**: Region / Collection / Datum / Cloud-Filter, Thumbnail-Grid, Direct-COG-Link, Focus-on-Map. |
| `frontend/src/components/SanctionsPanel.tsx` | DATA-Tab **SANCTIONS**: Watchlist-Suche + Live AIS-Screening; Hits gehen direkt auf den Globe. Exportiert auch `useSanctionedVessels` Hook (für andere Komponenten). |
| `frontend/src/components/Globe.tsx` | Aircraft-Trails (Polyline mit Glow) bei Click, sanktionierte Vessels rot mit ⚠-Outline, **FUSION HEATMAP** Layer (Rectangle-Grid mit HSL-Plasma-Skala + Legende). |
| `frontend/src/App.tsx` | Neue DATA-Tabs `stac` + `sanctions` registriert; Pegel-Tab nutzt Card-Grid mit Sparklines. |

### Automated smoke-test (PC)

```powershell
.\start.ps1
# Warten bis Backend + Frontend + Ollama laufen, dann:
.\scripts\smoke-test.ps1
# Erwartung: PASS 17+, FAIL 0 (prüft APIs, Vite-Proxy, Ollama-Chat, Frontend-Build)
```

### Quick smoke-test (PC, manuell)

```powershell
.\start.ps1
# Frontend: http://localhost:5176
# - GLOBE  → Layers: AIRCRAFT TRAILS, FUSION HEATMAP einschalten; auf Aircraft klicken → 30 min Trail erscheint
# - DATA   → STAC tab: Region "thailand" → 14 Tage Sentinel-2 Thumbnails
# - DATA   → SANCTIONS tab: "putin" suchen; AIS-Screening läuft automatisch alle 2 min
# - DATA   → PEGEL tab: 24 h Sparklines pro Pegel
```

### Used by RAG (already wired in `_phase1_background_tasks`)

```python
await rag_memory.ingest_stac_items(items)        # Sentinel-2 Thailand
await rag_memory.ingest_sanctions_hits(hits)     # AIS-Vessel-Treffer
```

## Phase 2 done (2026-06-06) — Map modes (Google Maps-style) + Ollama reliability

| Component | Purpose |
|-----------|---------|
| `frontend/src/lib/mapView.ts` | Shared `MapViewMode`: basemap (`streets`/`satellite`/`hybrid`/`terrain`), `render3d`, `buildings`, `photorealistic` |
| `frontend/src/components/MapModeBar.tsx` | UI-Leiste: KARTE · SATELLIT · HYBRID · GELÄNDE · 2D/3D · GEBÄUDE · PHOTO 3D (Ion) |
| `frontend/src/components/Globe.tsx` | Cesium: Esri/OSM Basemaps, World Terrain, OSM 3D Buildings, optional Photorealistic 3D Tiles, GPU-Tuning |
| `frontend/src/components/MapPanel.tsx` | MapLibre: Esri satellite/hillshade raster, vector PMTiles, `fill-extrusion` buildings, pitch 60° |
| `frontend/vite.config.ts` | Dev-Proxy `/api` → `http://127.0.0.1:8002` (120 s timeout — Windows-IPv6-Fix) |
| `backend/main.py` | `/api/models`: 127.0.0.1↔localhost Fallback, 12 s timeout, 20 s cache, Embed-Modelle gefiltert |
| `backend/.env.example` | `OLLAMA_HOST=127.0.0.1:11434` (Windows-Empfehlung) |
| `frontend/src/App.tsx` | AI-Tab: deutsche Ollama-Fehler, Retry-Button, Embed-Filter im Chat-Dropdown |

### Ollama setup (PC)

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text
# backend/.env:
OLLAMA_HOST=127.0.0.1:11434
OLLAMA_MODEL=qwen3:8b

.\start.ps1
# UI: http://localhost:5176  (nicht :8002 — nur API)
# Header: BACKEND + OLLAMA grün → AI-Tab → Modell qwen3:8b
```

### Map mode smoke-test

```powershell
.\start.ps1
# Unten rechts: SATELLIT + 3D + GEBÄUDE einschalten
# Globe: geneigte Kamera, OSM-Gebäude sichtbar
# MAP-Tab: Pitch + Gebäude-Extrusion aus PMTiles
# SPLIT: beide synchron (Basemap + Kamera inkl. Pitch)
```
