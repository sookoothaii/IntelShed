# Next LLM Mission — WorldBase

> Copy the **Start prompt** below into a new agent session.  
> Read first: `LLM_HANDOFF.md` → `docs/PHASE1_INTEGRATION.md` → this file.

## Leitprinzip

**Fusion vor Feeds** — eine Karte, Timeline, Entities, Investigation. Kein Feed ohne Globe- oder Briefing-Mehrwert.

Operator lebt **hauptsächlich in Thailand**; Hardware: **i9 + RTX 3080 Ti** — `world-z10` (~1 GB) oder PMTiles-in-Cesium sind realistisch.

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

### 1. PMTiles → sichtbar im UI (Höchster Hebel)

- Cesium unterstützt Protomaps-Vektor **nicht nativ**
- Optionen: MapLibre-Panel neben Globe; oder `pmtiles serve` + Protomaps-Style JSON; oder `world-z10` als Raster-Pfad
- Lokaler Stack liegt unter `data/pmtiles/` (gitignored) — nicht committen
- Test: `.\scripts\start-pmtiles-serve.ps1` → `http://127.0.0.1:8088/planet_z6.json`

### 2. Optional keys / Ops (User)

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text
# backend/.env: OLLAMA_MODEL, PMTILES_SERVE_URL=http://127.0.0.1:8088
# Optional: CLOUDFLARE_API_TOKEN, OPENSKY_*, RELIEFWEB_APPNAME
pip install -r backend/requirements.txt   # river, duckdb
```

### 3. Phase 2 Fusion (free, mehr Aufwand)

- TiTiler + STAC/COG router
- FollowTheMoney + nomenklatura + yente/OpenSanctions (AIS↔sanctions)
- `world-z10` global basemap: `.\scripts\download-pmtiles.ps1 -Region world-z10`

### 4. Polish

- Situation Board first-load (River scan in `/api/situations`)
- GTFS DE VehiclePosition; aircraft trails; pegel sparklines

---

## Do NOT

- Commit `backend/.env`, `data/pmtiles/`, secrets
- SCADA / mass tracking
- Neue Feed-Bridges ohne Globe- oder Briefing-Anbindung
- Memgraph (BSL) — Neo4j CE / ArcadeDB if graph needed

---

## Start prompt (copy)

```
Mission: WorldBase — PMTiles im UI + Phase 2 Fusion vorbereiten.

Erledigt (2026-06-06): Gold Phase 1+2 — Qwen3, RAG, River, hazards, outages, volcanoes, GIBS toggle, DuckDB stub, PMTiles stack (planet_z6 + thailand), Docker optional.

Lies: LLM_HANDOFF.md, docs/PHASE1_INTEGRATION.md, docs/NEXT_LLM_MISSION.md.
Globe: frontend/src/components/Globe.tsx
PMTiles: scripts/start-pmtiles-serve.ps1, backend/pmtiles_bridge.py

Ziel Session: PMTiles-Basemap neben/under Cesium sichtbar machen ODER world-z10 pull + status in /api/pmtiles/status.

Test: .\start.ps1 → http://localhost:5176
Ollama: qwen3:8b + nomic-embed-text laufen lassen (Ollama-App muss laufen).
Nicht: Secrets committen; 130 GB planet ohne -Force; neue Feeds ohne Layer.
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

### PMTiles (local)

- [ ] `.\scripts\download-pmtiles.ps1 -Region stack` (if missing)
- [ ] `.\scripts\start-pmtiles-serve.ps1` → TileJSON loads
- [ ] `GET /api/pmtiles/status` → archives list

### Next work

- [ ] Basemap visible in frontend (MapLibre or Cesium integration)
- [ ] Optional `world-z10` download
