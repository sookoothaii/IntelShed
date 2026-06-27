# AGENTS.md — WorldBase (PC stack)

> For AI coding agents. Operator docs: [`README.md`](README.md). Pi edge: [`offgrid-raspi/AGENTS.md`](offgrid-raspi/AGENTS.md).

---

## One sentence

**WorldBase** is a spatial intelligence workstation: React + Cesium globe, FastAPI with 30+ live feeds, local Ollama + NVIDIA NIM chat (6 providers), 3-layer anti-hallucination stack, FtM entity graph, 24h security briefing with agentic loop, and optional Pi↔PC sync for offline briefing on the edge node.

---

## Runtime (Windows dev)

| Service | URL | Notes |
|---------|-----|--------|
| **UI** | http://localhost:5176 | Always via Vite — not `:8002` for the HUD |
| **API** | http://127.0.0.1:8002 | OpenAPI: `/docs` |
| **Fast health** | `GET /api/health/ping` | Use before/after changes |
| **Ollama** | http://127.0.0.1:11434 | Default chat: `qwen3:8b` |
| **NVIDIA NIM** | https://integrate.api.nvidia.com/v1 | Free tier: `stepfun-ai/step-3.7-flash`; `NVIDIA_API_KEY` |
| **Start** | `.\start.ps1` | Waits for `/api/health/ping` before Vite (avoids proxy ECONNREFUSED); paths with spaces → `-LiteralPath`. Uvicorn reload excludes runtime DB/JSON files: `worldbase.db`, `data/entities.duckdb`, `data/ais_trajectory.db`, `data/intel_subgraph_latest.json` (literal paths, no globs) |
| **Verify** | `.\scripts\smoke-test.ps1` | 33 checks — run before claiming “done” (includes live feed envelope contract when API is up) |

Copy env: `backend\.env.example` → `backend\.env`, `frontend\.env.example` → `frontend\.env` (Cesium Ion token required for terrain/buildings).

---

## Current work focus (default)

Unless the user says otherwise, prioritize:

1. **24h security digest** — `backend/briefing_digest.py` + `backend/briefing_prompt.py` + `backend/node_briefing.py` (compat: `operator_briefing.py`, `node_sync.py`)
2. **Operator home region** — `WORLDBASE_OPERATOR_REGION=thailand` (LOCAL / REGION / GLOBAL buckets)
3. **GDELT local** — `backend/gdelt_bridge.py` → `/api/gdelt/pulse/local`, `/api/gdelt/geo/local`
4. **Pi pull loop** — PC generates briefing → Pi `GET /api/node/pull` → portal `briefing_latest.json`
5. **Intelligence UX** — FULL SITUATION overlay, SITUATIONS board, fusion hotspots in briefing, DATA → INTEL (ingest, feed sync, Splink resolution, Cytoscape overview)

**Track R (RAG / OSINT enhancement):** R0 + R1.1–R1.4 **shipped** — BGE reranker, ledger/NEWS ingest, spatial bbox, CRAG-lite chat CTX, adaptive YAML chunking, briefing agentic loop. **P1 Query Router shipped** — `query_router.py` (5 routes: vector/graph/spatial/hybrid/live, rule-based, 0 VRAM), `WORLDBASE_QUERY_ROUTER=1` (default on). **P4 Provenance shipped** — `provenance.py` (source reliability table, temporal decay, corroboration boost, conflict penalty; integrity in `digest_line_meta`, provenance in insight cards, source-weighted fusion cells), `WORLDBASE_PROVENANCE=1` (default on). **P3 Agentic Chat shipped** — `chat_agentic.py` (3-phase: coverage → retrieve → corroboration; gap detection, targeted retrieval via query router, `[corroborated]`/`[uncorroborated]` tags), `WORLDBASE_CHAT_AGENTIC=1` (default off, opt-in). **P3+ Multi-Agent Orchestrator shipped** — `agent_orchestrator.py` (5 agents: Coverage → Retrieval → Spatial → Corroboration → Synthesis; rule-based dispatcher, 0 VRAM; per-phase timeouts via `asyncio.wait_for`, circuit breaker per agent, phase timing `duration_ms`; fan-out/fan-in for Retrieval + Spatial; fail-soft; `agent_phase` action for HUD updates; MCP tools `worldbase_orchestrate` + `worldbase_agent_status`), `WORLDBASE_AGENT_ORCHESTRATOR=1` (default off, opt-in). **P2 Two-stage resolution shipped** — `entity_resolution.py` (per-dataset dedupe → cross-dataset link, `pipeline_mode=two_stage`, `list_datasets_for_schema()`), `WORLDBASE_ENTITY_RESOLUTION_PIPELINE=single` (default single, opt-in two_stage). **P2+ Dual-Pipeline shipped** — batch training (`train_model()`, `POST /train`), model persistence (`data/splink_model_{schema}.json`, `linker.misc.save_model_to_json`), adaptive loading (`_should_run_splink()` runs prediction with saved model even when `_SPLINK_ENABLED=0`), OSINT comparisons (`LevenshteinAtThresholds` on email, `JaroWinklerAtThresholds` on alias/weakAlias), Grauzonen endpoints (`GET /ambiguous`, `POST /label`), `resolution_labels` table for human-in-the-loop. Roadmap: [`docs/WORLDBASE_ROADMAP_2026.md`](docs/WORLDBASE_ROADMAP_2026.md). **P2++ Context Budget shipped** — `context_budget.py` (token budget per section: System 1.2k, Evidence 2.0k, RAG 1.5k, Aux 0.5k; provenance-based truncation: highest score first within category; refuse path when weighted quality < 0.35 → returns error without LLM call), `WORLDBASE_CONTEXT_BUDGET=1` (default on). **News feeds background ingest shipped** — `news_feeds.py` (ReliefWeb + RSS fetching moved out of chat request path; background autopilot refreshes every 10 min via `lifespan.py`; `chat_context.py` reads from `runtime_cache`), `WORLDBASE_NEWS_REFRESH_INTERVAL=600` (default 10 min), `WORLDBASE_NEWS_RSS_FEEDS` (comma-separated `name|url` pairs).

**Sprint 1 — LLM Workplan shipped:** **P1 Blackboard** — `agent_blackboard.py` (structured `Blackboard` dataclass: `evidence_registry`, `claim_candidates`, `conflicts`, `extracted_entities`, `retrieval_decisions`, `temporal_timeline`; all 5 agents read/write the same instance; `GET /api/agent/status` includes `blackboard_enabled` + condensed state in orchestrate result), `WORLDBASE_BLACKBOARD=1` (default off, opt-in). **P7 Personas** — prompt prefixes per agent phase (Geospatial Analyst, Evidence Clerk, Spatial Intelligence Analyst, Red-Team Reviewer, Intelligence Editor; 0 VRAM, prompt-string only). **P3 Evidence Chains** — `[EVIDENCE-NNN]` IDs auto-assigned, confidence tags (HIGH ≥0.8 / MEDIUM ≥0.5 / LOW) from `provenance_score`, temporal timeline sorted by `retrieved_at`, evidence/conflict/timeline blocks injected into synthesis prompt. **P2 JSON Schema** — `report_schema.py` (structured JSON output with regex fallback parser: plain JSON, markdown fences, trailing prose, trailing commas, line-by-line; `build_report_from_blackboard()` deterministic path; `format_report_as_text()` fallback). **P4 Conflict Detection** — `conflict_detection.py` (existence + temporal conflicts only; ≥24h threshold for temporal; severity scaled by provenance; capped at top 5; fail-soft). Tests: `test_llm_workplan.py` (48 tests). Full suite: 1154 passed.

**Sprint 2 — LLM Workplan shipped:** **P5 Critique-Refine** — `agent_orchestrator.py` two-pass synthesis (draft → critique → revise; `_critique_agent()` checks 10-item coverage checklist + evidence/conflict refs; `_revise_synthesis()` targeted re-retrieval for gaps; `_is_analyze_command()` trigger), `WORLDBASE_TWO_PASS=1` (default off, opt-in, only fires on `/analyze` or analysis-class queries). `verify_claim` tool in `chat_tools.py` (RAG memory + DuckDuckGo instant answer API; rule-based confidence: HIGH/MEDIUM/LOW/unknown; fail-soft). **P6a Route Outcome Ledger** — `route_ledger.py` (`route_outcomes` SQLite table; `record_outcome()` per retrieval; lazy weight recompute at N=50 threshold; `get_route_weights()` boosts empirically successful routes in `classify_query()`; `get_route_stats()` summary), `WORLDBASE_ROUTE_LEDGER=1` (default on). **P6c Evaluation Harness** — `test_chat_report_quality.py` (15 golden queries covering all 5 routes; regex/keyword checks: `[EVIDENCE-NNN]` refs, source tags, confidence tags, section headers, min block length; `check_report_quality()` function; orchestrator integration tests). Tests: `test_llm_workplan.py` (62 tests, +14 new), `test_route_ledger.py` (9 tests), `test_chat_report_quality.py` (21 tests). Full suite: 1216 passed.

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
| Latest text | `GET /api/briefing` — text, `digest`, `intel`, `quality`, `fusion_hotspots`, `digest_line_meta`, `watch_items`, `agentic`, **`insights`** |
| **Insight cards (Track A)** | `GET /api/insights?top=5` — fusion-ranked cards; narrated when Ollama up; in briefing + SITUATIONS — `backend/insights.py` |
| Force generate | `POST /api/briefing/generate` — header `X-API-Key` when `WORLDBASE_API_KEY` is set; `?force=1` bypasses snapshot cache |
| **Prediction ledger** | `quality.meta.prediction_accuracy_30d` / `prediction_pending` — watch outcomes after horizon; `backend/prediction_ledger.py` |
| **FtM subgraph** | `GET /api/intel/subgraph?hops=2&bbox=` — 2-hop graph around operator bbox; briefing prompt `INTEL SUBGRAPH` block; **temporal edge decay** (`decayed_confidence`, `decay_weight`, `age_days` per edge; `WORLDBASE_INTEL_EDGE_DECAY_DAYS=30` half-life; stale edges tagged in prompt) |
| **Spatial proximity edges** | `POST /api/intel/spatial/run` — rebuild `nearby` links after feed ingest (Track 3+) |
| **Spatial reasoning (P6)** | Chat tool + `GET /api/intel/spatial/query?q=within%2050km%20of%20Bangkok` — NL → spatial operation → FtM entities; `WORLDBASE_SPATIAL_REASONING=1` (default off, opt-in) |
| **Semantic intel edges** | `POST /api/intel/semantic/run` — colocated (`samePlace`), vessel-near-event (`nearEvent`), **cross-feed event correlation** (`relatedEvent`: text overlap + spatial proximity between Event/Thing from different feeds); sanctions screening; `WORLDBASE_INTEL_SEMANTIC_EDGES=1` (default on) |
| FtM → digest bridge | `backend/intel_briefing.py` |
| Autopilot | `WORLDBASE_BRIEFING_AUTOPILOT=1`, interval `WORLDBASE_BRIEFING_INTERVAL` (default 6 h) |
| FtM in digest | `WORLDBASE_BRIEFING_INTEL=1` (default), excludes `Airplane` by default |
| NewsData digest slots | `WORLDBASE_BRIEFING_NEWSDATA_SLOTS=2` (default) — reserved `News:` lines survive severity cap |
| NewsData / GDELT noise | Sports, entertainment, and celebrity headlines filtered before digest (`newsdata_bridge.is_sports_content`); tourism/local economy (e.g. Songkran) kept when situational |
| German output | `WORLDBASE_BRIEFING_LANG=de` (UI strings stay English) |
| Pi payload | `GET /api/node/pull` — v3: delta sync (`?since=` + `X-Briefing-Hash`), gzip, `intel_delta` (`nodes_added`/`edges_added`); v2 fallback (ETag/304, SHA-256, `intel_subgraph`); `WORLDBASE_NODE_PULL_DELTA=1` (default on) |
| **Trust probes** | `GET /api/trust` — field score 0–4 (briefing, GDELT, Ollama, Pi edge) + `feed_drift` freshness (connector provenance) |
| **CAMS haze (Thailand/ASEAN)** | `GET /api/cams/haze` — PM2.5, dust, AOD via Open-Meteo/CAMS; feeds briefing LOCAL |
| **HDX humanitarian** | `GET /api/humanitarian` — UN OCHA datasets (Myanmar border, displacement); briefing REGION |
| **NewsData.io (optional)** | `GET /api/newsdata`, `GET /api/newsdata/sources` — headlines complement GDELT; corroboration family `newsdata`; Free tier ~12h delay; `NEWSDATA_API_KEY` |
| **Dark Web / Darknet (P8)** | `GET /api/darkweb?q=...` — Ahmia/DarkSearch by default; optional Tor engines; `GET /api/darkweb/engines`, `GET /api/darkweb/mentions`, `GET /api/darkweb/entities?q=...`; `POST /api/darkweb/ingest`, `POST /api/darkweb/scrape`, `POST /api/darkweb/deep_search`; ransomware leak-site intel via `GET /api/darkweb/ransomware/groups`, `GET /api/darkweb/ransomware/victims`, `POST /api/darkweb/ransomware/refresh`, `POST /api/darkweb/ransomware/ingest`; ransomware briefing block (max 5 lines, FTM-correlation prioritised) when `WORLDBASE_BRIEFING_RANSOMWARE=1`; DATA → **DARKWEB** tab + globe layer; `WORLDBASE_DARKWEB=1`, `WORLDBASE_BRIEFING_DARKWEB=1`, `WORLDBASE_RANSOMWARE=1`; docs → [`docs/DARKWEB.md`](docs/DARKWEB.md) |
| **Maritime AIS** | `GET /api/maritime` — background AISstream WebSocket when `AISSTREAM_API_KEY` set (`stream_connected`, `stream_buffer` in JSON); MyShipTracking/AISHub fallback; Thailand corridor default |
| **Maritime Anomaly Detection (P7)** | `GET /api/maritime/anomalies`, `GET /api/maritime/trajectory/{mmsi}`, `GET /api/maritime/trajectory/stats` — AIS trajectory storage (`data/ais_trajectory.db`), behavioural anomaly detection (speed variance, AIS gaps >2h, night port visits, course changes >15°, risk zone proximity); in-memory ringbuffer + batch flush; `WORLDBASE_MARITIME_TRAJECTORY=1` (default off), `WORLDBASE_MARITIME_ANOMALY_THRESHOLD=0.6`; briefing bridge (`backend/maritime_briefing.py`) → MARITIME ANOMALIES block in prompt + watch items + FtM Vessel correlation by MMSI; `digest.maritime` exposed in `/api/briefing`; section hints require the block in generated text even when no anomalies; lifespan background task flushes ringbuffer + prunes old positions every 5 min; `backend/ais_trajectory.py`. **Bugfix (2026-06-26):** `start.ps1` / `main.py` reload-exclude patterns now use literal paths to prevent PowerShell glob expansion; `ais_bridge.py` route ordering fixed (`/trajectory/stats` before `/trajectory/{mmsi}`). **Live verified:** 1,064 positions, 223 vessels, briefing text includes maritime block. |
| **STAC feed snapshots** | `GET /api/stac/feeds/collection`, `GET /api/stac/feeds/items` — connector cache as STAC Items with bbox/geometry, registry links; DATA → **FEEDS** tab: STAC JSON + ⊕ fly-to |
| **Satellite Change Detection (K4)** | `GET /api/satellite/health`, `GET /api/satellite/change` — Sentinel-2 L2A COG window-read, NDVI/NDWI differencing, GeoJSON anomaly polygons; `WORLDBASE_SATELLITE_CHANGE=1` (default on); `backend/satellite_change.py`; DATA → **SATELLITE** tab |
| **Connectors** | `GET /api/connectors` — manifest catalog + cache overlay; export via `scripts/export_connectors.py` |
| **MCP (Cursor)** | Streamable HTTP `http://127.0.0.1:8002/api/mcp` — 13 tools when Agent Bus on — [`docs/MCP.md`](docs/MCP.md) |
| **Agent Bus** | `POST /api/agent/publish`, `GET /api/agent/stream` — globe fly/layer when HUD open — [`docs/MCP.md`](docs/MCP.md#agent-bus) |
| **FtM globe layer** | `GET /api/intel/entities?geolocated=1` → HUD **INTEL** toggle (`intelFt`) — [`docs/GLOBE.md`](docs/GLOBE.md#intel-ftm-globe-layer) |
| **DuckDB Write Queue** | `WORLDBASE_DUCKDB_QUEUE=1` — serializes all DuckDB writes via SQLite WAL + retry + DLQ; `GET /api/intel/queue/status`, `GET /api/admin/dlq` — `backend/duckdb_queue.py` |
| **Dynamic Feature Flags** | `GET /api/admin/flags`, `POST /api/admin/flags/{key}`, `GET /api/admin/flags/log` — SQLite-backed runtime toggles with 5s cache + audit log; `WORLDBASE_ADMIN_FLAGS=1` (default on), `WORLDBASE_FLAG_OVERRIDE=env` forces env-only; DATA → **FLAGS** tab — `backend/features.py` |
| **Document Export** | `GET /api/briefing/export?format=pdf` / `?format=docx` / `?format=pptx` — downloadable briefing report (reportlab + python-docx + python-pptx, 0 VRAM); `GET /api/connectors/export?format=xlsx` — feed status spreadsheet (openpyxl); FULL SITUATION → PDF / DOCX / PPTX buttons next to GENERATE — `backend/doc_export.py` |
| **Error Boundaries (J3)** | `ErrorBoundary` wraps Globe, Map, IntelGraph, FullAnalysis; Cesium `scene.renderError` → fallback UI + auto-retry (3×/3s); `POST /api/telemetry/frontend-error` — crash ingestion with structured log; `useCesiumErrorHandler` hook — `frontend/src/components/ErrorBoundary.tsx`, `frontend/src/hooks/useCesiumErrorHandler.ts` |
| **Prometheus metrics (I4)** | `GET /api/metrics` — 16 gauges + `health_check_duration_seconds` histogram; `WORLDBASE_METRICS=1` (default on) — `backend/metrics.py` |
| **Webhook alerting (I4)** | Briefing autopilot fires alerts when `trust_score<3`, `feed_stale>feed_fresh`, `duckdb_queue_backlog>40`; dedup via `alert_dedup` SQLite table (15 min per condition); `WORLDBASE_ALERT_WEBHOOK` (Discord/Slack/Telegram compatible) — `backend/alerting.py` |
| **OpenTelemetry tracing (I4)** | Auto-instruments FastAPI routes; `OTEL_EXPORTER_OTLP_ENDPOINT` + `WORLDBASE_OTEL=1` (default off); requires `opentelemetry-instrumentation-fastapi` — `backend/telemetry_otel.py` |
| **API Quota & Cost (J5)** | `GET /api/quota` — per-source daily usage, limits, cost est, 7-day trend; hard stop at 100% (feed → stale); alert at 80%; `WORLDBASE_QUOTA_MONITOR=1` (default on), `WORLDBASE_QUOTA_LIMIT_{SOURCE}` env overrides — `backend/quota_monitor.py` |
| **Prompt Injection Defense (J7)** | 3-layer defense-in-depth: **Layer 0** `prompt_guard.py` — regex input scan + NFKD/leetspeak/homoglyph normalization; **Layer 1** `rag_integrity.py` — RAG context integrity guard (scans briefing/feed/FtM chunks before LLM injection; weighted patterns + keyword density + context adjustment); **Layer 2** `session_guard.py` — SQLite-persisted multi-turn session state (roleplay/game/authority/emotional scoring with exponential decay); **Layer 3** `output_guard.py` — post-LLM leak prevention (system prompt leak, secret pattern detection, echo attack, forbidden tags); `WORLDBASE_SESSION_GUARD=1` (default on), `WORLDBASE_OUTPUT_GUARD=1` (default on); integrated in `chat_proxy.py` `_prepare_chat_messages()` + response path — `backend/test_prompt_security.py` (78 fixtures, 96.2% combined block rate) |
| **Mapping Schema Drift (J8)** | `POST /api/intel/feeds/validate`, `GET /api/intel/feeds/validate` — validates YAML mappings against JSON schemas in `backend/ingest/schemas/`; detects unmapped required fields, unknown fields, broken link refs; runtime `detect_payload_drift()` on feed ingest flags field renames; `GET /api/trust` shows `mapping_drift` per feed (ok/warning/error); `WORLDBASE_MAPPING_VALIDATOR=1` (default on); CI runs `mapping_validator.validate_all_mappings()` in backend-quality job — `backend/mapping_validator.py`, `backend/ingest/schemas/*.json` |
| **Context Budget (P2++)** | `context_budget.py` — token budget per section (System 1.2k, Evidence 2.0k, RAG 1.5k, Aux 0.5k); provenance-based truncation (highest score first); refuse path when weighted quality < 0.35 → returns error without LLM call; `WORLDBASE_CONTEXT_BUDGET=1` (default on); integrated in `chat_proxy.py` `_prepare_chat_messages()` |
| **News feeds background ingest** | `news_feeds.py` — ReliefWeb + RSS fetching moved out of chat request path; background autopilot refreshes every 10 min via `lifespan.py`; `chat_context.py` reads from `runtime_cache`; `WORLDBASE_NEWS_REFRESH_INTERVAL=600` (default 10 min), `WORLDBASE_NEWS_RSS_FEEDS` (comma-separated `name|url` pairs) |
| **Docker MCP setup** | `.\scripts\setup-docker-mcp-worldbase.ps1` — fetch + database-server profile |
| Deploy Pi scripts | `.\scripts\deploy-pi-sync.ps1` — see `offgrid-raspi/docs/WORLDBASE_PI_SYNC.md` |
| Pi runtime data | `world.json` not in Git — `offgrid-raspi/offgrid/content/RUNTIME.md`; inline geo in `world.json` |

Unit tests (no network): `python -m unittest test_mcp_tools test_agent_bus test_connector_registry test_briefing_quality test_operator_briefing test_briefing_agentic test_chat_agentic test_intel_briefing test_intel_subgraph test_intel_proximity test_intel_semantic_links test_prediction_ledger test_prediction_ground_truth test_corroboration_ground_truth test_subgraph_prompt_ground_truth test_newsdata_bridge test_ftm_store test_feed_ingest test_gdelt_bridge test_stac_feeds test_ais_bridge test_feed_envelope_contract test_chat_routing test_firewall_bridge test_prompt_guard test_prompt_security test_mapping_validator test_cams_bridge test_fusion_snapshots test_rag_rerank test_rag_spatial test_rag_crag test_rag_memory test_rag_chunking test_query_router test_provenance test_insights test_agent_orchestrator test_osint_tools test_freshness test_runtime_cache test_core_feeds_security test_model_cookbook test_entity_resolution test_entity_resolution_pipeline test_entity_resolution_dual_pipeline test_context_budget test_news_feeds test_duckdb_queue test_feature_flags test_config test_structured_log test_metrics_alerting test_quota_monitor test_async_db -v` in `backend/`. Optional: `pip install sentence-transformers` when `RAG_RERANK=1`.

Ground-truth pilots (offline): `python corroboration_ground_truth.py --fixtures`, `python prediction_ground_truth.py --fixtures`, `python subgraph_prompt_ground_truth.py --fixtures`; wrappers `.\scripts\corroboration-ground-truth-pilot.ps1`, `.\scripts\prediction-ground-truth-pilot.ps1`, `.\scripts\subgraph-prompt-ab-pilot.ps1`, `.\scripts\fusion-baseline-status.ps1`.

| Pilot | Measures | Live when |
|-------|----------|-----------|
| B-03 `prediction_ground_truth.py` | Watch-item hit/miss rules | Horizons elapsed (`prediction_pending` drops) |
| B-04 `corroboration_ground_truth.py` | Digest corroboration scores | `GET /api/briefing` → `digest_line_meta` |
| B-05 `subgraph_prompt_ground_truth.py` | Flat vs subgraph prompt chars + overlap | API-only (`/api/briefing` + `/api/intel/subgraph`) |
| B-06 `fusion-baseline-status.ps1` | Fusion grid snapshots vs 28 target | `GET /api/trust` → `fusion_compare` |

**B-06 note:** Snapshots accumulate when `GET /api/fusion/heatmap` runs (briefing/autopilot path) at most every 6 h (`fusion_heatmap.record_snapshot_if_due`). `fusion_compare.available=false` + `no recent grid cache` until first heatmap fetch after cold boot; baseline compare needs snapshots ≥24 h apart.

**B-05 note:** Subgraph prompt can be **larger** than flat when edge count is high (edge lines dominate). Prompt format caps: 24 nodes / 20 edges in `format_subgraph_prompt_block`; graph build caps via `WORLDBASE_INTEL_SUBGRAPH_NODE_LIMIT` (default 80).

**Firewall probe:** `.\scripts\firewall-probe.ps1` — slim guard regression (not in smoke test §1).

Live contract (opt-in, gated in smoke test §1 when `:8002` is up): `python -m unittest test_health_contract_live -v` — validates `/api/health` feed rows + curated envelope payloads (`cve`, `wildfires`, `gdacs`, …). Skips cleanly if API down.

Feed envelope contract: `backend/feeds/envelope.py` — shared validation for Phase 0/2; smoke test calls `test_health_contract_live`, not duplicated PowerShell logic.

Freshness classification: `backend/freshness.py` — `classify_freshness(age_sec, ttl_sec, error, stale_flag, has_payload, vocab)` is the single source of truth. Two vocabularies: `drift` (fresh/aging/stale/error/missing) for `feed_drift.py` + `trust_probes.py`, `health` (fresh/warn/stale/unknown) for `health.py`. Error takes precedence over stale-flag, which takes precedence over age.

On startup, `ais_bridge.start_aisstream_collector()` runs when `AISSTREAM_API_KEY` is set; `_stack_warmup()` (~6 s after boot) refreshes GDELT **local + global** pulse, traffic cams, maritime, CAMS haze, air quality, and Bangkok weather. Global pulse persists to `feed_registry` key `gdelt_pulse_global`.

---

## Key files

| Area | Path |
|------|------|
| App shell + FULL SITUATION | `frontend/src/App.tsx` |
| **NEWS tab** | `frontend/src/components/NewsPanel.tsx` — nav **NEWS** (NewsData + GDELT); replaces top-level FIREWALL tab |
| Globe + layers + click-to-detail | `frontend/src/components/Globe.tsx`, `GlobeDetailModal.tsx`, `frontend/src/hooks/layers/` |
| FtM globe layer | `frontend/src/hooks/layers/useIntelLayer.ts` — toggle **INTEL** in telemetry |
| Agent Bus HUD | `frontend/src/hooks/useAgentBus.ts`, `frontend/src/lib/agentBus.ts` |
| Globe terrain fail-soft | `frontend/src/lib/cesiumTerrain.ts` |
| Traffic cams | `backend/traffic_bridge.py`, `useTrafficCamsLayer.ts`, `TrafficCamPanel.tsx` |
| Webcams → globe stream | `backend/webcam_bridge.py`, `WebcamSection.tsx`, `WebcamStreamPanel.tsx` |
| Credential registry | `backend/credentials/registry.py`, `GET /api/credentials/status` |
| HUD styles | `frontend/src/styles/hud.css` |
| Feeds + cache | `backend/feeds_extra.py`, `backend/feed_registry.py`, `backend/connector_registry.py`, `backend/feeds/envelope.py`, `backend/feeds/runner.py` (FeedConnector) |
| Node sync + briefing routes | `backend/node_sync.py` (compat), `backend/node_ingest.py` (telemetry/SSE/mesh), `backend/node_briefing.py` (snapshot/LLM/pull), `backend/briefing_quality.py`, `backend/trust_probes.py` |
| MCP + Agent Bus | `backend/mcp_server.py`, `backend/agent_bus.py`, [`docs/MCP.md`](docs/MCP.md) |
| Operator digest | `backend/operator_briefing.py` (compat), `backend/briefing_digest.py` (classification/watch items), `backend/briefing_prompt.py` (LLM prompt/fallback) |
| FtM → 24h briefing | `backend/intel_briefing.py` |
| FtM subgraph (Track 3) | `backend/intel_subgraph.py` — `GET /api/intel/subgraph`; **temporal edge decay** (`decay_weight()`, `WORLDBASE_INTEL_EDGE_DECAY_DAYS=30`) |
| Spatial proximity (Track 3+) | `backend/intel_proximity.py` — `POST /api/intel/spatial/run`; runs after feed ingest when `WORLDBASE_INTEL_SPATIAL_EDGES=1` |
| Semantic intel edges (Track 3+) | `backend/intel_semantic_links.py` — colocated, vessel-near-event, **cross-feed event correlation** (`relatedEvent`), sanctions; `POST /api/intel/semantic/run`; `WORLDBASE_INTEL_SEMANTIC_EDGES=1` (default on) |
| Prediction ledger (Track 4) | `backend/prediction_ledger.py` |
| GDELT | `backend/gdelt_bridge.py` — adaptive backoff, region-first priority, stale-while-revalidate; local pulse `gdelt_pulse_local:{region}`; **global** pulse disk key `gdelt_pulse_global` + `warmup_global_pulse()` |
| CAMS haze | `backend/cams_bridge.py` — Open-Meteo/CAMS dust + AOD for Thailand/ASEAN cities |
| Humanitarian (HDX) | `backend/humanitarian_bridge.py` — CKAN search for Southeast Asia crises |
| NewsData headlines | `backend/newsdata_bridge.py` — optional API key; briefing + corroboration family |
| **Dark Web / Darknet OSINT (P8)** | `backend/darkweb_bridge.py` + `frontend/src/components/DarkwebPanel.tsx` + `frontend/src/hooks/layers/useDarkwebLayer.ts` + `frontend/src/lib/darkwebApi.ts` — Ahmia/DarkSearch + optional Tor engines; entity extraction; briefing block + insight cards; DATA → **DARKWEB** tab + globe layer; docs → [`docs/DARKWEB.md`](docs/DARKWEB.md) |
| Ground-truth pilots | `backend/corroboration_ground_truth.py`, `backend/prediction_ground_truth.py`, `backend/subgraph_prompt_ground_truth.py` |
| Maritime AIS | `backend/ais_bridge.py` — persistent AISstream collector + MyShipTracking; Malacca / Laem Chabang / Bangkok / Phuket / Singapore when operator region is Thailand |
| Feed drift | `backend/feed_drift.py` — count snapshots + freshness in `/api/trust`; uses `freshness.classify_freshness()` |
| **Freshness classifier** | `backend/freshness.py` — shared `classify_freshness()` with `drift` and `health` vocabularies; consumed by `health.py`, `feed_drift.py` |
| **Core feeds** | `backend/routes/core_feeds.py` — earthquakes + events via `FeedConnector.run()`; satellites/ISS/world via `runtime_cache` |
| STAC (imagery + feeds) | `backend/stac_bridge.py` — Element84 search + connector feed ItemCollection (bbox, geometry, registry links) |
| Connector + feed status UI | `frontend/src/components/FeedsStatusPanel.tsx` — DATA → FEEDS: registry, STAC links, globe fly-to |
| Fusion → briefing | `backend/fusion_heatmap.py` |
| Chat + LLM proxy | `backend/routes/chat.py` (compat), `backend/chat_context.py` (context builder + search), `backend/chat_proxy.py` (models/chat/providers), `backend/chat_context_enricher.py` (query-aware enrichment) — 6 providers: ollama, openai, anthropic, groq, openrouter, **nvidia** (NIM, OpenAI-compatible); `NVIDIA_API_KEY`, `NVIDIA_BASE_URL` (default `https://integrate.api.nvidia.com/v1`); models: `deepseek-ai/deepseek-v4-flash`, **`stepfun-ai/step-3.7-flash`** (fast tool-use, ~6-8s for `focus_globe` geocoding), `qwen/qwen3.5-122b-a10b`, `qwen/qwen3.5-397b-a17b`; `WORLDBASE_CHAT_PROVIDER=nvidia` + `WORLDBASE_CHAT_MODEL=stepfun-ai/step-3.7-flash`. **Chat tools:** `backend/chat_tools.py` — `focus_globe` (place geocoding via OpenStreetMap Nominatim; ignores LLM-guessed lat/lon when `place` provided), `geocode_place` (standalone geocoding), `spatial_query`, `entity_context`; MCP `worldbase_globe_fly_to` mirrors `focus_globe` with geocoding. **Query-aware context enrichment:** `chat_context_enricher.py` — `enrich_query_context(query)` extracts entities (places, event types, keywords) from user query → filters live feed caches (quakes, ReliefWeb, GDELT local, fusion hotspots) → injects relevant data into chat context; async enrichers (`_enrich_gdelt`, `_enrich_fusion_hotspots`) call bridge functions directly; synthesis directive with SATs, evidence weighting, red-team review, actionable intelligence injected when enriched context present; `GET /api/chat/context?q=...` for smoke testing. **Anti-Hallucination Stack (3 layers):** (1) **Prompt Protocol** — positive "RAW DATA INTERPRETER" role replaces 11 negative rules; explicit `AVAILABLE CONTEXT BLOCKS:` list in system prompt; 6-point protocol (answer first, source discipline, no fabrication, no source name-dropping, honesty over confidence, concise); entity-specific protocol block when globe entity selected. (2) **NIM Parameter Tweaks** — NVIDIA provider gets `temperature=0.15`, `top_p=0.4`, `max_tokens=2048` (1024 fast) to reduce reasoning-model creativity; other providers keep defaults. (3) **Claim Auditor** — `_claim_auditor()` post-generation verification (0 VRAM, CPU string-matching): checks response for source names (GDELT, USGS, ReliefWeb, etc.), URLs, and timestamps not present in context blocks; appends `⚠ CLAIM AUDITOR WARNING` with violation list; wired into all 4 non-streaming response paths (Ollama tools/plain, External tools/plain); meta in `firewall_result.claim_auditor`. **NVIDIA stream fix:** empty `choices: []` chunks handled via `or [{}]` pattern. |
| RAG memory | `backend/rag_memory.py`, `rag_hybrid.py`, `rag_rerank.py`, `rag_spatial.py`, `rag_crag.py` — hybrid RRF + optional BGE rerank; `GET /api/memory/search?spatial=1`, `GET /api/memory/stats` |
| **Query Router (P1)** | `backend/query_router.py` — 5 routes (vector/graph/spatial/hybrid/live), rule-based classification, 0 VRAM; `WORLDBASE_QUERY_ROUTER=1` (default on) |
| **Provenance (P4)** | `backend/provenance.py` — source reliability table (30+ feeds), temporal decay (6h half-life), corroboration boost, conflict penalty, ingestion chain hash; `WORLDBASE_PROVENANCE=1` (default on) |
| **Agentic Chat (P3)** | `backend/chat_agentic.py` — 3-phase chat loop (coverage → retrieve → corroboration); gap detection, targeted retrieval via query router, `[corroborated]`/`[uncorroborated]` tags; `WORLDBASE_CHAT_AGENTIC=1` (default off, opt-in) |
| **Multi-Agent Orchestrator (P3+)** | `backend/agent_orchestrator.py` — 5 agents (Coverage/Retrieval/Spatial/Corroboration/Synthesis), rule-based dispatcher (0 VRAM), per-phase timeouts, circuit breaker, phase timing; MCP tools `worldbase_orchestrate` + `worldbase_agent_status`; `WORLDBASE_AGENT_ORCHESTRATOR=1` (default off, opt-in) |
| **Model Cookbook (5.2)** | `backend/model_cookbook.py` — `GET /api/models/cookbook` — scans nvidia-smi VRAM + Ollama models, recommends model + num_ctx; 0 VRAM |
| FtM entity store | `backend/ftm_store.py` (compat), `backend/ftm_connection.py` (DuckDB conn + recovery), `backend/ftm_schema.py` (DDL + index drift), `backend/ftm_query.py` (CRUD/graph/briefing), `backend/ftm_sanctions.py` (OpenSanctions adapter), `backend/routes/ftm_api.py` (9 HTTP endpoints) |
| Document intel ingest (GLiNER; GLiREL opt-in) | `backend/intel_ingest.py`, [`docs/INTEL_INGEST.md`](docs/INTEL_INGEST.md), [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) |
| Entity resolution (exact + subset + optional Splink) | `backend/entity_resolution.py` — `POST /api/intel/resolution/run`, `POST /api/intel/resolution/train`, `GET /api/intel/resolution/ambiguous`, `POST /api/intel/resolution/label` |
| Live feed ingest (T2 YAML mappings) | `backend/feed_ingest.py`, `backend/ingest/mappings/` — `POST /api/intel/feeds/run` |
| INTEL graph panel | `frontend/src/components/IntelGraphPanel.tsx` |
| **OSINT reference toolkit** | `frontend/src/lib/osintToolkit.ts`, `OsintReferencePanel.tsx` — [`docs/OSINT_TOOLKIT.md`](docs/OSINT_TOOLKIT.md) |
| **HUD tab persistence** | `frontend/src/lib/hudSessionState.ts` — `sessionStorage`, same browser tab |
| **Insight synthesis (Track A)** | `backend/insights.py`, `SituationBoard.tsx` insight cards |
| Pi edge dashboard (DATA → EDGE) | `frontend/src/components/EdgePanel.tsx` — primary node `offgrid-pi`, sparklines via `/api/node/{id}/sensors/history` |
| Edge online/offline banner | `frontend/src/components/NodeHealthBanner.tsx` |
| HAK_GAL firewall bridge (optional) | `backend/firewall_bridge.py`, `backend/prompt_guard.py`, `docs/FIREWALL.md` |
| DB | `backend/worldbase.db`, `backend/data/entities.duckdb` — FtM: single writer (one API process); `reset_store()` on DuckDB FATAL (B-02 light) |
| **Backup** | `scripts/backup.ps1` — SQLite VACUUM INTO + DuckDB file copy + fusion parquet + subgraph JSON + TLE; `docs/BACKUP.md` restore guide |
| **Structured logging** | `backend/structured_log.py` — `StructuredLogger` (JSON output, secret redaction), `get_logger()`; replaces `print()` in lifespan, bootstrap_env, mcp_server, ftm_connection, rag_memory, aircraft routes |
| **Config central** | `backend/config.py` — `WorldBaseConfig` (Pydantic frozen), `get_config()` singleton with `@lru_cache`; fields for feed_ingest, briefing, entity_resolution, operator_region |

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

- PC: `backend/node_ingest.py` (was `node_sync.py`), `scripts/deploy-pi-sync.ps1`
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
| Sporadic API 500 `No response returned` on HUD poll | Uvicorn `--reload` restarting on SQLite WAL writes — use `.\start.ps1` (excludes `worldbase.db*` / `data/*.duckdb`); transient during hot reload otherwise |
| RAG rerank slow first search | BGE model cold load on CPU (~60–90 s first hit); `RAG_RERANK=1` + `pip install sentence-transformers` |
| Chat 401 with `WORLDBASE_API_KEY` set | Pass header `X-API-Key` on `POST /api/chat` |
| Briefing empty | `POST /api/briefing/generate`; check Ollama |
| LOCAL block thin | GDELT rate limits; verify `/api/gdelt/pulse/local` (stale cache with `count>0` still counts for trust/quality); also `/api/cams/haze`, `/api/humanitarian`, `/api/airquality` in briefing snapshot |
| Maritime layer empty | Set `AISSTREAM_API_KEY` in `backend/.env` and restart; expect `stream_connected=true` and `count` growing after ~30 s. No synthetic demo vessels — empty means upstream silent. Default regions: Malacca, Laem Chabang, Bangkok Port, Phuket, Singapore (`WORLDBASE_MARITIME_REGIONS=all` for global ports). Disable background collector: `WORLDBASE_MARITIME_AISSTREAM=0` |
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
| Pi pull stale after PC upgrade | `.\scripts\deploy-pi-sync.ps1`; verify `payload_version: 3` in pull JSON (v2 when no `?since=`); if deploy stops at sudo, run Pi one-liner in [`offgrid-raspi/docs/WORLDBASE_PI_SYNC.md`](offgrid-raspi/docs/WORLDBASE_PI_SYNC.md) |
| Portal shows local `world_brief` not PC briefing | Check `/var/lib/offgrid/briefing_latest.json`; pull log for `304 but cache missing/empty` (fixed `51f3e8c` — redeploy pull script); `grep _cache_has_briefing /usr/local/bin/worldbase_pull.py` → expect `2` |
| PC node_state stale after Pi reboot | Stale push buffer replay (fixed `51f3e8c` — push deletes buffer after `Ingest OK`); `sudo rm -f /var/lib/offgrid/worldbase_push_buffer.jsonl` + restart push |
| Pi push timeout storm | Deploy latest `worldbase_push.py` — exponential backoff + 45 s POST timeout; log `Ingest FAILED (streak=N) — backoff …` |
| Briefing generate timeout (PS) | Client `-TimeoutSec 600`; server may still finish — check `GET /api/briefing` → `created_at` |
| Firewall chat block / unreachable | `GET /api/firewall/status`; HAK_GAL on `:8001`; chat needs `firewall: true` + `chat_session_id`; see [`docs/FIREWALL.md`](docs/FIREWALL.md) |
