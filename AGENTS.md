# AGENTS.md — WorldBase (PC stack)

> For AI coding agents. Operator docs: [`README.md`](README.md). Deep reference: [`LLM_HANDOFF.md`](LLM_HANDOFF.md). Pi edge: [`offgrid-raspi/AGENTS.md`](offgrid-raspi/AGENTS.md).

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
| **Verify** | `.\scripts\smoke-test.ps1` | 25 checks — run before claiming “done” |

Copy env: `backend\.env.example` → `backend\.env`, `frontend\.env.example` → `frontend\.env` (Cesium Ion token required for terrain/buildings).

---

## Current work focus (default)

Unless the user says otherwise, prioritize:

1. **24h security digest** — `backend/operator_briefing.py` + `backend/node_sync.py`
2. **Operator home region** — `WORLDBASE_OPERATOR_REGION=thailand` (LOCAL / REGION / GLOBAL buckets)
3. **GDELT local** — `backend/gdelt_bridge.py` → `/api/gdelt/pulse/local`, `/api/gdelt/geo/local`
4. **Pi pull loop** — PC generates briefing → Pi `GET /api/node/pull` → portal `briefing_latest.json`
5. **Intelligence UX** — FULL SITUATION overlay, SITUATIONS board, fusion hotspots in briefing, DATA → INTEL graph (GLiNER ingest)

**Out of scope by default:** HAK_GAL LLM firewall (`FIREWALL_HOST`, `:8001`, firewall tab/chat toggle). Code stays; do not start, fix, or extend unless explicitly requested.

---

## Briefing pipeline

```
_gather_snapshot()  →  format_digest_sections()  →  Ollama prompt  →  SQLite briefings
                              ↑
                    gdelt_pulse_local, airquality, quakes, hazards, fusion top-3
```

| Action | Endpoint / file |
|--------|-----------------|
| Latest text | `GET /api/briefing` |
| Force generate | `POST /api/briefing/generate` |
| Autopilot | `WORLDBASE_BRIEFING_AUTOPILOT=1`, interval `WORLDBASE_BRIEFING_INTERVAL` (default 6 h) |
| German output | `WORLDBASE_BRIEFING_LANG=de` (UI strings stay English) |
| Pi payload | `GET /api/node/pull` (+ `X-Node-Token` when `NODE_INGEST_TOKEN` set) |
| Deploy Pi scripts | `.\scripts\deploy-pi-sync.ps1` — see `offgrid-raspi/docs/WORLDBASE_PI_SYNC.md` |

Unit tests (no network): `python -m unittest test_operator_briefing -v` in `backend/`.

---

## Key files

| Area | Path |
|------|------|
| App shell + FULL SITUATION | `frontend/src/App.tsx` |
| Globe + layers | `frontend/src/components/Globe.tsx`, `frontend/src/hooks/layers/` |
| HUD styles | `frontend/src/styles/hud.css` |
| Feeds + cache | `backend/feeds_extra.py`, `backend/feed_registry.py` |
| Node sync + briefing routes | `backend/node_sync.py` |
| Operator digest | `backend/operator_briefing.py` |
| GDELT | `backend/gdelt_bridge.py` |
| Fusion → briefing | `backend/fusion_heatmap.py` |
| RAG | `backend/rag_memory.py` |
| FtM entity store | `backend/ftm_store.py` |
| Document intel ingest (GLiNER; GLiREL opt-in) | `backend/intel_ingest.py`, [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md), [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) |
| INTEL graph panel | `frontend/src/components/IntelGraphPanel.tsx` |
| DB | `backend/worldbase.db`, `backend/data/entities.duckdb` |

---

## Conventions

- **Fail-soft feeds:** upstream errors → stale cache or `{ count: 0 }`, not HTTP 500.
- **UI language:** English labels/tooltips (see `.cursor/rules/english-only.mdc`). Briefing *output* may be German via env.
- **Minimal diffs:** match existing HUD style (uppercase labels, vanilla CSS, no Tailwind).
- **Commits:** only when the user explicitly asks.
- **Do not** edit `LLM_HANDOFF.md` unless the user requests doc updates.

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
| Paths break in PS | `-LiteralPath` for `D:\MCP Mods\worldbase` |

Full table: [`LLM_HANDOFF.md`](LLM_HANDOFF.md) → “If Something Breaks”.
