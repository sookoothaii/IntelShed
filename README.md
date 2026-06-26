# WorldBase

![MIT](https://img.shields.io/badge/License-MIT-green?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black)
![Cesium](https://img.shields.io/badge/Cesium-1.142-6CADDF?style=flat-square)
![Ollama](https://img.shields.io/badge/LLM-Ollama%20qwen3-black?style=flat-square)
![NVIDIA NIM](https://img.shields.io/badge/LLM-NVIDIA%20NIM%20step--3.7--flash-76B900?style=flat-square&logo=nvidia&logoColor=white)

**Spatial intelligence workstation** — live OSINT feeds on a Cesium globe, fusion analytics, and local AI chat.

WorldBase is a thin integration layer: almost everything here rests on libraries, datasets, and tools that other people built and shared. We are grateful to every maintainer whose work makes this project possible.

`FastAPI` · `React` · `Vite` · `SQLite` · `Ollama` · `NVIDIA NIM` · optional `Pi` edge sync

WorldBase is the **PC stack**. It extends the off-grid Pi workshop ([`offgrid-raspi`](https://github.com/sookoothaii/offgrid-raspi)) with heavy fusion, a 24h security briefing, and globe UX. Run WorldBase alone on a PC, or **Pi + PC together** via push/pull sync (see below).

---

## At a glance

| | |
|---|---|
| **Globe** | 30+ live layers — aircraft, quakes, disasters, energy, maritime, transit |
| **MAP** | Offline Protomaps via PMTiles — regional (`thailand`) or full planet (`planet_full` ~130 GB) |
| **Intelligence** | Situations, FtM entity graph (INTEL globe layer), OpenSanctions via Yente, hybrid RAG (sqlite-vec + FTS5 + RRF + optional BGE rerank) |
| **Briefing** | 24h security digest (LOCAL / REGION / GLOBAL), watch items, prediction ledger, **agentic loop** (coverage → RAG retrieve → corroboration) |
| **NEWS** | HUD **NEWS** tab — NewsData + GDELT local/global headline feed |
| **Dark Web** | Passive `.onion` OSINT (Ahmia, DarkSearch, optional Tor engines) → entity matching, FtM `Mention` ingest, DARK WEB panel |
| **Ransomware Intel** | Ransomware.live + RansomLook leak-site monitoring → FtM `Event` mapping, briefing block, watch items |
| **Telegram SOCMINT** | Allow-listed public channels → SEA scoring, FtM `Event`/`Mention` ingest, DATA → TELEGRAM panel |
| **Satellite CD (K4)** | Sentinel-2 L2A COG window-read — NDVI/NDWI change detection, GeoJSON anomaly polygons, DATA → SATELLITE panel |
| **Maritime Anomaly (P7)** | AIS trajectory storage + behavioural anomaly detection (speed variance, AIS gaps, night port visits, risk zone proximity) |
| **Entity Resolution** | Per-dataset dedupe → cross-dataset link (Splink), dual-pipeline (batch train + predict), human-in-the-loop labelling |
| **Multi-Agent (P3+)** | 5-agent orchestrator (Coverage → Retrieval → Spatial → Corroboration → Synthesis), rule-based dispatcher, 0 VRAM |
| **Track R** | **R0 + R1.1–R1.4 shipped** — rerank, spatial bbox, CRAG-lite chat, adaptive YAML chunking, briefing agentic loop — [`docs/RAG_OSINT_ROADMAP.md`](docs/RAG_OSINT_ROADMAP.md) |
| **Connectors** | Manifest registry + cache overlay — `GET /api/connectors`, DATA → **FEEDS**, STAC feed items |
| **AI** | Local chat via Ollama (`qwen3:8b` default); 6 providers incl. NVIDIA NIM (`stepfun-ai/step-3.7-flash`); spatial reasoning tool for "within X km of Y" queries; **query-aware context enrichment** — extracts entities from user query → filters live feeds → injects relevant data + synthesis directive; **3-layer anti-hallucination stack** — positive prompt protocol (RAW DATA INTERPRETER), NIM-specific parameter tweaks (temp 0.15, top_p 0.4), post-generation Claim Auditor (source/URL/timestamp verification against context blocks, 0 VRAM) |
| **Edge** | Off-grid Pi pushes sensors → PC fuses → hardened briefing pull back to Pi |
| **Trust** | Rule-based briefing quality + field trust score (FULL SITUATION panel; feed drift + connector provenance) |
| **Thailand operator** | CAMS haze, HDX humanitarian, GDELT local, maritime Malacca corridor — enriched LOCAL/REGION briefing blocks |
| **MCP** | Cursor/Claude: **13 tools** — briefing, nodes, feeds, generate, optional globe control — [`docs/MCP.md`](docs/MCP.md) |
| **Agent Bus** | MCP/REST → fly globe + toggle layers when HUD open at `:5176` |
| **Philosophy** | Positive intelligence — better decisions, not attacks |

---

## Quick start

**Prerequisites:** Python 3.11+, Node.js 18+, [Ollama](https://ollama.com/) (`qwen3:8b`, `nomic-embed-text`), free [Cesium Ion](https://ion.cesium.com/tokens) token. Optional: [NVIDIA NIM API key](https://build.nvidia.com/) for cloud reasoning models (free tier incl. `stepfun-ai/step-3.7-flash`). Windows: use `-LiteralPath` when the clone path contains spaces.

### Native (development)

```powershell
git clone https://github.com/sookoothaii/worldbase.git
cd worldbase
git submodule update --init --recursive   # Pi sync scripts in offgrid-raspi/
copy backend\.env.example backend\.env    # optional keys; see GET /api/credentials/status
copy frontend\.env.example frontend\.env  # required: VITE_CESIUM_ION_TOKEN
pip install -r backend\requirements.txt
.\start.ps1
```

| Service | URL |
|---------|-----|
| **UI** | http://localhost:5176 |
| **API** | http://localhost:8002/docs |
| **Health** | http://localhost:8002/api/health |
| **Health (fast)** | http://localhost:8002/api/health/ping |
| **Ollama** | http://127.0.0.1:11434 |

Open **http://localhost:5176** (Vite; binds `127.0.0.1` to avoid IPv6-only fallback). API docs: **http://127.0.0.1:8002/docs**.

### MCP + Agent Bus (optional)

For Cursor / Claude automation — full guide: [`docs/MCP.md`](docs/MCP.md).

```powershell
# backend/.env
WORLDBASE_MCP=1
WORLDBASE_MCP_WRITE=1
WORLDBASE_AGENT_BUS=1          # globe fly_to / layer toggle via MCP

# frontend/.env
VITE_WORLDBASE_AGENT_BUS=1     # HUD must be open at :5176
```

Restart backend + Vite; add `worldbase` to Cursor MCP (`http://127.0.0.1:8002/api/mcp` + `X-API-Key` if set). Expect **13 tools** when Agent Bus is on.

```powershell
ollama pull qwen3:8b
ollama pull nomic-embed-text   # RAG embeddings
# Optional Track R reranker (CPU):
pip install sentence-transformers   # when RAG_RERANK=1 in backend/.env
```

**Verify stack:** `.\scripts\smoke-test.ps1` → expect **33 PASS / 0 FAIL / 1 WARN** (health, credentials, connectors, trust probes, live feed envelope contract, STAC, satellite health, Vite proxy, Ollama chat, frontend build). The WARN is the expected intel-ingest auth gate when no API key is set for that check.

`.\start.ps1` waits for `GET /api/health/ping` before starting Vite (avoids proxy `ECONNREFUSED`). ~**6 s** after backend boot, a feed warm-up refreshes GDELT local + **global** pulse, traffic cams, maritime, CAMS haze, air quality, and Bangkok weather.

### Optional: slim prompt guard (no HAK_GAL required)

A small regex layer (`backend/prompt_guard.py`, 0 VRAM) may reduce obvious abuse on **MCP write tools** and on **chat** when the 🛡️ toggle is on. It is **not** a substitute for API keys or network isolation, and it does not change briefing quality or trust scores.

HAK_GAL on port `:8001` is an **optional** second opinion when a lean orchestrator happens to be running — full stack alongside Ollama on 16 GB VRAM is assumed unreliable unless you measure otherwise. Details → [`docs/FIREWALL.md`](docs/FIREWALL.md).

```env
# backend/.env — defaults; slim guard on without FIREWALL_HOST
WORLDBASE_SLIM_GUARD=1
WORLDBASE_SLIM_GUARD_MCP=1
```

HUD: chat 🛡️ toggle (optional slim guard) · API: `GET /api/firewall/status`, `GET /api/firewall/history` · top-level nav: **NEWS** tab (headlines)

### Optional: live maritime AIS (Thailand corridor)

Free key at [aisstream.io](https://aisstream.io) → `backend/.env`:

```env
AISSTREAM_API_KEY=your-key
# WORLDBASE_MARITIME_AISSTREAM=1          # background WebSocket collector (default on when key set)
# WORLDBASE_MARITIME_COLLECT_SEC=30       # one-shot snapshot when collector off
# WORLDBASE_MARITIME_STREAM_STALE_SEC=1800
# WORLDBASE_MARITIME_MAX_VESSELS=800
# WORLDBASE_MARITIME_REGIONS=malacca,laem_chabang,bangkok_port,phuket,singapore  # default when WORLDBASE_OPERATOR_REGION=thailand
```

Restart backend. The API reads a **background AISstream buffer** (non-blocking); JSON includes `stream_connected` and `stream_buffer`. Without the key, `/api/maritime` falls back to MyShipTracking or demo fleet.

**STAC feed items:** `GET /api/stac/feeds/items` exposes connector snapshots with bbox/geometry and registry links. In the HUD: **DATA → FEEDS** — STAC JSON link and ⊕ fly-to per connector.

### Optional: Dark Web / Darknet OSINT (no extra keys)

Passive `.onion` search via clearnet APIs — no Tor relay required for the default engines.

```env
WORLDBASE_DARKWEB=1
WORLDBASE_DARKWEB_ENGINES=ahmia,darksearch
WORLDBASE_BRIEFING_DARKWEB=1
# Optional: route .onion requests through a local Tor SOCKS5 proxy
# WORLDBASE_DARKWEB_TOR_PROXY=socks5://127.0.0.1:9050
```

Restart backend. The DARK WEB panel appears under **DATA → DARK WEB**. The bridge searches for operator queries and high-value FtM entities, matches results against the entity graph, and ingests them as `Mention` entities. It feeds a dedicated digest block and Situation cards when `WORLDBASE_BRIEFING_DARKWEB=1`. Details, engine list, and OPSEC guardrails → [`docs/DARKWEB.md`](docs/DARKWEB.md).

### Optional: Thailand briefing enrichment (no extra keys)

| Endpoint | Role |
|----------|------|
| `GET /api/cams/haze` | CAMS dust / AOD for Bangkok, Chiang Mai, ASEAN cities |
| `GET /api/humanitarian` | HDX datasets (Myanmar border, displacement) |
| `GET /api/gdelt/pulse/local` | Operator-region GDELT headlines |
| `GET /api/chat/context?q=...` | Query-aware chat context enrichment (smoke test endpoint) |

These feed the 24h security digest LOCAL / REGION blocks automatically. The chat context enricher (`backend/chat_context_enricher.py`) extracts entities from user queries and filters live feed caches (quakes, GDELT local, fusion hotspots) to inject relevant data into chat context, along with a synthesis directive (Structured Analytic Techniques, evidence weighting, red-team review, actionable intelligence).

### Offline maps (PMTiles)

```powershell
# Regional stack (~500 MB) — default for fast MAP load
.\scripts\download-pmtiles.ps1 -Region stack

# Full planet (~130 GB, resumable BITS)
.\scripts\download-pmtiles.ps1 -Region world-full -Force

# Optional ZXY MVT tiles (experimental Globe MVT layer)
.\scripts\start-pmtiles-serve.ps1   # http://127.0.0.1:8088
```

In **MAP** view, pick the archive in the dropdown. Default is **`thailand`** for speed; select **`planet_full`** for global offline detail when the ~130 GB file is present.

### Split view

**◫ SPLIT** in the HUD shows Globe (left) and Map (right) with linked camera sync.

- Both panes stay **mounted** (no remount on toggle — MapLibre keeps its state).
- CSS **grid** layout (`hud-main--split`) — no overlapping absolute layers over the WebGL canvas.
- On the globe half, heavy chrome (telemetry, controls, timeline) is hidden for a larger interactive area.
- First split open may briefly load PMTiles on the right; later toggles are instant.

Use for tactical overview (3D feeds) + precise 2D basemap side by side.

### Screenshots

| GLOBE | MAP | DATA | SPLIT |
|-------|-----|------|-------|
| ![Globe — Starlink orbits](docs/screenshots/globe-starlink-orbits.png) | ![MAP — PMTiles profile](docs/screenshots/map-pmtiles-profile.png) | ![DATA — quakes feed](docs/screenshots/data-quakes-feed.png) | ![SPLIT — globe + map](docs/screenshots/split-globe-map-sync.png) |

Full set: [`docs/screenshots/`](docs/screenshots/README.md)

### Docker + Pi sync

```powershell
.\scripts\start-docker.ps1    # HTTPS stack + node token
.\scripts\start-flowsint.ps1  # Optional: Flowsint OSINT graph
.\scripts\start-yente.ps1     # Optional: Yente OpenSanctions API
```

Details → [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md) · agent reference → [`AGENTS.md`](AGENTS.md)

---

## What works without keys

Most feeds are **fail-soft** (stale cache or empty payload on upstream errors — never a crashed globe).

| Tag | Layers | Key |
|-----|--------|-----|
| `no-key` | Aircraft (adsb.fi / adsb.lol), USGS, EONET, GDACS, SMARD, IODA outages, pegel, ISS, CelesTrak | — |
| `recommended` | NASA FIRMS wildfires, Cloudflare Radar outages | free signup |
| `optional` | OpenSky OAuth (recommended for full ADS-B), ENTSO-E EU energy, Blitzortung lightning, AISstream, ReliefWeb | varies |
| `required` | Cesium terrain/imagery | [Ion token](https://ion.cesium.com/tokens) |

Feed health → `GET /api/health` · trust score → `GET /api/trust` · key catalog (no secrets) → `GET /api/credentials/status` · templates → `backend/.env.example`, `frontend/.env.example`

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  React + CesiumJS (+ MapLibre 2D)          :5176        │
│  Globe · DATA · AI chat · Agent Bus subscriber          │
└───────────────────────────┬─────────────────────────────┘
                            │ /api/*
┌───────────────────────────▼─────────────────────────────┐
│  FastAPI + SQLite feed_cache                 :8002        │
│  MCP · Agent Bus · hybrid RAG · briefing agentic loop   │
│  briefing quality · /api/trust · claim auditor           │
└───────────────────────────┬─────────────────────────────┘
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
    USGS · NASA ·      Ollama :11434      Pi :8002/ingest
    GDACS · SMARD …    qwen3 + RAG        (offgrid-raspi)
         │       │
         │       └── NVIDIA NIM API (step-3.7-flash, free tier)
         │
         └── Cursor MCP (Streamable HTTP) + optional Docker MCP gateway
```

Agent reference → [`AGENTS.md`](AGENTS.md) · MCP setup → [`docs/MCP.md`](docs/MCP.md)

---

## Documentation

| Doc | Purpose |
|-----|---------|
| [`AGENTS.md`](AGENTS.md) | Runtime, endpoints, key files, troubleshooting |
| [`docs/RAG_OSINT_ROADMAP.md`](docs/RAG_OSINT_ROADMAP.md) | Track R — hybrid RAG + FtM OSINT enhancement plan |
| [`docs/WORLDBASE_ROADMAP_2026.md`](docs/WORLDBASE_ROADMAP_2026.md) | Full 2026 roadmap — P3–P10, J1–J6, K3–K4 changelog |
| [`docs/MCP.md`](docs/MCP.md) | Cursor MCP tools, Agent Bus, Docker gateway |
| [`docs/FIREWALL.md`](docs/FIREWALL.md) | Slim prompt guard (default) + optional HAK_GAL bridge (`:8001`) |
| [`docs/DARKWEB.md`](docs/DARKWEB.md) | Dark Web / Darknet OSINT module (P8) — engines, Tor proxy, OPSEC |
| [`docs/TELEGRAM.md`](docs/TELEGRAM.md) | Telegram SOCMINT bridge (K3) — allow-listed public channels, SEA scoring, OPSEC |
| [`docs/GLOBE.md`](docs/GLOBE.md) | Click-to-detail, layers, INTEL FtM, traffic cams |
| [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md) | Optional document intel ingest (GLiNER) |
| [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md) | Pi ↔ PC sync |

---

## Standing on the shoulders of giants

WorldBase is not a standalone invention. It is glue, configuration, and operator workflow on top of decades of open-source and open-data labour. We are deeply humbled by that fact and **profoundly grateful** to everyone who wrote the code, published the datasets, and answered questions in issue trackers so strangers could build on their work.

**To the giants whose shoulders we stand on: thank you.**

### Lineage & UX inspiration

| Project / person | Why we are grateful |
|------------------|---------------------|
| **[Bilawal Sidhu](https://www.youtube.com/watch?v=rXvU7bPJ8n4)** · *WorldView* | The original spark — tactical globe UX, vision modes, and multi-feed fusion on Cesium. |
| **[K-AI-STACK/WorldView](https://github.com/K-AI-STACK/WorldView)** | Open layer catalog and Cesium-first OSINT dashboard structure. |
| **[kevtoe/worldview](https://github.com/kevtoe/worldview)** | Full-stack proxy pattern, tactical UI tokens, Resium + Vite references. |
| **[petieclark/worldview](https://github.com/petieclark/worldview)** | Backend key proxying, health endpoints, Docker deployment patterns. |
| **[Reconurge/Flowsint](https://github.com/reconurge/flowsint)** | OSINT graph visualization — threat intel made approachable. |

### Core stack (we would not run without these)

| Project | Role in WorldBase |
|---------|-------------------|
| **[CesiumJS](https://cesium.com/)** & **[MapLibre](https://maplibre.org/)** | 3D/2D globe and offline map rendering. |
| **[React](https://react.dev/)** & **[Vite](https://vite.dev/)** | HUD, panels, dev server. |
| **[FastAPI](https://fastapi.tiangolo.com/)**, **[Pydantic](https://docs.pydantic.dev/)**, **[Uvicorn](https://www.uvicorn.org/)** | API, validation, async server. |
| **[SQLite](https://sqlite.org/)** & **[sqlite-vec](https://github.com/asg017/sqlite-vec)** | Local cache, briefing store, hybrid vector + FTS RAG — no cloud lock-in. |
| **[DuckDB](https://duckdb.org/)** | FtM entity graph storage when intel ingest is enabled. |
| **[Ollama](https://ollama.com/)** & **[Qwen](https://qwenlm.github.io/)** | Local LLM chat and briefing generation on operator hardware. |
| **[NVIDIA NIM](https://build.nvidia.com/)** & **[stepfun-ai](https://github.com/stepfun-ai)** | Cloud reasoning models (step-3.7-flash) via free NIM API — no local GPU required. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). |
| **[FollowTheMoney](https://followthemoney.tech/)** / **[aleph](https://github.com/alephdata/aleph)** ecosystem | Entity schema and graph patterns for OSINT ingest. |
| **[sentence-transformers](https://www.sbert.net/)** & **[BAAI/bge-reranker](https://huggingface.co/BAAI/bge-reranker-base)** | Optional CPU reranker after RRF (Track R0). |
| **[GLiNER](https://github.com/urchade/GLiNER)** (optional) | Zero-shot entity extraction for document intel — Apache-2.0. |

### Open data & civic APIs

We do not own the feeds. We fetch, cache, and fuse what others maintain — often on volunteer or public budget:

**USGS**, **NASA** (EONET, FIRMS, GIBS), **NOAA SWPC**, **GDACS**, **GDELT Project**, **SMARD**, **IODA**, **Open-Meteo**, **CAMS**, **HDX / UN OCHA**, **CelesTrak**, **adsb.lol / adsb.fi**, **Element84 STAC**, **Pegelonline**, **OpenSanctions**, **ReliefWeb**, and every engineer keeping civic endpoints alive. **You are the lifeblood of situational awareness.**

### Matching & compliance

| Project | Role |
|---------|------|
| **[OpenSanctions](https://www.opensanctions.org/)** & **[Yente](https://github.com/opensanctions/yente)** | Public CC-BY datasets and entity matching — transparency work we do not take for granted. |

### Maps & tiles

| Project | Role |
|---------|------|
| **[Protomaps](https://protomaps.com/)** / **PMTiles** | Offline regional and planet-scale basemaps. |

If we missed a dependency you rely on, please open an issue — attribution should be complete and honest. See also [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for optional ML components and license nuance.

---

## Pi + PC (two repos)

| Repo | Role | When you need it |
|------|------|------------------|
| **[worldbase](https://github.com/sookoothaii/worldbase)** (this repo) | Windows/Linux PC — Cesium globe, 30+ feeds, Ollama + NVIDIA NIM briefing, node API `:8002` | Spatial intelligence workstation; fusion and LLM digest |
| **[offgrid-raspi](https://github.com/sookoothaii/offgrid-raspi)** | Raspberry Pi — portal, sensors, mesh, offline services | Edge node that survives without mains; pushes telemetry to the PC |

**Together:** Pi `worldbase_push` → PC `POST /api/node/ingest` · PC briefing → Pi `GET /api/node/pull` (v2: ETag/304, SHA-256, `source: worldbase-pc`, briefing quality) → portal / LCD.  
**Canonical sync guide:** [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md)

This repo vendors the Pi repo as a **git submodule** at `offgrid-raspi/` (scripts + sync docs). The Pi itself clones `offgrid-raspi` separately; the PC clones `worldbase` and initializes submodules when you work on push/pull scripts.

**PC UI — EDGE dashboard:** In the HUD, open **DATA → EDGE** for live Pi stats (CPU/RAM/disk/load/uptime, room DHT, services, mesh) and 24h sparklines. The header shows **EDGE ONLINE** when `offgrid-pi` has pushed within 5 minutes (`GET /api/nodes`).

### Operator checks

| Check | Command |
|-------|---------|
| Nodes on PC | `Invoke-RestMethod http://127.0.0.1:8002/api/nodes` |
| Trust probes | `Invoke-RestMethod http://127.0.0.1:8002/api/trust` |
| PC pull payload (v2) | `GET /api/node/pull` with `X-Node-Token` when `NODE_INGEST_TOKEN` is set |
| Deploy token + HTTP to Pi | `.\scripts\setup-node-security.ps1` then `.\scripts\sync-pi.ps1` |
| Deploy hardened push/pull scripts | `.\scripts\deploy-pi-sync.ps1` |
| Smoke test | `.\scripts\smoke-test.ps1` → expect **33 PASS / 0 FAIL / 1 WARN** |
| Pi disk maintenance | `sudo bash pi-disk-maintenance.sh` (on Pi) |

---

## License

MIT — see repository terms for WorldBase core code.

Optional features (document intel ingest, external feeds, downloaded models) may pull in **separate third-party licenses**. In particular, **GLiREL relation extraction is disabled by default** because it is CC BY-NC-SA (non-commercial). See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) and [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md).
