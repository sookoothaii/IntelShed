# IntelShed (WorldBase) — Technical Stack Analysis

> **Generated:** 2026-07-01
> **Purpose:** Comprehensive technical reference for LLM-assisted development, onboarding, and architecture review.
> **Scope:** Backend, frontend, infrastructure, data layer, security, testing, CI/CD.

---

## 1. Executive Summary

IntelShed (formerly WorldBase) is a **spatial intelligence workstation** — a full-stack OSINT platform combining a React/Cesium globe frontend with a FastAPI backend running 30+ live data feeds, local + cloud LLM chat, an anti-hallucination evidence chain system, FollowTheMoney entity graph, and optional Raspberry Pi edge sync for offline briefing.

**Key metrics:**

| Metric | Value |
|--------|-------|
| Backend Python LOC | ~103,000 |
| Frontend TS/TSX LOC | ~34,000 |
| Backend Python files | 87 (top-level) + routes/middleware/auth/tasks |
| Frontend components | 57 React components |
| Frontend hooks | 7 custom hooks + 38 layer hooks |
| API routes | 375 |
| OpenAPI schemas | 38 |
| Backend tests | 2,592 (2,589 passed, 3 skipped) |
| Frontend tests | Vitest + RTL + Playwright E2E |
| Python dependencies | 97 (requirements.txt) + optional |
| Docker services | 6 (backend, web/Caddy, redis, celery-worker, celery-beat, flower) |
| Feature flags | 40+ via `WORLDBASE_*` env vars |

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Docker / Venv Runtime                        │
│                                                                     │
│  ┌──────────┐    ┌──────────────────────────────────────────────┐  │
│  │  Caddy   │───▶│  FastAPI Backend (Uvicorn)                   │  │
│  │  :80/:443│    │  127.0.0.1:8002                               │  │
│  └──────────┘    │                                              │  │
│       │          │  ┌─────────┐ ┌──────────┐ ┌────────────┐    │  │
│       │          │  │ Redis   │ │ Celery   │ │ DuckDB     │    │  │
│       │          │  │ :6380   │ │ Worker   │ │ (FtM graph)│    │  │
│       │          │  │         │ │ Beat     │ │            │    │  │
│       │          │  │         │ │ Flower   │ │            │    │  │
│       │          │  └─────────┘ └──────────┘ └────────────┘    │  │
│       │          │  ┌─────────────────────────────────────┐    │  │
│       │          │  │ SQLite (worldbase.db)               │    │  │
│       │          │  │ - Feeds, briefings, auth, audit     │    │  │
│       │          │  │ - Entity classification, retention  │    │  │
│       │          │  │ - Bitemporal versions, GDPR         │    │  │
│       │          │  └─────────────────────────────────────┘    │  │
│       │          └──────────────────────────────────────────────┘  │
│       │                                                            │
│       ▼                                                            │
│  ┌──────────┐                                                      │
│  │  Vite    │  Frontend SPA (React 18 + Cesium)                    │
│  │  :5176   │  Served by Caddy in Docker                           │
│  └──────────┘                                                      │
│                                                                     │
│  ┌──────────┐                                                      │
│  │ Ollama   │  Local LLM (qwen3:8b) — briefing generation          │
│  │ :11434   │                                                      │
│  └──────────┘                                                      │
│                                                                     │
│  ┌──────────┐                                                      │
│  │ NVIDIA   │  Cloud LLM (step-3.7-flash) — MCP chat default       │
│  │ NIM API  │  6 providers total via chat_model_router             │
│  └──────────┘                                                      │
│                                                                     │
│  ┌──────────┐                                                      │
│  │ Raspberry│  Pi edge node — pull sync, offline RAG, briefing     │
│  │ Pi       │  GET /api/node/pull → portal briefing_latest.json    │
│  └──────────┘                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Backend

### 3.1 Framework & Runtime

| Component | Version | Notes |
|-----------|---------|-------|
| Python | 3.12.7 | venv in `backend/venv/` |
| FastAPI | 0.136.3 | Uvicorn[standard] with reload |
| Pydantic | 2.13.4 | All request/response models |
| Uvicorn | >=0.32.0 | Bind 127.0.0.1:8002 (venv) / 0.0.0.0:8002 (Docker) |
| httpx | >=0.27.0 | Async HTTP client for all feed fetching |

### 3.2 Module Structure

**87 top-level Python modules** in `backend/`, organized by concern:

#### Data Feed Bridges (30+ live sources)
- `gdelt_bridge.py` — GDELT Events + GKG, local + West Asia presets
- `ais_bridge.py` + `ais_trajectory.py` — Maritime AIS (AISHub + streaming)
- `opensky_client.py` + `adsb_client.py` + `aircraft_provider.py` — ADS-B aircraft tracking
- `acled_bridge.py` — Armed Conflict Location & Event Data
- `blitzortung_bridge.py` — Lightning detection (Blitzortung.org)
- `osm_bridge.py` — OpenStreetMap critical infrastructure POIs (Overpass)
- `weather_forecast_bridge.py` — Open-Meteo multi-day forecast
- `cams_bridge.py` — Copernicus Atmosphere Monitoring Service
- `cap_bridge.py` — Common Alerting Protocol alerts
- `cve_bridge.py` — CVE vulnerability feed
- `eonet_bridge.py` — NASA EONET natural events
- `quakes_bridge.py` — USGS earthquakes
- `fire_bridge.py` — NASA FIRMS wildfire detection
- `news_feeds.py` — ReliefWeb + RSS background ingest
- `darkweb_bridge.py` + `darkweb_parsers.py` + `darkweb_tor.py` — Tor hidden service search (5 engine parsers)
- `breach_bridge.py` — HIBP k-anonymity credential leak monitoring
- `cyber_bridge.py` — Shodan InternetDB (keyless)
- `stac_bridge.py` — Sentinel-2 STAC search + satellite imagery
- `cams_bridge.py` — Copernicus atmosphere data
- `telegram_bridge.py` — Telegram channel monitoring
- `river_bridge.py` — River flow / flood monitoring (PegelOnline)
- `webcam_bridge.py` — Traffic + public webcam streams
- `ckan_harvester.py` — CKAN data portal harvester (5 portals)

#### Intelligence & Analysis
- `ftm_schema.py` + `ftm_store.py` + `ftm_query.py` — FollowTheMoney 4.0 entity graph (DuckDB)
- `entity_resolution.py` — Splink dual-pipeline entity resolution (single + two-stage)
- `intel_ingest.py` — Document ingestion with GLiNER NER + GLiREL relation extraction
- `provenance.py` — Source reliability scoring, temporal decay, corroboration boost
- `query_router.py` — 5-route classifier (vector/graph/spatial/hybrid/live, 0 VRAM)
- `route_ledger.py` — Route outcome ledger for empirical weight recompute
- `context_budget.py` — Token budget per section with provenance-based truncation
- `conflict_detection.py` — Existence + temporal conflict detection
- `report_schema.py` — Structured JSON report output with regex fallback parser

#### LLM & Chat
- `chat_proxy.py` — Main chat endpoint (6 providers via `chat_model_router.py`)
- `chat_agentic.py` — 3-phase agentic loop (coverage → retrieve → corroboration)
- `chat_context.py` + `chat_context_enricher.py` — RAG context assembly
- `chat_tools.py` — MCP tool definitions (verify_claim, etc.)
- `chat_routing.py` — Provider selection (Ollama, NVIDIA NIM, OpenAI, etc.)
- `agent_orchestrator.py` — 5-agent multi-agent orchestrator (Coverage → Retrieval → Spatial → Corroboration → Synthesis)
- `agent_blackboard.py` — Structured blackboard for agent evidence sharing
- `react_agent.py` — ReAct thought/action/observation loop
- `multi_hypothesis.py` — 3-stance draft generation + comparison
- `temporal_engine.py` — Granger causality + Mann-Kendall trend detection (pure Python, no numpy)

#### Briefing System
- `briefing_digest.py` — 24h security briefing digest generation
- `briefing_prompt.py` — Prompt assembly for briefing LLM
- `briefing_agentic.py` — Agentic briefing loop
- `briefing_pipeline.py` — Multi-stage briefing pipeline
- `briefing_quality.py` — Briefing quality scoring
- `node_briefing.py` — Pi sync briefing generation + delivery

#### Security & Auth
- `auth/security.py` — HMAC authentication with replay protection (nonce + timestamp)
- `auth/jwt.py` — JWT access/refresh tokens (RBAC3)
- `auth/audit.py` — Audit trail logging
- `middleware/rbac.py` — Role-based access control (admin/operator/viewer)
- `middleware/rate_limit.py` — Two-layer rate limiting (slowapi + sliding window)
- `middleware/security_headers.py` — CSP + security headers (ASGI middleware)
- `secrets_manager.py` — Secrets management
- `output_guard.py` — Output filtering / PII guard
- `classification.py` — CONFIDENTIAL/SECRET/UNCLASSIFIED labels + federation gate

#### Infrastructure
- `config.py` — `WorldBaseConfig` Pydantic model, 40+ feature flags, cached singleton
- `lifespan.py` — Startup/shutdown lifecycle (DB init, feed autopilot, warmup)
- `bootstrap.py` + `bootstrap_env.py` — Hydration endpoint + env bootstrapping
- `connector_registry.py` — Feed connector registration + health
- `feed_circuit_breaker.py` — ETag + exponential backoff circuit breaker
- `feed_autopilot.py` — Background feed refresh loop
- `runtime_cache.py` — Redis-backed cache with stale-while-revalidate
- `metrics.py` — Prometheus-compatible metrics
- `alerting.py` — Alert generation + delivery
- `anomaly_detector.py` + `anomaly_river.py` — Isolation Forest + River online anomaly detection
- `snapshot_archiver.py` — Ring-buffer snapshot archive for temporal replay
- `fusion_delta.py` — 24h fusion delta grid
- `graph_algorithms.py` — NetworkX PageRank + centrality on FtM graph
- `cii_engine.py` — Country Instability Index (0–100, 4 signal families)

#### Compliance
- `gdpr.py` — GDPR export/deletion
- `retention.py` — Data retention policies + TTL pruning
- `bitemporal.py` — Bi-temporal entity store (valid_time + system_time)

#### Visual Intelligence
- `blip_bridge.py` — BLIP image captioning (ONNX + NVIDIA VLM API)
- `colqwen2_service.py` — ColQwen2 visual document understanding (subprocess microservice)
- `sar_bridge.py` — SAR dark-vessel detection (CA-CFAR + Sentinel-1 + AIS cross-ref)

#### Other
- `mcp_server.py` — MCP server (Streamable HTTP at `/api/mcp`)
- `mcp_schema.py` + `mcp_jmespath.py` — MCP outputSchema + JMESPath projection
- `api_contracts.py` — OpenAPI → TypeScript client generator
- `benchmark_vec1.py` — vec1 benchmark (latency p50/p95/p99)
- `llm_ab.py` — LLM A/B comparison
- `subgraph_ab.py` — Subgraph A/B comparison (Jaccard similarity)
- `push_delivery.py` — SSE push delivery + watch items
- `gpu_budget_scheduler.py` — GPU/VRAM budget scheduler (firewall | llm slots)
- `whisper_bridge.py` — Whisper voice control (faster-whisper CUDA/CPU)
- `tts_bridge.py` — Piper TTS for briefing narration
- `rag_embed.py` — RAG embedding (sentence-transformers + ONNX reranker)
- `mapping_runner.py` — FtM ingest mapping runner
- `darkweb_briefing.py` — Dark web briefing integration

### 3.3 Route Registration

Routes are registered via `routes/registry.py` which imports and mounts all routers:

| Router file | Path prefix | Key endpoints |
|-------------|-------------|---------------|
| `health.py` | `/api/health` | `GET /ping`, `GET /` (full health) |
| `auth.py` | `/api/auth` | JWT login/refresh, API key validation |
| `admin.py` | `/api/admin` | Feature flags, config, maintenance |
| `ftm_api.py` | `/api/intel` | Entity CRUD, edges, statements, provenance |
| `core_feeds.py` | `/api/feeds` | 30+ feed endpoints (GDELT, AIS, quakes, etc.) |
| `chat.py` | `/api/chat` | Chat proxy + agentic + MCP tools |
| `briefing_pipeline.py` | `/api/briefing` | Briefing generation, export (PDF/DOCX/PPTX) |
| `aircraft.py` | `/api/aircraft` | ADS-B tracking |
| `metrics.py` | `/api/metrics` | Prometheus metrics |
| `telemetry.py` | `/api/telemetry` | OTel-style telemetry |
| `config.py` | `/api/config` | Runtime config inspection |
| `quota.py` | `/api/quota` | Rate limit quota info |
| `duckdb_queue.py` | `/api/duckdb` | DuckDB queue management |
| `intel_stix.py` | `/api/intel/stix` | STIX export |

**MCP server** mounted at `/api/mcp` (Streamable HTTP, 13+ tools).

### 3.4 Configuration System

`config.py` defines `WorldBaseConfig` (Pydantic BaseModel, frozen):

- **40+ feature flags** via `WORLDBASE_*` env vars
- Cached singleton with env-hash invalidation
- `from_env()` classmethod parses all env vars with defaults
- `_truthy()` helper for boolean env vars

Key flags:

| Flag | Default | Purpose |
|------|---------|---------|
| `WORLDBASE_RATE_LIMIT` | `1` | Sliding window rate limiter |
| `WORLDBASE_RATE_LIMIT_RPM` | `60` | Requests per minute per IP |
| `WORLDBASE_QUERY_ROUTER` | `1` | 5-route query classifier |
| `WORLDBASE_PROVENANCE` | `1` | Source reliability scoring |
| `WORLDBASE_BRIEFING_AUTOPILOT` | `1` | Auto-briefing generation |
| `WORLDBASE_CHAT_AGENTIC` | `0` | Agentic chat loop (opt-in) |
| `WORLDBASE_AGENT_ORCHESTRATOR` | `0` | 5-agent orchestrator (opt-in) |
| `WORLDBASE_TWO_PASS` | `0` | Critique-refine synthesis (opt-in) |
| `WORLDBASE_BLACKBOARD` | `0` | Agent blackboard (opt-in) |
| `WORLDBASE_ENTITY_RESOLUTION_PIPELINE` | `single` | Splink pipeline mode |
| `WORLDBASE_CONTEXT_BUDGET` | `1` | Token budget per section |
| `WORLDBASE_NEWS_REFRESH_INTERVAL` | `600` | Background news refresh (seconds) |
| `WORLDBASE_OPERATOR_REGION` | `thailand` | Local/Regional/Global bucketing |
| `WORLDBASE_GDPR` | `1` | GDPR export/deletion |
| `WORLDBASE_RETENTION` | `1` | Data retention pruning |
| `WORLDBASE_CLASSIFICATION` | `1` | Classification labels |
| `WORLDBASE_BITEMPORAL` | `1` | Bi-temporal entity store |
| `WORLDBASE_MCP` | `1` | MCP server mount |
| `WORLDBASE_WHISPER_BRIDGE` | `0` | Voice control (opt-in) |
| `WORLDBASE_TTS_BRIDGE` | `0` | Text-to-speech (opt-in) |
| `WORLDBASE_SAR` | `0` | SAR dark-vessel detection (opt-in) |
| `WORLDBASE_PUSH` | `0` | Proactive push delivery (opt-in) |
| `WORLDBASE_BENCHMARK` | `0` | vec1 benchmark (opt-in) |
| `WORLDBASE_LLM_AB` | `0` | LLM A/B comparison (opt-in) |

### 3.5 Middleware Stack

Middleware is applied in `main.py` in this order (outermost first):

1. **`health_check_timing`** — Timing middleware for `/api/health/*` endpoints
2. **`CORSMiddleware`** — Configured origins, credentials, methods, headers
3. **`GZipMiddleware`** — Minimum response size 500 bytes
4. **`SecurityHeadersMiddleware`** — CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy (ASGI, no buffering for SSE)
5. **`setup_rate_limiting()`** — slowapi exception handler + sliding window middleware

Rate limiting has two layers:
- **Layer 1: slowapi per-endpoint decorators** (fixed-window, Redis or in-memory)
  - `@rate_limit_node_ingest()` — 100/min per node
  - `@rate_limit_node_pull()` — 20/min per node
  - `@rate_limit_node_command()` — 10/min per admin
  - `@rate_limit_general()` — 1000/hour per IP
- **Layer 2: SlidingWindowLimiter** (global, per-IP sliding window)
  - Redis ZSET with in-memory deque fallback
  - API-key + node-token + health endpoints exempt
  - Per-endpoint overrides via `WORLDBASE_RATE_LIMIT_OVERRIDES`

---

## 4. Frontend

### 4.1 Framework & Build

| Component | Version | Notes |
|-----------|---------|-------|
| React | 18.3.1 | SPA, no SSR |
| TypeScript | ~5.6.2 | Strict mode |
| Vite | 6.0.1 | Dev server :5176, build to `dist/` |
| TanStack Query | ^5.101.0 | Server state management |
| Cesium | ^1.142.0 | 3D globe, terrain, entities, imagery |
| MapLibre GL | ^5.24.0 | 2D map alternative |
| Cytoscape | ^3.34.0 | Entity graph visualization |
| @hello-pangea/dnd | ^18.0.1 | Drag-and-drop (briefing kanban) |
| satellite.js | ^5.0.0 | Satellite orbit propagation |

### 4.2 Component Architecture

**57 React components** in `frontend/src/components/`:

#### Globe & Map
- `Globe.tsx` (3,095 LOC) — Main Cesium globe: entities, layers, imagery, terrain, camera fly-to, 3D models
- `MapPanel.tsx` — Map panel wrapper
- `MapModeBar.tsx` — Cesium ↔ MapLibre toggle
- `WindyMapOverlay.tsx` — Windy.com overlay
- `GlobeChat.tsx` — Chat-integrated globe commands
- `GlobeDetailModal.tsx` — Entity detail modal on globe

#### Intelligence Panels
- `FullAnalysisOverlay.tsx` (83,487 bytes) — Full situation analysis overlay
- `SituationBoard.tsx` — Situations board with fusion hotspots
- `BriefingKanban.tsx` — Briefing kanban board (drag-and-drop)
- `ChatPanel.tsx` (41,189 bytes) — Chat interface with agentic mode
- `DataPanel.tsx` (65,520 bytes) — Data ingestion, feed sync, entity resolution, graph overview
- `IntelGraphPanel.tsx` — Cytoscape entity graph
- `RelationshipExplorer.tsx` — Interactive graph exploration
- `EntityTimeline.tsx` — Entity first_seen → last_seen timeline
- `EntityDetailPanel.tsx` — Entity detail with statements
- `ProvenanceChain.tsx` — Source provenance chain visualization
- `RelatedEntitiesGraph.tsx` — Related entities subgraph
- `EdgePanel.tsx` — Edge detail panel

#### OSINT Panels
- `OsintPanel.tsx` — OSINT search interface
- `OsintExternalLinks.tsx` — External OSINT resource links
- `OsintReferencePanel.tsx` — OSINT reference management
- `DarkwebPanel.tsx` (37,203 bytes) — Dark web search + breach monitoring
- `SanctionsPanel.tsx` — Sanctions screening
- `SatellitePanel.tsx` — Satellite imagery browser
- `StacPanel.tsx` — STAC catalog browser
- `TelegramPanel.tsx` — Telegram channel monitor
- `NewsPanel.tsx` — News feed panel
- `WildfiresPanel.tsx` — Wildfire detection panel
- `WeatherSection.tsx` — Weather forecast panel
- `WebcamSection.tsx` / `WebcamStreamPanel.tsx` — Webcam streams
- `TrafficCamPanel.tsx` — Traffic camera panel
- `PegelSparkline.tsx` — River gauge sparkline
- `SensorSparklines.tsx` — Sensor data sparklines

#### Security & Firewall
- `FirewallPanel.tsx` (32,879 bytes) — HAK_GAL firewall control panel
- `FirewallMonitor.tsx` — Firewall status monitor
- `CredentialManagerPanel.tsx` — Credential manager

#### Analytics & Visualization
- `AnalystDashboard.tsx` — SVG-based Sankey + Timeline + Heatmap
- `TemporalReplay.tsx` — Snapshot time-travel replay
- `Sparkline.tsx` — Generic sparkline component
- `TrustGauge.tsx` — Trust/provenance gauge

#### Infrastructure
- `FeedsStatusPanel.tsx` — Feed health status
- `FeatureFlagsPanel.tsx` — Feature flag toggles
- `CalibrationTriggersPanel.tsx` — Calibration trigger management
- `NodeHealthBanner.tsx` — Pi node health banner
- `CommandPalette.tsx` — Command palette (Ctrl+Shift+P)
- `ActionBar.tsx` — Action toolbar
- `LayerTree.tsx` — Layer tree for globe
- `ContextMenu.tsx` — Right-click context menu
- `HotkeyHelp.tsx` — Hotkey help overlay
- `ErrorBoundary.tsx` — Error boundary wrapper
- `AgentLog.tsx` — Agent execution log
- `StepList.tsx` — Pipeline step list
- `SidebarLeft.tsx` / `SidebarRight.tsx` / `CenterRail.tsx` — Layout

### 4.3 Hooks

| Hook | Purpose |
|------|---------|
| `useSmartPoll.ts` | Adaptive polling: exponential backoff, hidden-tab throttle, circuit breaker |
| `useMapEngine.ts` | Lazy-loaded deck.gl, Cesium ↔ MapLibre toggle, localStorage persistence |
| `useSharedFeeds.ts` | Shared feed state via TanStack Query |
| `useBriefingPipeline.ts` | Briefing pipeline state machine |
| `useHotkeys.ts` | Global hotkey handler |
| `useAgentBus.ts` | Agent bus event subscription |
| `useCesiumErrorHandler.ts` | Cesium error boundary + recovery |
| `layers/` (38 hooks) | Per-layer Cesium entity management |

### 4.4 PWA & Offline

- `manifest.webmanifest` — App manifest with icons
- `sw.js` — Service worker: network-first API, SWR assets, cache-first Cesium
- SW registration in `main.tsx`
- Offline RAG on Pi via `sqlite-vec` + FTS5

### 4.5 Browser-Side ML

- `browser_ml.ts` — Transformers.js (ONNX Runtime Web) for NER + sentiment scoring
- Models: `Xenova/bert-base-NER-uncased` (~110MB), `Xenova/distilbert-base-uncased-finetuned-sst-2-english` (~65MB)
- Lazy-loaded via dynamic import, cached in IndexedDB

---

## 5. Data Layer

### 5.1 SQLite (`worldbase.db`)

Primary OLTP database for:
- Feed cache + metadata
- Briefing history + quality scores
- Auth audit trail
- Entity classification labels
- Retention policies + pruning log
- Bitemporal entity versions
- GDPR requests
- Route outcome ledger
- Anomaly detection state
- Federation nodes
- Resolution labels (human-in-the-loop)

### 5.2 DuckDB (`data/entities.duckdb`)

FollowTheMoney entity graph:
- `entities` table — FtM canonical entities (Person, Organization, Address, etc.)
- `statements` table — FtM 4.0 StatementEntity (8 columns: stmt_id, canonical_id, schema, original_value, external, first_seen, last_seen, origin)
- `edges` table — Relationship edges (worksFor, locatedAt, ownsAsset, mentionedIn, linkedTo, partOf)
- Spatial queries via `ST_Within` (duckdb-spatial, R-Tree disabled on 1.5.x)
- B-Tree index on lat/lon for <100k entities

### 5.3 Redis (`:6380`)

- Rate limiting (slowapi + sliding window ZSET)
- Runtime cache (stale-while-revalidate)
- Bootstrap hydration cache
- Celery broker + result backend
- Feed circuit breaker state
- News feed background ingest cache

### 5.4 AIS Trajectory DB (`data/ais_trajectory.db`)

Separate SQLite for AIS vessel trajectory storage.

### 5.5 Optional PostgreSQL

SQLAlchemy + asyncpg + Alembic migrations available but not default.

---

## 6. LLM Integration

### 6.1 Provider Matrix

| Provider | Endpoint | Default Model | Use Case |
|----------|----------|---------------|----------|
| Ollama (local) | `127.0.0.1:11434` | `qwen3:8b` | Briefing LLM, fallback chat |
| NVIDIA NIM | `integrate.api.nvidia.com/v1` | `stepfun-ai/step-3.7-flash` | MCP chat default |
| OpenAI | `api.openai.com/v1` | Configurable | Optional |
| Anthropic | `api.anthropic.com/v1` | Configurable | Optional |
| Google | `generativelanguage.googleapis.com` | Configurable | Optional |
| Mistral | `api.mistral.ai/v1` | Configurable | Optional |

### 6.2 Chat Pipeline

1. **Query Router** (`query_router.py`) — Rule-based 5-route classifier: vector / graph / spatial / hybrid / live (0 VRAM)
2. **Route Ledger** (`route_ledger.py`) — Empirical route weight recompute at N=50 threshold
3. **Agentic Chat** (`chat_agentic.py`) — 3-phase: coverage → retrieve → corroboration (opt-in)
4. **Multi-Agent Orchestrator** (`agent_orchestrator.py`) — 5 agents: Coverage → Retrieval → Spatial → Corroboration → Synthesis (opt-in)
5. **ReAct Agent** (`react_agent.py`) — Thought/Action/Observation loop with query router (opt-in)
6. **Multi-Hypothesis** (`multi_hypothesis.py`) — 3 stances (baseline, adversarial, forecast) + comparison (opt-in)
7. **Temporal Engine** (`temporal_engine.py`) — Granger causality + Mann-Kendall trend (opt-in)
8. **Two-Pass Synthesis** — Draft → critique → revise for `/analyze` commands (opt-in)

### 6.3 Anti-Hallucination Stack

1. **Provenance scoring** (`provenance.py`) — Source reliability table, temporal decay, corroboration boost, conflict penalty
2. **Evidence chains** — `[EVIDENCE-NNN]` IDs, confidence tags (HIGH ≥0.8 / MEDIUM ≥0.5 / LOW)
3. **Conflict detection** (`conflict_detection.py`) — Existence + temporal conflicts (≥24h threshold)
4. **Context budget** (`context_budget.py`) — Token budget per section, refuse path when weighted quality < 0.35
5. **CRAG-lite** — Chat context retrieval with correctness assessment
6. **Verify claim tool** (`chat_tools.py`) — RAG memory + DuckDuckGo instant answer API

### 6.4 RAG

- `rag_embed.py` — Sentence-transformers embeddings (GPU CUDA or CPU)
- BGE reranker (ONNX quantized, 0 VRAM) — `RAG_RERANK=1`
- Adaptive YAML chunking
- Spatial bbox filtering
- Background news ingest (ReliefWeb + RSS, 10-min refresh)

---

## 7. Security

### 7.1 Authentication

- **HMAC + Replay Protection** (`auth/security.py`) — Constant-time comparison, nonce/timestamp cache, configurable TTL (300s default)
- **JWT** (`auth/jwt.py`) — Access + refresh tokens, RBAC3 (admin/operator/viewer)
- **API Key** — `X-API-Key` header for external clients (Pi sync, MCP)
- **Node Token** — `X-Node-Token` header for Pi ingest/pull

### 7.2 Rate Limiting

Two-layer architecture (see §3.5):
- Layer 1: slowapi per-endpoint decorators (fixed-window)
- Layer 2: SlidingWindowLimiter global middleware (sliding window, Redis ZSET + in-memory fallback)
- Exemptions: API-key, node-token, `/api/health/*`

### 7.3 CSP & Security Headers

Three synchronized CSP sources:
1. `frontend/index.html` — `<meta http-equiv="Content-Security-Policy">` (dev mode)
2. `Caddyfile` — `Content-Security-Policy` header (Docker mode)
3. `backend/middleware/security_headers.py` — ASGI middleware (venv mode)

Policy: `default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com data:; img-src 'self' data: blob: https:; connect-src 'self' https://api.cesium.com wss: ws:; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'self'; base-uri 'self'; form-action 'self';`

Additional headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy: geolocation=(self), microphone=(), camera=()`, `X-Permitted-Cross-Domain-Policies: none`

### 7.4 Classification & Federation

- `classification.py` — 4 levels: UNCLASSIFIED < CONFIDENTIAL < SECRET < TOP_SECRET
- Federation gate filters entities by clearance level
- Per-entity + per-dataset classification labels

### 7.5 GDPR & Retention

- `gdpr.py` — Export + hard-delete + anonymization
- `retention.py` — 5 default policies (feed_cache 7d, auth_audit 90d, gdpr_requests 365d, statements/edges disabled)

---

## 8. Infrastructure

### 8.1 Docker Stack

6 services via `docker-compose.yml`:

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `backend` | `intelshed-backend:local` | 127.0.0.1:8002 | FastAPI + Uvicorn |
| `web` | `intelshed-web:local` (Caddy 2.7.6) | 80, 443 | TLS proxy + SPA serve |
| `redis` | `redis:7-alpine` | 127.0.0.1:6380 | Cache + rate limit + Celery broker |
| `celery-worker` | `intelshed-backend:local` | — | Background tasks (feeds, briefings) |
| `celery-beat` | `intelshed-backend:local` | — | Scheduled task runner |
| `flower` | `intelshed-backend:local` | 127.0.0.1:5555 | Celery monitoring |

**Caddy** serves the built SPA from `/srv` and proxies `/api` to the backend container. Self-signed TLS for `localhost` + LAN IP.

### 8.2 Venv Mode (Windows Dev)

- `start.ps1` — Starts Uvicorn + Vite, waits for `/api/health/ping` before Vite
- Backend: `127.0.0.1:8002`
- Frontend: `localhost:5176` (Vite dev server)
- Ollama: `127.0.0.1:11434`

**Critical:** Never run venv backend and Docker stack simultaneously — two separate databases cause silent data divergence.

### 8.3 Pi Edge Node

- `offgrid-raspi/` — Raspberry Pi configuration
- Pull sync: `GET /api/node/pull` (delta sync + conflict detection)
- Offline RAG: `sqlite-vec` + FTS5 keyword search
- Briefing delivery: `briefing_latest.json` on Pi portal
- WorldBase push: `POST /api/node/ingest`

### 8.4 Caddyfile

- HTTP → HTTPS redirect
- SPA serve with `try_files {path} /index.html`
- API proxy to backend
- Security headers (CSP, X-Frame-Options, etc.)
- Optional LAN lockdown (commented out)

---

## 9. Testing

### 9.1 Backend Tests

| Test file | Tests | Coverage |
|-----------|-------|----------|
| `test_rate_limiter.py` | 16 | Sliding window, exemptions, CSP headers |
| `test_context_budget.py` | 25 | Token budget, provenance truncation |
| `test_news_feeds.py` | 8 | RSS parsing, background refresh |
| `test_p5_statements.py` | 48 | FtM StatementEntity, provenance, conflicts |
| `test_llm_workplan.py` | 62 | Blackboard, personas, evidence chains, report schema |
| `test_route_ledger.py` | 9 | Route outcome recording, weight recompute |
| `test_chat_report_quality.py` | 21 | 15 golden queries, quality checks |
| `test_react_agent.py` | 18 | ReAct loop, thought generation, merge |
| `test_multi_hypothesis.py` | 22 | 3-stance drafts, comparison, merge |
| `test_temporal_engine.py` | 60 | Stats helpers, trend detection, Granger probe |
| `test_breach_bridge.py` | 30 | HIBP API, password check, monitor CRUD |
| `test_darkweb_parsers.py` | 26 | 5 engine-specific HTML parsers |
| `test_ckan_harvester.py` | 22 | CKAN harvest, YAML config, FtM ingest |
| `test_backup_auto.py` | 12 | SQLite VACUUM, S3 upload, restore test |
| `test_api_contracts.py` | 19 | OpenAPI → TS generation |
| `test_gdpr.py` | 9 | Export, delete, anonymize, audit |
| `test_retention.py` | 12 | Policy CRUD, pruning, logging |
| `test_classification.py` | 20 | Labels, federation gate, filtering |
| `test_bitemporal.py` | 16 | Version recording, time travel, corrections |
| `test_session16.py` | 40 | SAR CFAR, push SSE, subgraph, benchmark, LLM AB |
| + 40+ other test files | ~2,000+ | Feed bridges, auth, chat, briefing, etc. |
| **Total** | **2,592** | **2,589 passed, 3 skipped** |

### 9.2 Frontend Tests

- **Vitest + RTL** — Unit + component tests
- **Playwright E2E** — `e2e/flows.spec.ts`
- **PWA tests** — `test_pwa.test.ts` (15 tests)
- **Browser ML tests** — `test_browser_ml.test.ts` (18 tests)
- **SmartPoll tests** — `test_useSmartPoll.test.ts` (9 tests)
- **Analyst Dashboard** — `AnalystDashboard.test.tsx` (10 tests)
- **Temporal Replay** — `TemporalReplay.test.tsx` (11 tests)

### 9.3 Smoke Test

`.\scripts\smoke-test.ps1` — 33 checks including live feed envelope contract.

---

## 10. CI/CD

### 10.1 GitHub Actions (`.github/workflows/ci.yml`)

8 jobs:

| Job | Purpose | Required |
|-----|---------|----------|
| `frontend` | Build (tsc + vite) | Yes |
| `frontend-quality` | ESLint + Prettier | No (continue-on-error) |
| `frontend-test` | Vitest + coverage | Yes |
| `frontend-e2e` | Playwright E2E | No (continue-on-error) |
| `backend` | Import + compile + OpenAPI → TS | Yes |
| `backend-quality` | Ruff + MyPy + mapping drift | No (continue-on-error) |
| `pre-commit` | Pre-commit hooks | Yes |
| `backend-tests` | Full pytest suite | No (continue-on-error) |

### 10.2 Pre-commit Hooks (`.pre-commit-config.yaml`)

| Hook | Stage | Purpose |
|------|-------|---------|
| `ruff` | commit | Backend lint + fix |
| `ruff-format` | commit | Backend format check |
| `tsc` | commit | Frontend type check |
| `pytest-collect` | pre-push | Backend syntax/import check |
| `secret-guard` | pre-push | Block `.env` files in staging |

### 10.3 Pre-push Hook (`.husky/pre-push`)

4 gates (fail-fast): ruff check → pytest --collect-only → tsc --noEmit → secret guard

---

## 11. Engineering Hygiene (Track E)

### Session E1 — Shipped (2026-07-01)

| Item | Status | Details |
|------|--------|---------|
| E-01 Pre-push Hooks | ✅ | `.husky/pre-push` + `.pre-commit-config.yaml` |
| E-02 Rate Limiting | ✅ | `SlidingWindowLimiter` — Redis ZSET + in-memory fallback |
| E-07 CSP Hardening | ✅ | 3 sync sources: index.html, Caddyfile, SecurityHeadersMiddleware |

### Pending Sessions

| Session | Items | Status |
|---------|-------|--------|
| E2 | CI workflows + Cache stampede protection | Pending |
| E3 | Visual regression + MCP quota | Pending |

---

## 12. Key Design Patterns

### 12.1 Fail-Soft

All optional features use try/except with graceful degradation:
- Redis unavailable → in-memory fallback
- GPU unavailable → CPU fallback
- Cloud LLM unavailable → Ollama fallback → rule-based fallback
- GLiNER not installed → skip NER, continue ingest
- Splink not installed → skip entity resolution

### 12.2 Feature Flags

All features are env-var gated with `WORLDBASE_*` prefix. Defaults are conservative (safety-critical features on, experimental features off). Config is a frozen Pydantic model with env-hash invalidation.

### 12.3 Zero-VRAM Rule

All intelligence features (query router, agent orchestrator, blackboard, provenance, conflict detection, context budget, report schema) are rule-based with 0 VRAM. LLM calls are only made when explicitly needed and feature-flagged.

### 12.4 Pi Sync Compatibility

All new features must consider Pi sync:
- Briefing blocks must be JSON-serializable
- Entity graph changes must sync via delta
- Pi runs offline RAG with `sqlite-vec` — no GPU dependencies

### 12.5 ASGI Middleware (No Buffering)

`SecurityHeadersMiddleware` is implemented as raw ASGI middleware (not `BaseHTTPMiddleware`) to avoid buffering `StreamingResponse` / SSE (chat streaming).

---

## 13. File Layout

```
worldbase/
├── backend/                    # FastAPI backend
│   ├── main.py                 # App entry point
│   ├── config.py               # WorldBaseConfig (40+ flags)
│   ├── lifespan.py             # Startup/shutdown lifecycle
│   ├── middleware/             # Rate limit, RBAC, security headers
│   ├── auth/                   # HMAC, JWT, audit
│   ├── routes/                 # 16 route modules, registry.py
│   ├── tasks/                  # Celery tasks (briefing, feeds)
│   ├── tests/                  # Test suite (2,592 tests)
│   ├── ingest/                 # CKAN sources YAML
│   ├── venv/                   # Python virtualenv
│   ├── requirements.txt        # 97 dependencies
│   └── *.py                    # 87 top-level modules
├── frontend/                   # React SPA
│   ├── src/
│   │   ├── App.tsx             # Main app (702 LOC)
│   │   ├── main.tsx            # Entry + SW registration
│   │   ├── components/         # 57 React components
│   │   ├── hooks/              # 7 hooks + 38 layer hooks
│   │   └── lib/                # API client, browser ML, utils
│   ├── public/                 # PWA manifest, SW, favicon
│   ├── e2e/                    # Playwright E2E
│   ├── tests/                  # Vitest + RTL tests
│   └── package.json            # 12 deps, 22 devDeps
├── docker/                     # Docker configs
├── docs/                       # Documentation
├── scripts/                    # PowerShell + Python scripts
├── offgrid-raspi/              # Pi edge node
├── Caddyfile                   # Caddy config
├── docker-compose.yml          # 6-service stack
├── .pre-commit-config.yaml     # Pre-commit + pre-push hooks
├── .husky/pre-push             # Pre-push hook script
└── .github/workflows/ci.yml    # 8 CI jobs
```

---

## 14. Known Technical Debt

1. **MyPy** — `continue-on-error: true` in CI; type checking not enforced
2. **Frontend E2E** — `continue-on-error: true`; not blocking
3. **Frontend quality** — ESLint + Prettier not blocking
4. **Backend tests** — `continue-on-error: true` in CI; not blocking
5. **DuckDB spatial R-Tree** — Disabled on 1.5.x (duckdb-spatial #769); B-Tree on lat/lon sufficient for <100k entities
6. **PyICU on Windows** — Requires manual wheel install for `followthemoney`
7. **`regex` deprecation** — `FastAPIDeprecationWarning` for `regex` → `pattern` in `node_briefing.py`
8. **Visual regression** — Not yet implemented (Track E3)
9. **Cache stampede protection** — Not yet implemented (Track E2)
10. **MCP quota** — Not yet implemented (Track E3)

---

## 15. Environment Variables Reference

See `backend/.env.example` (594 lines) for complete reference. Key categories:

- **Security:** `WORLDBASE_API_KEY`, `NODE_INGEST_TOKEN`, `NODE_ADMIN_TOKEN`, `WORLDBASE_BIND_HOST`
- **Rate Limiting:** `WORLDBASE_RATE_LIMIT`, `WORLDBASE_RATE_LIMIT_RPM`, `RATE_LIMIT_STORAGE`, `RATE_LIMIT_REDIS_URL`
- **LLM:** `NVIDIA_API_KEY`, `NVIDIA_BASE_URL`, `OLLAMA_HOST`, `WORLDBASE_CHAT_AGENTIC`
- **Feeds:** `WORLDBASE_FEED_INGEST_INTERVAL`, `WORLDBASE_NEWS_REFRESH_INTERVAL`, `WORLDBASE_NEWS_RSS_FEEDS`
- **Intelligence:** `WORLDBASE_QUERY_ROUTER`, `WORLDBASE_PROVENANCE`, `WORLDBASE_CONTEXT_BUDGET`
- **Briefing:** `WORLDBASE_BRIEFING_AUTOPILOT`, `WORLDBASE_BRIEFING_AGENTIC_LOOP`
- **Entity Resolution:** `WORLDBASE_ENTITY_RESOLUTION_PIPELINE`, `WORLDBASE_ENTITY_RESOLUTION_AUTOPILOT`
- **Compliance:** `WORLDBASE_GDPR`, `WORLDBASE_RETENTION`, `WORLDBASE_CLASSIFICATION`, `WORLDBASE_BITEMPORAL`
- **Visual:** `WORLDBASE_BLIP`, `WORLDBASE_COLQWEN2`, `WORLDBASE_SAR`
- **Voice:** `WORLDBASE_WHISPER_BRIDGE`, `WORLDBASE_TTS_BRIDGE`
- **MCP:** `WORLDBASE_MCP`, `WORLDBASE_MCP_WRITE`
- **Operator:** `WORLDBASE_OPERATOR_REGION`, `WORLDBASE_LAN`

---

*End of analysis.*
