# Flowsint integration (WorldBase)

[Flowsint](https://github.com/reconurge/flowsint) is a graph-based OSINT platform (Neo4j, enrichers, investigations). WorldBase embeds it in the **OSINT** tab and probes health via `/api/flowsint/health`.

## Ports (do not confuse with WorldBase)

| Service | Port | Notes |
|---------|------|--------|
| WorldBase UI (Vite) | **5176** | `start.ps1` |
| WorldBase API | **8002** | FastAPI |
| Flowsint UI | **5173** | Docker `flowsint-app-prod` |
| Flowsint API | **5001** | Docker `flowsint-api-prod` |
| Neo4j browser | **7474** | Optional graph DB UI |

## Prerequisites

- Docker Desktop (Linux containers), WSL2 enabled
- Git
- ~8 GB free disk on **C:** (or move Docker disk image to D: — see `docs/DISK_MOVE_TO_D.md`)
- Disk space on D: for clone `worldbase/flowsint/` (gitignored)

## Install (Windows)

```powershell
cd "D:\MCP Mods\worldbase"
.\scripts\setup-flowsint.ps1
.\scripts\start-flowsint.ps1 -Build
```

First `-Build` can take 10–20 minutes.

1. Open http://localhost:5173 and **register** a local account.
2. Open WorldBase http://localhost:5176 → **OSINT** → **FLOWSINT GRAPH**.

## Configuration

| Variable | Where | Default |
|----------|-------|---------|
| `VITE_FLOWSINT_URL` | `frontend/.env` | `http://localhost:5173` |
| `FLOWSINT_URL` | `backend/.env` | `http://127.0.0.1:5173` |
| `FLOWSINT_API_URL` | `backend/.env` | `http://127.0.0.1:5001` |

Clone lives in `worldbase/flowsint/` (gitignored). Upstream: https://github.com/reconurge/flowsint

## WorldBase OSINT tab modes

| Mode | Purpose |
|------|---------|
| **QUICK TOOLS** | Built-in `/api/osint/*` (IP, domain, email, …) + globe pins |
| **FLOWSINT GRAPH** | Full Flowsint UI in iframe (investigations, enrichers) |

## Troubleshooting

**API container `exec ./entrypoint.sh: exec format error`:** The clone was checked out with Windows CRLF. Re-run `.\scripts\setup-flowsint.ps1` (normalizes `entrypoint.sh`) or convert manually, then `.\scripts\start-flowsint.ps1 -Build`.

## Stop / logs

```powershell
cd flowsint
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml logs -f api
```

## Pi / off-grid

Flowsint expects Docker + Neo4j + Postgres — **not** suitable for the 28 GB Pi root disk. Keep **OpenOSINT** on the Pi; run Flowsint on the **PC** alongside WorldBase.

## License

Flowsint is Apache-2.0. Use only for lawful, ethical investigation (see upstream README).
