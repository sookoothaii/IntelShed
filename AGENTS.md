# AGENTS.md — WorldBase (PC stack)

> For AI coding agents. Operator docs: [`README.md`](README.md). Pi edge: [`offgrid-raspi/AGENTS.md`](offgrid-raspi/AGENTS.md).

---

## One sentence

**WorldBase** is a spatial intelligence workstation: React + Cesium globe, FastAPI with 30+ live feeds, local Ollama chat, and optional Pi↔PC sync for offline briefing on the edge node.

---

## Runtime (Windows dev)

| Service | URL | Notes |
|---------|-----|--------|
| **UI** | http://localhost:5176 | Always via Vite — not `:8002` for the HUD |
| **API** | http://127.0.0.1:8002 | OpenAPI: `/docs` |
| **Fast health** | `GET /api/health/ping` | Use before/after changes |
| **Ollama** | http://127.0.0.1:11434 | Default chat: `qwen3:8b` |
| **Start** | `.\start.ps1` | Waits for `/api/health/ping` before Vite (avoids proxy ECONNREFUSED); paths with spaces → `-LiteralPath` |
| **Verify** | `.\scripts\smoke-test.ps1` | 31 checks — run before claiming “done” (includes live feed envelope contract when API is up) |

Copy env: `backend\.env.example` → `backend\.env`, `frontend\.env.example` → `frontend\.env` (Cesium Ion token required for terrain/buildings).

---

## Current work focus (default)

Unless the user says otherwise, prioritize:

1. **24h security digest** — `backend/operator_briefing.py` + `backend/node_sync.py`
2. **Operator home region** — `WORLDBASE_OPERATOR_REGION=thailand` (LOCAL / REGION / GLOBAL buckets)
3. **GDELT local** — `backend/gdelt_bridge.py` → `/api/gdelt/pulse/local`, `/api/gdelt/geo/local`
4. **Pi pull loop** — PC generates briefing → Pi `GET /api/node/pull` → portal `briefing_latest.json`
5. **Intelligence UX** — FULL SITUATION overlay, SITUATIONS board, fusion hotspots in briefing, DATA → INTEL (ingest, feed sync, Splink resolution, Cytoscape overview)

**Out of scope by default:** HAK_GAL LLM firewall — optional spare-parts HTTP bridge (`FIREWALL_HOST`, `:8001`); baseline guard is `prompt_guard.py` (0 VRAM). Do not assume full HAK_GAL stack runs or fits 16 GB VRAM. Doc: [`docs/FIREWALL.md`](docs/FIREWALL.md).

---

## Briefing pipeline

```
_gather_snapshot()  →  intel_briefing.gather_for_briefing()  →  format_digest_sections()
                              ↑                                      ↑
                    live feeds (GDELT, quakes, …)              FtM graph (who/what)
                              ↓
                    build_security_advisor_prompt()  →  Ollama  →  SQLite briefings
                              ↑
                    fusion top-3 + INTEL ENTITIES block in prompt
```

Stored briefing JSON (`sources` column) includes `intel`, `digest`, and **`quality`** (rule-based score 0–1). Pi pull v2 adds `ETag`, `content_sha256`, `quality`, `source: worldbase-pc`.

| Action | Endpoint / file |
|--------|-----------------|
| Latest text | `GET /api/briefing` — text, `digest`, `intel`, `quality`, `fusion_hotspots`, `digest_line_meta`, `watch_items` |
| Force generate | `POST /api/briefing/generate` — header `X-API-Key` when `WORLDBASE_API_KEY` is set; `?force=1` bypasses snapshot cache |
| **Prediction ledger** | `quality.meta.prediction_accuracy_30d` / `prediction_pending` — watch outcomes after horizon; `backend/prediction_ledger.py` |
| **FtM subgraph** | `GET /api/intel/subgraph?hops=2&bbox=` — 2-hop graph around operator bbox; briefing prompt `INTEL SUBGRAPH` block |
| **Spatial proximity edges** | `POST /api/intel/spatial/run` — rebuild `nearby` links after feed ingest (Track 3+) |
| FtM → digest bridge | `backend/intel_briefing.py` |
| Autopilot | `WORLDBASE_BRIEFING_AUTOPILOT=1`, interval `WORLDBASE_BRIEFING_INTERVAL` (default 6 h) |
| FtM in digest | `WORLDBASE_BRIEFING_INTEL=1` (default), excludes `Airplane` by default |
| NewsData digest slots | `WORLDBASE_BRIEFING_NEWSDATA_SLOTS=2` (default) — reserved `News:` lines survive severity cap |
| NewsData / GDELT noise | Sports, entertainment, and celebrity headlines filtered before digest (`newsdata_bridge.is_sports_content`); tourism/local economy (e.g. Songkran) kept when situational |
| German output | `WORLDBASE_BRIEFING_LANG=de` (UI strings stay English) |
| Pi payload | `GET /api/node/pull` — v2: ETag/304, SHA-256, quality, `intel_subgraph` compact graph (+ `X-Node-Token` when set) |
| **Trust probes** | `GET /api/trust` — field score 0–4 (briefing, GDELT, Ollama, Pi edge) + `feed_drift` freshness (connector provenance) |
| **CAMS haze (Thailand/ASEAN)** | `GET /api/cams/haze` — PM2.5, dust, AOD via Open-Meteo/CAMS; feeds briefing LOCAL |
| **HDX humanitarian** | `GET /api/humanitarian` — UN OCHA datasets (Myanmar border, displacement); briefing REGION |
| **NewsData.io (optional)** | `GET /api/newsdata`, `GET /api/newsdata/sources` — headlines complement GDELT; corroboration family `newsdata`; Free tier ~12h delay; `NEWSDATA_API_KEY` |
| **Maritime AIS** | `GET /api/maritime` — background AISstream WebSocket when `AISSTREAM_API_KEY` set (`stream_connected`, `stream_buffer` in JSON); MyShipTracking/AISHub fallback; Thailand corridor default |
| **STAC feed snapshots** | `GET /api/stac/feeds/collection`, `GET /api/stac/feeds/items` — connector cache as STAC Items with bbox/geometry, registry links; DATA → **FEEDS** tab: STAC JSON + ⊕ fly-to |
| **Connectors** | `GET /api/connectors` — manifest catalog + cache overlay; export via `scripts/export_connectors.py` |
| **MCP (Cursor)** | Streamable HTTP `http://127.0.0.1:8002/api/mcp` — 13 tools when Agent Bus on — [`docs/MCP.md`](docs/MCP.md) |
| **Agent Bus** | `POST /api/agent/publish`, `GET /api/agent/stream` — globe fly/layer when HUD open — [`docs/MCP.md`](docs/MCP.md#agent-bus) |
| **FtM globe layer** | `GET /api/intel/entities?geolocated=1` → HUD **INTEL** toggle (`intelFt`) — [`docs/GLOBE.md`](docs/GLOBE.md#intel-ftm-globe-layer) |
| **Docker MCP setup** | `.\scripts\setup-docker-mcp-worldbase.ps1` — fetch + database-server profile |
| Deploy Pi scripts | `.\scripts\deploy-pi-sync.ps1` — see `offgrid-raspi/docs/WORLDBASE_PI_SYNC.md` |
| Pi runtime data | `world.json` not in Git — `offgrid-raspi/offgrid/content/RUNTIME.md`; inline geo in `world.json` |

Unit tests (no network): `python -m unittest test_mcp_tools test_agent_bus test_connector_registry test_briefing_quality test_operator_briefing test_intel_briefing test_intel_subgraph test_intel_proximity test_prediction_ledger test_prediction_ground_truth test_corroboration_ground_truth test_newsdata_bridge test_ftm_store test_feed_ingest test_gdelt_bridge test_stac_feeds test_ais_bridge test_feed_envelope_contract test_chat_routing test_firewall_bridge test_prompt_guard test_cams_bridge test_fusion_snapshots -v` in `backend/`.

Ground-truth pilots (offline): `python corroboration_ground_truth.py --fixtures`, `python prediction_ground_truth.py --fixtures`; wrappers `.\scripts\corroboration-ground-truth-pilot.ps1`, `.\scripts\prediction-ground-truth-pilot.ps1`, `.\scripts\fusion-baseline-status.ps1`.

Live contract (opt-in, gated in smoke test §1 when `:8002` is up): `python -m unittest test_health_contract_live -v` — validates `/api/health` feed rows + curated envelope payloads (`cve`, `wildfires`, `gdacs`, …). Skips cleanly if API down.

Feed envelope contract: `backend/feeds/envelope.py` — shared validation for Phase 0/2; smoke test calls `test_health_contract_live`, not duplicated PowerShell logic.

On startup, `ais_bridge.start_aisstream_collector()` runs when `AISSTREAM_API_KEY` is set; `_stack_warmup()` (~6 s after boot) refreshes GDELT local pulse, traffic cams, maritime, CAMS haze, air quality, and Bangkok weather.

---

## Key files

| Area | Path |
|------|------|
| App shell + FULL SITUATION | `frontend/src/App.tsx` |
| Globe + layers + click-to-detail | `frontend/src/components/Globe.tsx`, `GlobeDetailModal.tsx`, `frontend/src/hooks/layers/` |
| FtM globe layer | `frontend/src/hooks/layers/useIntelLayer.ts` — toggle **INTEL** in telemetry |
| Agent Bus HUD | `frontend/src/hooks/useAgentBus.ts`, `frontend/src/lib/agentBus.ts` |
| Globe terrain fail-soft | `frontend/src/lib/cesiumTerrain.ts` |
| Traffic cams | `backend/traffic_bridge.py`, `useTrafficCamsLayer.ts`, `TrafficCamPanel.tsx` |
| Webcams → globe stream | `backend/webcam_bridge.py`, `WebcamSection.tsx`, `WebcamStreamPanel.tsx` |
| Credential registry | `backend/credentials/registry.py`, `GET /api/credentials/status` |
| HUD styles | `frontend/src/styles/hud.css` |
| Feeds + cache | `backend/feeds_extra.py`, `backend/feed_registry.py`, `backend/connector_registry.py`, `backend/feeds/envelope.py` |
| Node sync + briefing routes | `backend/node_sync.py`, `backend/briefing_quality.py`, `backend/trust_probes.py` |
| MCP + Agent Bus | `backend/mcp_server.py`, `backend/agent_bus.py`, [`docs/MCP.md`](docs/MCP.md) |
| Operator digest | `backend/operator_briefing.py` |
| FtM → 24h briefing | `backend/intel_briefing.py` |
| FtM subgraph (Track 3) | `backend/intel_subgraph.py` — `GET /api/intel/subgraph` |
| Spatial proximity (Track 3+) | `backend/intel_proximity.py` — `POST /api/intel/spatial/run`; runs after feed ingest when `WORLDBASE_INTEL_SPATIAL_EDGES=1` |
| Prediction ledger (Track 4) | `backend/prediction_ledger.py` |
| GDELT | `backend/gdelt_bridge.py` — adaptive backoff, region-first priority, stale-while-revalidate; local pulse persisted to `feed_cache` (`gdelt_pulse_local:{region}`) |
| CAMS haze | `backend/cams_bridge.py` — Open-Meteo/CAMS dust + AOD for Thailand/ASEAN cities |
| Humanitarian (HDX) | `backend/humanitarian_bridge.py` — CKAN search for Southeast Asia crises |
| NewsData headlines | `backend/newsdata_bridge.py` — optional API key; briefing + corroboration family |
| Ground-truth pilots | `backend/corroboration_ground_truth.py`, `backend/prediction_ground_truth.py` |
| Maritime AIS | `backend/ais_bridge.py` — persistent AISstream collector + MyShipTracking; Malacca / Laem Chabang / Bangkok / Phuket / Singapore when operator region is Thailand |
| Feed drift | `backend/feed_drift.py` — count snapshots + freshness in `/api/trust` |
| STAC (imagery + feeds) | `backend/stac_bridge.py` — Element84 search + connector feed ItemCollection (bbox, geometry, registry links) |
| Connector + feed status UI | `frontend/src/components/FeedsStatusPanel.tsx` — DATA → FEEDS: registry, STAC links, globe fly-to |
| Fusion → briefing | `backend/fusion_heatmap.py` |
| RAG | `backend/rag_memory.py` |
| FtM entity store | `backend/ftm_store.py` |
| Document intel ingest (GLiNER; GLiREL opt-in) | `backend/intel_ingest.py`, [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md), [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) |
| Entity resolution (exact + subset + optional Splink) | `backend/entity_resolution.py` — `POST /api/intel/resolution/run` |
| Live feed ingest (T2 YAML mappings) | `backend/feed_ingest.py`, `backend/ingest/mappings/` — `POST /api/intel/feeds/run` |
| INTEL graph panel | `frontend/src/components/IntelGraphPanel.tsx` |
| Pi edge dashboard (DATA → EDGE) | `frontend/src/components/EdgePanel.tsx` — primary node `offgrid-pi`, sparklines via `/api/node/{id}/sensors/history` |
| Edge online/offline banner | `frontend/src/components/NodeHealthBanner.tsx` |
| HAK_GAL firewall bridge (optional) | `backend/firewall_bridge.py`, `backend/prompt_guard.py`, `docs/FIREWALL.md` |
| DB | `backend/worldbase.db`, `backend/data/entities.duckdb` — FtM: single writer (one API process); `reset_store()` on DuckDB FATAL (B-02 light) |

---

## Conventions

- **Fail-soft feeds:** upstream errors → stale cache or `{ count: 0 }`, not HTTP 500.
- **UI language:** English labels/tooltips. Briefing *output* may be German via env.
- **Minimal diffs:** match existing HUD style (uppercase labels, vanilla CSS, no Tailwind).
- **Commits:** only when the user explicitly asks.
- **Local-only (never commit):** `.cursor/`, `briefs/`, `LLM_HANDOFF.md`, `progress.txt`, and other operator plans or LLM handoff notes. Public agent docs: `README.md` and this file only.

---

## Pi subtree

`offgrid-raspi/` is the OGN edge stack (LCD, world-sync, mesh). When changing Pi↔PC sync, touch both:

- PC: `backend/node_sync.py`, `scripts/deploy-pi-sync.ps1`
- Pi: `offgrid-raspi/scripts/worldbase_push.py`, `worldbase_pull.py`

Push reads:

- `$OFFGRID_CONTENT/telemetry/esp32_state.json` (canonical OGN path) — DHT/USB
- `/var/lib/offgrid/sensor_node.json` (fallback)
- `/var/lib/offgrid/mesh_state.json`
- `/var/lib/offgrid/gps_location.json`

Legacy `sensor_data.json` / `mesh_nodes.json` / `gps.json` are **not** used. See `worldbase_push.py` for the resolution order.

---

## Common failures

| Symptom | Likely fix |
|---------|------------|
| UI unreachable / Vite `ECONNREFUSED :8002` | Use `.\start.ps1` (backend warm-up before Vite); browser on **localhost:5176**; hard refresh after backend reload |
| Briefing empty | `POST /api/briefing/generate`; check Ollama |
| LOCAL block thin | GDELT rate limits; verify `/api/gdelt/pulse/local` (stale cache with `count>0` still counts for trust/quality); also `/api/cams/haze`, `/api/humanitarian`, `/api/airquality` in briefing snapshot |
| Maritime layer shows demo fleet | Set `AISSTREAM_API_KEY` in `backend/.env` and restart; expect `stream_connected=true` and `count` growing after ~30 s. Default regions: Malacca, Laem Chabang, Bangkok Port, Phuket, Singapore (`WORLDBASE_MARITIME_REGIONS=all` for global ports). Disable background collector: `WORLDBASE_MARITIME_AISSTREAM=0` |
| GDELT trust 0 after cold boot | Wait ~90 s for startup warm-up or `GET /api/gdelt/pulse/local`; disk cache `gdelt_pulse_local:thailand` hydrates trust probe |
| Pi old brief | deploy scripts + token; `brief.source` should be `worldbase-pc` |
| INTEL ingest 503 | optional ML stack not installed — see `docs/INTEL_INGEST.md` + `backend/requirements.txt` |
| API 500 / startup crash (DuckDB) | Only one process may open `entities.duckdb`; `ftm_store.init_store()` is fail-soft — check `GET /api/health` → `ftm.ready`. Do not test FtM via external CLI while stack runs. After `FATAL … invalidated`, restart backend (`.\start.ps1`). FtM read routes run on the event-loop thread (no `asyncio.to_thread`). |
| Paths break in PS | `-LiteralPath` for `D:\MCP Mods\worldbase` |
| Globe blank / terrain 503 | Ion CDN blip or stale Vite env — restart frontend; ellipsoid fallback in `cesiumTerrain.ts` |
| Webcam click shows text only | Old build — card must pass `webcam` ref to `focusOn`; expect **LIVE FEED** modal with iframe |
| Weather dot ≠ camera | Thailand coloured dots are **WEATHER** layer; traffic cams are Singapore only until iTIC |
| MCP tools missing in Cursor | Restart backend after `WORLDBASE_AGENT_BUS`; refresh Cursor MCP server |
| Agent Bus `delivered: 0` | HUD needs `VITE_WORLDBASE_AGENT_BUS=1` + open tab at `:5176` |
| INTEL layer count `—` | Toggle **INTEL** under telemetry (OSINT/FULL preset enables `intelFt`); wait ~2 s for FtM fetch |
| Splink resolution test fail | Optional — `pip install 'splink>=4.0,<5'` or ignore if not using Splink |
| Trust 2/4 in FULL SITUATION | Check `GET /api/trust` probes — GDELT ok with stale cache if `count>0`; Pi edge online; Ollama: `OLLAMA_HOST=127.0.0.1:11434` or `http://127.0.0.1:11434` (probe normalizes both) |
| Pi pull stale after PC upgrade | `.\scripts\deploy-pi-sync.ps1`; verify `payload_version: 2` in pull JSON |
| Pi push timeout storm | Deploy latest `worldbase_push.py` — exponential backoff + 45 s POST timeout; log `Ingest FAILED (streak=N) — backoff …` |
| Briefing generate timeout (PS) | Client `-TimeoutSec 600`; server may still finish — check `GET /api/briefing` → `created_at` |
| Firewall chat block / unreachable | `GET /api/firewall/status`; HAK_GAL on `:8001`; chat needs `firewall: true` + `chat_session_id`; see [`docs/FIREWALL.md`](docs/FIREWALL.md) |
