# WorldBase MCP Tools

[Model Context Protocol](https://modelcontextprotocol.io/) surface on the WorldBase FastAPI backend. Lets Cursor, Claude Desktop, or other MCP clients query briefing, Pi nodes, situations, and feed samples **without** scraping the HUD — and trigger a new 24h briefing via write tools.

Transport: **Streamable HTTP** at `http://127.0.0.1:8002/api/mcp` (same host as the API).

**Tool count (typical):** 8 read + 1 write (`worldbase_briefing_generate`) + 4 globe (when Agent Bus enabled) = **13 tools**.

Globe camera control uses the **Agent Bus** when enabled — see [Agent Bus](#agent-bus) below. FtM entities on the globe (**INTEL** layer) are a separate HUD feature — see [`docs/GLOBE.md`](GLOBE.md#intel-ftm-globe-layer).

---

## Enable / disable

| Env | Default | Effect |
|-----|---------|--------|
| `WORLDBASE_MCP` | `1` | Mount MCP at `/api/mcp` on startup |
| `WORLDBASE_MCP_WRITE` | `1` | Register `worldbase_briefing_generate` write tool |
| `WORLDBASE_AGENT_BUS` | `0` | Globe MCP tools + `/api/agent/*` (requires HUD subscriber) |
| `WORLDBASE_API_KEY` | empty | When set, MCP requires header `X-API-Key` |
| `WORLDBASE_BIND_HOST` | `127.0.0.1` | If bound to LAN (`0.0.0.0`) without API key, MCP auth is **required** |

Install dependency (once):

```powershell
pip install "mcp>=1.27,<2"
```

Restart backend after changes. Startup log should show:

```text
[MCP] Tools mounted at /api/mcp (X-API-Key required; write on; globe on)
```

(`globe off` when `WORLDBASE_AGENT_BUS=0` — globe MCP tools are not registered.)

---

## Cursor configuration

Add to your user or project MCP config (`.cursor/mcp.json` or Cursor Settings → MCP):

```json
{
  "mcpServers": {
    "worldbase": {
      "url": "http://127.0.0.1:8002/api/mcp",
      "headers": {
        "X-API-Key": "your-WORLDBASE_API_KEY-if-set"
      }
    }
  }
}
```

Omit the `headers` block when `WORLDBASE_API_KEY` is unset and the API binds to localhost only.

**After backend env changes** (especially `WORLDBASE_AGENT_BUS`): restart backend, then **restart or refresh Cursor MCP** so new tools appear in the tool list (e.g. `worldbase_globe_fly_to`).

---

## Tools

### Read

| Tool | Purpose |
|------|---------|
| `worldbase_health` | Liveness, FtM ready flag, feed cache count |
| `worldbase_briefing_latest` | Latest 24h briefing digest + text preview |
| `worldbase_nodes` | Pi / edge nodes (online, GPS, sensors) |
| `worldbase_situations` | Unified situation board (limit param, default 20) |
| `worldbase_fusion_hotspots` | Top fusion heatmap cells |
| `worldbase_intel_subgraph` | 2-hop FtM subgraph around operator bbox (`hops`, optional `bbox`, `window_hours`) |
| `worldbase_feed_sample` | Allowlisted feed sample (`feed_id`, `limit`) |
| `worldbase_feed_allowlist` | Valid `feed_id` values for feed sample |

### Write (`WORLDBASE_MCP_WRITE=1`)

| Tool | Purpose |
|------|---------|
| `worldbase_briefing_generate` | Run full 24h briefing pipeline (Ollama → SQLite). Optional `lang` (`en` / `de`), `include_full_text` |

Same auth gate as `/api/chat` and `POST /api/briefing/generate`: when `WORLDBASE_API_KEY` is set, MCP requests need `X-API-Key`. Generation takes 30–90 s (Ollama + feed fusion); prefer `worldbase_briefing_latest` for quick reads.

### Globe (`WORLDBASE_AGENT_BUS=1` + `VITE_WORLDBASE_AGENT_BUS=1`)

Requires an **open HUD tab** at `:5176` on the same machine. MCP/API publishes actions; the browser stream executes them.

| Tool | Purpose |
|------|---------|
| `worldbase_globe_fly_to` | Fly globe to `lat`, `lon`, optional `height`, `title` |
| `worldbase_globe_toggle_layer` | Show/hide a feed layer (`layer`, optional `enabled`) |
| `worldbase_globe_get_camera` | Last camera position synced from HUD |
| `worldbase_globe_layers` | Valid `layer` keys for toggle |

REST equivalents: `POST /api/agent/publish`, `GET /api/agent/stream` (SSE), `POST /api/agent/camera`.

---

### Feed allowlist

`worldbase_feed_sample` only accepts: `aircraft`, `airquality`, `earthquakes`, `eonet`, `gdacs`, `gdacs_v2`, `geopolitics`, `markets`, `military`, `outages`, `pegel`, `reliefweb`, `spaceweather`, `wildfires`, `energy_de`.

Reads `feed_cache` first; falls back to live bridge fetch for a subset when cache is empty.

---

## Agent Bus

Backend module: `backend/agent_bus.py`. In-memory pub/sub for a **single operator session** (no Redis).

```
MCP worldbase_globe_fly_to / REST POST /api/agent/publish
  → SSE GET /api/agent/stream (browser fetch + X-API-Key)
  → App.tsx useAgentBus → focusOnMap / layer toggle on Globe
```

Enable both sides:

```env
# backend/.env
WORLDBASE_AGENT_BUS=1

# frontend/.env
VITE_WORLDBASE_AGENT_BUS=1
```

Restart backend and Vite after changes. MCP globe tools register only when `WORLDBASE_AGENT_BUS=1`.

### REST API (same bus)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/api/agent/status` | open | `enabled`, subscriber count, layer keys |
| POST | `/api/agent/publish` | `X-API-Key` when set | Publish `fly_to` or `toggle_layer` |
| GET | `/api/agent/stream` | `X-API-Key` when set | SSE stream (HUD subscribes via `fetch`) |
| POST | `/api/agent/camera` | open | HUD posts camera position (debounced) |
| GET | `/api/agent/camera` | `X-API-Key` when set | Last synced camera for MCP read |

**Publish example** (PowerShell, with API key in `backend/.env`):

```powershell
$h = @{ 'X-API-Key' = 'your-key'; 'Content-Type' = 'application/json' }
$body = '{"action":"fly_to","lat":9.55,"lon":100.05,"height":400000,"title":"Koh Samui"}'
Invoke-RestMethod -Method POST -Uri 'http://127.0.0.1:8002/api/agent/publish' -Headers $h -Body $body
```

Expect `delivered` ≥ 1 when a HUD tab at `:5176` has `VITE_WORLDBASE_AGENT_BUS=1`.

---

## Tests

From `backend/` (no network for unit tests):

```powershell
python -m unittest test_mcp_tools test_agent_bus -v
```

| Module | Covers |
|--------|--------|
| `test_mcp_tools.py` | MCP helpers, auth gates, briefing generate mock |
| `test_agent_bus.py` | Publish validation, layer keys, disabled → 503 |

Live MCP checks: use Cursor `worldbase` server or `GET /api/health/ping` before calling tools.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| Cursor shows 7 tools, not 12 | Agent Bus off or stale MCP cache | Set `WORLDBASE_AGENT_BUS=1`, restart backend, refresh Cursor MCP |
| `worldbase_briefing_generate` timeout | Ollama slow (30–90 s normal) | Wait; use `worldbase_briefing_latest` for reads |
| MCP / chat 401 | `WORLDBASE_API_KEY` set | Add `X-API-Key` in Cursor MCP config + `VITE_WORLDBASE_API_KEY` in `frontend/.env` |
| Agent publish `delivered: 0` | No HUD subscriber | Open `:5176`, set `VITE_WORLDBASE_AGENT_BUS=1`, restart Vite |
| Agent stream 503 | `WORLDBASE_AGENT_BUS=0` | Enable in `backend/.env`, restart backend |
| `ftm_ready: false` in MCP | DuckDB lock (second process) | One backend only; check `GET /api/health` → `ftm.ready` |

---

## Implementation

| Area | Path |
|------|------|
| MCP server | `backend/mcp_server.py` |
| Agent Bus | `backend/agent_bus.py` |
| HUD subscriber | `frontend/src/hooks/useAgentBus.ts` |
| Globe layer listener | `frontend/src/components/Globe.tsx`, `frontend/src/lib/agentBus.ts` |

- Reuses the same Python paths as `chat_tools.py` and REST routes (no HTTP loopback).
- Write path calls `node_sync.generate_briefing_internal()` — same as autopilot and `POST /api/briefing/generate`.
- Globe control: publish → stream → `focusOnMap` / layer toggle when Agent Bus enabled.

---

## Docker MCP Gateway (MCP_DOCKER)

Use Docker MCP Toolkit profile **`ai_coding`** alongside the native **`worldbase`** HTTP server. They complement each other:

| Source | Role |
|--------|------|
| **`worldbase`** (`/api/mcp`) | Briefing, Pi nodes, situations, fusion, feed samples (structured, auth-aware) |
| **`MCP_DOCKER`** | `fetch` (external URLs + `host.docker.internal:8002`), `database-server` (SQL / NL queries on synced DB) |
| **`filesystem_mcp`** | Direct host `db_query` on `backend/worldbase.db` (no container volume) |

### One-time setup

From repo root:

```powershell
.\scripts\setup-docker-mcp-worldbase.ps1
```

This script:

1. Copies `backend/worldbase.db` into Docker volumes `worldbase-mcp-data` and `mcp-sqlite`
2. Imports `docker/mcp/ai_coding-worldbase.profile.yaml` (adds **`fetch`** + **`database-server`** with read-only volume)
3. Pre-pulls MCP images

**Restart Cursor** after setup so `MCP_DOCKER` reloads the profile.

Re-run the script after major DB changes to refresh the Docker copy (read-only snapshot).

### Profile contents

| Server | Tools | Notes |
|--------|-------|-------|
| `fetch` | `fetch` | USGS, GDACS, ReliefWeb, public API paths via `host.docker.internal` |
| `database-server` | `list_tables`, `execute_sql`, `query_database`, … | SQLite at `/data/worldbase.db` inside container |
| `context7`, `sequentialthinking` | (existing) | Unchanged from default `ai_coding` template |

The catalog **`SQLite`** image (`mcp/sqlite`) is **not** included — published entrypoint fails on current images. Use `database-server` or `filesystem_mcp` `db_query` instead.

### Ops snapshot (code-mode)

Extended fetch script: `docker/mcp/ops-snapshot.js`

Register once per Cursor session (or after MCP gateway restart):

```text
MCP_DOCKER → code-mode
  name: ops-snapshot
  servers: ["fetch"]
  script: <contents of docker/mcp/ops-snapshot.js>
```

Run:

```text
MCP_DOCKER → mcp-exec → code-mode-ops-snapshot
```

Combines WorldBase health ping (via Docker → host), USGS M2.5+ feed, GDACS earthquake + flood lists. Pair with `worldbase_briefing_latest` and `worldbase_fusion_hotspots` for full ops picture.

(ReliefWeb API blocks autonomous MCP fetch — use `worldbase_feed_sample` feed_id=`reliefweb` instead.)

### Host SQL (filesystem_mcp)

No Docker volume required:

```text
filesystem_mcp → db_query
  db_type: sqlite
  connection_string: D:/MCP Mods/worldbase/backend/worldbase.db
  query: SELECT created_at FROM briefings ORDER BY id DESC LIMIT 3
```

### Files

| Path | Purpose |
|------|---------|
| `docker/mcp/ai_coding-worldbase.profile.yaml` | Exportable Docker MCP profile |
| `docker/mcp/ops-snapshot.js` | code-mode fetch bundle |
| `scripts/setup-docker-mcp-worldbase.ps1` | Volume sync + profile import |

---

## Optional firewall (MCP write tools — Phase B)

**Baseline (always, 0 VRAM):** `prompt_guard.slim_prompt_scan` on MCP write tools (`WORLDBASE_SLIM_GUARD_MCP=1` default).

**Optional enrichment:** when `FIREWALL_HOST` and `WORLDBASE_FIREWALL_MCP=1` are set, write tools get a second pass via HAK_GAL `/v1/detect`. **Fail-open** if HAK_GAL is down (unless `WORLDBASE_FIREWALL_MCP_FAIL_CLOSED=1`).

Gated tools: `worldbase_briefing_generate`, `worldbase_globe_fly_to`, `worldbase_globe_toggle_layer`. Read tools unchanged.

HAK_GAL full stack is **not** a hard dependency — see [`docs/FIREWALL.md`](FIREWALL.md) and `research/HAK_GAL_PICK_LIST.md`.
