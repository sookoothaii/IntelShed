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

## Next (still free)

- **TiTiler/STAC** Router für Sentinel-2/Landsat-Daten in Thailand
- **OpenSanctions / FollowTheMoney** (AIS ↔ sanctions)
- **UI Polish** (Situation Board First-Load, GTFS VehiclePosition, Pegel Sparklines)
