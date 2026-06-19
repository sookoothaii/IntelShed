# WorldBase MCP Read Tools

Read-only [Model Context Protocol](https://modelcontextprotocol.io/) surface on the WorldBase FastAPI backend. Lets Cursor, Claude Desktop, or other MCP clients query briefing, Pi nodes, situations, and feed samples **without** scraping the HUD or opening the globe.

Transport: **Streamable HTTP** at `http://127.0.0.1:8002/api/mcp` (same host as the API).

Globe camera control (Agent Bus) is **not** included — see roadmap Phase 2.

---

## Enable / disable

| Env | Default | Effect |
|-----|---------|--------|
| `WORLDBASE_MCP` | `1` | Mount MCP at `/api/mcp` on startup |
| `WORLDBASE_API_KEY` | empty | When set, MCP requires header `X-API-Key` |
| `WORLDBASE_BIND_HOST` | `127.0.0.1` | If bound to LAN (`0.0.0.0`) without API key, MCP auth is **required** |

Install dependency (once):

```powershell
pip install "mcp>=1.27,<2"
```

Restart backend after changes. Startup log should show:

```text
[MCP] Read tools mounted at /api/mcp (open (localhost, no API key))
```

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

---

## Tools

| Tool | Purpose |
|------|---------|
| `worldbase_health` | Liveness, FtM ready flag, feed cache count |
| `worldbase_briefing_latest` | Latest 24h briefing digest + text preview |
| `worldbase_nodes` | Pi / edge nodes (online, GPS, sensors) |
| `worldbase_situations` | Unified situation board (limit param, default 20) |
| `worldbase_fusion_hotspots` | Top fusion heatmap cells |
| `worldbase_feed_sample` | Allowlisted feed sample (`feed_id`, `limit`) |
| `worldbase_feed_allowlist` | Valid `feed_id` values for feed sample |

### Feed allowlist

`worldbase_feed_sample` only accepts: `aircraft`, `airquality`, `earthquakes`, `eonet`, `gdacs`, `gdacs_v2`, `geopolitics`, `markets`, `military`, `outages`, `pegel`, `reliefweb`, `spaceweather`, `wildfires`, `energy_de`.

Reads `feed_cache` first; falls back to live bridge fetch for a subset when cache is empty.

---

## Tests

From `backend/` (no network for unit tests):

```powershell
python -m unittest test_mcp_tools -v
```

---

## Implementation

- Module: `backend/mcp_server.py`
- Reuses the same Python paths as `chat_tools.py` and REST routes (no HTTP loopback).
- Write tools (`generate_briefing`, globe control) are Phase 2+.

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
