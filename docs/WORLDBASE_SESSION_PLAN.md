# WorldBase V4 — Aufgabenplan nach Sessions (~200k Tokens pro Session)

> **Quellen:** `docs/WORLDBASE_ROADMAP_V4.md` + `research/WORLDBASE_RESEARCH_CONSOLIDATED.md` + WorldMonitor-Vergleich (2026-06-30)
> **Stand:** 2026-06-30  
> **Annahme:** Eine Session = ~200k Token Kontextfenster. Jede Aufgabe ist so geschnitten, dass sie in eine Session passt (Code + Dokumentation + Tests + Review).  
> **Konventionen:** venv-Python, feature flags default off, fail-soft, Unit-Tests vor Merge, Pi-Sync beachten, Backend-Neustart explizit kommunizieren.

---

## Hinweis zu V4-23 Anomaly Detection

Widersprüchlicher Status:
- `WORLDBASE_RESEARCH_CONSOLIDATED.md` §2: **V4-23 shipped** (2026-06-30)
- `WORLDBASE_ROADMAP_V4.md` Sprint 1: **V4-23 TODO**

**Empfohlene erste Sub-Aufgabe in Session 3:** Code-Status verifizieren (`backend/anomaly_detector.py`, Feature-Flag `WORLDBASE_ANOMALY_DETECTION`, Briefing-Block). Falls shipped, Status in Roadmap aktualisieren; falls lückenhaft, vervollständigen.

---

## Session 1 — Foundation & Quick Wins (Frontend-Perf + Feed-Resilienz + MCP-Schema) ✅ shipped

**Ziel:** Mehrere kleine, unabhängige V4-Items mit hohem ROI auf einmal abarbeiten.

**V4-Items:**
- V4-44 MCP `outputSchema` + JMESPath Projection
- V4-45 Bootstrap Hydration Endpoint
- V4-64 Feed Circuit Breaker (ETag + exponential backoff)

**Deliverables:**
- `backend/mcp_schema.py` + `backend/mcp_jmespath.py` + Integration in `mcp_server.py`
- `backend/bootstrap.py` + Redis-Cache + `GET /api/bootstrap`
- `backend/feed_circuit_breaker.py` + ETag-Tracking in Feed-Autopilot
- Tests: `test_mcp_schema.py`, `test_bootstrap.py`, `test_feed_circuit_breaker.py`
- Frontend: `bootstrapApi.ts`, Anpassung `App.tsx` für initialen Hydration-Call
- Docs: `docs/MCP.md`, `docs/FEEDS.md` aktualisieren

**Abhängigkeiten:** keine (baut auf bereits shipped MCP-Server / Redis / Feed-Autopilot auf)

---

## Session 2 — Regionale Datenquellen erweitern (ACLED + Lightning + Wetter + OSM) ✅ shipped

**Ziel:** Antizipationsfähigkeit für Thailand/ASEAN verbessern; kostenlose, key-lose APIs.

**V4-Items:**
- V4-16 ACLED Connector
- V4-54 Lightning Detection Bridge
- V4-55 OSM Critical Infrastructure POIs
- V4-56 Multi-Day Weather Forecast

**Deliverables:**
- `backend/acled_bridge.py` + `GET /api/acled/events` + Briefing-Block
- `backend/lightning_bridge.py` (Blitzortung/LightningMaps) + Cesium-Layer
- `backend/osm_bridge.py` (Overpass API) + `GET /api/osm/infrastructure`
- `backend/weather_forecast_bridge.py` (Open-Meteo) + `GET /api/weather/forecast`
- FtM-Ingest für Address / Organization / Event
- Frontend: Cesium-Layer für Blitze + OSM-POIs + Wetter-Panel
- Tests: je `test_*.py`, Smoke-Test-Erweiterung

**Abhängigkeiten:** keine

---

## Session 3 — Anomalie, Graph-Algorithmen & Fusion-Delta  ✅ shipped

**Ziel:** Aus Snapshot-Archiver (V4-09 ✅) und FtM-Graph operationelle Intelligenz generieren.

**V4-Items:**
- V4-23 Anomaly Detection (Status klären)
- V4-24 Graph Algorithms (NetworkX)
- V4-52 Fusion Delta Grid (24h Compare)

**Deliverables:**
- Status-Check V4-23; ggf. `backend/anomaly_detector.py` finalisieren + Autopilot-Hook
- `backend/graph_algorithms.py` — PageRank, centrality, community detection auf FtM-Graph
- `backend/fusion_delta.py` — `GET /api/fusion/heatmap?compare=24h` mit `delta_score`
- Cesium-Pulse-Animation für Delta-Zellen
- Watch-Item-Generierung aus `delta_score`
- Tests: `test_anomaly_detector.py`, `test_graph_algorithms.py`, `test_fusion_delta.py`

**Abhängigkeiten:** V4-09 Snapshot Archiver ✅, V4-05 DuckDB ✅

---

## Session 4 — Country Instability Index (CII)  ✅ shipped

**Ziel:** Quantitativer 0–100 Risiko-Score pro Land; größter UX-Vorteil gegenüber WorldMonitor.

**V4-Items:**
- V4-43 Country Instability Index

**Deliverables:**
- `backend/cii_engine.py` — 4 gewichtete Signalfamilien (Konflikt, Wirtschaft, Klima, Governance)
- Integration GDELT + NewsData + ACLED (wenn Session 2 fertig) + Snapshot-Archiver
- `GET /api/cii/country?code=TH` + `GET /api/cii/rankings`
- Cesium-Choropleth-Layer für CII
- Briefing-Block: COUNTRY INSTABILITY
- 24h-Delta + Trend-Indikator
- Tests: `test_cii_engine.py` (mindestens 20 Länder-Fixtures)

**Abhängigkeiten:** GDELT ✅, NewsData ✅, V4-09 ✅; besser wenn Session 2 (ACLED) vorher fertig

---

## Session 5 — Dark Web & Breach Intelligence vertiefen  ✅ shipped

**Ziel:** Qualität der Dark-Web-OSINT erhöhen; Credential-Leak-Monitoring ohne Privatsphäre-Verletzung.

**V4-Items:**
- ~~V4-58 Engine-specific HTML Parsers (Torch, Tor66, TorDex, Haystak, Not Evil)~~ ✅ shipped (2026-07-01)
- ~~V4-59 Breach / Credential-Leak Intelligence (HIBP k-anonymity)~~ ✅ shipped (2026-07-01)

**V4-59 Implementierung (P8.8 — shipped):**
- `backend/breach_bridge.py` — HIBP API v3 für Email-Breach-Checks + Pwned Passwords k-anonymity API (SHA1-Prefix, nie volle Hashes senden)
- SQLite-Monitor-Tabelle: SHA1-Hash + base64-kodierte Email (Obfuscation), `breach_checks`-Tabelle für Historie
- 7 API-Endpoints unter `/api/darkweb/breach/`: `status`, `check`, `password`, `monitor` (POST/DELETE), `monitors`, `refresh`
- Briefing-Integration: `gather_breach_briefing()` in `node_briefing.py` → `breach_digest` in `briefing_digest.py` → BREACH-Block in `briefing_prompt.py`
- Watch-Items: `build_breach_watch_items()` — nur neue Breaches (`is_new=True`), severity `critical` bei Password-Datenklassen
- Frontend: BREACH-Tab in `DarkwebPanel.tsx` + 7 API-Funktionen in `darkwebApi.ts` (Email-Check, Password-Check, Monitor-Verwaltung)
- Config: `WORLDBASE_BREACH=1`, `WORLDBASE_BRIEFING_BREACH=1`, `WORLDBASE_HIBP_API_KEY` (erforderlich für Email-Checks; Password-Checks funktionieren ohne Key)
- Tests: `test_breach_bridge.py` — 30 Tests (alle grün); bestehende 41 Darkweb-Tests unbeeinträchtigt
- Caching mit TTL (default 3600s), Rate-Limiting (1.5s zwischen HIBP-Requests), fail-soft bei Netzwerkfehlern
- Router registriert in `routes/registry.py`

**V4-58 Implementierung (shipped):**
- `backend/darkweb_parsers.py` — 5 engine-spezifische HTML-Parser mit BeautifulSoup4
- Parser: `parse_torch()`, `parse_tor66()`, `parse_tordex()`, `parse_haystak()`, `parse_notevil()`
- Jeder Parser: engine-spezifische CSS-Selektoren + URL-Redirect-Unwrapping + Dedup + Fallback-Link-Extraction
- Integration in `darkweb_bridge._search_tor_engine()`: versucht dedizierten Parser, fällt auf `_parse_tor_html()` zurück
- Tests: `test_darkweb_parsers.py` — 26 Tests (alle grün); 61 Tests gesamt mit `test_darkweb_bridge.py`

**Abhängigkeiten:** P8.2 Dark Web Search ✅, V4-59 ✅

---

## Session 6 — Cyber Intelligence & Ontology-Expansion (Grundlage)    ✅ shipped

**Ziel:** FtM-Schema um Cyber- und Finanz-Entitäten erweitern; Shodan-InternetDB anbinden.

**V4-Items:**
- V4-60 Cyber & Financial Intel Ontology
- V4-59 (Teil) IOC-Extraktion aus Intel-Ingest

**Deliverables:**
- `backend/ftm_schema.py` erweitern: `Organization`, `Person`, `Document`, `IpAddress`, `Domain`, `Url`, `Asset`
- `backend/ftm_store.py` erweitern: `intel_edges` Tabelle für `worksFor`, `locatedAt`, `ownsAsset`, `mentionedIn`, `linkedTo`, `partOf`
- `backend/cyber_bridge.py` — Shodan InternetDB (keyless)
- IOC-Regex-Extraktion (IP, Domain, URL, Hash, E-Mail) in `intel_ingest`
- `GET /api/intel/entities?schema=Organization` + `GET /api/intel/edges?type=worksFor`
- Tests: `test_ontology_expansion.py`, `test_cyber_bridge.py`

**Abhängigkeiten:** FtM schema ✅, `ftm_store.py` ✅

---

## Session 7 — Relationship Explorer + Timeline + Credential Manager  ✅ shipped

**Ziel:** Frontend für die neue Ontology; interaktive Graph-Exploration und Operator-Profile.

**V4-Items:**
- V4-61 Relationship Explorer + Timeline
- Teil von §14 Foundry: Credential Manager UI

**Deliverables:**
- `frontend/src/components/RelationshipExplorer.tsx` — Cytoscape.js, Expand/Collapse, Edge-Filter
- `frontend/src/components/EntityTimeline.tsx` — first_seen → last_seen
- `GET /api/intel/entities/{id}/timeline`
- Credential Manager Panel im DATA-Tab (`GET/POST/DELETE /api/credentials`)
- Tests: Vitest für Komponenten, `test_relationship_explorer.py` (Backend)

**Abhängigkeiten:** V4-60 (Session 6) abgeschlossen

---

## Session 8 — GPU/VRAM-Management & Inference-Beschleunigung

**Ziel:** Ollama + HAK_GAL Firewall koexistieren auf 16 GB VRAM; lokale Inference beschleunigen.

**V4-Items:**
- V4-51 GPU Budget Scheduler
- V4-04 Embedding Acceleration (GPU)
- V4-13 Speculative Decoding (optional, falls machbar)

**Deliverables:**
- `backend/gpu_budget_scheduler.py` — Slots `firewall` | `llm`, `ollama_bridge.unload_models()`
- `GET /api/gpu/budget`
- `backend/rag_embed.py` GPU-Pfad mit sentence-transformers CUDA
- Falls Ollama-Support klar: Draft-Modell (0.5B) + qwen3:14b Validation
- Tests: `test_gpu_budget_scheduler.py` (mock Ollama), `test_rag_embed_gpu.py`
- Docs: `docs/FIREWALL.md`, `docs/VRAM.md`

**Abhängigkeiten:** Ollama ✅, HAK_GAL Firewall Bridge (Phase A) ✅

---

## Session 9 — Voice, TTS, PWA & Pi Offline RAG ✅

**Ziel:** Hands-free Bedienung + Mobile + Off-Grid-Fähigkeit.

**Status:** Shipped — 44 tests passed (29 Python + 15 Vitest)

**V4-Items:**
- ✅ V4-28 Whisper Voice Control
- ✅ V4-29 Piper TTS
- ✅ V4-30 PWA
- ✅ V4-33 Pi Offline RAG Service

**Deliverables:**
- ✅ `backend/whisper_bridge.py` — faster-whisper CUDA/CPU + Hotkey-Handler (PTT via keyboard+sounddevice)
  - Routes: `GET /api/whisper/status`, `POST /api/whisper/transcribe`, `POST /api/whisper/start-listener`, `POST /api/whisper/stop-listener`, `GET /api/whisper/transcripts`, `GET /api/whisper/kb/export`
- ✅ `backend/tts_bridge.py` — Piper CPU-TTS für Briefing-Narration (fallback WAV generator)
  - Routes: `GET /api/tts/status`, `POST /api/tts/speak`, `POST /api/tts/narrate`, `GET /api/tts/voices`
- ✅ PWA-Manifest + Service Worker (offline Caching von App-Shell)
  - `frontend/public/manifest.webmanifest` + `frontend/public/sw.js` (network-first API, SWR assets, cache-first Cesium)
  - SW registration in `frontend/src/main.tsx`, manifest+apple meta tags in `index.html`
- ✅ Pi: Mini-Vector-Store (sqlite-vec) + condensed KB sync
  - `offgrid-raspi/offgrid/bin/offline_rag.py` — FTS5 keyword + sqlite-vec vector search, CLI (`sync`/`search`/`stats`/`serve`), HTTP server mode
- ✅ Tests: `test_whisper_bridge.py` (15), `test_tts_bridge.py` (14), `test_pwa.test.ts` (15 Vitest)

**Config:** `WORLDBASE_WHISPER_BRIDGE=0` (opt-in), `WORLDBASE_TTS_BRIDGE=0` (opt-in) — both in `config.py` + `.env.example`

**Abhängigkeiten:** Pi Sync ✅

---

## Session 10 — Visual Intelligence (BLIP + ColQwen2 + Browser ML)

**Ziel:** Bilder/Video im OSINT-Workflow nutzen; client-seitige ML-Scoring.

**Status:** ✅ Shipped — 78 Tests (60 backend + 18 frontend), alle grün.

**V4-Items:**
- V4-15 BLIP Image Captioning
- V4-22 ColQwen2 (als On-Demand-Microservice)
- V4-48 Browser-Side ML (ONNX NER + Scoring)

**Deliverables:**
- `backend/blip_bridge.py` — ONNX GPU/CPU + optional NVIDIA VLM API
- `backend/colqwen2_service.py` — separater Prozess, on-demand start/stop
- `frontend/src/lib/browser_ml.ts` — Transformers.js ONNX für Headline-Scoring + NER
- Tests: `test_blip_bridge.py` (30 tests), `test_colqwen2_service.py` (30 tests), `test_browser_ml.test.ts` (18 tests)

**Abhängigkeiten:** V4-51 (Session 8) für VRAM-Scheduling

### Technische Details

#### V4-15 — BLIP Image Captioning (`backend/blip_bridge.py`)

**Architektur:** Lazy-loading Singleton mit `asyncio.Lock`. Auto-Backend-Auswahl: NVIDIA VLM API wenn `NVIDIA_API_KEY` gesetzt, sonst ONNX Runtime (CUDA/CPU). ONNX-Export beim ersten Start via `transformers` library.

**Routes (FastAPI):**
- `GET /api/vision/blip/status` — Modell-Status, Backend, Warmup-State
- `POST /api/vision/blip/caption` — Upload Image File → Caption
- `POST /api/vision/blip/caption-url` — Body `{"url": "..."}` → Caption (via HTTP-Download)

**Env-Vars:**
- `WORLDBASE_BLIP=0` — default off, opt-in
- `WORLDBASE_BLIP_BACKEND=auto` — auto/onnx/nvidia (auto=nvidia wenn `NVIDIA_API_KEY` gesetzt)
- `WORLDBASE_BLIP_MODEL=Salesforce/blip-image-captioning-base`
- `WORLDBASE_BLIP_DEVICE=auto` — auto/cuda/cpu (ONNX only)
- `WORLDBASE_BLIP_ONNX_DIR=data/models/blip_onnx` — ONNX model cache dir
- `WORLDBASE_BLIP_NVIDIA_MODEL=meta/llama-3.2-90b-vision-instruct`
- `WORLDBASE_BLIP_MAX_IMAGES=8` — Rate-Limit
- `WORLDBASE_BLIP_TIMEOUT=30` — NVIDIA API Timeout (Sekunden)

**Warmup:** In `lifespan.py` `_stack_warmup()` registriert — lädt Modell vorab nach Boot (nach RAG reranker warmup).

**ONNX-Details:**
- Export: `OnnxBlipCaptioner` Klasse mit `onnxruntime.InferenceSession`, CUDA + CPU Execution Providers
- Tokenizer: `transformers.AutoTokenizer` aus model cache dir
- Fallback: CPU wenn CUDA nicht verfügbar

**NVIDIA VLM API:**
- OpenAI-compatible endpoint (`NVIDIA_BASE_URL` + `/chat/completions`)
- Vision-Model: `meta/llama-3.2-90b-vision-instruct` (configurierbar)
- Image als base64 data URL im message content
- Fail-soft: Fallback auf ONNX bei API-Fehler

#### V4-22 — ColQwen2 Visual Document Understanding (`backend/colqwen2_service.py`)

**Architektur:** On-demand Subprocess-Microservice. Hauptprozess schreibt ein Python-Script (`_write_script()`) mit minimalem HTTP-Server (uvicorn), startet es als Subprocess und proxyt Requests. Idle-Monitor auto-stopt nach konfigurierbarem Timeout.

**Routes (FastAPI):**
- `GET /api/vision/colqwen2/status` — Prozess-Status, PID, Port, Uptime, Idle
- `POST /api/vision/colqwen2/start` — Startet Subprocess (mit Health-Check-Polling)
- `POST /api/vision/colqwen2/stop` — Stoppt Subprocess + Idle-Monitor
- `POST /api/vision/colqwen2/query` — Body `{"images": ["base64..."], "query": "text"}` → Antwort
- `POST /api/vision/colqwen2/ingest` — Body `{"images": ["base64..."], "doc_id": "..."}` → Indexierung

**Env-Vars:**
- `WORLDBASE_COLQWEN2=0` — default off, opt-in
- `WORLDBASE_COLQWEN2_MODEL=vidore/colqwen2-v0.1`
- `WORLDBASE_COLQWEN2_PORT=8009` — Microservice-Port
- `WORLDBASE_COLQWEN2_DEVICE=auto` — auto/cuda/cpu
- `WORLDBASE_COLQWEN2_IDLE_TIMEOUT=300` — Auto-Stop nach N Sekunden Idle
- `WORLDBASE_COLQWEN2_START_TIMEOUT=120` — Max Sekunden für Startup
- `WORLDBASE_COLQWEN2_MAX_CONCURRENT=4` — Semaphore für parallele Requests

**Subprocess-Lifecycle:**
1. `start_service()` → `_write_script()` + `subprocess.Popen` → `_wait_for_health()` pollt `/health`
2. `_idle_monitor()` → Background-Task, prüft alle 10s `_last_activity`, killt bei Timeout
3. `stop_service()` → `_kill_process()` (terminate → wait → kill) + Cancel idle monitor
4. `_proxy_post()` → `httpx.AsyncClient` POST an `127.0.0.1:{port}/query` oder `/ingest`

**Concurrency:** `asyncio.Semaphore(_MAX_CONCURRENT)` begrenzt parallele Proxy-Requests.

#### V4-48 — Browser-Side ML (`frontend/src/lib/browser_ml.ts`)

**Architektur:** Transformers.js (ONNX Runtime Web) im Browser. Lazy-loading via dynamischem Import (`_setLoader()` für Test-Injection). Variable-basierte Import-Strings um Vite static analysis zu umgehen (Package ist optional).

**Modelle (downloaded from HuggingFace Hub, cached in IndexedDB):**
- NER: `Xenova/bert-base-NER-uncased` (~110MB) — token-classification
- Sentiment: `Xenova/distilbert-base-uncased-finetuned-sst-2-english` (~65MB) — text-classification

**API (exported functions):**
- `initBrowserMl()` — Lädt beide Pipelines (idempotent, cached via `_initPromise`)
- `getBrowserMlStatus()` — `{ ready, nerLoaded, sentimentLoaded, error }`
- `extractEntities(text)` → `NerEntity[]` — Person/Organization/Location mit B-/I-Prefix-Stripping
- `scoreHeadline(text)` → `{ score, sentiment, sentimentScore, entities, text }` — 0–1 Relevance Score
- `scoreHeadlines(texts[])` → Batch-Scoring (sequenziell, `BATCH_SIZE=8`)
- `rankHeadlines(scores[], minScore?)` → Sortiert nach Score desc, optional Filter
- `aggregateEntities(scores[])` → Entity-Frequency über alle Headlines
- `preloadBrowserMl()` — Fail-soft Preload
- `_setLoader(fn)` — Test-Hook: Override Transformers.js Loader

**Scoring-Logik:**
- Basis: Sentiment-Score (NEGATIVE → hoch, POSITIVE → niedrig)
- Boost: Intelligence-Relevante Keywords (drone, strike, military, border, explosion, ...)
- NER-Entity-Boost: Mehr Entities → höhere Relevanz
- Clamping: 0.0–1.0

**Type-Mapping:** `B-PER` → `PER` → `Person` (strip `B-`/`I-` prefix, dann `ENTITY_TYPE_MAP`)

**Frontend-Test-Strategie:** `_setLoader()` injiziert Mock-Loader → `mockPipelineFn` returned `mockNerPipeline` / `mockSentimentPipeline` → Keine echten Modelle nötig. 18 Vitest-Tests in `test_browser_ml.test.ts`.

### Wiring

| Datei | Änderung |
|---|---|
| `backend/routes/registry.py` | Router für `blip_bridge` + `colqwen2_service` registriert |
| `backend/lifespan.py` | BLIP warmup in `_stack_warmup()` (nach RAG reranker) |
| `backend/.env.example` | Alle Env-Vars dokumentiert (V4-15, V4-22, V4-48) |
| `frontend/src/lib/browser_ml.d.ts` | Ambient TS declarations für optionale dynamic imports |

---

## Session 11 — Agentic Intelligence (ReAct + Multi-Hypothesis + Temporal) ✅ SHIPPED

**Ziel:** Autonomere OSINT-Chain + bessere Zukunftsabschätzung.

**Status:** Implementiert, 100 neue Tests, 246 Tests gesamt (0 Failures).

**V4-Items:**
- V4-25 ReAct Agent Loop ✅
- V4-20 Multi-Hypothesis Synthesis ✅
- V4-21 Temporal Analysis Engine ✅

**Deliverables:**
- `backend/react_agent.py` — Thought/Action/Observation Loop mit Query-Router
- `backend/multi_hypothesis.py` — 3 Drafts + Vergleich (Cloud-LLM bevorzugt, Ollama-Fallback)
- `backend/temporal_engine.py` — Granger-Causality-Probe + Trend-Detection auf Feed-Zeitreihen
- Integration in Chat-Agentic-Pfad
- Tests: `test_react_agent.py`, `test_multi_hypothesis.py`, `test_temporal_engine.py`

**Abhängigkeiten:** V4-01 Smart Router ✅, P3 Agentic Chat ✅, V4-09 ✅

### Umsetzung-Notizen

**Config (`backend/config.py`):**
- `WORLDBASE_REACT_AGENT=0` (default off), `WORLDBASE_REACT_AGENT_MAX_STEPS=5`, `WORLDBASE_REACT_AGENT_STEP_TIMEOUT=15.0`
- `WORLDBASE_MULTI_HYPOTHESIS=0` (default off), `WORLDBASE_MULTI_HYPOTHESIS_DRAFTS=3`
- `WORLDBASE_TEMPORAL_ENGINE=0` (default off), `WORLDBASE_TEMPORAL_ENGINE_MAX_LAG=3`, `WORLDBASE_TEMPORAL_ENGINE_MIN_POINTS=5`
- 9 neue Config-Felder in `WorldBaseConfig` dataclass + `from_env()` Parsing

**`react_agent.py` — ReAct Loop:**
- Rule-based Thought-Generator (0 VRAM): Step 0 = immer Search, thin result → alt-route Search, sufficient content → Synthesize
- Actions: `search` (query_router.route_retrieval), `search_alt` (alternate route via alt_map), `synthesize` (deterministic merge), `done`
- `_merge_blocks()` dedupliziert Lines (case-insensitive), `_synthesize()` erzeugt Header + Context
- `ReActTrace` dataclass mit `to_dict()`, `format_react_trace_line()` für Prompt-Injection
- Step-Timeout via `asyncio.wait_for()`, Force-Synthesize am Ende falls nicht konvergiert
- 18 Tests (env, thought-gen, merge, synthesize, trace-line, loop mit mocks, timeout, max-steps)

**`multi_hypothesis.py` — 3 Drafts + Vergleich:**
- 3 Stances: A=baseline (factual), B=adversarial (red-team), C=forecast (24-72h projections)
- LLM-Pfad: Cloud-Provider via `chat_model_router.available_providers()` → Ollama-Fallback → rule-based
- `_call_cloud()` nutzt `chat_routing` (PROVIDER_CONFIG, select_api_key, select_base_url) — OpenAI-compatible API
- `_call_ollama()` direkt via httpx zu Ollama `/api/chat`
- Rule-based Fallback: struktur unterschiedliche Drafts aus Source-Tags, kein LLM nötig
- `_compare_drafts()`: Scoring nach Content-Länge (cap 2000) + LLM-Bonus (+0.5) + Adversarial-Bonus (+0.3) + Forecast-Bonus (+0.2) + Error-Penalty (-1.0)
- `_merge_drafts()`: Best-First, `[SELECTED]`-Marker, Header `=== MULTI-HYPOTHESIS SYNTHESIS ===`
- Parallele LLM-Calls via `asyncio.gather()`, gemischte LLM/rule-based Drafts möglich
- 22 Tests (env, stances, prompt-building, rule-based drafts, compare, merge, trace-line, run mit mocks)

**`temporal_engine.py` — Granger + Trends:**
- Pure-Python Statistik (kein numpy/scipy): `_mean`, `_std` (sample, n-1), `_linear_regression` (OLS), `_mann_kendall` (S-Statistic + Normal-Approx p-value), `_normal_cdf` (erf), `_f_distribution_cdf` (Normal-Approx für d1,d2>4), `_pearson_corr`, `_gauss_solve` (Gaussian elimination mit partial pivot)
- `detect_trend()`: Lineare Regression (slope, R²) + Mann-Kendall (S, p-value) → Direction (increasing/decreasing/flat), normalized strength
- `granger_probe()`: Lagged Regression — Restricted (y~y_lagged) vs Unrestricted (y~y_lagged+cause_lagged) → F-Test → p-value aus F-Distribution, Direction via Pearson-Corr
- `_r2_multi()`: Multiple Regression R² via Normal Equations + Gaussian Elimination
- Feed-Extraktion: `_collect_feed_series()` liest `runtime_cache.cache_get_stale()` für GDELT pulse:local:thailand, quakes:day:2.5, eonet, aircraft
- `_bucket_series()`: Hourly Bucketing (count per 3600s), `_align_series()`: Nearest-Neighbor Alignment
- `_parse_timestamp()`: ISO, GDELT-Format (YYYYMMDDTHHMMSSZ), date-only, epoch
- 60 Tests (stats-helpers, parse-timestamp, bucketing, alignment, trend-detection, granger-probe, format, run mit mocks)

**Integration in `chat_agentic.py`:**
- Phasen 4-6 in `run_chat_agentic_loop()` nach Corroboration (Phase 3):
  - Phase 4: Temporal Analysis → `run_temporal_analysis()` → `formatted_block` wird an RAG-Block angehängt
  - Phase 5: ReAct Agent → `run_react_loop()` → ersetzt `block` mit `final_block` (inkl. Synthesis-Header)
  - Phase 6: Multi-Hypothesis → `run_multi_hypothesis()` → `merged_block` wird an RAG-Block angehängt
- Jede Phase: try/except fail-soft, env-gated, Trace-Metadata in `trace["temporal"]`, `trace["react"]`, `trace["multi_hypothesis"]`
- Phasen-Liste in Trace erhält `{"phase": "temporal"|"react"|"multi_hypothesis", ...}` Einträge
- Reihenfolge bewusst: Temporal zuerst (liefert Kontext), dann ReAct (iterative Verbesserung), dann Multi-Hypothesis (Synthese)

**Test-Ergebnisse:**
- `test_react_agent.py`: 18 tests ✅
- `test_multi_hypothesis.py`: 22 tests ✅
- `test_temporal_engine.py`: 60 tests ✅
- Regression: `test_chat_agentic.py` (26), `test_config.py`, `test_llm_workplan.py`, `test_route_ledger.py`, `test_chat_report_quality.py`, `test_agent_orchestrator.py` — alle ✅
- Gesamt: 246 passed, 0 failed, 1 pre-existing warning (unrelated)

---

## Session 12 — Federation, HAK_GAL Firewall B–D & Red-Team

**Ziel:** Agentic-Sicherheit härten; MCP-Write-Tools gaten, Outbound-Scan, Audit.

**V4-Items:**
- V4-38 Federated Citizen Mesh — **nur experimenteller Prototyp**, nicht produktiv
- V4-63 HAK_GAL Firewall Phases B–D
- V4-26 Red-Team / Prompt-Injection QA

**Deliverables:**
- `backend/firewall_bridge.py` erweitern: `firewall_scan_tool()`, `firewall_scan_response()`, `GET /api/firewall/history`
- MCP-Write-Tools gaten (`worldbase_briefing_generate`, `globe_fly_to`, `globe_toggle_layer`)
- `WORLDBASE_FIREWALL_MCP`, `WORLDBASE_FIREWALL_TRACE`, `WORLDBASE_FIREWALL_SHADOW`
- Experimenteller Federation-Proof-of-Concept: verschlüsselte Intel-Sharing-Nachricht (kein Produktiv-Feature)
- Red-Team-Fixtures + `test_firewall_mcp.py`
- Tests: `test_firewall_mcp.py`, `test_redteam.py`

**Abhängigkeiten:** HAK_GAL Firewall Phase A ✅

---

## Session 13 — Infrastructure, Harvester & DR  ✅ SHIPPED

**Ziel:** Datenportal-Integration generisch; Backup-Automatisierung; API-Verträge.

**V4-Items:**
- V4-35 CKAN Harvester
- V4-41 DR Automation
- V4-49 API Contract Generation (Pydantic → OpenAPI → TS)

**Deliverables:**
- `backend/ckan_harvester.py` + YAML-Config + Registry-Erweiterung
- `scripts/backup_auto.py` + S3/MinIO-Upload + Restore-Test
- OpenAPI → TypeScript-Client Generator in CI
- Tests: `test_ckan_harvester.py`, `test_backup_auto.py`, `test_api_contracts.py`

**Abhängigkeiten:** connector_registry.py ✅

**Umsetzung (Jul 2026):**

- **V4-35 CKAN Harvester ✅** — `backend/ckan_harvester.py` mit YAML-Config (`backend/ingest/ckan_sources.yml`, 5 Portale: data.go.th, data.gov.sg, data.gov.uk, data.gov, data.europa.eu). FeedConnector-Caching, Harvest-Log (SQLite), optionales FtM-Ingest via mapping_runner. 5 API-Endpoints unter `/api/ckan/`. Feature-Flag: `WORLDBASE_CKAN_HARVESTER=1`. Registry-Eintrag in `connector_registry.py` + Router in `routes/registry.py` + `lifespan.py` init.
- **V4-41 DR Automation ✅** — `scripts/backup_auto.py`: SQLite VACUUM INTO, DuckDB/JSON/Parquet file copy, SHA-256-Checksums im Manifest, S3/MinIO-Upload via boto3, Restore-Test (Checksum-Verify + SQLite/DuckDB/JSON-Integrität). CLI-Flags: `--upload-s3`, `--restore-test`, `--include-env`.
- **V4-49 API Contract Generation ✅** — `backend/api_contracts.py`: OpenAPI-Schema-Extraction → TypeScript-Client-Generator (Interfaces, camelCase-Funktionen, Path/Query-Params, Body-Serialization, API-Key-Injection). 3 Endpoints unter `/api/contracts/`. CI-Step in `ci.yml` generiert `frontend/src/lib/apiClient.ts`.
- **Tests ✅** — 53 neue Tests (alle passing): `test_ckan_harvester.py` (22), `test_backup_auto.py` (12), `test_api_contracts.py` (19). Bestehende `test_connector_registry.py` (12) weiterhin green.

---

## Session 14 — UI/UX & Analytics-Erweiterungen  ✅ SHIPPED

**Ziel:** Analytische Dashboards, adaptive Polling, Zeitreise-Replay, Monitoring.

**V4-Items:**
- V4-31 Analyst Dashboard (SVG-basiert statt Deck.gl — keine zusätzliche Dependency)
- V4-46 SmartPollLoop
- V4-65 Temporal Replay
- V4-69 Grafana Dashboard

**Deliverables:**
- `frontend/src/components/AnalystDashboard.tsx` — Sankey, Timeline, Heatmap (SVG, keine Deck.gl-Dependency)
- `frontend/src/hooks/useSmartPoll.ts` — Backoff, hidden-tab throttle, circuit breaker
- `frontend/src/components/TemporalReplay.tsx` — Zeitreise mit Snapshot-Archiver
- `docs/grafana-dashboard.json` — 10-Panel Grafana-Dashboard für OTel/Prometheus-Metriken
- CSS in `frontend/src/styles/hud.css` (V4-31 + V4-65 Sektionen)
- App.tsx: ANALYST + REPLAY Buttons im HUD-Header, lazy-loaded mit ErrorBoundary
- Tests: `tests/unit/test_useSmartPoll.test.ts` (9), `tests/components/AnalystDashboard.test.tsx` (10), `tests/components/TemporalReplay.test.tsx` (11) — 30/30 passing

**Abhängigkeiten:** V4-09 ✅, V4-31/Deck.gl teilweise; Grafana-Metriken ✅

**Umsetzung (Jul 2026):**

- **V4-46 SmartPollLoop ✅** — `frontend/src/hooks/useSmartPoll.ts`: Exponentieller Backoff (capped at `maxInterval`), Hidden-Tab-Throttle (reschedule auf `hiddenInterval` bei `visibilitychange`), Circuit Breaker (öffnet nach N konsekutiven Fehlern, Half-Open-Recovery nach Cooldown). `refetch()`/`reset()` Controls, Timer-Cleanup bei Unmount. Configurable: `interval`, `maxInterval`, `hiddenInterval`, `backoffMultiplier`, `breakerThreshold`, `breakerCooldownMs`, `enabled`, `immediate`.
- **V4-31 Analyst Dashboard ✅** — `frontend/src/components/AnalystDashboard.tsx`: SVG-basierte Visualisierungen (keine Deck.gl-Dependency). **Sankey**: Feed-Flow-Diagramm (Source-Feeds → FRESH/STALE/ERROR) aus `/api/health`. **Timeline**: Swim-Lane-Event-Timeline mit Severity-Farben aus `/api/insights`. **Heatmap**: Geospatial-Scatter mit Score-basiertem Color/Radius aus `/api/fusion/heatmap`. Alle 3 nutzen `useSmartPoll` für adaptives Polling mit Live-Status-Indikatoren. 2×2-Grid-Layout mit Poll-Metrics-Panel.
- **V4-65 Temporal Replay ✅** — `frontend/src/components/TemporalReplay.tsx`: `useSnapshotArchiver` (Ring-Buffer, max 120 Snapshots), Timeline-Scrubber mit Sparkline, Play/Pause/Step-Controls (0.5×–4× Speed), Auto-Capture-Toggle (30s/1m/5m Intervalle), JSON Export/Import, Snapshot-Detail-View mit Feed-Status. Nutzt `useSmartPoll` für Auto-Capture-Polling.
- **V4-69 Grafana Dashboard ✅** — `docs/grafana-dashboard.json`: 10-Panel-Dashboard für Prometheus. Panels: Feed Status Counts (stat), Briefing Quality Score (gauge), Briefing Age (timeseries), DuckDB Entity Graph (timeseries), AIS Maritime Feed (timeseries), Ollama Status (stat), Pi Edge Node (stat), Health Check Latency Histogram (timeseries), RAG Query Stats (timeseries), Prediction Watch (timeseries). `${DS_PROMETHEUS}` Variable, 30s Refresh, `intelshed-overview` UID.
- **App.tsx ✅** — `ANALYST` + `REPLAY` Buttons im HUD-Header (zwischen PIPELINE und CYBER/MSS). Beide lazy-loaded mit `Suspense` + `ErrorBoundary`. State: `analystOpen`, `replayOpen` (useState, nicht persisted).
- **CSS ✅** — V4-31 + V4-65 Sektionen in `hud.css` (ca. 335 Zeilen): Fullscreen-Overlay-Layout, Panel-Grid, SVG-Responsive, Replay-Controls, Snapshot-Detail, Feed-Dots.
- **Tests ✅** — 30 neue Tests (alle passing): `test_useSmartPoll.test.ts` (9: idle, immediate poll, exponential backoff, circuit breaker open, circuit recovery, hidden-tab throttle, refetch, reset, unmount cleanup), `AnalystDashboard.test.tsx` (10: title, close, panel labels, status indicators, SVG rendering, empty states), `TemporalReplay.test.tsx` (11: title, close, playback controls, auto toggle, capture/export/import/clear buttons, empty state, speed/interval selectors, footer status).

---

## Session 15 — Compliance, Klassifikation & Bitemporalität

**Ziel:** Daten-Lebenszyklus, Klassifikation für Federation, Audit-Trail.

**V4-Items:**
- V4-06 GDPR Export/Deletion
- V4-07 Data Retention
- V4-10 Classification Gate
- V4-39 Bitemporal Entity Store

**Deliverables:**
- `backend/gdpr.py` — Export + Löschung personenbezogener Daten
- `backend/retention.py` — policies + TTL-Pruning
- `backend/classification.py` — CONFIDENTIAL/SECRET/UNCLASSIFIED labels
- `backend/bitemporal.py` — valid_time / system_time für FtM-Entitäten
- Tests: `test_gdpr.py`, `test_retention.py`, `test_classification.py`, `test_bitemporal.py`

**Abhängigkeiten:** Auth/RBAC3.✅

**Umsetzung (Jul 2026):**

- **V4-06 GDPR Export/Deletion ✅** — `backend/gdpr.py`: `export_personal_data(entity_id)` sammelt PII-Bundle aus FtM DuckDB (entities, statements, edges), legacy SQLite entity_store, und audit_trail. `delete_personal_data(entity_id, hard_delete=True)` unterstützt Hard-Delete und Anonymisierung ([REDACTED] PII-Felder). `list_data_subjects(query)` durchsucht Person-Entities nach Name/Email/ID. Alle GDPR-Requests werden in SQLite `gdpr_requests`-Tabelle protokolliert. 4 API-Routes unter `/api/gdpr/*` (search, export, delete, history). Operator-only RBAC.
- **V4-07 Data Retention ✅** — `backend/retention.py`: Retention-Policy CRUD in SQLite `retention_policies`-Tabelle. Pruning-Logic für SQLite und DuckDB (TTL-basiert, timestamp-column). 5 Default-Policies: `feed_cache` (7d), `auth_audit` (90d), `gdpr_requests` (365d), `statements` (disabled), `edges` (disabled). `prune_table()` und `prune_all()` mit Logging in `retention_log`-Tabelle. 6 API-Routes unter `/api/retention/*` (policies CRUD, prune, prune/{id}, log). Operator für Modify/Prune, Viewer für Read.
- **V4-10 Classification Gate ✅** — `backend/classification.py`: `ClassificationLevel` IntEnum (UNCLASSIFIED=0 < CONFIDENTIAL=1 < SECRET=2 < TOP_SECRET=3), case-insensitive Parser mit Hyphen-Toleranz. Per-Entity Labels in SQLite `entity_classification`-Tabelle. Per-Dataset Defaults in `dataset_classification`-Tabelle. Federation Node Registry (`federation_nodes`-Tabelle) mit `max_clearance`-Level. `federation_gate(entity_ids, max_clearance)` filtert Entities by Clearance → (allowed, blocked). `filter_entities_by_clearance(entities, level)` für Listen-Filterung. `bulk_classify_entities()` für Batch-Operationen. 12 API-Routes unter `/api/classification/*`. Operator für Modify, Viewer für Read.
- **V4-39 Bitemporal Entity Store ✅** — `backend/bitemporal.py`: `entity_versions`-Tabelle mit `valid_from`/`valid_to` (Real-World-Zeit) und `system_from`/`system_to` (DB-Transaktionszeit). Auto-Incrementing Version-Numbers mit automatischem `system_to`-Closing bei neuer Version. Time-Travel-Queries: `as_of_system_time()` (was did we know at X?), `as_of_valid_time()` (what was true at Y?), `as_of_both()` (combined bi-temporal). `correct_valid_time()` für Metadata-Corrections ohne neue Version. JSON-serialisierte Properties/Datasets. 7 API-Routes unter `/api/bitemporal/*`. Operator für Write, Viewer für Read.
- **Config Flags ✅** — `config.py`: `WORLDBASE_GDPR` (default `1`), `WORLDBASE_RETENTION` (default `1`), `WORLDBASE_RETENTION_PRUNE_INTERVAL` (default `3600`), `WORLDBASE_CLASSIFICATION` (default `1`), `WORLDBASE_DEFAULT_CLASSIFICATION` (default `UNCLASSIFIED`), `WORLDBASE_BITEMPORAL` (default `1`).
- **Routes ✅** — `routes/registry.py`: Alle 4 Router registriert (`gdpr.router`, `retention.router`, `classification.router`, `bitemporal.router`).
- **Tests ✅** — 57 Tests (alle passing): `test_gdpr.py` (9: table creation, request recording, export empty/with SQLite entity, hard delete, anonymise, history, audit trail, PII props), `test_retention.py` (12: table creation, default policies, CRUD, pruning SQLite, disabled/zero-TTL skip, prune_all, logging, not-found), `test_classification.py` (20: enum values, string parsing, label, table creation, entity classify/get/bulk/remove, dataset defaults, federation node CRUD, gate allows/blocks/all-pass/int-level, entity filtering, stats), `test_bitemporal.py` (16: table creation, version recording/increment, history, get version, system/valid/both time travel, null interval, corrections, stats, system_to closing, property serialization).
- **Docker ✅** — Live in Docker getestet: Alle 4 Module aktiv, Classification classify/gate/stats verifiziert, Retention 5 Default-Policies seeded, Bitemporal version recording + history verifiziert, GDPR history + export 404 verifiziert.

---

## Session 16 — Strategische / Forschungs-Features & finale Aufpolierung

**Ziel:** Langfristige Capabilities und Validierung; keine Blocker für Produktivbetrieb.

**V4-Items:**
- V4-36 ADS-B Aircraft Tracking
- V4-37 SAR Dark-Vessel Detection
- V4-50 Dual Map Engine (deck.gl + Cesium)
- V4-53 Pi Offline PMTiles Basemap
- V4-62 Proactive Push Delivery
- V4-66 Subgraph A/B
- V4-67 vec1 Benchmark
- V4-68 LLM A/B
- V4-70 Social OSINT (nur Forschungsprototyp, ToS/Ethik)

**Deliverables:**
- ADS-B: `backend/adsb_bridge.py` (OpenSky/ADSBExchange)
- SAR: `backend/sar_bridge.py` (Sentinel-1 batch processing)
- Dual Map: `frontend/src/hooks/useMapEngine.ts` + lazy-loaded deck.gl
- Pi PMTiles: `go-pmtiles` Wrapper + Offline-Basemap
- Push Delivery: WebSocket/Server-Sent Events für Watch-Items
- Subgraph A/B: `backend/subgraph_ab.py` — Vergleich zweier Intel-Subgraphen
- vec1 Benchmark + LLM A/B: `backend/benchmark_vec1.py`, `backend/llm_ab.py`
- Social OSINT: Design-Doc + ToS-Risiko-Bewertung, kein Code
- Tests: je nach implementierten Items

**Abhängigkeiten:** diverse, siehe Roadmap

---

## WorldMonitor-Vergleich — Engineering Hygiene Track

> **Quelle:** Direkter Vergleich mit `github.com/koala73/worldmonitor` (v2.8.0, AGPL-3.0), durchgeführt 2026-06-30.
> **Referenz-Repo:** `d:\MCP Mods\worldmonitor` (geklont, `npm run dev` auf localhost:3000 verifiziert)

### Zusammenfassung

WorldMonitor ist das reifere **Software-Produkt** (API-Verträge via Protobuf, 500+ Tests, 15 CI-Workflows, 4-Layer Cache, Circuit Breakers, ETag/304, Rate Limiting, Visual Regression, Tauri-Desktop, i18n, Varianten-System, Browser-ML via ONNX). WorldBase ist das innovativere **Forschungstool** (Anti-Hallucination-Stack, Agent Orchestrator + Blackboard, Evidence Chains, FtM-StatementEntity, Pi-Edge-Sync, Darknet-OSINT, Local-LLM, DuckDB-Spatial, Query Router + Route Ledger). WorldMonitor's Vorteil ist Engineering-Discipline; WorldBase's Vorteil ist Analysetiefe.

### Was WorldBase bereits abdeckt (keine Aktion nötig)

| WorldMonitor-Feature | WorldBase-Äquivalent | Status |
|---|---|---|
| Circuit Breakers | V4-64 Feed Circuit Breaker | ✅ Session 1 shipped |
| ETag/304 | V4-64 ETag-Tracking | ✅ Session 1 shipped |
| API-Verträge (Protobuf → OpenAPI) | V4-49 Pydantic → OpenAPI → TS | Session 13 geplant |
| Browser-side ML (ONNX) | V4-48 Browser-Side ML | ✅ Session 10 shipped |
| Smart Poll Loop | V4-46 SmartPollLoop | Session 14 geplant |
| Bootstrap Hydration | V4-45 Bootstrap Endpoint | ✅ Session 1 shipped |
| MCP outputSchema | V4-44 MCP Schema + JMESPath | ✅ Session 1 shipped |

### Neue Items aus WorldMonitor-Vergleich

Diese Items sind **nicht** in der V4-Roadmap und werden als paralleler Track E geführt. Sie sind cross-cutting und unabhängig von den fachlichen Sessions 4–16.

| ID | Item | Aufwand | ROI | WeltMonitor-Referenz |
|---|---|---|---|---|
| E-01 | Pre-push Hooks erweitern | 0.5 Tage | Hoch | `.husky/pre-push`: typecheck, esbuild bundle, edge import guard, markdown lint, version sync, secret guard |
| E-02 | Rate Limiting (sliding window) | 1 Tag | Hoch | `api/_rate-limit.js` + Upstash; per-IP, per-endpoint overrides |
| E-03 | CI-Workflows erweitern | 1 Tag | Hoch | 15+ GitHub-Workflows: security-audit, feed-validation, proto-check, deploy-gate |
| E-04 | Cache Stampede Protection | 2 Tage | Mittel | `cachedFetchJson()` — concurrent cache-misses teilen einen upstream fetch + Redis write |
| E-05 | Visual Regression Tests | 2–3 Tage | Mittel | Playwright golden screenshots per Variante (WorldBase hat Playwright E2E, aber keine Visual Regression) |
| E-06 | MCP Quota & Protocol Conformance | 2 Tage | Mittel | quota, presets, protocol conformance tests, tool annotations, output budget |
| E-07 | CSP Hardening | 0.5 Tage | Hoch | 3 synchrone CSP-Quellen (meta, header, tauri.conf.json) |

---

## Track E — Engineering Hygiene (parallel zu fachlichen Sessions)

Track-E-Sessions können unabhängig von Sessions 4–16 ausgeführt werden. Empfehlung: E-01 bis E-03 frühzeitig (vor Session 4), E-04 bis E-06 mittelfristig (vor Session 10), E-07 jederzeit.

### Session E1 — Pre-push Hooks + Rate Limiting + CSP (Quick Wins)

**Ziel:** Engineering-Hygiene-Basis auf WorldMonitor-Niveau bringen.

**Items:**
- E-01 Pre-push Hooks erweitern
- E-02 Rate Limiting (sliding window)
- E-07 CSP Hardening

**Deliverables:**
- `.husky/pre-push` erweitert: `ruff check`, `mypy` (optional), `pytest --collect-only` (Syntax-Check), `npm run typecheck` (Frontend), secret-scan (`.env`-Dateien in staging-area blocken)
- `backend/rate_limiter.py` — sliding-window per-IP via Redis (oder in-memory fallback), per-endpoint overrides konfigurierbar in `config.py`
- `WORLDBASE_RATE_LIMIT=1` (default on), `WORLDBASE_RATE_LIMIT_RPM=60` (default)
- Integration in FastAPI middleware; API-Key-Requests exempt, `/api/health/*` exempt
- CSP: `index.html` meta-tag + Caddyfile header + Docker Caddyfile synchronisieren
- Tests: `test_rate_limiter.py`, pre-push hook manual verification
- Docs: `docs/ENGINEERING.md` (neu) mit Hook-Dokumentation

**Abhängigkeiten:** Redis ✅ (für Rate Limiting; in-memory fallback falls Redis nicht verfügbar)

---

### Session E2 — CI-Pipeline + Cache Stampede Protection

**Ziel:** CI auf WorldMonitor-Niveau; Cache-Korrektheit unter Last.

**Items:**
- E-03 CI-Workflows erweitern
- E-04 Cache Stampede Protection

**Deliverables:**
- `.github/workflows/` erweitern:
  - `security-audit.yml` — `pip-audit` + `npm audit` bei PR und täglich
  - `feed-validation.yml` — Smoke-Test aller Feeds bei Feed-Code-Änderungen und täglich
  - `deploy-gate.yml` — aggregiert required statuses für branch protection
  - `typecheck.yml` — `mypy backend/` + `tsc --noEmit frontend/` bei PR
- `backend/cache_coalesce.py` — `cached_fetch_json()` pattern: concurrent cache-misses für gleichen Key teilen einen upstream fetch via `asyncio.Lock` + in-flight tracking
- Integration in `runtime_cache.py` und `feed_autopilot.py`
- Tests: `test_cache_coalesce.py` (concurrent requests → 1 upstream fetch), `test_ci_workflows.py` (YAML-Struktur validierung)
- Docs: `docs/ENGINEERING.md` erweitern

**Abhängigkeiten:** CI ✅ (bestehender `ci.yml`), Redis ✅ (optional für verteilte Coalescing)

---

### Session E3 — Visual Regression + MCP Quota

**Ziel:** UI-Stabilität messbar machen; MCP auf WorldMonitor-Reife bringen.

**Items:**
- E-05 Visual Regression Tests
- E-06 MCP Quota & Protocol Conformance

**Deliverables:**
- `e2e/visual.spec.ts` — Playwright golden screenshots: Globe, BriefingKanban, DataPanel, ChatPanel, SituationBoard pro Theme (dark/light)
- `scripts/update-golden-screenshots.ps1` — golden image regeneration
- `npm run test:e2e:visual` + `npm run test:e2e:visual:update` scripts
- `backend/mcp_quota.py` — per-tool quota (daily/hourly), `WORLDBASE_MCP_QUOTA=1` (default off)
- `backend/mcp_conformance.py` — protocol version check, tool annotations schema, output budget enforcement
- `tests/test_mcp_quota.py`, `tests/test_mcp_conformance.py`
- MCP tool annotations: `readOnlyHint`, `destructiveHint`, `idempotentHint` für alle 13+ tools
- Docs: `docs/MCP.md` erweitern um Quota + Conformance

**Abhängigkeiten:** Playwright ✅, MCP-Server ✅

---

## Priorisierungs-Empfehlung

**Für Citizen-ROI (Scenario B aus Machbarkeitsstudie):**
1. Session 1 (Quick Wins) ✅
2. Session 2 (Regionale Daten) ✅
3. Session 3 (Anomalie/Graph/Delta) ✅
4. **Session E1 (Pre-push + Rate Limiting + CSP)** — Engineering-Basis, parallel zu Session 4
5. Session 4 (CII — höchster UX-Win)
6. Session 5 (Dark Web/Breach) — V4-59 ✅ shipped, V4-58 offen
7. **Session E2 (CI + Cache Stampede)** — parallel zu Session 5/6
8. Session 9 (Voice/PWA/Pi)
9. Session 8 (GPU-Scheduler)

**Für Analyst-Powerhouse (Scenario C):**
1. Session 4 (CII)
2. Session 3 (Graph/Delta) ✅
3. Session 6+7 (Ontology/Relationship)
4. **Session E1 (Pre-push + Rate Limiting + CSP)** — frühzeitig, parallel
5. Session 10 (Visual Intelligence)
6. Session 11 (ReAct/Temporal)
7. Session 14 (Analytics)
8. **Session E3 (Visual Regression + MCP Quota)** — vor oder mit Session 14

**Engineering-Hygiene-Empfehlung (unabhängig von Scenario):**
- Track E1 so früh wie möglich — Pre-push Hooks und Rate Limiting sind Quick Wins mit hohem ROI
- Track E2 vor Session 10 (Cache-Coalescing wird wichtiger sobald mehr Feeds laufen)
- Track E3 vor Session 14 (Visual Regression braucht stabile UI, MCP Quota wird wichtiger mit mehr Tools)

---

## Handoff-Checkliste pro Session

Jede Session sollte folgende Schritte enthalten:

1. **Codebase-Audit** — vorhandene Module lesen, nicht neu erfinden
2. **Feature-Flag** default off in `config.py` + `.env.example`
3. **Implementation** — Backend + Frontend + Tests
4. **Smoke-Test** laufen lassen: `.\scripts\smoke-test.ps1`
5. **Backend-Neustart** explizit kommunizieren — nur der Operator darf `start.ps1`, `start-docker.ps1` oder Uvicorn starten
6. **Status aktualisieren** in `docs/WORLDBASE_ROADMAP_V4.md` und `progress.txt`
7. **Testsuite grün** halten: `backend\venv\Scripts\python.exe -m pytest backend/tests`

---

## Token-Budget pro Session

Eine 200k-Token-Session erlaubt ca.:
- **Systemkontext:** ~20k Tokens (AGENTS.md, relevante Roadmap-Abschnitte, Codebase-Audit)
- **Implementation:** ~120k Tokens (mehrere Dateien á 300–400 LOC, Tests, Frontend)
- **Review & Iteration:** ~40k Tokens (Smoke-Test, Fehlerbehebung, Dokumentation)
- **Puffer:** ~20k Tokens

Wenn eine Session zu groß wird, in zwei Sessions splitten (z.B. Session 16 in 16a + 16b).
