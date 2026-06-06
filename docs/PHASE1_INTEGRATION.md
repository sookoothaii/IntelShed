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

## Next (still free)

TiTiler/STAC, OpenSanctions/yente, PMTiles in Cesium viewer, RTL-SDR when hardware arrives.
