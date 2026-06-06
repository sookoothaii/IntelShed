# Next LLM Mission — WorldBase

> Copy the **Start prompt** below into a new agent session.  
> Read first: `LLM_HANDOFF.md` → `docs/PHASE1_INTEGRATION.md` → this file.

## Leitprinzip

**Fusion vor Feeds** — eine Karte, Timeline, Entities, Investigation. Kein Feed ohne Globe- oder Briefing-Mehrwert.

Operator lebt **hauptsächlich in Thailand**; Hardware: **i9 + RTX 3080 Ti** — `world-z10` (~1 GB) oder PMTiles-in-Cesium sind realistisch.

## Erledigt 2026-06-06 (Stufe D — Google-Maps-Modus + Ollama-Zuverlässigkeit)

- **MapModeBar** (`MapModeBar.tsx` + `mapView.ts`): KARTE / SATELLIT / HYBRID / GELÄNDE, 2D/3D, GEBÄUDE, optional PHOTO 3D (Cesium Ion). Shared State für Globe + MapPanel + Split-View.
- **Globe GPU + 3D**: World Terrain, OSM Buildings, Esri Satellite/Hillshade Basemaps, Photorealistic 3D Tiles (Ion 2275207), FXAA + `resolutionScale`.
- **MapPanel 3D**: Esri Raster-Layer, PMTiles `fill-extrusion`, Pitch 60°, Kamera-Sync inkl. Pitch.
- **Ollama-Fix Windows**: `OLLAMA_HOST=127.0.0.1:11434`, `/api/models` Fallbacks + Cache, Embed-Modelle rausgefiltert, Vite-Proxy `127.0.0.1:8002`, AI-Tab Retry + deutsche Hinweise.

## Erledigt 2026-06-06 (Stufe C — Phase 2 Fusion: STAC, OpenSanctions, Trails, Fusion-Heatmap)

- **RAG-Bugfix**: 5 Funktionen in `rag_memory.py` waren fälschlich eingerückt → broken. Korrekt + erweitert um `ingest_stac_items` und `ingest_sanctions_hits`.
- **STAC/Sentinel-2** (`backend/stac_bridge.py`): Element84 EarthSearch (kostenlos, kein Key), Regionen-Presets (`thailand`, `mekong-delta`, `bangkok`, `phuket`, `germany`, `rhein`), Range-aware Thumbnail-Proxy. Optional TiTiler für NDVI/True-Color Tiles.
- **OpenSanctions** (`backend/sanctions_bridge.py`): bewusst **lokal-first** — lädt CC-BY Bulk-CSV (~450 MB) einmal pro 24 h, In-Memory Token-Match (Jaccard + Substring), MMSI/IMO Identifier-Lookup. AIS-Vessel-Screening flaggt sanktionierte Schiffe im Globe rot. Optional Yente self-hosted oder paid REST.
- **Aircraft Trails** (`backend/aircraft_trails.py`): Background-Snapshot alle 30 s, SQLite-Storage mit Hard-Cap (200k Rows / 6 h). Globe zeigt 30-min Trail beim Aircraft-Click.
- **Pegel Sparklines** (`backend/pegel_bridge.py` + `frontend/src/components/PegelSparkline.tsx`): `/api/pegel/{uuid}/history?hours=24`, dependency-free SVG. Rendert im DATA-Pegel-Grid und im Globe Target-Panel.
- **Fusion-Heatmap** (`backend/fusion_heatmap.py`, neu, Killer-Feature): aggregiert quakes + GDACS + hazards + volcanoes + anomalies + outages + pegel + aircraft-density auf Lat/Lon-Grid; Globe-Layer mit HSL-Plasma-Skala + Legende.
- **Situation Board First-Load**: Startup pre-warms River-Scan + `unified_situations` + Fusion-Heatmap → instant first-paint.

## Erledigt 2026-06-06 (Stufe B — RAG, Entity-Card, Cesium Eval, Split-View)

- **RAG Erweitert**: `rag_memory.py` indexiert jetzt automatisch auch `hazards`, `situations`, und `volcanoes`. Harter Ringbuffer (2000 chunks) in SQLite implementiert, um die $O(n)$ Cosine-Search schnell zu halten (ohne `sqlite-vec`).
- **Entity-Context-Card**: Globe-Clicks auf Entities (`aircraft`, `pegel`, `volcano` etc.) fetchen nun den Fusion-Graphen via `GET /api/entity/{id}/context` und zeigen verwandte Einträge direkt im Target-Panel (`Globe.tsx` -> `EntityContextCard`).
- **Cesium 1.142 Eval**: `package.json` auf `cesium@1.142.0` gehoben. Experimenteller Layer-Toggle "MVT (EXPERIMENTAL)" im Globe eingeführt, der den neuen nativen `MVTDataProvider` über den 3D-Globus legt.
- **Split-View**: Neuer **◫ SPLIT** Button im UI. Rendert `Globe` und `MapPanel` (2D MapLibre) nebeneinander inkl. asynchronem **Camera-Sync** in beide Richtungen.

---

## Erledigt (nicht nochmal von null)

### Phase A–B (2026-06-04)

Situation Board, Entities, Chat-Tools, Time Slider, adsb.lol/OpenSky, GDACS crises, GDELT pulse, SMARD/ENERGY, Pi sparklines, Flowsint export.

### Gold Phase 1+2 (2026-06-04–06) — committed

| Modul | API / UI |
|-------|----------|
| Qwen3 + RAG | `OLLAMA_MODEL=qwen3:8b`, `nomic-embed-text`, `search_memory` tool |
| Hazards | `GET /api/hazards` → Globe **HAZARDS** + GDELT GEO |
| River | `GET /api/anomalies/river` → Situations + briefing |
| Outages | `GET /api/outages` (IODA; CF optional) → Globe **OUTAGES** |
| Volcanoes | `GET /api/volcanoes` → Globe **VOLCANOES** |
| GIBS | `GET /api/gibs/*` → Globe imagery toggle FIRES/GOES/VIIRS |
| Fusion stub | `GET /api/fusion/*` (DuckDB spatial) |
| PMTiles | `download-pmtiles.ps1 -Region stack` → `planet_z6` + `thailand`; `start-pmtiles-serve.ps1` :8088 |
| Docker | `docker-compose.yml`, `docs/DOCKER_DEPLOY.md` (optional deploy) |

Details: **`docs/PHASE1_INTEGRATION.md`**

---

## Fokus nächste Instanz (Priorität)

### 1. TiTiler-Service starten (Phase 2 ist live, nur die NDVI-Kacheln fehlen noch)

- TiTiler in Docker oder via uvicorn: `docker run -p 8001:8000 ghcr.io/developmentseed/titiler:latest`
- `backend/.env` → `TITILER_URL=http://127.0.0.1:8001`
- Bridge emittiert dann automatisch `titiler_tiles.truecolor` und `titiler_tiles.ndvi` URLs in `/api/stac/search`. Frontend muss nur eine Cesium `UrlTemplateImageryProvider` registrieren — siehe `gibsLayer` Logik in `Globe.tsx` als Vorlage.

### 2. OpenSanctions: yente self-hosting (volle Match-API ohne 0.10 €/Call)

- `docker compose -f https://github.com/opensanctions/yente/raw/main/docker-compose.yml up -d`
- `backend/.env` → `OPENSANCTIONS_YENTE_URL=http://127.0.0.1:8000`
- Default-Datensatz reicht; ggf. zusätzliche Datasets über `YENTE_DATASETS`.

### 3. Globe-Polish

- **Sanctioned Vessel Trail**: bei Treffer ähnliche Polyline wie für Aircraft (AIS hat keine eigene History — entweder MyShipTracking historization oder eigener Snapshot-Loop).
- **Heatmap Toggle in Briefing**: Top-3 Fusion-Cells dem LLM-Briefing als Prompt-Context anhängen.
- **GTFS Live VehiclePositions**: VBB liefert nur `trip_updates`. Optionen: `gtfs.de` Aggregat (bereits hinterlegt, oft leer), `DELFI` (deutschlandweit, benötigt Anmeldung), oder Frontend-Interpolation aus letzten zwei trip_updates.

### 4. world-z10 Basemap (~1 GB)

- `.\scripts\download-pmtiles.ps1 -Region world-z10`
- Cesium MapPanel automatisch verfügbar — kein Code-Change.

### 5. Optional keys / Ops (User)

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text
# backend/.env: OLLAMA_HOST=127.0.0.1:11434  OLLAMA_MODEL=qwen3:8b
# PMTILES_SERVE_URL=http://127.0.0.1:8088
# Optional: CLOUDFLARE_API_TOKEN, OPENSKY_*, RELIEFWEB_APPNAME
pip install -r backend/requirements.txt   # river, duckdb
```

---

## Do NOT

- Commit `backend/.env`, `data/pmtiles/`, secrets
- SCADA / mass tracking
- Neue Feed-Bridges ohne Globe- oder Briefing-Anbindung
- Memgraph (BSL) — Neo4j CE / ArcadeDB if graph needed

---

## Start prompt (copy)

```
Mission: WorldBase — Phase 3 Polish (Phase 2 Fusion ist live)

Erledigt (2026-06-06):
- Phase 1+2 Gold — Qwen3, RAG, River, hazards, outages, PMTiles
- Stufe B — RAG-Erweiterung, Entity-Card, Cesium 1.142, Split-View
- Stufe C (Phase 2 Fusion):
  * STAC/Sentinel-2 (Element84) — /api/stac/* mit Thailand-Presets + Thumbnail-Proxy
  * OpenSanctions lokal-first (CC-BY CSV) — /api/sanctions/* + AIS-Vessel-Screening (rot im Globe)
  * Aircraft Trails — /api/aircraft/trails + 30s Background-Snapshot + Globe-Polyline
  * Pegel Sparklines — /api/pegel/{uuid}/history + SVG-Komponente
  * FUSION HEATMAP — /api/fusion/heatmap, Globe-Toggle mit Legende
  * Situations First-Load via Startup-Prewarm
  * rag_memory.py Indentation-Bug behoben + neue ingest_stac_items/ingest_sanctions_hits
- Stufe D (Map Modes + Ollama):
  * MapModeBar: KARTE/SATELLIT/HYBRID/GELÄNDE + 2D/3D + GEBÄUDE + PHOTO 3D
  * Globe OSM Buildings + Esri Basemaps; MapPanel pitch + extrusion
  * Ollama Windows-Fix: 127.0.0.1, /api/models Cache, Vite-Proxy-Fix

Lies: LLM_HANDOFF.md, docs/PHASE1_INTEGRATION.md, docs/NEXT_LLM_MISSION.md.

Ziel-Optionen Session:
A) TiTiler-Service starten → echte NDVI/True-Color Tiles statt nur Thumbnails
B) yente self-hosting → unbegrenzte Sanctions /match API (kostenlos lokal)
C) GTFS DE VehiclePositions (interpolation oder DELFI)
D) world-z10 Basemap-Download für globale 2D-Karte
E) Heatmap-Cells in LLM-Briefing als Prompt-Context

Test: .\start.ps1 → .\scripts\smoke-test.ps1 (FAIL 0) → http://localhost:5176
  - DATA → STAC: Region "thailand" zeigt Sentinel-2 Thumbnails
  - DATA → SANCTIONS: "putin" + AIS-Screening
  - GLOBE → Aircraft anklicken → Trail-Polyline
  - GLOBE → Layer FUSION HEATMAP einschalten → Hotspots + Legend
  - DATA → PEGEL: Sparklines pro Gauge

Ollama: qwen3:8b + nomic-embed-text (Ollama-App muss laufen).
Nicht: Secrets committen; neue Feeds ohne Globe-Layer.
```

---

## Test checklist

### Regression

- [ ] `GET /api/hazards` → geocoded alerts
- [ ] `GET /api/outages` → IODA items
- [ ] `GET /api/anomalies/river` → engine river or zscore
- [ ] `GET /api/memory/stats` → chunks after briefing
- [ ] Globe layers: HAZARDS, OUTAGES, NASA GIBS FIRES
- [ ] Chat: model **qwen3:8b**, tool `search_memory`

### PMTiles & Split-View

- [ ] `.\scripts\download-pmtiles.ps1 -Region stack` (if missing)
- [ ] `GET /api/pmtiles/status` → archives list
- [ ] **MAP** tab in nav renders Protomaps basemap
- [ ] **SPLIT** toggle activates side-by-side view with Camera-Sync
- [ ] Experimental MVT Layer toggle on Globe

### Phase 2 Fusion (done 2026-06-06)

- [x] STAC / Sentinel-2 search + thumbnail proxy
- [x] OpenSanctions local-first + AIS vessel screening
- [x] Aircraft trails (30 s snapshot)
- [x] Pegel sparklines (24 h history endpoint + SVG)
- [x] **FUSION HEATMAP** Globe layer
- [x] Situation Board pre-warm

### Next work

- [ ] TiTiler service + NDVI/True-Color Cesium ImageryLayer
- [ ] yente Docker for unlimited sanctions /match
- [ ] GTFS-Realtime VehiclePosition fallback (DELFI or interpolated)
- [ ] world-z10 PMTiles download (~1 GB)
- [ ] Heatmap top-cells injected into briefing prompt
