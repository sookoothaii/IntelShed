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
| **Start** | `.\start.ps1` | Paths with spaces → `-LiteralPath` |
| **Verify** | `.\scripts\smoke-test.ps1` | 29 checks — run before claiming “done” |

Copy env: `backend\.env.example` → `backend\.env`, `frontend\.env.example` → `frontend\.env` (Cesium Ion token required for terrain/buildings).

---

## Current work focus (default)

Unless the user says otherwise, prioritize:

1. **24h security digest** — `backend/operator_briefing.py` + `backend/node_sync.py`
2. **Operator home region** — `WORLDBASE_OPERATOR_REGION=thailand` (LOCAL / REGION / GLOBAL buckets)
3. **GDELT local** — `backend/gdelt_bridge.py` → `/api/gdelt/pulse/local`, `/api/gdelt/geo/local`
4. **Pi pull loop** — PC generates briefing → Pi `GET /api/node/pull` → portal `briefing_latest.json`
5. **Intelligence UX** — FULL SITUATION overlay, SITUATIONS board, fusion hotspots in briefing, DATA → INTEL (ingest, feed sync, Splink resolution, Cytoscape overview)

**Out of scope by default:** HAK_GAL LLM firewall (`FIREWALL_HOST`, `:8001`, firewall tab/chat toggle). Code stays; do not start, fix, or extend unless explicitly requested.

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
| Latest text | `GET /api/briefing` — text, `digest`, `intel`, `quality`, `fusion_hotspots` |
| Force generate | `POST /api/briefing/generate` |
| FtM → digest bridge | `backend/intel_briefing.py` |
| Autopilot | `WORLDBASE_BRIEFING_AUTOPILOT=1`, interval `WORLDBASE_BRIEFING_INTERVAL` (default 6 h) |
| FtM in digest | `WORLDBASE_BRIEFING_INTEL=1` (default), excludes `Airplane` by default |
| German output | `WORLDBASE_BRIEFING_LANG=de` (UI strings stay English) |
| Pi payload | `GET /api/node/pull` — v2: ETag/304, SHA-256, quality (+ `X-Node-Token` when set) |
| **Trust probes** | `GET /api/trust` — field score 0–4 (briefing, GDELT, Ollama, Pi edge) |
| **Connectors** | `GET /api/connectors` — manifest catalog + cache overlay; export via `scripts/export_connectors.py` |
| **MCP (Cursor)** | Streamable HTTP `http://127.0.0.1:8002/api/mcp` — 12 tools when Agent Bus on — [`docs/MCP.md`](docs/MCP.md) |
| **Agent Bus** | `POST /api/agent/publish`, `GET /api/agent/stream` — globe fly/layer when HUD open — [`docs/MCP.md`](docs/MCP.md#agent-bus) |
| **FtM globe layer** | `GET /api/intel/entities?geolocated=1` → HUD **INTEL** toggle (`intelFt`) — [`docs/GLOBE.md`](docs/GLOBE.md#intel-ftm-globe-layer) |
| **Docker MCP setup** | `.\scripts\setup-docker-mcp-worldbase.ps1` — fetch + database-server profile |
| Deploy Pi scripts | `.\scripts\deploy-pi-sync.ps1` — see `offgrid-raspi/docs/WORLDBASE_PI_SYNC.md` |
| Pi runtime data | `world.json` not in Git — `offgrid-raspi/offgrid/content/RUNTIME.md`; inline geo in `world.json` |

Unit tests (no network): `python -m unittest test_mcp_tools test_agent_bus test_connector_registry test_briefing_quality test_operator_briefing test_intel_briefing test_ftm_store test_feed_ingest -v` in `backend/`.

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
| Feeds + cache | `backend/feeds_extra.py`, `backend/feed_registry.py`, `backend/connector_registry.py` |
| Node sync + briefing routes | `backend/node_sync.py`, `backend/briefing_quality.py`, `backend/trust_probes.py` |
| MCP + Agent Bus | `backend/mcp_server.py`, `backend/agent_bus.py`, [`docs/MCP.md`](docs/MCP.md) |
| Operator digest | `backend/operator_briefing.py` |
| FtM → 24h briefing | `backend/intel_briefing.py` |
| GDELT | `backend/gdelt_bridge.py` |
| Fusion → briefing | `backend/fusion_heatmap.py` |
| RAG | `backend/rag_memory.py` |
| FtM entity store | `backend/ftm_store.py` |
| Document intel ingest (GLiNER; GLiREL opt-in) | `backend/intel_ingest.py`, [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md), [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) |
| Entity resolution (exact + subset + optional Splink) | `backend/entity_resolution.py` — `POST /api/intel/resolution/run` |
| Live feed ingest (T2 YAML mappings) | `backend/feed_ingest.py`, `backend/ingest/mappings/` — `POST /api/intel/feeds/run` |
| INTEL graph panel | `frontend/src/components/IntelGraphPanel.tsx` |
| Pi edge dashboard (DATA → EDGE) | `frontend/src/components/EdgePanel.tsx` — primary node `offgrid-pi`, sparklines via `/api/node/{id}/sensors/history` |
| Edge online/offline banner | `frontend/src/components/NodeHealthBanner.tsx` |
| DB | `backend/worldbase.db`, `backend/data/entities.duckdb` |

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
| UI unreachable | `.\start.ps1`; browser on **localhost:5176** |
| Briefing empty | `POST /api/briefing/generate`; check Ollama |
| LOCAL block thin | GDELT rate limits; verify `/api/gdelt/pulse/local` |
| Pi old brief | deploy scripts + token; `brief.source` should be `worldbase-pc` |
| INTEL ingest 503 | optional ML stack not installed — see `docs/INTEL_INGEST.md` + `backend/requirements.txt` |
| API 500 / startup crash (DuckDB) | Only one process may open `entities.duckdb`; `ftm_store.init_store()` is fail-soft — check `GET /api/health` → `ftm.ready` |
| Paths break in PS | `-LiteralPath` for `D:\MCP Mods\worldbase` |
| Globe blank / terrain 503 | Ion CDN blip or stale Vite env — restart frontend; ellipsoid fallback in `cesiumTerrain.ts` |
| Webcam click shows text only | Old build — card must pass `webcam` ref to `focusOn`; expect **LIVE FEED** modal with iframe |
| Weather dot ≠ camera | Thailand coloured dots are **WEATHER** layer; traffic cams are Singapore only until iTIC |
| MCP tools missing in Cursor | Restart backend after `WORLDBASE_AGENT_BUS`; refresh Cursor MCP server |
| Agent Bus `delivered: 0` | HUD needs `VITE_WORLDBASE_AGENT_BUS=1` + open tab at `:5176` |
| INTEL layer count `—` | Toggle **INTEL** under telemetry (OSINT/FULL preset enables `intelFt`); wait ~2 s for FtM fetch |
| Splink resolution test fail | Optional — `pip install 'splink>=4.0,<5'` or ignore if not using Splink |
| Trust 2/4 in FULL SITUATION | Normal when GDELT probe or Pi edge offline — check `GET /api/trust` probes |
| Pi pull stale after PC upgrade | `.\scripts\deploy-pi-sync.ps1`; verify `payload_version: 2` in pull JSON |
