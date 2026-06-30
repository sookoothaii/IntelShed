# WorldBase Roadmap V4 — Citizen OSINT Build Plan

> **Audience:** AI coding agents. Not human documentation.
> **Purpose:** Actionable build plan derived from V3 + external citizen-OSINT philosophy research.
> **Philosophy:** Online as standard, offline as safety net. Maximum information for the ordinary citizen on affordable hardware. Cost zero. Every feature degrades gracefully without GPU. Fail-soft. Feature flags default off.
> **Hardware:** Lenovo Legion i9-12900HX, RTX 3080 Ti 16 GB VRAM, Raspberry Pi 4 8 GB. Every feature must also run on a cheap laptop without GPU.
> **Created:** 2026-06-30
> **Last updated:** 2026-06-30 (Sprint A1–C2 shipped, live-verified via Docker API; V4-43–V4-50 added from WorldMonitor competitive analysis; V4-51–V4-70 added from consolidated research; external assessment integrated)
> **Supersedes:** V3 (kept for reference at `WORLDBASE_ROADMAP_V3.md`)
> **Feasibility study:** `docs/MACHBARKEITSSTUDIE_V4.md` — all findings integrated below
> **Stack analysis:** `docs/WORLDBASE_STACK_ANALYSIS.md` — current architecture reference

---

## Core Philosophy

WorldBase is a **digital emancipation tool** — David's sling against Big Tech data monopolies. The goal is not a technical hobby but **maximum information for the ordinary citizen on affordable hardware**, with convenience and depth.

### Five Pillars

1. **Online as standard, offline as safety net** — Use free API tiers (NVIDIA NIM, Groq, OpenRouter free models) for speed and capability when online; fail over to local Ollama/llama.cpp when offline. One-click toggle in UI for citizen transparency.
2. **API-first, local-second** — Use free external models for heavy lifting if online; fail over to local models when offline. Don't waste VRAM replicating what a free cloud API does better.
3. **GPU for local tasks only** — Use VRAM for real-time reranking, embeddings, image captioning, TTS/STT, local inference. Never a forced cloud dependency. Every GPU feature has a CPU fallback.
4. **Cost zero** — No paid subscriptions. Only APIs with generous free tiers (NVIDIA, Groq, OpenRouter, Hugging Face inference). Every feature has a local equivalent.
5. **Raspberry Pi as off-grid assistant** — Provides offline RAG and sensor ingestion. Doesn't force disconnection. Works when the Legion is off.

### VRAM Budget Analysis (16 GB RTX 3080 Ti)

Not all GPU features can reside in VRAM simultaneously. On-demand loading is **mandatory**.

| Component | VRAM | Mode |
|-----------|------|------|
| Ollama qwen3:14b Q4 (baseline) | ~8–9 GB | Persistent |
| BGE-Reranker GPU (V4-03) | +0.5 GB | Persistent |
| Embedding GPU (V4-04) | +1 GB | On-demand |
| BLIP GPU (V4-15) | +1 GB | On-demand (sporadic) |
| Whisper GPU (V4-28) | +1 GB | On-demand (hotkey) |
| Speculative Decoding draft (V4-13) | +0.5 GB | On-demand |
| LoRA Training (V4-12, QLoRA 14B) | ~14 GB | Overnight (unloads 14B base) |
| ColQwen2 (V4-22, 3B) | +4 GB | **Cannot coexist with 14B** — on-demand microservice |
| GNN Training (V4-18) | +2 GB | **Cannot coexist with 14B** — overnight or CPU |

**Rule:** Before Phase 3, build a **VRAM-Manager** (`backend/vram_manager.py`) with priority queue, LRU eviction, and `GET /api/vram/status` health endpoint. Blocks new model loads at >90% VRAM usage. Prevents OOM crashes. **This is the single highest-leverage prerequisite for all GPU features** — it decides whether BLIP, ColQwen2, Whisper, and LoRA can coexist.

**Daily VRAM schedule:**
```
Persistent:  14B Ollama (~8 GB) + BGE-Reranker (~0.5 GB) = ~8.5 GB
On-demand:   Embedding (~1 GB), BLIP (~1 GB), Whisper (~1 GB) — loaded when needed
Overnight:   LoRA training (~14 GB, unloads 14B) or ColQwen2 indexing (~4 GB)
```

### Key Principles for Any Enhancement

- **Graceful degradation** — Every feature must work on a cheap laptop without a GPU, but exploit the 3080 Ti to its fullest when available.
- **Fail-soft required** — All new connectors and ML features must degrade gracefully on error.
- **Feature flags default off** — Backward compatible. Opt-in for new capabilities.
- **Docker-first** — All features must work in Docker stack.
- **No commercial APIs as hard dependencies** — Free tier or open source only.
- **Test coverage** — Every new module needs unit tests before merge.
- **Pi sync** — New briefing data must flow through `/api/node/pull`.
- **Only user may start/restart the backend.**
- **Always use `backend\venv\Scripts\python.exe`** for Python commands.
- **Additive migrations only** — New entity types must not break existing FtM schema.
- **ONNX export path** — GNN/ML models must have ONNX export for CPU deployment.
- **Federated sharing requires classification gate** — No SECRET data leaves instance.

---

## What Changed from V3

### Dropped (overkill for citizen single-user station)

| V3 ID | Feature | Reason |
|-------|---------|--------|
| V3-2 | Celery + Redis Task Queue | Overkill for single-user station. asyncio is sufficient. Redis stays as cache/pubsub, not as Celery broker. |
| V3-10 | Meilisearch Global Search | SQLite FTS5 is sufficient, zero extra process, works offline perfectly. Replaced by V4-08. |
| V3-31 | PostgreSQL + pgvector Migration | SQLite + DuckDB already handle all metadata and vectors. Keep simplicity. No multi-node deployment needed for citizen use. |
| V3-32 | Kafka/Redpanda Stream Processing | Overkill. asyncio + Redis Streams (already available) suffice for single-user event processing. |

### Shipped in Sprint A (2026-06-30)

| V4 ID | Feature | Sprint |
|-------|---------|--------|
| V4-01 | Smart Model Router | A1 |
| V4-02 | RBAC + Rate Limit (config tuning) | — |
| V4-03 | BGE-Reranker CUDA | A2 |
| V4-05 | DuckDB 1.6 + R-Tree auto-enable | B1 |
| V4-08 | FTS5 Global Search | A3 |
| V4-09 | Snapshot Archiver | B2 |
| V4-14 | Telegram Bridge (audit complete) | C1 |
| V4-19 | Predictive Analytics (LightGBM) | C2 |

### Reframed

| V3 ID | V4 ID | Change |
|-------|-------|--------|
| V3-19 | V4-05 | Model Router → Smart Model Router with online-first/local-fallback chain (NVIDIA NIM → Groq → Ollama). UI toggle "Use Cloud AI". |
| V3-26 | V4-15 | BLIP Image Captioning → GPU-accelerated (ONNX GPU when available, CPU fallback). Online: optional NVIDIA VLM API for richer descriptions. |
| V3-20 | V4-18 | GNN Event Correlation → Experiment. **MVP: Graph Attention Network (GAT) with homogeneous graph** (not heterogeneous GNN). Train locally on GPU, deploy as ONNX for CPU inference. Online mode can use free LLM to infer relations via prompt. Rule-based fallback for offline. Heterogeneous GNN deferred to V2. |
| V3-7 | V4-20 | Multi-Hypothesis Synthesis → Use free large online models (OpenRouter/Groq) for multi-draft. Offline: single-pass with optional two-pass (existing). |

### Added (from citizen-OSINT philosophy)

| V4 ID | Feature | Source |
|-------|---------|--------|
| V4-03 | BGE-Reranker on CUDA | External: GPU acceleration for hybrid RAG |
| V4-04 | Embedding Acceleration (GPU) | External: sentence-transformers on CUDA |
| V4-08 | SQLite FTS5 Global Search | External: replaces Meilisearch, zero daemon |
| V4-11 | Self-Consistency Voting | External: 3× inference with different seeds, majority vote |
| V4-12 | LoRA Fine-Tuning on OSINT Data | External: QLoRA on RTX 3080 Ti, personal OSINT co-pilot |
| V4-13 | Speculative Decoding | External: Draft model (0.5B) + large model (14B) validation, 2-3× speedup |
| V4-24 | Whisper Voice Control (GPU) | External: faster-whisper CUDA for "Ask the Globe" |
| V4-25 | Piper TTS for Briefing Narration | External: CPU-only, offline, morning briefing readout |
| V4-28 | Pi Offline RAG Service | External: mini-Qdrant or SQLite vector store on Pi, condensed KB sync |
| V4-35 | Federated Citizen Mesh | External: encrypted intel sharing between citizen WorldBase instances, no central server |

### Added (from WorldMonitor competitive analysis, 2026-06-30)

| V4 ID | Feature | Source |
|-------|---------|--------|
| V4-43 | Country Instability Index (CII) | WorldMonitor: quantitative 0–100 risk score per country, 4 weighted signal families, 24h delta |
| V4-44 | MCP outputSchema + JMESPath Projection | WorldMonitor: 39 MCP tools with outputSchema + jmespath (80–95% response reduction) |
| V4-45 | Bootstrap Hydration Endpoint | WorldMonitor: tiered fast/slow aggregated load, 2 requests instead of 20+ |
| V4-46 | SmartPollLoop (Adaptive Refresh) | WorldMonitor: exponential backoff, hidden-tab throttle, circuit breaker integration |
| V4-47 | Route Explorer + Scenario Engine | WorldMonitor: supply chain what-if workflows, chokepoint exposure, disruption scenarios |
| V4-48 | Browser-Side ML (ONNX NER + Scoring) | WorldMonitor: Transformers.js client-side headline scoring + entity extraction |
| V4-49 | API Contract Generation (Pydantic → TS) | WorldMonitor: proto-first contracts, zero schema drift; adapted to Pydantic → OpenAPI → TS client |
| V4-50 | Dual Map Engine (deck.gl flat map) | WorldMonitor: 56 layer types, deck.gl + globe.gl dual engine; enhances V4-31 |

### Added (from consolidated research, 2026-06-30)

| V4 ID | Feature | Source |
|-------|---------|--------|
| V4-51 | GPU Budget Scheduler | Research §10: sequential GPU slots for Ollama + HAK_GAL firewall coexistence on 16 GB VRAM |
| V4-52 | Fusion Delta Grid (24h Compare) | Research Track 5: `GET /api/fusion/heatmap?compare=24h` with cell `delta_score`, Cesium pulse animation |
| V4-53 | Pi Offline PMTiles Basemap | Research B-07: PMTiles v3 on Pi SD card + go-pmtiles server, offline basemap without PC |
| V4-54 | Lightning Detection Bridge | Research §8: Blitzortung/LightningMaps, monsoon early warning, corroborate with CAMS/outages |
| V4-55 | OSM Critical Infrastructure POIs | Research §8: Overpass API, hospitals/ports/borders in operator bbox, Track 2 corroboration |
| V4-56 | Multi-Day Weather Forecast | Research §8: Open-Meteo 72h structured forecast for watch items, Track 1 anticipation |
| V4-57 | Displacement Monitoring Feed | Research §8: IOM DTM / UNHCR, Myanmar border displacement signals, extends HDX bridge |
| V4-58 | Dark Web Engine-Specific Parsers | Research §6a P8.7: per-engine HTML parsers for 5 Tor search engines, improves entity extraction ✅ Shipped |
| V4-59 | Breach / Credential-Leak Intelligence | Research §6a P8.8/K1: HIBP k-anonymity API, credential leak monitoring, briefing integration |
| V4-60 | Cyber & Financial Intel Ontology | Research §14: new entity types (Organization, Person, CyberIndicator, FinancialAsset), typed edges, Shodan bridge |
| V4-61 | Relationship Explorer + Timeline | Research §14.4: Cytoscape interactive graph with edge type filters, entity timeline view |
| V4-62 | Proactive Push Delivery | Research Track 8: Meshtastic compact alerts (<237 B), local HTTP hook, email/Telegram push |
| V4-63 | Firewall Phase B–D Hardening | Research §11: MCP write gate, epistemic abstention UX, fail-closed mode, trust probe |
| V4-64 | Feed Circuit Breaker + ETag Polling | Research §13.6: per-feed circuit breaker, conditional GET (ETag/If-None-Match) for feed polling |
| V4-65 | Temporal Replay (Time-Slider Globe) | Research §6a J.2: historical globe state replay from snapshot archives |
| V4-66 | Subgraph Quality A/B Validation | Research B-05/B-09/B-10: validate FtM subgraph quality impact, hallucination count, Splink eval |
| V4-67 | vec1 ANN Benchmark | Research B-01: SQLite vec1 (IVFADC + OPQ) vs sqlite-vec brute-force at 50k+ vectors |
| V4-68 | LLM Briefing Model A/B | Research B-11: qwen3:8b vs phi-4:14b comparison for briefing quality |
| V4-69 | Grafana/Loki Observability Dashboard | Research B-08: metrics dashboard for feed health, briefing quality, entity growth |
| V4-70 | Social Media OSINT (Mastodon/Bluesky) | Research §6a H.3: federated social media intelligence (deferred — ToS/ethics) |

---

## External Assessment — WorldMonitor vs WorldBase (2026-06-30)

> **Source:** Independent external review, 2026-06-30.
> **Context:** WorldMonitor (~62k GitHub stars) is an enterprise risk intelligence platform. WorldBase is a citizen-OSINT workstation. The comparison is fair and architecturally precise.

### Core divergence: Enterprise vs Citizen

| Dimension | WorldMonitor | WorldBase |
|-----------|-------------|-----------|
| **Target audience** | Enterprise risk analysts, supply chain managers | Citizen OSINT, privacy-conscious, hobby analysts |
| **Business model** | Freemium / PRO-gated (Route Explorer, Scenario Engine) | 100% free, 0 subscription, open source |
| **Architecture principle** | Scale-to-Enterprise (gRPC, 39 MCP tools, 25 languages) | Scale-to-Individual (FastAPI, SQLite, 16 GB VRAM) |
| **Intelligence type** | Quantified (CII score, layered risk) | Narrativ + Graph (briefing, FtM, provenance) |

### Point-by-point assessment

**Full agreement (no objections):**

| # | Point | Comment |
|---|-------|---------|
| 1 | Proto-First API | Fair. But: for single-developer, protobuf CI overhead is unjustified. FastAPI/Pydantic is sufficient for citizen stack. |
| 2 | CII v8 — Quantified Score | **The biggest gap.** A numerical country score is extremely valuable. Narrative briefings are good, but "Thailand = 34, +12 in 24h" is instantly understandable. |
| 5 | 39 MCP Tools + JMESPath | Fair. But: 13 tools are sufficient for Cursor/Claude citizen use. 39 tools is enterprise scale. |
| 6 | Bootstrap Hydration | Clear performance win. 2 requests instead of 20+. Should be adopted. |
| 7 | SmartPollLoop | Clearly better. Adaptive polling dramatically reduces API load. |
| 10 | Browser-Side ML | Genuine architecture advantage. Transformers.js for client-side NER/scoring is elegant. |

**Agreement with caveats:**

| # | Point | Caveat |
|---|-------|--------|
| 3 | 56 Map Layer + Dual Engine | 56 layers sound impressive, but how many are genuinely useful? WorldBase has 15+ layers, all OSINT-relevant (GDELT, quakes, AIS, dark web, satellite). Breadth ≠ depth. Cesium is significantly more powerful for 3D terrain than globe.gl. |
| 4 | Route Explorer + Scenario Engine | PRO-gated at WorldMonitor. That is a paid feature. WorldBase is entirely free. For citizen OSINT, a scenario engine is nice-to-have, not critical. |
| 8 | Tauri Desktop App | Cool, but: WorldBase has Pi Edge Sync (V4-33) — a Raspberry Pi as offline intelligence butler is significantly more valuable for citizen OSINT than a desktop binary. |
| 9 | 25 Languages + RTL | Important for enterprise broad reach. For citizen OSINT: the user is one person, language is configurable (`WORLDBASE_BRIEFING_LANG=de`). Multilingual support is P3. |

### What WorldBase should adopt from WorldMonitor

1. **CII Score (V4-43)** — Highest priority. Quantifies narrative briefings into an immediately understandable number. Uses existing data (GDELT, fusion, AIS, anomaly detection). No new feed required. ~1–2 weeks.
2. **Bootstrap Hydration (V4-45)** — P1. `GET /api/bootstrap?tier=fast|slow` aggregates all frontend initialization data. Low-hanging fruit. ~2–3 days.
3. **SmartPollLoop (V4-46)** — P2. Adaptive polling with exponential backoff and hidden-tab throttle. Frontend change. ~1–2 days.
4. **Browser-Side ML (V4-48)** — P3 (experimental). Transformers.js for client-side NER on briefing text. Would reduce server load. But: 16 GB VRAM is sufficient for server-side. Not urgent.

### What WorldBase does better — and why it matters for citizen OSINT

| WorldBase feature | Why it matters more for citizen OSINT than enterprise features |
|-------------------|------------------------------------------------------------------|
| **3-Layer Anti-Hallucination** | A citizen trusts no institution. Provenance + CRAG + corroboration are trust mechanisms, not just quality features. |
| **FtM Entity Graph** | Enterprise tools have CRMs. Citizen OSINT has nothing. FtM is the citizen CRM for world events. |
| **Pi Edge Sync** | A Pi for <100 € that works without internet is more valuable to a prepper than a Tauri desktop app. |
| **Darknet OSINT** | Enterprise has threat-intel vendor contracts. Citizen has only WorldBase. |
| **DuckDB Spatial** | No enterprise tool uses DuckDB as spatial engine. Technical advantage (columnar, Parquet, H3). |
| **Entity Resolution (Splink)** | Splink ML linkage on a Pi is unique. |

### Strategic conclusion

> **WorldMonitor is a better enterprise tool. WorldBase is a better citizen tool.**

This is not a bug, it is a design decision. WorldBase should not copy everything from WorldMonitor. The three features to adopt (CII, Bootstrap Hydration, SmartPollLoop) enhance the citizen-OSINT value proposition without compromising the architecture. Everything else (Tauri, 25 languages, 56 layers, protobuf) is enterprise overhead that contradicts the citizen philosophy.

**The gap that truly hurts:** CII v8. A quantitative country score from WorldBase data would be a spectacular feature. The rest is nice-to-have.

---

## Priority Matrix

### Tier 1 — Foundation Acceleration & Balance (≤1 week, high impact)

| # | ID | Feature | Effort | Impact | Restart? | Status |
|---|----|---------|--------|--------|----------|--------|
| 1 | V4-01 | Smart Model Router with Fallback Chain | ~250 LOC | Critical | Yes | ✅ Shipped (A1) |
| 2 | V4-02 | RBAC + Rate Limiting On by Default | ~120 LOC | High | Yes | ✅ Shipped (config tuning only) |
| 3 | V4-03 | BGE-Reranker on CUDA | ~150 LOC | High | Yes | ✅ Shipped (A2) |
| 4 | V4-04 | Embedding Acceleration (GPU) | ~100 LOC | Medium | Yes | Open |
| 5 | V4-05 | DuckDB 1.6 Upgrade + H3 Spatial Index | ~200 LOC | Critical | Yes | ✅ Shipped (B1 — R-Tree auto-enable on >=1.6) |
| 6 | V4-06 | GDPR / DSAR Module | ~250 LOC | High | Yes | Open |
| 7 | V4-07 | Data Retention Policy Engine | ~150 LOC | High | Yes | Open |
| 8 | V4-08 | SQLite FTS5 Global Search | ~200 LOC | High | Yes | ✅ Shipped (A3) |
| 9 | V4-09 | Daily Snapshot Archiver (Parquet) | ~150 LOC | High | Yes | ✅ Shipped (B2) |
| 10 | V4-10 | Automatic Data Classification | ~200 LOC | Medium | Yes | Open |
| 11 | V4-43 | Country Instability Index (CII) | ~400 LOC | Critical | Yes | Open |
| 12 | V4-44 | MCP outputSchema + JMESPath | ~150 LOC | High | Yes | ✅ Shipped (Sprint 1) |
| 13 | V4-45 | Bootstrap Hydration Endpoint | ~200 LOC | High | Yes | ✅ Shipped (Sprint 1) |
| 14 | V4-46 | SmartPollLoop (Adaptive Refresh) | ~200 LOC FE | Medium | No (FE) | Open |
| 15 | V4-51 | GPU Budget Scheduler | ~300 LOC | High | Yes | Open |
| 16 | V4-64 | Feed Circuit Breaker + ETag Polling | ~200 LOC | High | Yes | ✅ Shipped (Sprint 1) |

### Tier 1-2 — Data Sources & Connectors (1-2 weeks)

| # | ID | Feature | Effort | Impact | Restart? | Status |
|---|----|---------|--------|--------|----------|--------|
| 11 | V4-14 | Telegram Connector (Telethon) | ~300 LOC | High | Yes | ✅ Shipped (C1 — audit complete) |
| 12 | V4-16 | ACLED Conflict Connector | ~200 LOC | High | Yes | Open |
| 13 | V4-17 | STIX/TAXII 2.1 Server Endpoint | ~300 LOC | Critical | Yes | Open |
| 14 | V4-54 | Lightning Detection Bridge | ~150 LOC | Medium | Yes | Open |
| 15 | V4-55 | OSM Critical Infrastructure POIs | ~200 LOC | High | Yes | Open |
| 16 | V4-56 | Multi-Day Weather Forecast | ~150 LOC | Medium | Yes | Open |
| 17 | V4-57 | Displacement Monitoring Feed | ~200 LOC | Medium | Yes | Open |

### Tier 2 — Local AI Superpowers (1-2 weeks each, high leverage)

| # | ID | Feature | Effort | Impact | Restart? | Status |
|---|----|---------|--------|--------|----------|--------|
| 14 | V4-11 | Self-Consistency Voting | ~150 LOC | Medium | Yes | Open |
| 15 | V4-12 | LoRA Fine-Tuning on OSINT Data | ~400 LOC | High | No (scripts) | Open |
| 16 | V4-13 | Speculative Decoding | ~400-600 LOC | Medium | Yes | Open |
| 17 | V4-15 | BLIP Image Captioning (GPU RAG) | ~200 LOC | Medium | Yes | Open |
| 18 | V4-22 | ColQwen2 Multimodal RAG | ~400 LOC | High | Yes | Open |
| 19 | V4-47 | Route Explorer + Scenario Engine | ~500 LOC | High | Yes | Open |
| 20 | V4-48 | Browser-Side ML (ONNX NER + Scoring) | ~300 LOC FE | Medium | No (FE) | Open |
| 21 | V4-52 | Fusion Delta Grid (24h Compare) | ~250 LOC | High | Yes | Open |
| 22 | V4-58 | Dark Web Engine-Specific Parsers | ~200 LOC | Medium | Yes | ✅ Shipped |
| 23 | V4-59 | Breach / Credential-Leak Intelligence | ~300 LOC | Medium | Yes | ✅ Shipped |
| 24 | V4-60 | Cyber & Financial Intel Ontology | ~400 LOC | High | Yes | Open |

### Tier 2-3 — Intelligence & ML (1-2 weeks each)

| # | ID | Feature | Effort | Impact | Restart? | Status |
|---|----|---------|--------|--------|----------|--------|
| 19 | V4-18 | GNN Event Correlation (GAT MVP) | ~400 LOC | High | Yes | Open |
| 20 | V4-19 | Predictive Analytics (LightGBM) | ~350 LOC | High | Yes | ✅ Shipped (C2) |
| 21 | V4-20 | Multi-Hypothesis Synthesis | ~200 LOC | Medium | Yes | Open |
| 22 | V4-21 | Temporal Reasoning Agent | ~350 LOC | High | Yes | Open |
| 23 | V4-23 | Anomaly Detection (Isolation Forest) | ~300 LOC | Medium | Yes | ✅ Shipped (Sprint 1) |
| 24 | V4-24 | NetworkX Graph Algorithms | ~250 LOC | Medium | Yes | Open (Sprint 1 P1) |
| 25 | V4-25 | ReAct Loop in Agentic Chat | ~300 LOC | Medium | Yes | Open |
| 26 | V4-26 | Automated Red-Team Pipeline | ~250 LOC | Medium | No | Open |
| 27 | V4-27 | Cross-Feed Event Correlation (Rule + LLM) | ~250 LOC | Medium | Yes | Open |
| 28 | V4-49 | API Contract Generation (Pydantic → TS) | ~200 LOC tooling | Medium | No | Open |
| 29 | V4-50 | Dual Map Engine (deck.gl flat map) | ~400 LOC FE | Medium | No (FE) | Open |
| 30 | V4-61 | Relationship Explorer + Timeline | ~400 LOC FE | Medium | No (FE) | Open |
| 31 | V4-65 | Temporal Replay (Time-Slider Globe) | ~1000 LOC FE | Medium | No (FE) | Open |

### Tier 3 — UX, Voice & Accessibility

| # | ID | Feature | Effort | Impact | Restart? | Status |
|---|----|---------|--------|--------|----------|--------|
| 28 | V4-28 | Whisper Voice Control (GPU) | ~200 LOC | Medium | Yes | Open (Sprint 2 P1) |
| 29 | V4-29 | Piper TTS for Briefing Narration | ~150 LOC | Medium | Yes | Open (Sprint 2 P1) |
| 30 | V4-30 | PWA + Notification Bell | ~150 LOC FE | Medium | No (FE) | Open (Sprint 2 P1) |
| 31 | V4-31 | Deck.gl/Kepler.gl Analyst Dashboard | ~400 LOC FE | Medium | No (FE) | Open |
| 32 | V4-32 | Multi-User Collaboration (Yjs) | ~500 LOC | High | Yes | Open |

### Tier 3-4 — Edge & Offline Resiliency

| # | ID | Feature | Effort | Impact | Restart? | Status |
|---|----|---------|--------|--------|----------|--------|
| 33 | V4-33 | Pi Offline RAG Service | ~300 LOC | High | No (Pi) | Open (Sprint 4 P1) |
| 34 | V4-34 | ONNX Edge Inference (Pi) | ~300 LOC | Medium | No (Pi) | Open |
| 35 | V4-35 | Generic CKAN Harvester | ~250 LOC | Medium | Yes | Open (Sprint 1 P1) |
| 36 | V4-36 | ADS-B + SatNOGS (RF OSINT) | ~350 LOC | Medium | Yes | Open |
| 37 | V4-37 | Sentinel-1 SAR Integration | ~350 LOC | Medium | Yes | Open |
| 38 | V4-53 | Pi Offline PMTiles Basemap | ~200 LOC Pi | High | No (Pi) | Open |

### Tier 4 — Strategic / Long-term

| # | ID | Feature | Effort | Impact | Restart? | Status |
|---|----|---------|--------|--------|----------|--------|
| 38 | V4-38 | Federated Citizen Mesh (Experiment) | ~400 LOC | High | Yes | Open (Experiment only) |
| 39 | V4-39 | Bitemporal Graph (valid_from/until) | ~300 LOC | Medium | Yes | Open |
| 40 | V4-40 | FtM Ontology Extension | ~250 LOC | Medium | Yes | Open |
| 41 | V4-41 | Disaster Recovery Automation | ~200 LOC | Medium | No | Open (Sprint 1 P1) |
| 42 | V4-42 | Chaos + Load + Property Tests | ~300 LOC | Low-Med | No | Open |
| 43 | V4-62 | Proactive Push Delivery | ~250 LOC | Medium | Yes | Open |
| 44 | V4-63 | Firewall Phase B–D Hardening | ~400 LOC | Medium | Yes | Open |
| 45 | V4-66 | Subgraph Quality A/B Validation | ~200 LOC tests | Medium | No | Open (research) |
| 46 | V4-67 | vec1 ANN Benchmark | ~150 LOC scripts | Low | No | Open (research) |
| 47 | V4-68 | LLM Briefing Model A/B | ~100 LOC scripts | Low | No | Open (research) |
| 48 | V4-69 | Grafana/Loki Observability Dashboard | ~200 LOC config | Low | No | Open |
| 49 | V4-70 | Social Media OSINT (Mastodon/Bluesky) | ~400 LOC | Medium | Yes | Deferred (ToS/ethics) |

---

## Recommended Build Order

> **Feasibility study finding:** V4-05 and V4-09 are the most critical enablers. Without V4-09 (Snapshots), Phase 4 ML features (V4-19, V4-21, V4-23) cannot train. Start them first, not last.
> **Update 2026-06-30:** Sprint A1–C2 (7 items) shipped and live-verified. Remaining timeline adjusted.

### ✅ Sprint A — Shipped (2026-06-30)

| Sprint | Items | Status |
|--------|-------|--------|
| A1 | V4-01 Smart Model Router | ✅ Shipped |
| A2 | V4-03 BGE-Reranker CUDA | ✅ Shipped |
| A3 | V4-08 FTS5 Global Search | ✅ Shipped |
| B1 | V4-05 DuckDB 1.6 + R-Tree auto-enable | ✅ Shipped |
| B2 | V4-09 Snapshot Archiver | ✅ Shipped |
| C1 | V4-14 Telegram Bridge (audit) | ✅ Shipped |
| C2 | V4-19 Predictive Analytics | ✅ Shipped |

**Test count:** 1811 backend tests (up from 1281 at V2 completion).
**Live-verified:** Docker stack, 26 feeds (21 fresh), briefing quality 0.922, Pi online, AIS 104 vessels.

### Remaining Sprints (from feasibility study)

**Sprint 1 — Intelligence & Infrastructure (weeks 1-4):**
~~V4-23 (Anomaly Detection)~~ ✅ Shipped → ~~V4-44 (MCP outputSchema)~~ ✅ Shipped → ~~V4-45 (Bootstrap Hydration)~~ ✅ Shipped → V4-24 (Graph Algo) → V4-35 (CKAN) → V4-41 (DR Automation) → V4-16 (ACLED) → V4-17 (STIX/TAXII) → **V4-43 (CII)**

**Sprint 2 — Voice & UX (weeks 4-7):**
V4-28 (Whisper) → V4-29 (Piper TTS) → V4-30 (PWA) → V4-15 (BLIP) → V4-04 (Embedding GPU) → **V4-46 (SmartPollLoop)**

**Sprint 3 — VRAM-Manager + Advanced AI (weeks 7-12):**
VRAM-Manager (prerequisite) → V4-13 (Speculative Decoding) → V4-11 (Self-Consistency) → V4-12 (LoRA, overnight) → V4-22 (ColQwen2, on-demand) → **V4-47 (Route Explorer + Scenario Engine)** → **V4-48 (Browser ML)**

**Sprint 4 — Edge & Offline (weeks 12-16):**
V4-33 (Pi Offline RAG) → V4-34 (ONNX Pi) → V4-25 (ReAct Loop) → V4-20 (Multi-Hyp) → V4-27 (Cross-Feed) → **V4-49 (API Contract Gen)**

**Sprint 5 — Compliance & Classification (weeks 16-19):**
V4-06 (GDPR) → V4-07 (Retention) → V4-10 (Classification) → V4-26 (Red-Team)

**Sprint 6 — Strategic (weeks 19-28):**
V4-31 (Deck.gl) → V4-32 (Yjs Collab) → V4-36 (ADS-B) → V4-37 (SAR) → V4-39 (Bitemporal) → V4-40 (FtM Extended) → V4-42 (Chaos Tests) → V4-38 (Federation — experiment only) → **V4-50 (Dual Map Engine)**

**Sprint 7 — GNN (weeks 28-32):**
V4-18 (GNN GAT MVP) → V4-21 (Temporal Reasoning)

> **Updated timeline:** 36–48 weeks (~9–12 months) full-time, 16–22 months at hobby pace (10h/week). Sprint A saved ~4 weeks. V4-43–V4-50 add ~4 weeks to total (3 items in Sprint 1 are quick wins: V4-44 ~150 LOC, V4-45 ~200 LOC, V4-46 ~200 LOC FE).

---

## V4-01 — Smart Model Router with Fallback Chain ✅ Shipped (A1, 2026-06-30)

**Why:** Currently qwen3:8b handles everything. The citizen philosophy demands online-first with offline fallback. A smart router uses free cloud models (NVIDIA NIM step-fun-3.5-fast, Groq Llama 3.3 70B) as the primary "big brain" when online, and falls back to local Ollama when offline or rate-limited.

**Scope:**
- `backend/model_router.py` — query complexity classifier + provider selector with fallback chain
- Fallback chain: NVIDIA NIM (free, fast) → Groq (free, fast) → OpenRouter free models → local Ollama (qwen3:14b with GPU offload) → local Ollama (qwen3:8b)
- Complexity signals: token length, entity density, crisis vocabulary, spatial reasoning required, multi-hop query
- Rule-based scoring (0 VRAM): score >= 0.7 → cloud strong model, 0.4-0.7 → cloud fast model, < 0.4 → local fast
- Health check: `internet_available()` check (ping NVIDIA NIM endpoint, 2s timeout)
- UI toggle: "Use Cloud AI" (on/off) — citizen transparency. When off, always uses local models.
- Integration in `chat_proxy.py` — intercept before provider dispatch
- `GET /api/models/route?q=...` — preview routing decision (debug)
- `GET /api/models/status` — provider availability, current routing mode
- `WORLDBASE_MODEL_ROUTING=0` (default off, opt-in)
- `WORLDBASE_CLOUD_AI=1` (default on when routing enabled — can be toggled in UI)
- Tests: `test_model_router.py` — complexity scoring, cascade selection, fallback on provider unavailable, offline detection, UI toggle respect

**Key design:**
- Fallback is automatic and silent — citizen never needs to know which provider served the response
- Rate-limit detection: if NVIDIA returns 429, automatically try Groq, then OpenRouter, then local
- When `WORLDBASE_CLOUD_AI=0` (UI toggle off), router skips all cloud providers and uses local only
- Provider switching is trivial (existing 6-provider proxy already handles this)

---

## V4-02 — RBAC + Rate Limiting On by Default

**Why:** No per-client request throttling. API key brute-force, Identity OSINT enumeration (83 platforms), and chat endpoint abuse are unprotected. Protect your station; simple local user/password.

**Scope:**
- `backend/middleware/rate_limit.py` — slowapi integration with Redis backend
- Default limits: 60 req/min per IP (general), 10 req/min (chat), 5 req/min (identity OSINT), 3 req/min (briefing generate)
- RBAC: simple HTTP basic auth or X-API-Key for local use (already shipped in Phase 2.1)
- `WORLDBASE_RATE_LIMIT=0` (default off, opt-in)
- Env overrides: `WORLDBASE_RATE_LIMIT_GENERAL`, `WORLDBASE_RATE_LIMIT_CHAT`, `WORLDBASE_RATE_LIMIT_OSINT`
- `GET /api/rate-limit/status` — current limits + hit counts
- Tests: `test_rate_limit.py` — limit enforcement, header presence, bypass for admin

**Dependency:** `slowapi` (lightweight, FastAPI-native, Redis-backed)

---

## V4-03 — BGE-Reranker on CUDA ✅ Shipped (A2, 2026-06-30)

**Why:** Current BGE reranker runs on CPU (2-3s per query). On GPU, reranking drops to <200ms. This allows expanding RAG storage to all GDELT articles (last 7 days), all Telegram messages, all CAMS reports — more relevant data than any free cloud RAG offering. Big-Tech RAG solutions limit context size or charge money. Local vector search through more data, staying offline.

**Scope:**
- `backend/rag_reranker_gpu.py` — ONNX Runtime GPU backend for BGE reranker
- Enable `onnxruntime-gpu` when GPU available (CUDA provider). Keep CPU path as fallback.
- Auto-detection: check for CUDA availability at startup, select GPU or CPU provider
- `WORLDBASE_RERANKER_GPU=0` (default off, opt-in) — auto-enables when GPU detected and flag is on
- Integration: `rag_hybrid.py` calls reranker via abstraction layer (GPU or CPU, transparent)
- Tests: `test_rag_reranker_gpu.py` — GPU detection, reranking correctness, CPU fallback, fail-soft

**Dependencies:** `onnxruntime-gpu` (CUDA wheel), existing BGE model

---

## V4-04 — Embedding Acceleration (GPU)

**Why:** sentence-transformers runs on CPU for embedding generation. RAG index rebuilds take minutes. On GPU, embedding throughput increases 10-20×, enabling real-time RAG index updates as new feeds arrive.

**Scope:**
- `backend/embedding_gpu.py` — GPU-accelerated sentence-transformers wrapper
- Auto-detection: check for CUDA at startup, move model to GPU if available
- CPU fallback: if no GPU or CUDA error, transparently falls back to CPU
- Integration: `rag_memory.py` and `rag_hybrid.py` use abstraction layer
- `WORLDBASE_EMBEDDING_GPU=0` (default off, opt-in)
- Tests: `test_embedding_gpu.py` — GPU detection, embedding correctness, CPU fallback

**Dependencies:** `torch` with CUDA, `sentence-transformers` (already installed)

---

## V4-05 — DuckDB 1.6 Upgrade + H3 Spatial Index ✅ Shipped (B1, 2026-06-30)

**Why:** DuckDB 1.5.x bug #769 disables R-Tree index, forcing full-scan ST_Within. DuckDB 1.6.0 fixes this. As fallback/workaround, H3 hexagonal indexing provides fast spatial joins without R-Tree. Pure local, huge speedup. Solves the spatial performance problem without external services.

**Scope:**
- Upgrade DuckDB to 1.6.x in `requirements.txt` + Dockerfile
- Verify R-Tree index works after upgrade; re-enable `_create_rtree_index()`
- If R-Tree still unstable: implement H3 index column via `h3` Python library
  - `h3.latlng_to_cell(lat, lon, resolution=7)` on entity upsert → `h3_index` column
  - ST_Within approximated by H3 cell JOIN (O(1) lookup vs O(n) scan)
  - H3 resolution 7 ≈ 5km² cells — configurable via `WORLDBASE_H3_RESOLUTION`
- Frontend: H3-based heatmap layer (CesiumJS H3 plugin)
- `WORLDBASE_DUCKDB_RTREE=1` (re-enable after upgrade), `WORLDBASE_H3_INDEX=0` (opt-in fallback)
- Tests: `test_h3_spatial.py` — index creation, cell lookup, ST_Within vs H3 comparison

**Dependencies:** `duckdb>=1.6.0`, `h3` Python package (Uber's H3, pure Python bindings)

---

## V4-06 — GDPR / DSAR Module

**Why:** WorldBase processes personal data (Identity OSINT, Domain Intel, FtM Person entities). No Data Subject Access Request (DSAR) handling, no Right to be Forgotten, no data portability. Legal requirement for EU/UK operations.

**Scope:**
- `backend/gdpr.py` — DSAR export, erasure, restriction
- `GET /api/gdpr/subject/{entity_id}` — export all FtM entities + statements + edges + audit log entries for a person (JSON bundle)
- `POST /api/gdpr/subject/{entity_id}/erase` — cascade delete: entity + statements + edges + resolution labels + RAG vectors; audit log entry preserved with `erased_at` timestamp
- `POST /api/gdpr/subject/{entity_id}/restrict` — mark entity as restricted; future feed ingest skips matching; flag in FtM metadata
- `GET /api/gdpr/audit` — list all DSAR requests (admin only)
- `WORLDBASE_GDPR=0` (default off, opt-in)
- Tests: `test_gdpr.py` — export completeness, cascade delete, restriction enforcement, audit trail

**Design:**
- Erase uses `ftm_query.delete_entity()` (new) + RAG vector deletion + resolution label deletion
- Restriction sets `meta.restricted = true` on entity; `feed_ingest.py` checks before upsert
- Export includes: entity, statements, edges (both directions), resolution labels, RAG matches, briefing mentions
- All operations audit-logged via `auth/audit.py`

---

## V4-07 — Data Retention Policy Engine

**Why:** No configurable deletion periods. Identity OSINT results, dark web data, and personal entities accumulate indefinitely. Legal/ethical risk. GDPR requires purpose-limited retention.

**Scope:**
- `backend/retention.py` — policy engine with per-source retention rules
- YAML config: `backend/ingest/retention_policies.yaml`
  ```yaml
  identity_osint: 30d
  darkweb_results: 90d
  ransomware_victims: 180d
  ftm_persons_from_news: 365d
  ftm_sanctions: infinite
  ```
- Daily cleanup task: scan FtM entities by `source_feed` → delete expired → audit log
- `POST /api/admin/retention/run` — manual trigger
- `GET /api/admin/retention/policies` — view current policies
- `WORLDBASE_RETENTION=0` (default off — no automatic deletion)
- Tests: `test_retention.py` — policy matching, cascade delete, audit trail, exempt sources

---

## V4-08 — SQLite FTS5 Global Search ✅ Shipped (A3, 2026-06-30)

**Why:** No global search across entities, briefings, feeds, and documents. V3 proposed Meilisearch (extra daemon, ~50MB RAM). SQLite FTS5 is already built into SQLite, zero extra process, works offline perfectly, typo-tolerant with trigram tokenizer. Sufficient for single-user citizen station.

**Scope:**
- `backend/search_fts5.py` — SQLite FTS5 index management + search API
- Indexes: `entities_fts` (FtM entity names + properties), `briefings_fts` (briefing text + digest lines), `feeds_fts` (feed envelope metadata), `documents_fts` (RAG chunk text)
- Trigram tokenizer for typo tolerance (or porter tokenizer for English stemming)
- `GET /api/search?q=...&index=...&limit=20` — unified search endpoint
- Background indexing: on entity upsert / briefing save / feed ingest → FTS5 document add (trigger-based or explicit)
- `WORLDBASE_SEARCH=0` (default off, opt-in)
- Tests: `test_search_fts5.py` — indexing, search, typo tolerance, multi-index, fail-soft

**Advantages over Meilisearch:** Zero extra daemon, zero extra RAM, works offline, already in SQLite. Disadvantage: no fuzzy search as good as Meilisearch, but trigram tokenizer covers most typo cases.

---

## V4-09 — Daily Snapshot Archiver (Parquet) ✅ Shipped (B2, 2026-06-30)

**Why:** Most feeds deliver current state only. No historical depth for trend analysis or temporal replay. Daily snapshots in Parquet (columnar, compressed) prepare the foundation.

**Scope:**
- `backend/snapshot_archiver.py` — daily cron job (asyncio task in lifespan)
- Snapshots: feed envelopes (count, source, updated), FtM entity count, briefing quality, fusion hotspot coordinates, GDELT pulse, AIS position count, CAMS PM2.5
- Storage: `data/snapshots/YYYY/MM/DD.parquet` (DuckDB EXPORT or pyarrow)
- `GET /api/snapshots/list?from=&to=` — list available snapshots
- `GET /api/snapshots/{date}` — download snapshot as Parquet
- Frontend: timeline slider reads snapshots for temporal replay
- `WORLDBASE_SNAPSHOT_ARCHIVER=1` (default on — low overhead)
- `WORLDBASE_SNAPSHOT_RETENTION_DAYS=365` (auto-cleanup)
- Tests: `test_snapshot_archiver.py` — snapshot creation, Parquet schema, retention cleanup

**DuckDB synergy:** Parquet files are directly queryable by DuckDB (`read_parquet()`). Enables `SELECT * FROM 'data/snapshots/2026/06/*.parquet' WHERE ...` for historical analysis.

---

## V4-10 — Automatic Data Classification

**Why:** No classification labels on entities. Operators cannot distinguish public intel from sensitive/dark web data. Access control and handling rules differ by classification.

**Scope:**
- `backend/classification.py` — auto-classify entities on ingest
- Classification levels: `PUBLIC`, `INTERNAL`, `SECRET`
- Source-based rules:
  - Dark web, ransomware, identity OSINT → `INTERNAL`
  - News feeds (Reuters, GDELT), public APIs → `PUBLIC`
  - Sanctions, breach data → `SECRET`
- FtM `meta.classification` field on entity
- Audit log: access to `INTERNAL`/`SECRET` entities logged via `auth/audit.py`
- Alerting: unusual access patterns (bulk export of SECRET entities) → webhook
- `GET /api/admin/classification/rules` — view rules
- `WORLDBASE_CLASSIFICATION=0` (default off, opt-in)
- Tests: `test_classification.py` — source mapping, inheritance, audit logging

---

## V4-11 — Self-Consistency Voting

**Why:** Local 14B models with 4-bit quantization reach 90% of GPT-4o quality for OSINT tasks. Self-consistency voting (3× inference with different seeds, majority vote) closes the remaining gap. This is an asymmetrical advantage: no cloud dependency, better quality than single-pass.

**Scope:**
- `backend/self_consistency.py` — multi-sample inference + voting
- Pipeline: query → 3× Ollama inference (different `seed` param) → vote on most consistent answer
- Voting strategies: exact match (for structured output), embedding similarity (for free text), LLM judge (for complex answers)
- Integration in `chat_proxy.py` — when enabled, wraps LLM call with 3 samples
- `WORLDBASE_SELF_CONSISTENCY=0` (default off, opt-in)
- `WORLDBASE_SELF_CONSISTENCY_SAMPLES=3` (configurable)
- Tests: `test_self_consistency.py` — multi-sample, voting strategies, tie-breaking, fail-soft

**Cost:** 3× LLM calls. Only for complex queries (score >= 0.7 in model router). Online: use free cloud model 3× (fast). Offline: use local model 3× (slower but private).

---

## V4-12 — LoRA Fine-Tuning on OSINT Data

**Why:** Big Tech trains on billions of general data. A citizen can train targeted on **their own collected OSINT intel** (briefings, FtM graph extracts, manual corrections). With QLoRA on RTX 3080 Ti, a model can be trimmed to better understand "suspicious maritime pattern" than any generic cloud model. This is a personal OSINT co-pilot trained on your data — an asymmetrical advantage no corporation can replicate.

**Scope:**
- `scripts/train_lora.py` — QLoRA fine-tuning script
- Training data export: SQLite briefings + human evaluations → JSONL training dataset
  - Source: `briefings` table (text), `resolution_labels` table (human feedback), `prediction_ledger` (outcomes)
  - Format: instruction-response pairs ("Analyze this maritime pattern: ..." → "This indicates...")
- Model: qwen3-8b or DeepSeek-R1-Distill-Qwen-14B (4-bit quantization, LoRA rank 16-64)
- Training: overnight on RTX 3080 Ti (16GB VRAM sufficient for 8B QLoRA, 14B with Q4)
- Output: LoRA adapter weights → merge with base model or load as adapter in Ollama
- `POST /api/admin/train/lora` — trigger training (admin only, runs as background task)
- `GET /api/admin/train/status` — training progress, loss curve, ETA
- `WORLDBASE_LORA_TRAINING=0` (default off, opt-in)
- Tests: `test_lora_training.py` — data export, training config, adapter loading, fail-soft

**Dependencies:** `peft`, `trl`, `transformers`, `bitsandbytes` (all pip-installable, GPU required for training)

**Feasibility study findings:**
- Training time: 6–12 hours overnight. VRAM: ~14 GB (unloads 14B base model during training).
- **Data quality is the biggest risk**, not hardware. Filter: only briefings with `quality >= 0.7`, only manually verified resolution labels. A badly trained LoRA model is worse than the base model.
- Evaluation: run against existing test suite before merging. Rollback if quality drops.
- Training runs overnight when user sleeps (14B model unloaded, full VRAM for training).

---

## V4-13 — Speculative Decoding

**Why:** Local inference on 14B models is slower than cloud APIs. Speculative decoding uses a tiny draft model (Qwen3-0.5B) to propose fast tokens, and the large 14B model validates them. This accelerates inference by 2-3× at the same VRAM usage, bringing local latency closer to cloud API latency.

**Scope:**
- `backend/speculative_decode.py` — speculative decoding wrapper for Ollama
- Draft model: Qwen3-0.5B (fits in <1GB VRAM alongside 14B model)
- Target model: qwen3:14b (or any local model)
- Pipeline: draft model generates N candidate tokens → target model validates in parallel → accept/reject → repeat
- Integration: `chat_proxy.py` uses speculative decoding when local model selected and GPU available
- `WORLDBASE_SPECULATIVE_DECODING=0` (default off, opt-in)
- Tests: `test_speculative_decode.py` — draft generation, validation, speedup measurement, fail-soft

**Dependencies:** `transformers` (already installed), draft model download (Qwen3-0.5B, ~1GB)

**Feasibility study findings:**
- Ollama does not support native speculative decoding. The wrapper works outside Ollama (draft + target model in transformers).
- **Realistic effort: 400–600 LOC**, not 200. More complex than initially estimated.
- Alternative: wait for Ollama-native speculative decoding support (if it arrives).
- Only applies to local inference path. Cloud APIs handle their own optimization.

---

## V4-14 — Telegram Connector (Telethon) ✅ Shipped (C1, 2026-06-30 — audit complete)

**Why:** Telegram is the #1 platform for crisis OSINT (Syria, Ukraine, Sahel). Mastodon/Bluesky are planned but Telegram is mission-critical for real-time crisis intelligence. Free, invaluable crisis data, works online (scraping), no GPU needed.

**Scope:**
- `backend/telegram_bridge.py` — Telethon-based public channel monitor
- Config: `WORLDBASE_TELEGRAM_API_ID`, `WORLDBASE_TELEGRAM_API_HASH` (from my.telegram.org)
- Monitor list: YAML config `backend/ingest/telegram_channels.yaml` (channel ID, name, region, language)
- NER enrichment: GLiNER extraction (already in `intel_ingest.py`) → FtM Person/Organization/Event
- Geo-extraction: regex + NER for place names → lat/lon via existing `_TH_CITIES` + Nominatim
- `GET /api/telegram/messages?channel=&since=` — paginated messages
- `POST /api/telegram/ingest` — manual trigger for channel ingest
- Briefing: "TELEGRAM SOCMINT" block in `briefing_prompt.py`
- `WORLDBASE_TELEGRAM=0` (default off, opt-in)
- Tests: `test_telegram_bridge.py` — mock Telethon client, NER extraction, FtM mapping, fail-soft

**Compliance:** Public channels only. No private group access. No message storage beyond FtM metadata (text → entity, not raw archive). Rate-limited per Telegram API limits. When offline, simply pauses.

---

## V4-15 — BLIP Image Captioning (GPU RAG)

**Why:** ColQwen2 (V4-22) is the full multimodal solution but requires 3B params. BLIP is a lightweight alternative: generate text captions from webcam/satellite images, then index captions in existing text RAG. Every satellite image, every webcam snapshot, and later every Telegram image gets automatically captioned and indexed in the RAG vector store. A locally operated image search engine that competes with Google Lens for OSINT purposes, but preserves privacy.

**Scope:**
- `backend/image_captioning.py` — BLIP model loader (ONNX, GPU when available, CPU fallback)
- Inputs: webcam snapshots, satellite thumbnails (Sentinel-2 quicklook), briefing PDFs (page render)
- Pipeline: image → BLIP caption → text → `rag_memory.py` index
- GPU path: ONNX Runtime GPU provider when CUDA available (instant captioning)
- CPU path: ONNX Runtime CPU provider (slower, ~2-3s per image)
- Online optional: NVIDIA free VLM API for richer descriptions if desired, but local is the baseline
- `POST /api/memory/caption` — upload image → caption + index
- `GET /api/memory/caption/search?q=...` — search captions (uses existing RAG)
- `WORLDBASE_IMAGE_CAPTIONING=0` (default off, opt-in)
- `WORLDBASE_IMAGE_CAPTIONING_GPU=1` (auto-enable when GPU detected)
- Dependency: `onnxruntime` (+ `onnxruntime-gpu` for GPU path) + BLIP ONNX model (~400MB)
- Tests: `test_image_captioning.py` — mock model, caption generation, RAG indexing, GPU/CPU fallback

---

## V4-16 — ACLED Conflict Connector

**Why:** GDELT covers news-reported events. ACLED (Armed Conflict Location & Event Data) provides curated, geolocated conflict events for Africa, Middle East, Asia, Latin America. Fills Sahel/Africa/LatAm coverage gap. Free API, runs on PC, enriches feeds.

**Scope:**
- `backend/acled_bridge.py` — ACLED API client (REST, API key required)
- `GET /api/acled/events?bbox=&since=&event_type=` — conflict events as GeoJSON
- FtM mapping: ACLED event → FtM `Event` with geo, actors → `Organization`/`Person`
- Briefing: "CONFLICT EVENTS" block in LOCAL/REGION bucket
- Globe layer: conflict events (color-coded by event_type)
- `WORLDBASE_ACLED=0` (default off, opt-in)
- `WORLDBASE_ACLED_API_KEY` — required (free academic access)
- Tests: `test_acled_bridge.py` — mock API, FtM mapping, geo-coding, fail-soft

---

## V4-17 — STIX/TAXII 2.1 Server Endpoint

**Why:** Without STIX/TAXII, WorldBase cannot exchange intelligence with SIEMs (Splunk, Sentinel, QRadar) or TIPs (OpenCTI, MISP). This is the industry standard for threat-intel sharing. Not critical for citizen, but useful for sharing with community.

**Scope:**
- `backend/stix_taxii.py` — STIX 2.1 bundle import/export, TAXII 2.1 server
- FtM → STIX mapping (Person→Identity, Event→ObservedData, Organization→Identity, Domain→Infrastructure, Mention→ObservedData)
- `POST /api/stix/bundle` — import STIX 2.1 JSON bundle → FtM entities
- `GET /api/stix/bundle` — export current graph as STIX 2.1 bundle
- `GET /api/taxii/discovery` — TAXII 2.1 discovery service
- `GET /api/taxii/collections` — collection list
- `GET /api/taxii/collections/{id}/objects` — poll objects with `?since=` pagination
- `WORLDBASE_STIX_TAXII=0` (default off, opt-in)
- Dependency: `stix2` Python library (pure Python, 0 VRAM)
- Tests: `test_stix_taxii.py` — bundle round-trip, FtM mapping, TAXII pagination

**Key design decisions:**
- STIX bundle import reuses `entity_store.upsert_entity` + `ftm_query` — no new storage
- TAXII collections map to operator regions (thailand, west-asia, global)
- Provenance: STIX `created_by_ref` → FtM `source_feed` mapping

---

## V4-18 — GNN Event Correlation (MVP: Graph Attention Network)

**Why:** Current `relatedEvent` detection is rule-based (text overlap + spatial proximity). Big Tech uses Graph Neural Networks to find hidden connections. With PyTorch Geometric and the RTX 3080 Ti, a lightweight model can be trained on the FtM graph to embed entities and relationships into a vector space. Suddenly: "Find all entities that behave like this suspicious company." That's intelligence others pay six figures for.

**Feasibility study finding:** Heterogeneous GNN with PyTorch Geometric is too complex for 16 GB VRAM and ONNX export is risky. **MVP: Graph Attention Network (GAT) with homogeneous graph** — 80% of the benefit at 20% of the complexity. Heterogeneous GNN deferred to V2.

**Scope:**
- `backend/gnn_correlation.py` — GNN-based event correlation
- Training data: existing `intel_semantic_links` edges (positive) + random non-edges (negative)
- Model: 2-layer **Graph Attention Network (GAT)** with homogeneous graph (MVP). Heterogeneous GNN deferred to V2.
- ONNX export: GAT exports cleanly to ONNX (homogeneous graphs are simpler than heterogeneous)
- Features: entity type, source_feed, geo-distance, temporal delta, text embedding similarity
- Pipeline: train offline on GPU → export ONNX → deploy in `intel_semantic_links.py` as optional scorer
- Online mode: can use a more powerful free LLM to infer relations via prompt
- Offline mode: ONNX inference on CPU (0 VRAM) or rule-based fallback
- `POST /api/intel/gnn/train` — trigger training (admin)
- `POST /api/intel/gnn/predict` — run GNN scoring on current graph
- `WORLDBASE_GNN_CORRELATION=0` (default off, opt-in)
- Tests: `test_gnn_correlation.py` — mock model, feature extraction, ONNX inference, fail-soft

**VRAM note:** Training requires GPU (or CPU, slow). Inference via ONNX on CPU — 0 VRAM for deployment. Rule-based fallback when model unavailable.

---

## V4-19 — Predictive Analytics (LightGBM) ✅ Shipped (C2, 2026-06-30)

**Why:** Prediction ledger tracks watch-item outcomes but has no forecasting model. LightGBM on watch-item time series can estimate outbreak probabilities. Train nightly on GPU (or CPU), run predictions on CPU. Entirely local, no API. Closes the feedback loop.

**Scope:**
- `backend/predictive_analytics.py` — LightGBM forecaster on watch-item time series
- Features: daily event counts per region, GDELT tone trend, AIS anomaly rate, CAMS PM2.5 trend, fusion hotspot count
- Target: binary (escalation within 7 days) or regression (event count in 7 days)
- Training: `POST /api/predict/train` — uses historical watch-item outcomes from `prediction_ledger`
- Auto-retrain: every 30 days when enough labeled data accumulates
- Prediction: `GET /api/predict/forecast?region=&horizon=7d` — probability + confidence interval
- Briefing: "LOCAL CITIZEN FORECAST" block with top-3 predicted risks + probability
- `WORLDBASE_PREDICTIVE_ANALYTICS=0` (default off, opt-in)
- Dependency: `lightgbm` (CPU-only, 0 VRAM)
- Tests: `test_predictive_analytics.py` — feature extraction, training, prediction, auto-retrain

---

## V4-20 — Multi-Hypothesis Synthesis

**Why:** Current 2-pass synthesis (draft → critique → revise) produces a single hypothesis. MAVEN-style multi-hypothesis deliberation generates 3 competing hypotheses, tests each against evidence, and selects the best-supported one. When online, use free large models (OpenRouter/Groq/NVIDIA) for multi-draft synthesis. Offline: single-pass with optional two-pass (existing).

**Scope:**
- `backend/multi_hypothesis.py` — generate N hypotheses, score against evidence, select best
- Integration in `agent_orchestrator.py` Synthesis phase:
  1. Generate 3 hypotheses (different prompt prefixes: "optimistic", "pessimistic", "adversarial")
  2. Score each against blackboard evidence (coverage, corroboration, conflict count)
  3. Select highest-scoring hypothesis as final output
  4. Log all hypotheses + scores in briefing metadata
- Online: use free large model (e.g., google/gemini-2.5-flash on OpenRouter, or NVIDIA nemotron) for each draft
- Offline: single-pass with optional two-pass (existing WORLDBASE_TWO_PASS)
- `WORLDBASE_MULTI_HYPOTHESIS=0` (default off, opt-in)
- Tests: `test_multi_hypothesis.py` — hypothesis generation, scoring, selection, metadata

**Note:** This costs 3× LLM calls for synthesis. Only fires when `WORLDBASE_MULTI_HYPOTHESIS=1` AND `WORLDBASE_TWO_PASS=1`. Online: 3× cloud model (fast, free). Offline: 3× local model (slower) or single-pass fallback.

---

## V4-21 — Temporal Reasoning Agent

**Why:** Current graph has temporal edge decay (30-day half-life) but no temporal reasoning. The orchestrator describes what happened, not what will happen next. Temporal Knowledge Graph reasoning predicts future events from historical clue paths.

**Scope:**
- `backend/temporal_reasoning.py` — temporal pattern detection + prediction
- Rule-based temporal chains: "Event A (earthquake) → Event B (AIS gap) → Event C (port closure)" with time deltas
- Granger-causality on time-series feeds: AIS position count, GDELT event tone, CAMS PM2.5, earthquake magnitude
- `pandas` + `statsmodels` (already available) for Granger test — 0 VRAM
- Integration: 6th agent in orchestrator ("Temporal Analyst") — runs after Corroboration, before Synthesis
- Blackboard extension: `temporal_predictions` field with confidence + horizon
- Briefing: "TEMPORAL FORECAST" block in `briefing_prompt.py`
- `WORLDBASE_TEMPORAL_REASONING=0` (default off, opt-in)
- Tests: `test_temporal_reasoning.py` — pattern detection, Granger test, prediction generation, fail-soft

**Key design:**
- Temporal chains stored in SQLite `temporal_patterns` table (event_type_a, event_type_b, mean_delta_sec, std_delta_sec, observation_count)
- Patterns learned from `intel_semantic_links` (relatedEvent edges) + feed timestamps
- Prediction: when Event A observed, query patterns → predict Event B within mean_delta ± std_delta
- Confidence: observation_count × temporal_decay_factor × spatial_overlap

---

## V4-22 — ColQwen2 Multimodal RAG

**Why:** Current RAG is text-only. ColQwen2 indexes document pages as images (no OCR needed) and accepts text or image queries. Satellite imagery, webcam screenshots, PDF briefings, and intel documents could be directly searchable.

**Scope:**
- `backend/rag_multimodal.py` — ColQwen2 model loader (ONNX, CPU or GPU), image indexing, late-interaction matching
- Index pipeline: PDF page → PIL Image → ColQwen2 embeddings → SQLite vector store
- Query: text query → ColQwen2 → late-interaction scoring → ranked image results
- `GET /api/memory/multimodal/search?q=...` — search indexed images
- `POST /api/memory/multimodal/ingest` — upload image/PDF → index
- Integration with `rag_hybrid.py` — RRF fusion of text + multimodal results
- `WORLDBASE_RAG_MULTIMODAL=0` (default off, opt-in)
- Dependency: `colpali-engine` or ONNX export of ColQwen2 (~3B params, CPU-inferable, GPU-accelerated)
- Tests: `test_rag_multimodal.py` — mock model, indexing, query, fusion

**VRAM note:** ColQwen2-3B fits in 4GB VRAM or runs on CPU (slower). **Cannot coexist with 14B Ollama model in 16 GB VRAM.** Implement as on-demand microservice: ColQwen2 loaded only for multimodal queries, Ollama model unloaded first. CPU fallback (~5–10s per query) when VRAM occupied. Opt-in only.

---

## V4-23 — Anomaly Detection (Isolation Forest) ✅ SHIPPED

**Shipped:** 2026-06-30

**What:** Isolation Forest anomaly detection on 8 feed time series (GDELT event/geo count, earthquake count, CAMS PM2.5 avg, AIS position count, fusion hotspot count, GDACS count, hazard count). CPU-only, 0 VRAM.

**Implementation:**
- `backend/anomaly_detector.py` — `IsolationForest` with z-score fallback when sklearn not installed
- Feeds monitored: GDELT event count, GDELT geo count, earthquake count, CAMS PM2.5 avg, AIS position count, fusion hotspot count, GDACS count, hazard count
- Model: `sklearn.ensemble.IsolationForest` (CPU, 0 VRAM, `n_jobs=1`)
- Training: rolling 30-day window, daily retrain via autopilot
- Detection: `POST /api/anomalies/detect` — run detection on latest feed metrics
- Listing: `GET /api/anomalies/iso` — list stored detections (`?feed=&since=`)
- Training: `POST /api/anomalies/iso/train` — retrain from historical data
- Status: `GET /api/anomalies/iso/status` — model status + metrics
- FtM: anomaly → `Event` entity with `type=anomaly` via `ingest_anomalies_as_events()`
- Briefing: ANOMALY ALERT block in `briefing_prompt.py` + digest items in `briefing_digest.py` + watch items + `gather_anomaly_digest()` in `node_briefing.py`
- Autopilot: hourly detect + daily retrain in `lifespan.py`
- Model persistence: `data/anomaly_if_model.json` (pickle) + `data/anomaly_if_stats.json` (metadata)
- SQLite tables: `anomaly_metrics` (time series), `anomaly_detections` (stored anomalies)
- `WORLDBASE_ANOMALY_DETECTION=0` (default off, opt-in)
- `WORLDBASE_BRIEFING_ANOMALY=0` (default off, opt-in)
- Config: `anomaly_detection_enabled`, `briefing_anomaly` in `config.py`
- Feature flags: `anomaly_detection`, `briefing_anomaly` in `features.py`
- Router registered in `routes/registry.py`
- Tests: `test_anomaly_detector.py` (52 tests) — feature flags, DB init, metric extraction, feature matrix, severity mapping, storage, training (IF + z-score), detection, FtM ingestion, briefing digest, watch items, model status, fail-soft

---

## V4-24 — NetworkX Graph Algorithms

**Why:** No PageRank, community detection, or shortest-path on FtM graph. NetworkX (already Python, CPU-only, no API) can compute these now via DuckDB → Pandas → NetworkX → DuckDB. High insight value, zero cost.

**Scope:**
- `backend/graph_algorithms.py` — NetworkX integration
- Algorithms: Louvain community detection, PageRank centrality, betweenness centrality, shortest-path
- Pipeline: export FtM edges to Pandas DataFrame → NetworkX graph → compute → write results to DuckDB `graph_metrics` table
- `POST /api/intel/graph/compute` — trigger computation (admin)
- `GET /api/intel/graph/communities` — community assignments
- `GET /api/intel/graph/centrality?type=pagerank` — centrality scores
- Frontend: Intel panel shows top-10 central entities, community coloring on Cytoscape
- `WORLDBASE_GRAPH_ALGORITHMS=0` (default off, opt-in)
- Tests: `test_graph_algorithms.py` — graph construction, algorithm execution, result persistence

---

## V4-25 — ReAct Loop in Agentic Chat

**Why:** Chat tools (focus_globe, spatial_query, verify_claim) exist but are not orchestrated. A ReAct (Reason+Act) loop enables multi-step autonomous OSINT research: LLM thinks → selects tool → gets result → thinks again. When online, the orchestrator uses a free large model; offline: scaled-down version with local Qwen3 and limited tool set.

**Scope:**
- `backend/react_loop.py` — ReAct loop implementation
- Loop: `thought → action → observation → thought → ...` until done or max iterations
- Available tools: `focus_globe`, `spatial_query`, `entity_context`, `verify_claim`, `geocode_place`
- Max iterations: 10 (configurable via `WORLDBASE_REACT_MAX_ITER`)
- Integration in `chat_agentic.py` — when ReAct enabled, replaces linear 3-phase with iterative loop
- Frontend: Agent Bus shows `react_thought` / `react_action` / `react_observation` events
- `WORLDBASE_REACT_LOOP=0` (default off, opt-in)
- Tests: `test_react_loop.py` — tool selection, iteration limit, observation parsing, fail-soft

---

## V4-26 — Automated Red-Team Pipeline

**Why:** Anti-hallucination stack has 96.2% block rate on 78 fixtures. But new attack vectors emerge continuously. Automated red-team bot generates adversarial prompts via LLM mutation, tests all 4 guard layers, and reports bypasses. High-quality assurance without added hardware.

**Scope:**
- `backend/red_team.py` — automated adversarial prompt generation + testing
- Mutation strategies: roleplay injection, authority claim, emotional manipulation, base64 encoding, leetspeak, homoglyph substitution, multi-turn buildup
- Test against: `prompt_guard.py`, `rag_integrity.py`, `session_guard.py`, `output_guard.py`
- Report: bypass rate per layer, per mutation strategy, per guard pattern
- `POST /api/admin/red-team/run` — trigger red-team sweep (admin only)
- `GET /api/admin/red-team/report` — latest report
- CI integration: `scripts/red-team-ci.py` — runs in GitHub Actions on PR
- `WORLDBASE_RED_TEAM=0` (default off, opt-in)
- Tests: `test_red_team.py` — mutation generation, guard testing, report generation

---

## V4-27 — Cross-Feed Event Correlation (Rule + LLM)

**Why:** Current rule engine finds candidate correlations. A free LLM (online) can evaluate if two events are truly linked and generate a confidence score. Offline: skip the LLM step, show candidates only.

**Scope:**
- `backend/cross_feed_correlation.py` — rule-based candidate generation + LLM evaluation
- Rule engine: existing `intel_semantic_links.py` for fast candidates (spatial + temporal overlap)
- LLM evaluation: when online, send candidate pairs to free cloud model for semantic relatedness scoring
- Offline: rule-based candidates only, confidence from spatial/temporal overlap score
- `POST /api/intel/correlate` — trigger correlation run
- `GET /api/intel/correlations?since=` — list correlated event pairs
- Briefing: "CROSS-FEED CORRELATION" block when high-confidence correlations found
- `WORLDBASE_CROSS_FEED_CORRELATION=0` (default off, opt-in)
- Tests: `test_cross_feed_correlation.py` — rule candidates, LLM evaluation, offline fallback

---

## V4-28 — Whisper Voice Control (GPU)

**Why:** "WorldBase, was ist heute wichtig?" — voice control for "Ask the Globe". faster-whisper with CUDA for offline speech-to-text. Activates on hotkey. Simple intent mapping like the current NL mapper. No microphone data sent to AWS. Barrierefreiheit for all.

**Scope:**
- `backend/voice_stt.py` — faster-whisper with CUDA backend
- Hotkey activation (configurable, default: Ctrl+Space)
- Audio capture: `sounddevice` (microphone input, 5s default)
- STT: faster-whisper `WhisperModel("base", device="cuda", compute_type="int8_float16")` on GPU
- CPU fallback: `device="cpu"` when no GPU
- Intent mapping: reuse existing NL mapper in `chat_tools.py`
- Integration: STT result → `/api/chat` endpoint → response → optional TTS (V4-29)
- `WORLDBASE_VOICE_STT=0` (default off, opt-in)
- Tests: `test_voice_stt.py` — mock audio, transcription, intent mapping, GPU/CPU fallback

**Dependencies:** `faster-whisper`, `sounddevice` (both pip-installable)

---

## V4-29 — Piper TTS for Briefing Narration

**Why:** Read out the morning briefing while you make coffee. CPU-only, works offline, no cloud dependency. Piper is a fast, local neural TTS system.

**Scope:**
- `backend/voice_tts.py` — Piper TTS wrapper
- Model: Piper en_US-amy-medium (~60MB, CPU-only, ~5× real-time on i9)
- Input: briefing text → sentence splitting → TTS → WAV/MP3 output
- `POST /api/briefing/narrate` — generate audio for latest briefing
- `GET /api/briefing/audio/{id}` — download audio file
- Frontend: play button on briefing panel
- `WORLDBASE_VOICE_TTS=0` (default off, opt-in)
- `WORLDBASE_TTS_MODEL=en_US-amy-medium` (configurable, download from Piper releases)
- Tests: `test_voice_tts.py` — text splitting, TTS generation, audio output, fail-soft

**Dependencies:** `piper-tts` (pip-installable, CPU-only, no GPU needed)

---

## V4-30 — PWA + Notification Bell

**Why:** No mobile UI. No in-app notifications. A PWA wrapper enables field use on tablets/phones. Offline-capable after first load. Works on any cheap Android via browser — no App Store needed.

**Scope:**
- `frontend/vite.config.ts` — add `vite-plugin-pwa` with manifest + service worker
- `frontend/src/components/NotificationBell.tsx` — bell icon with unread count, dropdown list
- `frontend/src/hooks/useNotifications.ts` — SSE subscription to alert events (reuse Agent Bus SSE)
- Alert sources: `alerting.py` webhook conditions → SSE event → notification bell
- `frontend/src/lib/pwa.ts` — offline briefing cache (service worker caches last briefing JSON)
- Leaflet map for mobile (lighter than Cesium, loads faster on cheap phones)
- Tests: Vitest component test for NotificationBell + useNotifications

**Effort:** ~150 LOC frontend, 0 backend changes (SSE already exists)

---

## V4-31 — Deck.gl/Kepler.gl Analyst Dashboard

**Why:** Cesium is primary visualization. Specialized analytical visualizations (flow maps, Sankey diagrams, timelines) need deck.gl or Kepler.gl. Professional analysts expect these.

**Scope:**
- `frontend/src/components/AnalystDashboard.tsx` — separate tab with deck.gl/Kepler.gl
- Visualizations:
  - **Flow maps:** AIS route streams, entity movement patterns
  - **Sankey diagrams:** FtM money/resource flows between organizations
  - **Timeline:** GDELT event timeline, briefing history, entity first_seen/last_seen
  - **Heatmap:** H3-weighted fusion hotspot density
  - **Scatter plot:** earthquake magnitude vs depth, AIS speed vs course
- Data source: existing API endpoints (`/api/intel/entities`, `/api/ais/positions`, `/api/gdelt/geo`)
- `frontend/src/lib/deckglLayers.ts` — reusable deck.gl layer configs
- **Lazy loading required:** deck.gl is ~1 MB gzipped. Separate route `/analyst` with lazy loading. Do NOT include in main Cesium bundle.
- Tests: Vitest component tests for each visualization type

---

## V4-32 — Multi-User Collaboration (Yjs)

**Why:** No multi-user features. Professional teams need shared annotations, collaborative briefing review, and real-time cursor sharing. WebSocket Gateway already shipped — perfect backend foundation.

**Scope:**
- `backend/collab.py` — Yjs document server via WebSocket
  - Shared documents: briefing annotations, entity notes, globe markers
  - CRUD via Yjs CRDT (conflict-free replicated data types)
  - Persistence: Yjs document state → SQLite `collab_documents` table
- `frontend/src/hooks/useCollab.ts` — Yjs client hook
  - `useCollabDocument(docId)` — subscribe to shared document
  - Cesium entity annotations sync in real-time
  - Briefing insight comments sync across users
- `frontend/src/components/CollabCursor.tsx` — shared cursor overlay on globe
- `WORLDBASE_COLLAB=0` (default off, opt-in)
- Auth: requires `WORLDBASE_RBAC=1` — only authenticated users can join
- Tests: `test_collab.py` — document creation, CRDT sync, persistence, auth gate

---

## V4-33 — Pi Offline RAG Service

**Why:** On the Pi runs a miniature version of the RAG system, fed with condensed briefings and entity dossiers. Over a 7-inch touchscreen (30 EUR) or smartphone on local WiFi, anyone in the household can do OSINT research — the Legion PC can be off. A personal intelligence butler that only needs wall power.

**Scope:**
- `offgrid-raspi/pi_rag.py` — lightweight RAG service on Pi 4
- Vector store: **SQLite vector store with numpy-based cosine similarity** (not Qdrant — Pi 4 RAM is too constrained for Docker + Qdrant). Pure Python, no extra process.
- Knowledge base: sync from PC via `/api/node/pull` — last 10 briefings, top 100 entities, active watch items (~5 MB total)
- API: tiny FastAPI on Pi (port 8081) — `GET /search?q=...` → vector search → return briefing/entity snippets
- UI: mobile-friendly web page (Flask or FastAPI static) for Pi's LCD or WiFi-connected phone
- Sync: PC pushes condensed KB to Pi on briefing generation; Pi pulls when PC is online
- Offline mode: Pi serves from local vector store, no PC needed
- `WORLDBASE_PI_RAG=0` (default off, opt-in)
- Tests: `offgrid-raspi/test_pi_rag.py` — vector store, search, sync, fail-soft

**Dependencies:** `numpy` (pure Python cosine), `fastapi` on Pi. No Qdrant, no Docker on Pi.

---

## V4-34 — ONNX Edge Inference (Pi)

**Why:** Pi is display-only. Sensor data (ESP32 DHT/USB) is sent raw to PC for processing. Edge inference on Pi 4 (4GB+ RAM) with ONNX Runtime can classify sensor anomalies locally in ~47ms, reducing bandwidth and enabling offline alerting.

**Scope:**
- `offgrid-raspi/edge_inference.py` — ONNX Runtime model loader, sensor anomaly classifier
- Model: lightweight MobileNetV2 or custom 3-layer MLP trained on historical sensor data
- Input: temperature, humidity, GPS, mesh node count → Output: normal/anomaly + confidence
- When anomaly detected: immediate LCD alert + push to PC (high priority)
- When normal: batch send every 5 min (current behavior)
- `offgrid-raspi/edge_buffer.py` — entropy-based buffering: high-entropy sensor readings prioritized
- Model training: `scripts/train_edge_model.py` on PC using historical Pi sensor data from `node_push_log`
- Tests: `offgrid-raspi/test_edge_inference.py` — model loading, classification, fail-soft

**Dependencies:** `onnxruntime` on Pi (ARM64 wheel available), `numpy`

---

## V4-35 — Generic CKAN Harvester

**Why:** C.3 (Thailand data.go.th) was a one-off connector. Many national open data portals use CKAN. A generic harvester with YAML mappings can integrate all of them.

**Scope:**
- `backend/ckan_harvester.py` — abstract CKAN client (generalizes `thai_opendata.py`)
- Config: `backend/ingest/ckan_sources.yaml` — list of CKAN instances with API URL, region, keyword filters
  ```yaml
  sources:
    - name: thailand
      url: https://data.go.th/api/3/action
      region: thailand
      keywords: [environment, air quality, water]
    - name: uk
      url: https://data.gov.uk/api/3/action
      region: europe
      keywords: [environment, transport]
  ```
- `GET /api/ckan/sources` — list configured sources
- `GET /api/ckan/{source}/datasets` — browse datasets
- `POST /api/ckan/{source}/ingest` — ingest to FtM
- `WORLDBASE_CKAN_HARVESTER=0` (default off, opt-in)
- Tests: `test_ckan_harvester.py` — multi-source config, dataset fetch, FtM mapping

---

## V4-36 — ADS-B + SatNOGS (RF OSINT)

**Why:** AIS covers maritime. No air traffic tracking (ADS-B) or satellite telemetry (SatNOGS). These are open-source RF OSINT that complement AIS for comprehensive transportation monitoring. ADS-B via local SDR stick is offline-capable but online for data enrichment.

**Scope:**
- `backend/adsb_bridge.py` — ADS-B Exchange API client (aircraft positions)
  - `GET /api/adsb/aircraft?bbox=` — aircraft in bbox as GeoJSON
  - Globe layer: aircraft icons (similar to AIS vessels)
  - Anomaly: military aircraft, unusual routes, disappeared transponders
- `backend/satnogs_bridge.py` — SatNOGS Network API client (satellite observations)
  - `GET /api/satnogs/observations?since=` — satellite passes
  - Globe layer: satellite trajectories
  - Intel: identify unusual satellite behavior, communication blackouts
- `WORLDBASE_ADSB=0`, `WORLDBASE_SATNOGS=0` (both default off, opt-in)
- Tests: `test_adsb_bridge.py`, `test_satnogs_bridge.py` — mock API, geo-mapping, fail-soft

---

## V4-37 — Sentinel-1 SAR Integration

**Why:** Sentinel-2 (optical) cannot see through clouds or at night. Sentinel-1 (SAR) is weather-independent and can detect ships at any time. For maritime anomaly detection, SAR is a game-changer: ship detection in fog/night/storms.

**Scope:**
- `backend/sar_bridge.py` — Copernicus Sentinel-1 GRD search + ship detection
- Ship detection: CFAR (Constant False Alarm Rate) algorithm on SAR amplitude
- `GET /api/sar/ships?bbox=...&since=...` — detected ships as GeoJSON
- Cross-reference with AIS: SAR-detected ships without AIS → dark vessels → anomaly
- Globe layer: SAR ship detections (red = no AIS match, green = AIS confirmed)
- Briefing: "SAR MARITIME" block when dark vessels detected in operator region
- `WORLDBASE_SAR=0` (default off, opt-in)
- Dependency: `rasterio` (already installed for K4), `scipy` (for CFAR)
- Tests: `test_sar_bridge.py` — mock SAR data, CFAR detection, AIS cross-reference

**Feasibility study finding:** Sentinel-1 GRD data is ~1 GB per scene. Download + processing is bandwidth- and CPU-intensive. **Implement as daily batch process, not real-time.** AIS cross-reference requires temporal synchronization (SAR scene time close to AIS positions).

---

## V4-38 — Federated Citizen Mesh (Experiment)

**Why:** The ultimate spear-equalizer. Multiple WorldBase instances (citizen-to-citizen) could exchange encrypted summaries of entities or warnings — without a central server, without a corporation in the middle. A decentralized early-warning system that Big Tech neither controls nor can shut down.

**Feasibility study finding:** This is the philosophically most important feature, but also the most technically complex. **Classified as experiment, not production feature.** Start with 2–3 peers in a VPN. Unsolved problems: NAT-Traversal (citizen instances behind router NATs), key management on Pi (no TPM), trust mechanism (gossip without central authority). Do NOT promise in 16-week timeline.

**Scope:**
- `backend/federation.py` — instance-to-instance encrypted intel exchange
- `POST /api/federation/share` — push local subgraph (PUBLIC classification only) as encrypted STIX bundle to peer instances
- `POST /api/federation/receive` — receive encrypted STIX bundle from peer → decrypt → FtM import
- `GET /api/federation/peers` — list configured peer instances
- Config: `backend/ingest/federation_peers.yaml` — peer URLs + public keys
- Encryption: end-to-end via `cryptography` library (X25519 key exchange, AES-256-GCM)
- Provenance: peer-sourced entities tagged with `source_feed=federation:{peer_name}`
- Access control: only `PUBLIC` classification entities shared (depends on V4-10)
- Gossip protocol: peers relay warnings to other peers (mesh, not star topology)
- `WORLDBASE_FEDERATION=0` (default off, opt-in)
- Tests: `test_federation.py` — bundle export/import, encryption, peer config, provenance, classification gate

**Depends on:** V4-17 (STIX/TAXII), V4-10 (Data Classification)

---

## V4-39 — Bitemporal Graph (valid_from / valid_until)

**Why:** Edges have temporal decay but no proper bitemporal model. Point-in-time queries ("What did we know about entity X on date Y?") require valid_time + transaction_time.

**Scope:**
- `ftm_schema.py` migration: add `valid_from`, `valid_until` to `statements` table
- `valid_from`/`valid_until`: when the fact was true in reality (from source data)
- `first_seen`/`last_seen`: when WorldBase recorded it (transaction time — already exists)
- `ftm_query.py`: `get_entity_at_time(entity_id, timestamp)` — returns entity state at point in time
- `GET /api/intel/entity/{id}/history?at=2025-01-01` — point-in-time query
- Frontend: timeline slider on entity detail modal shows historical state
- `WORLDBASE_BITEMPORAL=0` (default off, opt-in)
- Tests: `test_bitemporal.py` — migration, point-in-time query, valid_until handling

---

## V4-40 — FtM Ontology Extension

**Why:** Standard FtM types (Person, Organization, Event) are good for financial crime. Security/military intelligence needs: MilitaryUnit, Incident, Infrastructure, SupplyRoute.

**Scope:**
- `backend/ftm_extended_schema.py` — extended entity types as Thing subclasses
- New types:
  - `MilitaryUnit` (subclass of Organization): unit_id, branch, country, strength
  - `Incident` (subclass of Event): severity, casualties, status
  - `Infrastructure` (subclass of Thing): type (port/airport/powerplant/refinery), capacity, status
  - `SupplyRoute` (subclass of Thing): origin, destination, mode, status
- `ftm_schema.py` migration: add new tables/columns for extended properties
- `ftm_query.py`: typed queries per extended type
- Feed ingest: YAML mappings updated to use extended types where appropriate
- Globe layer: infrastructure icons (port/airport/powerplant symbols)
- `WORLDBASE_FTM_EXTENDED=0` (default off, opt-in)
- Tests: `test_ftm_extended.py` — schema migration, CRUD, typed queries

---

## V4-41 — Disaster Recovery Automation

**Why:** `backup.ps1` is manual. Production needs daily automated snapshots, encrypted off-site storage, and point-in-time recovery.

**Scope:**
- `scripts/backup_auto.py` — automated daily backup
- Backup targets: SQLite (VACUUM INTO), DuckDB (EXPORT DATABASE), fusion parquet, subgraph JSON, TLE
- Storage: S3-compatible (MinIO, AWS S3, Backblaze B2) via `boto3`
- Encryption: AES-256 via `cryptography` library before upload
- Retention: daily (30 days), weekly (12 weeks), monthly (12 months)
- `POST /api/admin/backup/run` — manual trigger
- `GET /api/admin/backup/status` — last backup time, size, location
- Restore: `scripts/restore.py` — download + decrypt + restore
- `WORLDBASE_BACKUP_AUTO=0` (default off, opt-in)
- `WORLDBASE_BACKUP_S3_URL`, `WORLDBASE_BACKUP_S3_BUCKET`, `WORLDBASE_BACKUP_S3_KEY`, `WORLDBASE_BACKUP_S3_SECRET`
- Tests: `test_backup_auto.py` — backup creation, encryption, S3 upload (mock), restore

---

## V4-42 — Chaos + Load + Property Tests

**Why:** No fault injection, no load testing, no property-based testing. Confidence in resilience is based on unit tests only. High-quality assurance without added hardware.

**Scope:**
- `backend/test_chaos.py` — chaos engineering tests:
  - DuckDB FATAL injection → verify 3-tier recovery
  - Redis connection drop → verify in-memory fallback
  - Ollama timeout → verify briefing fail-soft
  - Feed connector 500 → verify stale cache served
- `scripts/locustfile.py` — load testing:
  - `/api/briefing` (1 req/6h sim), `/api/chat` (10 concurrent), `/api/intel/entities` (50 concurrent)
  - Measure p50/p95/p99 latency + error rate
- `backend/test_property.py` — Hypothesis property-based tests:
  - `ftm_schema.py`: "For all valid entity types, upsert + query round-trips"
  - `entity_resolution.py`: "For all duplicate pairs, resolution is deterministic"
  - `briefing_quality.py`: "For all briefing texts, quality score is in [0, 1]"
- `WORLDBASE_CHAOS_TEST=0` (default off — only runs in CI or manual)

---

## V4-43 — Country Instability Index (CII)

**Why:** WorldMonitor's biggest UX advantage: a quantitative 0–100 stress score per country, computed every ~8 minutes from weighted signal families. A user sees "Thailand CII = 34, +12 in 24h" and knows the stress level instantly. WorldBase's briefing is narrative; CII is numerical. This is the single highest-leverage gap to close.

**Scope:**
- `backend/cii_engine.py` — Country Instability Index calculation engine
- **Score model:** `score = baseline_risk * 0.40 + event_score * 0.60 + supplemental_boosts` (clamped 0–100)
- **4 signal families (event_score):**
  - **Conflict 30%** — ACLED battles/explosions (when V4-16 shipped), GDELT conflict tone, fatalities, OREF-style alerts
  - **Unrest 25%** — GDELT protest events, ACLED protests/riots (when available), outage severity
  - **Security 20%** — Military flights (ADS-B when V4-36 shipped), AIS military vessels, aviation closures, GPS jamming (when feed available)
  - **Information 25%** — NewsData headline volume + GDELT tone velocity, classified threat summaries
- **Supplemental boosts (capped):** Earthquakes +25, Displacement +20, Travel advisories +15, Climate anomalies +15, Sanctions +14, Cyber threats +12, Maritime disruptions +10, Wildfires +8
- **Floor scores:** UCDP active war ≥70, UCDP minor conflict ≥50, Do-not-travel ≥60, Reconsider-travel ≥50
- **Tier-1 countries:** 31 curated countries with individual `baseline_risk` + `event_multiplier` (config YAML)
- **All other countries:** `DEFAULT_BASELINE_RISK = 15`, `DEFAULT_EVENT_MULTIPLIER = 1.0`
- **24h delta:** daily snapshot comparison → signed movement (+/- points)
- **Redis cache:** versioned by `methodology_version` with stale-cache fallback
- API: `GET /api/cii/scores` — all country scores, `GET /api/cii/scores/{country_code}` — single country with component breakdown, `GET /api/cii/trend/{country_code}?days=7` — historical trend
- Briefing: "CII SNAPSHOT" block in `briefing_prompt.py` — top-5 stressed countries in operator region + 24h movers
- Frontend: CII choropleth heatmap layer on Cesium, CII panel with component bar chart
- `WORLDBASE_CII=0` (default off, opt-in)
- `WORLDBASE_CII_INTERVAL=480` (recompute every 8 minutes, configurable)
- Config: `backend/ingest/cii_countries.yaml` — per-country baseline + multiplier
- Tests: `test_cii_engine.py` — score calculation, component weighting, floor enforcement, supplemental caps, 24h delta, cache fallback, fail-soft

**Dependencies:** GDELT (shipped), NewsData (shipped), earthquake feeds (shipped). ACLED (V4-16) enhances Conflict component but is not required — GDELT covers it. ADS-B (V4-36) enhances Security but is not required.

**Key design:**
- CII is intentionally not a raw media-volume index. Log dampening for high-observability countries prevents news-heavy countries from inflating.
- Provenance integration: each component score tagged with source feeds and reliability weights (reuses `provenance.py`)
- Snapshot integration: CII scores archived daily via V4-09 (✅ Shipped) for historical trend

---

## V4-44 — MCP outputSchema + JMESPath Projection

**Why:** WorldMonitor's MCP server exposes 39 tools with `outputSchema` (MCP 2025-06-18 spec) and `jmespath` server-side projection (80–95% response size reduction). WorldBase has 13 MCP tools with neither. This is a quick win: low effort, high token-efficiency impact, better MCP spec compliance.

**Scope:**
- `backend/mcp_schema.py` — outputSchema generation from Pydantic response models
  - For each MCP tool, auto-generate JSON Schema from the FastAPI response model
  - Include in `tools/list` response as `outputSchema` field (MCP 2025-06-18 spec)
  - Clients can validate responses and author projections without `tools/call`
- `backend/mcp_jmespath.py` — JMESPath server-side projection
  - Every tool accepts optional `jmespath` string argument
  - Apply JMESPath expression to response JSON after tool execution, before return
  - Typical reduction: 80–95% (e.g., `briefings[*].insights[*].title` instead of full briefing object)
- `describe_tool` meta-tool: returns full uncompressed tool definition (for when compressed `tools/list` description is ambiguous)
- `summary` flag on cache-backed tools: returns counts + 3-item samples instead of full lists
- Update all 13 existing MCP tools in `mcp_server.py` to include `outputSchema` + accept `jmespath`
- `WORLDBASE_MCP_OUTPUT_SCHEMA=1` (default on — spec compliance)
- `WORLDBASE_MCP_JMESPATH=1` (default on — token efficiency)
- Tests: `test_mcp_schema.py` — schema generation correctness, JMESPath projection, describe_tool, summary flag

**Dependencies:** `jmespath` Python library (pure Python, 0 VRAM, pip-installable)

---

## V4-45 — Bootstrap Hydration Endpoint

**Why:** WorldMonitor loads all key data in 2 parallel requests (`/api/bootstrap?tier=fast` + `?tier=slow`) with CDN caching. WorldBase's frontend polls 20+ individual endpoints on page load. A bootstrap endpoint cuts Time-to-Interactive significantly and reduces API call overhead.

**Scope:**
- `backend/bootstrap.py` — aggregated bootstrap endpoint
- `GET /api/bootstrap?tier=fast` — critical real-time data (s-maxage=1200, stale-while-revalidate=300):
  - Latest briefing (insights, watch_items, quality)
  - Fusion hotspots (current)
  - Feed status (fresh/stale/error counts)
  - Active situations
  - CII scores (when V4-43 enabled)
  - AIS positions (latest snapshot, capped at 500)
  - Anomaly detections (latest 10, when V4-23 enabled)
- `GET /api/bootstrap?tier=slow` — less time-sensitive data (s-maxage=7200, stale-while-revalidate=1800):
  - FtM entity counts + graph stats
  - GDELT pulse summary
  - CAMS PM2.5 latest
  - Earthquake events (last 24h)
  - Dark web digest (when enabled)
  - Ransomware digest (when enabled)
  - Prediction forecast (when V4-19 enabled)
- Redis cache: each tier cached as a single Redis key with TTL matching s-maxage
- Frontend: replace individual polling on page load with 2 bootstrap fetches, then switch to individual SmartPollLoop (V4-46) for updates
- `WORLDBASE_BOOTSTRAP=0` (default off, opt-in)
- Tests: `test_bootstrap.py` — tier assembly, cache hit/miss, staleness, fail-soft (missing feeds don't break bootstrap)

**Key design:**
- Bootstrap is additive — individual endpoints remain available for targeted polling
- Each sub-section fails independently (one feed down → bootstrap still returns rest)
- Negative caching: `__WM_NEG__` sentinel for missing data (avoid re-fetching known-empty)

---

## V4-46 — SmartPollLoop (Adaptive Data Refresh)

**Why:** WorldMonitor's SmartPollLoop implements exponential backoff (2× per failure, up to 4×), hidden-tab throttle (5× interval when `visibilityState=hidden`), manual trigger, attempt tracking → circuit breaker, and reason tagging. WorldBase's frontend polls with fixed intervals — no backoff, no hidden-tab optimization. Reduces API calls and improves resilience.

**Scope:**
- `frontend/src/hooks/useSmartPoll.ts` — adaptive polling hook
- **Exponential backoff:** consecutive failures multiply poll interval by `backoffMultiplier` (default 2×), up to 4× base interval. Single success resets to 1×.
- **Hidden-tab throttle:** when `document.visibilityState === 'hidden'`, multiply interval by `hiddenMultiplier` (default 5×). A 60s poll slows to 5min when tab is backgrounded.
- **Manual trigger:** `handle.triggerNow()` forces immediate poll regardless of interval.
- **Attempt tracking:** consecutive failure counter feeds into circuit breaker. After `maxAttempts` (default 5), poll loop stops and circuit breaker serves cached data.
- **Reason tagging:** each poll carries `SmartPollReason` (`'interval'`, `'resume'`, `'manual'`, `'startup'`) so handlers can adjust (e.g., startup polls fetch larger datasets).
- Replace existing `setInterval`-based polling in `useFeedStatus`, `useBriefing`, `useFusionHotspots`, `useSituations`, etc.
- Tests: Vitest for backoff, throttle, circuit breaker, manual trigger

**Effort:** ~200 LOC frontend, 0 backend changes

---

## V4-47 — Route Explorer + Scenario Engine

**Why:** WorldMonitor's flagship workflows: Route Explorer plans shipments between countries (chokepoint exposure, bypass corridors, land alternatives, per-country import exposure). Scenario Engine runs pre-built disruption scenarios (conflict, weather, sanctions, tariff shocks) and resolves impact across chokepoints, sectors, and countries on the map. WorldBase has maritime AIS and chokepoint awareness in fusion, but no interactive what-if tool. This is the biggest analytical gap for operational intelligence use.

**Scope:**
- `backend/route_explorer.py` — route analysis engine
  - Input: origin country, destination country, HS2 commodity code (optional)
  - Output: 4 tabs — Current Route, Alternatives, Land Corridors, Impact Summary
  - Chokepoint exposure: Hormuz, Malacca, Suez, Panama, Bab-el-Mandeb, Taiwan Strait, Bosphorus
  - Bypass corridors: alternative sea routes with distance/time delta
  - Land alternatives: rail/road corridors (China-Europe rail, Trans-Siberian, etc.)
  - Per-country import exposure: % of GDP dependent on transited goods
  - Data: AIS positions (current), GDELT events along route, fusion hotspots, chokepoint status
- `backend/scenario_engine.py` — disruption scenario simulator
  - Pre-built scenarios: Hormuz closure, Malacca piracy surge, Suez blockage, Taiwan Strait conflict, global sanctions shock, tariff war, major earthquake near port
  - Each scenario: affected chokepoints, affected countries, affected sectors, estimated duration
  - Map overlay: highlighted affected regions, disrupted routes, alternative corridors
  - Supply Chain panel: per-country impact summary
  - `POST /api/scenario/run?scenario=hormuz_closure` — execute scenario, return impact assessment
  - `GET /api/scenario/list` — available scenarios
- Frontend: `RouteExplorer.tsx` modal + `ScenarioEngine.tsx` panel
  - Route drawn on Cesium with chokepoint markers
  - Scenario overlay: affected regions highlighted, disrupted routes in red, alternatives in green
- `WORLDBASE_ROUTE_EXPLORER=0` (default off, opt-in)
- `WORLDBASE_SCENARIO_ENGINE=0` (default off, opt-in)
- Tests: `test_route_explorer.py` — chokepoint detection, route calculation, exposure analysis; `test_scenario_engine.py` — scenario execution, impact propagation

**Dependencies:** AIS (shipped), GDELT (shipped), fusion hotspots (shipped), chokepoint config (new YAML). CII (V4-43) enhances scenario impact scoring but is not required.

---

## V4-48 — Browser-Side ML (ONNX NER + Scoring)

**Why:** WorldMonitor runs a 3-stage pipeline client-side: keyword pre-filter → browser ML model (ONNX) → optional LLM refinement. Headline scoring and NER happen in the browser, reducing server load and enabling offline analysis. WorldBase's ML is entirely server-side (Ollama/NVIDIA NIM). Client-side ML is a paradigm shift for privacy and offline capability.

**Scope:**
- `frontend/src/lib/browserNer.ts` — Transformers.js (ONNX) NER in Web Worker
  - Model: `Xenova/bert-base-NER` or smaller `Xenova/distilbert-base-uncased` (~250MB, cached in IndexedDB)
  - Input: news headlines, GDELT event descriptions, briefing insight text
  - Output: entities (Person, Organization, Location) with confidence scores
  - Feed into existing entity matching pipeline (client-side pre-filter before server enrichment)
- `frontend/src/lib/browserScorer.ts` — headline importance scoring in Web Worker
  - Model: lightweight ONNX classifier (fine-tuned DistilBERT or custom 3-layer MLP)
  - Input: headline text → Output: importance score 0–1
  - Enables priority-based rendering (high-score headlines first)
  - Training: export from server-side labeled data (briefing quality scores + manual corrections)
- `frontend/src/workers/mlWorker.ts` — Web Worker for ML inference (doesn't block UI)
- ONNX Runtime capability detection: WebGL backend when available, WASM fallback
- Integration: news panel uses browser NER for instant entity highlighting, server enrichment runs async
- `WORLDBASE_BROWSER_ML=0` (default off, opt-in — frontend env var)
- Tests: Vitest for NER extraction, scoring, Web Worker communication, fallback

**Key design:**
- Browser ML is a pre-filter, not a replacement for server-side NER (GLiNER + LLM). Client highlights entities instantly; server enriches with FtM matching + graph edges.
- Models cached in IndexedDB after first download (~250MB one-time). Subsequent loads from cache.
- Privacy: text never leaves browser for client-side analysis. Server enrichment is opt-in per article.

---

## V4-49 — API Contract Generation (Pydantic → TypeScript)

**Why:** WorldMonitor uses Protocol Buffers with `sebuf` for contract-first API development — 276 protos, 34 services, auto-generated TypeScript clients + OpenAPI specs. Zero schema drift between frontend and backend. WorldBase uses FastAPI + Pydantic which auto-generates OpenAPI, but there's no generated TypeScript client — the frontend manually defines API types. This causes drift when backend models change.

**Scope:**
- `scripts/gen_api_contracts.py` — contract generation script
  - Reads FastAPI OpenAPI spec from `/openapi.json`
  - Generates TypeScript interfaces + fetch-based client classes → `frontend/src/generated/api/`
  - Generates Pydantic response models for testing → `backend/generated/client_models.py`
  - CI check: `make api-check` — regenerates and fails if output differs from committed files (like WorldMonitor's `proto-check.yml`)
- `frontend/src/generated/api/` — auto-generated TypeScript client (DO NOT EDIT)
  - One file per API domain: `briefing.ts`, `intel.ts`, `feeds.ts`, `darkweb.ts`, `mcp.ts`, etc.
  - Typed request/response interfaces, fetch-based client methods
- `frontend/src/lib/apiClient.ts` — thin wrapper that uses generated clients
- Replace manually-typed API calls in frontend with generated client
- `WORLDBASE_API_CONTRACT_GEN=0` (default off — generation is manual, CI check is opt-in)
- Tests: `test_api_contracts.py` — generated client compiles, types match OpenAPI spec

**Adaptation note:** WorldMonitor uses protobuf because they're TypeScript-first. WorldBase is Python-first with FastAPI. Pydantic → OpenAPI → TypeScript is the equivalent pipeline. No protobuf needed — FastAPI already produces OpenAPI 3.1.0. We just need the generation + CI enforcement step.

**Dependencies:** `openapi-typescript` (npm, dev dependency), `datamodel-code-generator` (Python, for optional Pydantic client models)

---

## V4-50 — Dual Map Engine (deck.gl Flat Map)

**Why:** WorldMonitor offers both 3D globe (globe.gl) and 2D flat map (deck.gl + MapLibre GL) with 56 layer types. WorldBase has Cesium only. A flat map is better for certain analytical tasks (route planning, choropleth heatmaps, flow maps) and loads faster on mobile/low-end devices. V4-31 (Deck.gl/Kepler.gl Analyst Dashboard) partially addresses this, but as a separate tab. V4-50 integrates deck.gl as a first-class map engine alternative to Cesium.

**Scope:**
- `frontend/src/components/DeckGlMap.tsx` — deck.gl + MapLibre GL flat map component
  - Layer parity with Cesium: AIS positions, fusion hotspots, earthquakes, GDELT events, dark web, CII choropleth
  - Map projections: Mercator (default), Equal Earth (for global choropleth)
  - Smooth transition between globe (Cesium) and flat map (deck.gl) — toggle in UI
- `frontend/src/lib/deckglLayers.ts` — reusable deck.gl layer configs (enhances V4-31)
  - ScatterplotLayer (AIS, earthquakes, events)
  - HeatmapLayer (fusion hotspots, GDELT density)
  - ArcLayer (entity flows, route explorer)
  - GeoJsonLayer (country boundaries, CII choropleth)
  - TextLayer (entity labels)
- `frontend/src/hooks/useMapEngine.ts` — map engine switcher (Cesium ↔ deck.gl)
  - State persisted to localStorage
  - Camera sync: when switching, preserve center + zoom level
- Layer catalog: 20+ layer types (target parity with Cesium layers, not WorldMonitor's 56)
- `WORLDBASE_DUAL_MAP=0` (default off, opt-in — frontend env var)
- Tests: Vitest for layer rendering, engine switching, camera sync

**Dependencies:** `deck.gl` (npm, ~1MB gzipped — lazy loaded), `maplibre-gl` (npm, open-source MapLibre)

**Relationship to V4-31:** V4-31 is a separate analyst dashboard tab with specialized visualizations (Sankey, timeline). V4-50 is a full alternative map engine that replaces Cesium as the primary view when toggled. They share `deckglLayers.ts` configs.

---

## V4-51 — GPU Budget Scheduler

**Why:** On 16 GB VRAM, Ollama (~11 GB) + HAK_GAL firewall (~0.5–2.5 GB) + Cesium WebGL (~0.3–1.5 GB) can exceed the budget. No shared GPU mutex exists between processes. Research §10 identified a sequential slot scheduler as feasible new code (~300 LOC).

**Scope:**
- `backend/gpu_budget_scheduler.py` — asyncio lock with slots `firewall` | `llm`
- State machine: IDLE → FIREWALL_SLOT → LLM_SLOT → IDLE
- `ollama_bridge.unload_models()` — HTTP to host Ollama (`keep_alive: 0`)
- Optional `nvidia-smi` VRAM probe: reject at < `WORLDBASE_GPU_MIN_FREE_MIB`
- Hook in `routes/chat.py` `_prepare_chat_messages`
- `GET /api/gpu/budget` for HUD/debug
- Config: `WORLDBASE_GPU_SCHEDULER=0` (default off), `WORLDBASE_GPU_OLLAMA_UNLOAD_FOR_FIREWALL=0`, `WORLDBASE_GPU_MIN_FREE_MIB=2048`, `WORLDBASE_GPU_PROFILE=16g`
- Tests: `test_gpu_budget_scheduler.py` (mock Ollama)

**Dependencies:** Ollama (shipped), HAK_GAL firewall bridge (shipped Phase A)

**Research ref:** §10.5 GPU slot scheduler

---

## V4-52 — Fusion Delta Grid (24h Compare)

**Why:** Track 5 identified that fusion grid deltas power watch items (Track 1) and prediction outcomes (Track 4). Snapshot archiver (V4-09) shipped, but `GET /api/fusion/heatmap?compare=24h` with cell `delta_score` is still open. B-06 needs 7 days of 6h snapshots before trusting `fusion_compare.available=true`.

**Scope:**
- `backend/fusion_delta.py` — compute cell `delta_score` from snapshot archives
- `GET /api/fusion/heatmap?compare=24h` — returns cells with `delta_score` field
- Cesium pulse animation on cells with Δ > threshold (frontend)
- Watch item generation cites `cell_id` + `delta_score`
- Config: `WORLDBASE_FUSION_DELTA=0` (default off)
- Tests: `test_fusion_delta.py`

**Dependencies:** V4-09 Snapshot Archiver (✅ Shipped), `fusion_heatmap.py` (shipped)

**Research ref:** Track 5, B-06

---

## V4-53 — Pi Offline PMTiles Basemap

**Why:** Pi edge has no offline basemap. PMTiles v3 spec is stable; `go-pmtiles` is a single binary. Cesium JS does not yet natively support PMTiles (community loader exists). B-07/B-12 from research backlog.

**Scope:**
- Pi: install `go-pmtiles` server, download Thailand/ASEAN PMTiles file to SD card
- `offgrid-raspi/offgrid/bin/pmtiles_server.py` — wrapper to start/stop go-pmtiles
- Portal UI: load Leaflet + PMTiles layer for offline basemap
- Config: `WORLDBASE_PI_PMTILES_PATH=/data/basemap.pmtiles`
- Tests: manual Pi verification; automated test for PMTiles file existence

**Dependencies:** Pi sync (shipped), go-pmtiles binary (external)

**Research ref:** B-07, B-12, §13.1

---

## V4-54 — Lightning Detection Bridge

**Why:** Blitzortung/LightningMaps provides real-time lightning strike data. Monsoon early warning for Thailand/ASEAN. Corroborates with CAMS (air quality) and outage detection. Research §8 rated OPEN / high research value for operator region.

**Scope:**
- `backend/lightning_bridge.py` — Blitzortung WebSocket or LightningMaps RSS
- `GET /api/lightning/strikes` — recent strikes with lat/lon/timestamp/intensity
- Cesium layer: lightning strike markers (recent 24h, fading)
- Briefing: monsoon/severe weather alert block in LOCAL bucket
- Config: `WORLDBASE_LIGHTNING=0` (default off), `BLITZORTUNG_USER` / `BLITZORTUNG_PASSWORD` (env, currently empty)
- Tests: `test_lightning_bridge.py`

**Dependencies:** No backend deps; Blitzortung account (env already has empty placeholders)

**Research ref:** §8 External Data Sources, Track 1/5

---

## V4-55 — OSM Critical Infrastructure POIs

**Why:** Overpass API (OSM) can extract hospitals, ports, borders, power plants in operator bbox. Critical for Track 2 corroboration (is the event near a hospital?) and Track 3 spatial graph (infrastructure entities). Research §8 rated OPEN / high value.

**Scope:**
- `backend/osm_bridge.py` — Overpass API query for critical infrastructure POIs
- `GET /api/osm/infrastructure?type=hospital|port|border|power` — filtered POIs
- FtM ingest: `Address` / `Organization` entities from OSM tags
- Cesium layer: infrastructure POI markers
- Briefing: "nearby infrastructure" context in LOCAL bucket
- Config: `WORLDBASE_OSM_OVERPASS=0` (default off)
- Tests: `test_osm_bridge.py`

**Dependencies:** No backend deps; Overpass API (free, no key)

**Research ref:** §8, Track 2/3

---

## V4-56 — Multi-Day Weather Forecast

**Why:** Open-Meteo provides free 72h structured forecast (wind, precipitation, severe weather). Track 1 anticipation needs structured weather horizon for watch items. Currently only partial (Windy/Open-Meteo basic). Research §8 rated PARTIAL.

**Scope:**
- `backend/weather_forecast_bridge.py` — Open-Meteo multi-day forecast API
- `GET /api/weather/forecast?lat=&lon=&days=3` — structured 72h forecast
- Watch item generation: severe weather warnings as watch items with `horizon_h`
- Briefing: WEATHER FORECAST block in LOCAL bucket
- Config: `WORLDBASE_WEATHER_FORECAST=0` (default off)
- Tests: `test_weather_forecast.py`

**Dependencies:** No backend deps; Open-Meteo API (free, no key)

**Research ref:** §8, Track 1/4

---

## V4-57 — Displacement Monitoring Feed

**Why:** IOM DTM / UNHCR displacement data for Myanmar border region. Extends HDX bridge. Research §8 rated OPEN / high value for operator region (Thailand-Myanmar border). Track 1 anticipation.

**Scope:**
- Extend `backend/humanitarian_bridge.py` with IOM DTM / UNHCR data sources
- `GET /api/humanitarian/displacement` — displacement flows
- FtM ingest: `Person` (displaced populations as aggregate), `Event` (displacement event)
- Briefing: DISPLACEMENT block in REGION bucket
- Config: `WORLDBASE_DISPLACEMENT_FEED=0` (default off)
- Tests: `test_displacement_feed.py`

**Dependencies:** HDX bridge (shipped)

**Research ref:** §8, Track 1

---

## V4-58 — Dark Web Engine-Specific HTML Parsers ✅ shipped (2026-07-01)

**Why:** Current dark web search uses a generic HTML parser for all Tor engines. Engine-specific parsers improve result extraction quality (titles, URLs, snippets). Research §6a P8.7 rated Tier 2, ~200 LOC.

**Shipped implementation:**
- `backend/darkweb_parsers.py` — 5 engine-specific BeautifulSoup4 parsers in a single module (not per-file)
- Parsers: `parse_torch()`, `parse_tor66()`, `parse_tordex()`, `parse_haystak()`, `parse_notevil()`
- Each parser: engine-specific CSS selectors + URL redirect unwrapping (`/redirect?url=`, `/url?q=`, `/url?u=`) + dedup by URL + `.onion` validation + fallback generic link extraction
- Registry: `has_engine_parser()`, `parse_engine_html()`, `list_parser_engines()`
- Integration: `darkweb_bridge._search_tor_engine()` calls `darkweb_parsers.parse_engine_html()` first, falls back to `_parse_tor_html()` if empty or exception
- Tests: `test_darkweb_parsers.py` — 26 tests (all pass); 61 combined with `test_darkweb_bridge.py`
- No new config flags needed — parsers activate automatically when engine is in `_ENGINE_REGISTRY`

**Original scope (for reference):**
- `backend/darkweb_parsers/` — per-engine parsers: `torch.py`, `tor66.py`, `tordex.py`, `haystak.py`, `not_evil.py`
- Each parser: extract `{ title, url, snippet }` from engine-specific HTML structure
- Fallback: generic parser if engine-specific parser fails
- Config: `WORLDBASE_DARKWEB_PARSERS=1` (default on when darkweb enabled)
- Tests: `test_darkweb_parsers.py` with fixture HTML

**Dependencies:** P8.2 dark web search (shipped)

**Research ref:** §6a P8.7

---

## V4-59 — Breach / Credential-Leak Intelligence ✅ shipped (2026-07-01)

**Why:** HIBP k-anonymity API allows checking if credentials have been breached without exposing the credentials themselves. Research §6a P8.8/K1 rated Tier 2, ~300 LOC. Extends dark web OSINT into credential monitoring.

**Shipped implementation (P8.8):**
- `backend/breach_bridge.py` — HIBP API v3 email breach checks + Pwned Passwords k-anonymity API (SHA1 prefix, never full hash)
- SQLite monitor table: SHA1 hash + base64-encoded email (obfuscation), `breach_checks` table for history
- 7 API endpoints under `/api/darkweb/breach/`: `status`, `check`, `password`, `monitor` (POST/DELETE), `monitors`, `refresh`
- Briefing integration: `gather_breach_briefing()` → `breach_digest` → `briefing_digest.py` → BREACH block in `briefing_prompt.py`
- Watch items: `build_breach_watch_items()` — only new breaches, severity critical for password data classes
- Frontend: BREACH tab in `DarkwebPanel.tsx` + 7 API functions in `darkwebApi.ts`
- Config: `WORLDBASE_BREACH=1`, `WORLDBASE_BRIEFING_BREACH=1`, `WORLDBASE_HIBP_API_KEY` (required for email checks; password checks work without key)
- Tests: `test_breach_bridge.py` — 30 tests (all pass)
- Caching with TTL (default 3600s), rate-limiting (1.5s between HIBP requests), fail-soft on network errors
- Router registered in `routes/registry.py`

**Original scope (for reference):**
- ~~`backend/breach_bridge.py` — HIBP k-anonymity API client~~
- ~~`GET /api/breaches/check?email=` — k-anonymity check~~ → `POST /api/darkweb/breach/check`
- ~~`POST /api/breaches/monitor` — register email for monitoring~~ → `POST /api/darkweb/breach/monitor`
- ~~Briefing: BREACH ALERT block~~ → BREACH / CREDENTIAL-LEAK block in `briefing_prompt.py`
- ~~Config: `WORLDBASE_BREACH_MONITOR=0`~~ → `WORLDBASE_BREACH=1`, `WORLDBASE_BRIEFING_BREACH=1`, `WORLDBASE_HIBP_API_KEY`
- ~~Tests: `test_breach_bridge.py`~~ → 30 tests, all pass

**Dependencies:** No backend deps; HIBP API (paid API key for email checks; password k-anonymity is free)

**Research ref:** §6a P8.8/K1

---

## V4-60 — Cyber & Financial Intel Ontology

**Why:** Research §14 (Foundry Ontology) identified expansion to Organization, Person, CyberIndicator, Infrastructure, FinancialAsset entity types with typed edges (worksFor, locatedAt, ownsAsset, etc.). Shodan InternetDB (keyless) for cyber indicators. Moves WorldBase toward Palantir-style intelligence workstation.

**Scope:**
- Extend `ftm_schema.py` with Organization, Person, Document, CyberIndicator (IpAddress, Domain, Url), Infrastructure, FinancialAsset (Asset)
- `backend/cyber_bridge.py` — Shodan InternetDB (keyless, free)
- `intel_edges` table for typed relationships (worksFor, locatedAt, ownsAsset, mentionedIn, linkedTo, partOf)
- `GET /api/intel/entities?schema=Organization` filter
- `GET /api/intel/edges?type=worksFor` filter
- IOC extraction from intel ingest (regex: IP, domain, URL, hash)
- Config: `WORLDBASE_CYBER_INTEL=0` (default off)
- Tests: `test_cyber_bridge.py`, `test_ontology_expansion.py`

**Dependencies:** FtM schema (shipped), `ftm_store.py` (shipped)

**Research ref:** §14 Foundry Ontology

---

## V4-61 — Relationship Explorer + Timeline

**Why:** Research §14.4 identified that the current `IntelGraphPanel.tsx` is a basic implementation. Need interactive Cytoscape graph with edge type filters (sameAs, worksFor, locatedAt) and entity timeline view (first_seen → last_seen). P2 priority.

**Scope:**
- `frontend/src/components/RelationshipExplorer.tsx` — Cytoscape.js interactive graph
  - Expand/collapse neighbors by edge type
  - Edge type filter checkboxes
  - Color-coded by entity schema
- `frontend/src/components/EntityTimeline.tsx` — timeline view (first_seen → last_seen events)
- `GET /api/intel/entities/{id}/timeline` — sorted events for entity
- Tests: Vitest for graph rendering, filter logic

**Dependencies:** V4-60 (ontology expansion for typed edges), Cytoscape.js (already used in IntelGraphPanel)

**Research ref:** §14.4

---

## V4-62 — Proactive Push Delivery

**Why:** Research Track 8 identified that low-frequency notifications (1-2/day) increase anticipation value more than new globe layers. Meshtastic supports JSON payloads up to 237 bytes — sufficient for compact watch-item alerts. Local HTTP hook and email/Telegram push also viable.

**Scope:**
- `backend/push_delivery.py` — multi-channel push notification dispatcher
- Channels: Meshtastic (Pi, <237 B compact watch summary), local HTTP hook (`POST /api/briefing/hook`), email (SMTP), Telegram bot
- Triggers: new briefing generated, trust score < 3, anomaly detected, breach found
- Config: `WORLDBASE_PUSH_DELIVERY=0` (default off), per-channel env vars
- Tests: `test_push_delivery.py`

**Dependencies:** Alerting (shipped), Pi sync (shipped), Meshtastic (Pi-side, external)

**Research ref:** Track 8

---

## V4-63 — Firewall Phase B–D Hardening

**Why:** Research §11 identified gaps in MCP write tool scanning (ASI02), epistemic abstention UX (Phase C), and fail-closed mode (Phase D). Phase A shipped (session-aware ingress). Phases B–D close the agentic security gap.

**Scope:**
- Phase B: `firewall_scan_tool()` for MCP write tools, `WORLDBASE_FIREWALL_MCP=1`, `GET /api/firewall/history`, `X-Logging` trace header
- Phase C: `firewall_classify()` → HAK_GAL `/api/v2/classify` (Wilson CI, abstention), chat UX third state (ALLOW | ABSTAIN | BLOCK), optional outbound response scan
- Phase D: `WORLDBASE_FIREWALL_FAIL_CLOSED=1`, 5th trust probe `firewall_reachable`, shadow mode `WORLDBASE_FIREWALL_SHADOW=1`
- Tests: `test_firewall_phase_bcd.py`

**Dependencies:** Phase A (shipped), HAK_GAL orchestrator (external)

**Research ref:** §11.7 Phases B–D

---

## V4-64 — Feed Circuit Breaker + ETag Polling

**Why:** Research §13.6 identified that conditional GET (ETag/If-None-Match) is underused in OSINT pipelines. Circuit breaker per feed prevents cascading latency. WorldBase already uses ETag for Pi sync — extend to feed polling.

**Scope:**
- `backend/feed_circuit_breaker.py` — per-feed circuit breaker (trip after N consecutive failures, half-open after cooldown)
- Extend `feeds/envelope.py` with `etag` and `last_modified` fields
- Feed pollers: send `If-None-Match` / `If-Modified-Since` headers
- `GET /api/feeds/circuit-breaker` — circuit breaker status per feed
- Config: `WORLDBASE_FEED_CIRCUIT_BREAKER=1` (default on), `WORLDBASE_FEED_CB_THRESHOLD=5`, `WORLDBASE_FEED_CB_COOLDOWN=300`
- Tests: `test_feed_circuit_breaker.py`

**Dependencies:** Feed autopilot (shipped), `feed_drift.py` (shipped)

**Research ref:** §13.6

---

## V4-65 — Temporal Replay (Time-Slider Globe)

**Why:** Research §6a J.2 identified temporal replay as a ~1000 LOC feature. With V4-09 Snapshot Archiver (shipped), historical globe state replay is possible. Analyst can scrub through time to see how the situation evolved.

**Scope:**
- `frontend/src/components/TimeSlider.tsx` — timeline scrubber component
- `GET /api/snapshots/globe?ts=` — globe state at timestamp (entities, feeds, fusion)
- Cesium: load historical state, animate between snapshots
- Config: `WORLDBASE_TEMPORAL_REPLAY=0` (default off, frontend env)
- Tests: Vitest for time slider, snapshot loading

**Dependencies:** V4-09 Snapshot Archiver (✅ Shipped), Cesium (shipped)

**Research ref:** §6a J.2

---

## V4-66 — Subgraph Quality A/B Validation

**Why:** Research B-05/B-09/B-10 are open validation tasks: does FtM subgraph improve briefing quality? GraphRAG-lite hallucination count with/without subgraph? Splink eval dedup rate? These are research validation items, not new features.

**Scope:**
- `backend/tests/test_subgraph_quality.py` — A/B test harness
  - B-05: Same briefing prompt with and without INTEL SUBGRAPH block, compare quality metrics
  - B-09: Hallucination count (LLM-invented events not in snapshot) with/without subgraph
  - B-10: Splink dedup rate on FtM statements (precision/recall on labeled pairs)
- `scripts/subgraph_ab_test.py` — CLI runner for A/B comparison
- Config: No env flag — test/research only
- Tests: Self-contained test suite

**Dependencies:** Intel subgraph (shipped), Splink (shipped), briefing pipeline (shipped)

**Research ref:** B-05, B-09, B-10

---

## V4-67 — vec1 ANN Benchmark

**Why:** Research B-01 identified SQLite vec1 (IVFADC + OPQ, merged June 2026) as a potential ANN replacement for sqlite-vec brute-force at 50k+ vectors. Today sqlite-vec is fine at <100k. Benchmark before adopting.

**Scope:**
- `scripts/bench_vec1.py` — benchmark script
  - Load 10k, 50k, 100k vectors from RAG corpus
  - Compare sqlite-vec brute-force vs vec1 ANN (latency, recall@10)
  - Report: P50/P99 search latency, recall, memory
- Config: No env flag — benchmark script only
- Tests: N/A (benchmark, not production code)

**Dependencies:** sqlite-vec (shipped), vec1.c (compile from source)

**Research ref:** B-01, §13.5

---

## V4-68 — LLM Briefing Model A/B

**Why:** Research B-11 identified LLM model A/B for briefings (qwen3:8b vs phi-4:14b) as eligible after verification pipeline exists. P4 Provenance shipped, so this is now eligible. Anti-pattern: never run A/B before verification — that's resolved.

**Scope:**
- `scripts/llm_briefing_ab.py` — A/B comparison script
  - Generate same briefing with qwen3:8b and phi-4:14b (or qwen3:14b)
  - Compare: quality score, corroboration, hallucination count, token usage, latency
  - Output: markdown report with metrics table
- Config: No env flag — script only
- Tests: N/A (comparison script)

**Dependencies:** Ollama (shipped), briefing pipeline (shipped), P4 Provenance (shipped)

**Research ref:** B-11, §9.2

---

## V4-69 — Grafana/Loki Observability Dashboard

**Why:** Research B-08 identified Grafana/Loki as an observability dashboard for when metrics need a dashboard. WorldBase already has OTel+Prometheus (I3 shipped), but no visualization layer.

**Scope:**
- `docker/grafana/` — Grafana provisioning config
- `docker/grafana/dashboards/` — pre-built dashboards: feed health, briefing quality, entity growth, DuckDB queue, API latency
- `docker-compose.observability.yml` — optional overlay with Grafana + Loki + Promtail
- Config: `WORLDBASE_OBSERVABILITY=0` (default off)
- Tests: N/A (config/provisioning)

**Dependencies:** OTel+Prometheus (shipped), Docker (shipped)

**Research ref:** B-08

---

## V4-70 — Social Media OSINT (Mastodon/Bluesky)

**Why:** Research §6a H.3 identified federated social media (Mastodon, Bluesky) as a potential OSINT source. Deferred due to ToS/ethics concerns. GDELT provides partial coverage. Listed as Tier 3, ~400 LOC.

**Scope:**
- `backend/social_bridge.py` — Mastodon API (public timeline, keyword search), Bluesky API (public posts, search)
- `GET /api/social/search?q=` — aggregated social media search
- FtM ingest: `Mention` entities from social posts
- Briefing: SOCIAL SIGNALS block (metadata only, not content — ToS compliance)
- Config: `WORLDBASE_SOCIAL_OSINT=0` (default off, opt-in)
- Tests: `test_social_bridge.py`

**Dependencies:** No backend deps; Mastodon/Bluesky APIs (free, public)

**Research ref:** §6a H.3, §13.9 blind spot #3

---

## Dependency Graph

```
Phase 1 (Foundation):
  V4-01 (Smart Model Router)    ── ✅ Shipped — depends on chat_proxy (shipped)
  V4-02 (RBAC + Rate Limit)    ── ✅ Shipped (config tuning only)
  V4-03 (BGE-Reranker GPU)     ── ✅ Shipped — depends on RAG infra (shipped)
  V4-04 (Embedding GPU)        ── depends on RAG infra (shipped) → Sprint 2
  V4-05 (DuckDB 1.6+H3)       ── ✅ Shipped — unblocks V4-37 (SAR spatial), V4-24 (graph algo spatial)
  V4-06 (GDPR)                 ── no deps → Sprint 5
  V4-07 (Retention)            ── depends on V4-06 (GDPR erase infra) → Sprint 5
  V4-08 (SQLite FTS5 Search)   ── ✅ Shipped
  V4-09 (Snapshot Archiver)    ── ✅ Shipped — unblocks V4-19 (✅ Shipped), V4-21 (Temporal), V4-23 (Anomaly)
  V4-10 (Classification)       ── no deps → unblocks V4-38 (Federation) → Sprint 5

Phase 2 (Data Sources):
  V4-14 (Telegram)             ── ✅ Shipped (audit complete)
  V4-16 (ACLED)                ── no deps → Sprint 1
  V4-17 (STIX/TAXII)           ── no deps → unblocks V4-38 (Federation) → Sprint 1

Phase 3 (Local AI Superpowers):
  V4-11 (Self-Consistency)     ── depends on V4-01 (✅ Shipped) → Sprint 3
  V4-12 (LoRA Fine-Tuning)     ── depends on briefing data (shipped), GPU → Sprint 3
  V4-13 (Speculative Decoding) ── depends on Ollama (shipped), GPU → Sprint 3
  V4-15 (BLIP Captioning)      ── depends on RAG infra (shipped) → Sprint 2
  V4-22 (ColQwen2)             ── depends on RAG infra (shipped); V4-15 is lightweight precursor → Sprint 3

Phase 4 (Intelligence & ML):
  V4-18 (GNN Correlation)      ── depends on intel_semantic_links (shipped) → Sprint 7
  V4-19 (Predictive)           ── ✅ Shipped — depends on prediction_ledger (shipped) + V4-09 (✅ Shipped)
  V4-20 (Multi-Hypothesis)     ── depends on orchestrator (shipped) + V4-01 (✅ Shipped) → Sprint 4
  V4-21 (Temporal)             ── depends on intel_semantic_links (shipped) + V4-09 (✅ Shipped) → Sprint 7
  V4-23 (Anomaly Detection)    ── ✅ Shipped — depends on feed time series (shipped) + V4-09 (✅ Shipped)
  V4-24 (Graph Algo)           ── depends on FtM graph (shipped) + V4-05 (✅ Shipped) → Sprint 1
  V4-25 (ReAct Loop)           ── depends on chat_tools (shipped) → Sprint 4
  V4-26 (Red-Team)             ── depends on anti-hallucination stack (shipped) → Sprint 5
  V4-27 (Cross-Feed Corr.)     ── depends on intel_semantic_links (shipped) + V4-01 (✅ Shipped) → Sprint 4

Phase 5 (UX, Voice & Edge):
  V4-28 (Whisper STT)          ── no backend deps → Sprint 2
  V4-29 (Piper TTS)            ── no backend deps → Sprint 2
  V4-30 (PWA)                  ── no backend deps → Sprint 2
  V4-31 (Deck.gl)              ── no backend deps → Sprint 6
  V4-32 (Collab Yjs)           ── depends on WebSocket Gateway (shipped) + RBAC (✅ Shipped) → Sprint 6
  V4-33 (Pi Offline RAG)       ── depends on Pi sync (shipped) → Sprint 4
  V4-34 (ONNX Pi)              ── no backend deps → Sprint 4

Phase 6 (Strategic):
  V4-35 (CKAN Harvester)       ── generalizes thai_opendata.py (shipped) → Sprint 1
  V4-36 (ADS-B+SatNOGS)        ── no deps → Sprint 6
  V4-37 (SAR)                  ── depends on rasterio (installed) + V4-05 (✅ Shipped) → Sprint 6
  V4-38 (Federated Mesh)       ── depends on V4-17 (STIX) + V4-10 (Classification) → Sprint 6 (experiment)
  V4-39 (Bitemporal)           ── depends on ftm_schema (shipped) → Sprint 6
  V4-40 (FtM Ontology)         ── depends on ftm_schema (shipped) → Sprint 6
  V4-41 (DR Automation)        ── no deps → Sprint 1
  V4-42 (Tests)                ── no deps → build anytime → Sprint 6

Phase 7 (WorldMonitor Competitive Response):
  V4-43 (CII)                  ── depends on GDELT (shipped) + NewsData (shipped) + V4-09 (✅ Shipped) → Sprint 1
  V4-44 (MCP outputSchema)     ── ✅ Shipped — depends on mcp_server.py (shipped)
  V4-45 (Bootstrap Hydration)  ── ✅ Shipped — depends on Redis (shipped) + existing endpoints
  V4-46 (SmartPollLoop)        ── no backend deps → Sprint 2
  V4-47 (Route Explorer)       ── depends on AIS (shipped) + GDELT (shipped) + fusion (shipped); V4-43 enhances → Sprint 3
  V4-48 (Browser ML)           ── no backend deps → Sprint 3
  V4-49 (API Contract Gen)     ── depends on FastAPI OpenAPI (shipped) → Sprint 4
  V4-50 (Dual Map)             ── no backend deps; enhances V4-31 → Sprint 6

Phase 8 (Consolidated Research):
  V4-51 (GPU Budget Scheduler) ── depends on Ollama (shipped) + firewall_bridge (shipped) → Sprint 2
  V4-52 (Fusion Delta Grid)    ── depends on V4-09 (✅ Shipped) + fusion_heatmap (shipped) → Sprint 2
  V4-53 (Pi PMTiles)           ── depends on Pi sync (shipped) → Sprint 4
  V4-54 (Lightning Bridge)     ── no deps → Sprint 2
  V4-55 (OSM POIs)             ── no deps → Sprint 2
  V4-56 (Weather Forecast)     ── no deps → Sprint 2
  V4-57 (Displacement Feed)    ── depends on HDX bridge (shipped) → Sprint 3
  V4-58 (Darkweb Parsers)      ── depends on P8.2 darkweb search (shipped) → Sprint 2
  V4-59 (Breach Intel)         ── no deps → Sprint 3
  V4-60 (Cyber Ontology)       ── depends on ftm_schema (shipped) + ftm_store (shipped) → Sprint 3
  V4-61 (Relationship Explorer)── depends on V4-60 (ontology) + Cytoscape (shipped) → Sprint 4
  V4-62 (Push Delivery)        ── depends on alerting (shipped) + Pi sync (shipped) → Sprint 5
  V4-63 (Firewall B–D)         ── depends on Phase A (shipped) + HAK_GAL (external) → Sprint 3
  V4-64 (Circuit Breaker)      ── ✅ Shipped — depends on feed autopilot (shipped)
  V4-65 (Temporal Replay)      ── depends on V4-09 (✅ Shipped) + Cesium (shipped) → Sprint 5
  V4-66 (Subgraph A/B)         ── depends on intel subgraph (shipped) + Splink (shipped) → Sprint 3 (research)
  V4-67 (vec1 Benchmark)       ── depends on sqlite-vec (shipped) → Sprint 4 (research)
  V4-68 (LLM A/B)              ── depends on Ollama (shipped) + P4 Provenance (shipped) → Sprint 4 (research)
  V4-69 (Grafana Dashboard)    ── depends on OTel+Prometheus (shipped) → Sprint 5
  V4-70 (Social OSINT)         ── deferred (ToS/ethics) → Sprint 6+
```

---

## Shipped Items Reference (from V2 + V3)

All items from V2 roadmap are shipped. See `docs/WORLDBASE_ROADMAP_V2.md` for details:
- P10 Domain Intel, C.3 Thai Open Data, J.3 Agent Swarm, J.1 Ask the Globe
- P1–P11 core series, LLM Workplan Sprint 1+2, K3/K4, I1–I10, J1–J8
- Phase 2.1 RBAC, Phase 2.2 Secrets, Phase 3.1 Pi Conflict, Phase 4.4 MCP Policy
- Gap Fixes (Label Versioning, Drift Persistence, Tor Audit, Quality Gate)

V3 items not carried to V4 (dropped with rationale):
- V3-2 (Celery) — overkill for single-user, asyncio sufficient
- V3-10 (Meilisearch) — replaced by V4-08 (SQLite FTS5)
- V3-31 (PostgreSQL) — SQLite + DuckDB sufficient, keep simplicity
- V3-32 (Kafka/Redpanda) — overkill, asyncio + Redis Streams sufficient

**Test totals at V2 completion:** 1281+ backend, 280+ frontend, 34 smoke.
**Test totals after Sprint A (V4):** 1811 backend, 280+ frontend, 34 smoke (+530 backend tests from V4 features).

---

## Go/No-Go Decision Matrix (from Feasibility Study)

| Feature | Go/No-Go | Begründung |
|---------|----------|------------|
| V4-01 (Smart Model Router) | **✅ Shipped** | Trivial, kritischer Enabler, sofortiger ROI |
| V4-02 (RBAC + Rate Limit) | **✅ Shipped** | Sicherheit, optional für Single-User |
| V4-03 (BGE-Reranker GPU) | **✅ Shipped** | Hoher ROI, ONNX-Runtime reif |
| V4-04 (Embedding GPU) | **GO (low prio)** | Nützlich, aber CPU-Fallback ok |
| V4-05 (DuckDB + H3) | **✅ Shipped** | Kritischer Enabler, R-Tree-Fix |
| V4-06 (GDPR) | **GO (low prio)** | Compliance, niedrigere Priorität für Single-User |
| V4-07 (Retention) | **GO (low prio)** | Abhängig von V4-06 |
| V4-08 (FTS5 Search) | **✅ Shipped** | Trivial, großer UX-Win |
| V4-09 (Snapshot Archiver) | **✅ Shipped** | Kritischer Enabler für 3+ spätere Features |
| V4-10 (Classification) | **GO (low prio)** | Enabler für Federation, nicht dringend |
| V4-11 (Self-Consistency) | **GO (low prio)** | 3× LLM-Kosten (Zeit), marginaler Qualitätsgewinn |
| V4-12 (LoRA Training) | **GO (caution)** | Experimentell, Datenqualität kritisch |
| V4-13 (Speculative Decoding) | **GO (caution)** | Komplexer als geschätzt (400-600 LOC), Ollama-Support unklar |
| V4-14 (Telegram) | **✅ Shipped** | #1 OSINT-Quelle, etabliertes Pattern |
| V4-15 (BLIP) | **GO** | Leichtgewichtig, sofortiger Nutzen |
| V4-16 (ACLED) | **GO** | Einfach, füllt wichtige Lücke |
| V4-17 (STIX/TAXII) | **GO (low prio)** | Interoperabilität, nicht kritisch für Citizen |
| V4-18 (GNN) | **NO-GO (as specified)** | MVP mit homogenem GAT stattdessen |
| V4-19 (Predictive) | **✅ Shipped** | LightGBM trivial, hoher ROI |
| V4-20 (Multi-Hypothesis) | **GO (low prio)** | 3× LLM-Kosten |
| V4-21 (Temporal) | **GO** | Rule-Engine einfach, Granger als Bonus |
| V4-22 (ColQwen2) | **GO (caution)** | On-demand Microservice, CPU-Fallback langsam |
| V4-23 (Anomaly Detection) | **GO** | Trivial (Isolation Forest) |
| V4-24 (Graph Algo) | **GO** | Trivial (NetworkX) |
| V4-25 (ReAct) | **GO** | Autonomes OSINT, etabliertes Pattern |
| V4-26 (Red-Team) | **GO (low prio)** | QA-Win, nicht dringend |
| V4-27 (Cross-Feed Corr.) | **GO (low prio)** | Rule-Engine bereits shipped, LLM optional |
| V4-28 (Whisper) | **GO** | Barrierefreiheit, etabliert |
| V4-29 (Piper TTS) | **GO** | CPU-only, einfach |
| V4-30 (PWA) | **GO** | Mobile, einfach |
| V4-31 (Deck.gl) | **GO (caution)** | Bundle-Size, lazy-loading nötig |
| V4-32 (Yjs Collab) | **GO (low prio)** | Single-User-Station: nicht kritisch |
| V4-33 (Pi Offline RAG) | **GO** | Herzstück der Citizen-Philosophie |
| V4-34 (ONNX Pi) | **GO (low prio)** | Pi-RAM-Limit |
| V4-35 (CKAN) | **GO** | Trivial (Generalisierung) |
| V4-36 (ADS-B) | **GO (low prio)** | Interessant, nicht kritisch |
| V4-37 (SAR) | **GO (caution)** | Dark-Vessel-Detection, Datenmenge hoch, Batch-Prozess |
| V4-38 (Federation) | **NO-GO (as specified)** | Experiment statt Produktionsfeature |
| V4-39 (Bitemporal) | **GO (low prio)** | Audit-Trail, nicht dringend |
| V4-40 (FtM Extended) | **GO (low prio)** | Military-Intel, für Citizen nicht kritisch |
| V4-41 (DR Automation) | **GO** | Backup wichtig |
| V4-42 (Chaos Tests) | **GO (low prio)** | QA, CI-Integration |
| V4-43 (CII) | **GO** | Größter UX-Vorteil von WorldMonitor, numerischer Score statt narrativ |
| V4-44 (MCP outputSchema) | **GO** | Quick Win, spec-compliance, Token-Effizienz |
| V4-45 (Bootstrap Hydration) | **GO** | Frontend-Perf, 2 Requests statt 20+ |
| V4-46 (SmartPollLoop) | **GO** | Frontend-Resilienz, Backoff + Hidden-Tab |
| V4-47 (Route Explorer) | **GO (caution)** | Komplex (~500 LOC), hoher analytischer Wert |
| V4-48 (Browser ML) | **GO (caution)** | Bundle-Size (~250MB ONNX), Privacy-Vorteil |
| V4-49 (API Contract Gen) | **GO** | CI-Enforcement gegen Schema-Drift |
| V4-50 (Dual Map) | **GO (caution)** | Bundle-Size, lazy-loading nötig, überschneidet mit V4-31 |
| V4-51 (GPU Budget Scheduler) | **GO** | VRAM-Mutex, verhindert OOM bei Firewall+Ollama |
| V4-52 (Fusion Delta Grid) | **GO** | Nutzt V4-09 Snapshots, hoher Antizipations-Wert |
| V4-53 (Pi PMTiles) | **GO (low prio)** | Pi-Ressourcen, erst nach Pi RAG |
| V4-54 (Lightning) | **GO** | Kostenlos, monsoon early warning für TH |
| V4-55 (OSM POIs) | **GO** | Overpass kostenlos, Track 2 Korroboration |
| V4-56 (Weather Forecast) | **GO** | Open-Meteo kostenlos, Track 1 Antizipation |
| V4-57 (Displacement) | **GO** | IOM/UNHCR, Myanmar-Fokus, HDX-Erweiterung |
| V4-58 (Darkweb Parsers) | ✅ Shipped | 5 engine-spezifische HTML-Parser (BS4), Qualität Darkweb-OSINT — P8.7 shipped 2026-07-01 |
| V4-59 (Breach Intel) | ✅ Shipped | HIBP k-anonymity, OpSec-Relevanz — P8.8 shipped 2026-07-01 |
| V4-60 (Cyber Ontology) | **GO** | Palantir-style Erweiterung, Shodan kostenlos |
| V4-61 (Relationship Explorer) | **GO (low prio)** | UI-Erweiterung, abhängig von V4-60 |
| V4-62 (Push Delivery) | **GO** | Low-frequency notifications, hoher ROI |
| V4-63 (Firewall B–D) | **GO (caution)** | HAK_GAL-abhängig, MCP-Security |
| V4-64 (Circuit Breaker) | **GO** | Feed-Resilienz, ETag-Effizienz |
| V4-65 (Temporal Replay) | **GO (low prio)** | ~1000 LOC FE, nutzt V4-09 |
| V4-66 (Subgraph A/B) | **GO (research)** | Validierung, keine neue Feature |
| V4-67 (vec1 Benchmark) | **GO (research)** | Benchmark, erst bei >50k Vektoren relevant |
| V4-68 (LLM A/B) | **GO (research)** | Modell-Vergleich, P4 Voraussetzung erfüllt |
| V4-69 (Grafana Dashboard) | **GO (low prio)** | Visualisierung, nicht kritisch |
| V4-70 (Social OSINT) | **DEFERRED** | ToS/Ethik, GDELT deckt teilweise ab |

---

## Alternative Build Scenarios (from Feasibility Study)

### Scenario A: Full Build (all 70 Features)
Phasen 1–8 sequenziell. Dauer: 12–16 Monate Vollzeit, 24–30 Monate Hobby.

### Scenario B: Citizen MVP (highest Citizen-ROI only)
**Phase 1 (reduced):** ~~V4-01~~ ✅, ~~V4-05~~ ✅, ~~V4-09~~ ✅, ~~V4-08~~ ✅, ~~V4-03~~ ✅, V4-43 (CII), V4-44 (MCP Schema), V4-45 (Bootstrap), V4-64 (Circuit Breaker)
**Phase 2 (full):** ~~V4-14~~ ✅, V4-16, V4-46 (SmartPollLoop), V4-54 (Lightning), V4-55 (OSM POIs), V4-56 (Weather)
**Phase 3 (reduced):** V4-15, V4-13, V4-48 (Browser ML), V4-52 (Fusion Delta), V4-58 (Darkweb Parsers)
**Phase 4 (reduced):** ~~V4-19~~ ✅, V4-23, V4-25, V4-49 (API Contracts), ~~V4-59 (Breach Intel)~~ ✅, V4-60 (Cyber Ontology)
**Phase 5 (full):** V4-28, V4-29, V4-30, V4-33, V4-51 (GPU Scheduler)
**Phase 6 (only):** V4-35, V4-41, V4-62 (Push Delivery)
**Dauer:** 5–7 Monate Vollzeit, 10–14 Monate Hobby (Sprint A hat 8 der 27 Features bereits geliefert).

### Scenario C: Analyst Powerhouse (ML/Intelligence focus)
Skip: V4-06, V4-07, V4-28, V4-29, V4-30, V4-33, V4-34, V4-38
Focus: V4-18, V4-19, V4-21, V4-22, V4-24, V4-25, V4-31, V4-37

### Scenario D: Minimal Viable WorldBase (fastest ROI, 16 features)
1. ~~V4-01 (Smart Model Router)~~ ✅ Shipped — Cloud/Local-Toggle
2. ~~V4-05 (DuckDB + H3)~~ ✅ Shipped — Spatial Performance
3. ~~V4-09 (Snapshot Archiver)~~ ✅ Shipped — Historie
4. ~~V4-14 (Telegram)~~ ✅ Shipped — OSINT-Quelle
5. ~~V4-03 (BGE-Reranker GPU)~~ ✅ Shipped — RAG-Speed
6. ~~V4-19 (Predictive)~~ ✅ Shipped — Forecasting (nach 30d Snapshots)
7. ~~V4-23 (Anomaly Detection)~~ ✅ Shipped — Automatische Alerts
8. ~~V4-44 (MCP outputSchema)~~ ✅ Shipped — Token-Effizienz (~150 LOC quick win)
9. ~~V4-45 (Bootstrap Hydration)~~ ✅ Shipped — Frontend-Perf (~200 LOC quick win)
10. V4-43 (CII) — Numerischer Risk Score (höchster UX-Win)
11. ~~V4-64 (Circuit Breaker)~~ ✅ Shipped — Feed-Resilienz (~200 LOC quick win)
12. V4-55 (OSM POIs) — Infrastruktur-Kontext (~200 LOC)
13. V4-56 (Weather Forecast) — 72h Vorhersage (~150 LOC)
14. V4-28 (Whisper) — Voice
15. V4-30 (PWA) — Mobile
16. V4-33 (Pi Offline RAG) — Off-Grid
**Dauer:** 2–3 Monate Vollzeit (9/16 bereits shipped).

---

## Philosophy Alignment Check

| Philosophy Pillar | How Addressed |
|-------------------|---------------|
| Online as standard, offline as safety net | V4-01 Smart Model Router with automatic fallback chain. UI toggle "Use Cloud AI". All features degrade gracefully. |
| Max information for the citizen | All new data sources (V4-14 Telegram, V4-16 ACLED, V4-36 ADS-B, V4-37 SAR) are free, open, local-first. RAG expanded with GPU reranker (V4-03). CII (V4-43) provides instant quantitative risk assessment. Browser ML (V4-48) enables client-side analysis. |
| Affordable hardware | Everything runs on Lenovo Legion + Pi, with clear path to weaker machines. GPU features have CPU fallback. PWA (V4-30) works on cheap Android. |
| Convenience / healthy balance | One click to use cloud AI (V4-01), effortless fallback, no constant tinkering. Voice control (V4-28) and TTS (V4-29) for hands-free use. |
| No forced cloud dependency | Every function has a local equivalent. Offline works. LoRA fine-tuning (V4-12) creates personal model that doesn't need cloud. |
| Privacy | Identity OSINT, dark web, voice data — all processed locally. No microphone to AWS. No personal data to cloud. Browser ML (V4-48) keeps text analysis client-side. |
| Citizen mesh | V4-38 Federated Citizen Mesh — decentralized intel sharing, no central server, no corporation in the middle. |

---

## Summary: 70 Items Across 8 Phases — 10 Shipped, 60 Remaining

| Phase | Duration (planned) | Duration (realistic) | Items | Shipped | Focus |
|-------|----------|----------|-------|---------|-------|
| 1 | Weeks 1-3 | 4-5 weeks | V4-01–V4-10, V4-43–V4-45 | 6/13 | Foundation: Smart Router, GPU RAG, Spatial, Compliance, Search, CII, MCP Schema, Bootstrap |
| 2 | Weeks 3-5 | 2-3 weeks | V4-14, V4-16, V4-17, V4-46, V4-51, V4-54–V4-56, V4-58 ✅, V4-64 | 2/10 | Data Sources & Resilience: Telegram, ACLED, STIX, SmartPollLoop, GPU Scheduler, Lightning, OSM, Weather, Darkweb Parsers, Circuit Breaker |
| 3 | Weeks 5-8 | 4-6 weeks | V4-11–V4-13, V4-15, V4-22, V4-47, V4-48, V4-52, V4-57, V4-59 ✅, V4-60, V4-63, V4-66 | 1/12 | Local AI & Intel: Self-Consistency, LoRA, Spec Decoding, BLIP, ColQwen2, Route Explorer, Browser ML, Fusion Delta, Displacement, Breach, Cyber Ontology, Firewall B–D, Subgraph A/B |
| 4 | Weeks 8-12 | 6-8 weeks | V4-18–V4-27, V4-49, V4-53, V4-61, V4-67, V4-68 | 1/13 | Intelligence & Edge: GNN, Predictive, Multi-Hyp, Temporal, Anomaly, Graph Algo, ReAct, Red-Team, Cross-Feed, API Contracts, Pi PMTiles, Relationship Explorer, vec1 Bench, LLM A/B |
| 5 | Weeks 12-16 | 5-7 weeks | V4-28–V4-34, V4-62, V4-65, V4-69 | 0/10 | UX, Edge & Ops: Voice, TTS, PWA, Deck.gl, Collab, Pi RAG, ONNX Pi, Push Delivery, Temporal Replay, Grafana |
| 6 | Weeks 16+ | 6-10 weeks | V4-35–V4-42, V4-50, V4-70 | 0/10 | Strategic: CKAN, RF OSINT, SAR, Federation, Bitemporal, Ontology, DR, Tests, Dual Map, Social OSINT |

**Shipped count:** 10/70 (V4-01, V4-02, V4-03, V4-05, V4-08, V4-09, V4-14, V4-19, V4-58, V4-59)
**Total realistic timeline:** 42–56 weeks (~10–14 months) full-time, 20–28 months at hobby pace (10h/week). Sprint A saved ~4 weeks.

---

## Prioritized Work Plan (Cross-Instance Execution)

> **Created:** 2026-06-30 — System research + codebase audit of all 42 items.
> **Last updated:** 2026-06-30 — Sprint A1–C2 shipped, live-verified via Docker API.
> **Purpose:** Allows multiple LLM instances to work on V4 sequentially. Each instance picks the next uncompleted item, implements it, marks it done, and logs the session.
> **Methodology:** Cross-referenced Go/No-Go matrix, dependency graph, and actual codebase state (grep + file reads). Filtered by ROI, dependency-unblocking value, and existing partial implementations.

### Live Verification Results (2026-06-30, Docker Stack)

| Check | Result |
|-------|--------|
| `/api/health/ping` | ✅ OK |
| Feeds | 26 total, 21 fresh, 4 stale, 0 error |
| Briefing | quality=0.922, 5 insights, 5 watch_items, 2 agentic rounds |
| Pi Edge | online, age=28s |
| AIS | 104 vessels, stream_connected=true |
| Connectors | 38 |
| Credentials | 14 configured |
| DuckDB entities | 945 (fresh Docker DB, growing) |
| Prediction accuracy 30d | 1.0 (26 samples) |
| Snapshot Archiver | count=1 (V4-09 ✅) |
| Predictive status | endpoint responds (V4-19 ✅, flag off) |
| Global Search | endpoint responds (V4-08 ✅, flag off) |
| Feature flags | 48 registered, all V4 flags present |
| Dark Web | enabled=true, 3 engines |
| Test count | 1811 backend |

### Codebase Audit Results (verified 2026-06-30)

| V4 Item | Codebase State | Gap to Fill |
|---------|---------------|-------------|
| V4-01 (Smart Model Router) | ✅ `chat_model_router.py` shipped — complexity classifier + fallback chain | **Done** — live-verified via `/api/models/status` |
| V4-02 (RBAC + Rate Limit) | ✅ `middleware/rate_limit.py` fully implemented, `config.py` has `rbac_enabled` | **Done** — config tuning only |
| V4-03 (BGE-Reranker GPU) | ✅ `rag_rerank.py` ONNX with `CUDAExecutionProvider` support | **Done** — `RAG_RERANK_DEVICE=cuda` activates GPU path |
| V4-05 (DuckDB + H3) | ✅ DuckDB >=1.5.4 with R-Tree auto-enable on >=1.6.0; lat/lon BETWEEN fallback | **Done** — `_drop_rtree_index_if_present()` only runs on <1.6 |
| V4-08 (FTS5 Search) | ✅ `global_search.py` shipped — multi-table FTS5 across entities/briefings/feeds | **Done** — `WORLDBASE_GLOBAL_SEARCH=0` (opt-in) |
| V4-09 (Snapshot Archiver) | ✅ `snapshot_archiver.py` shipped — daily Parquet snapshots + manifest | **Done** — `WORLDBASE_SNAPSHOT_ARCHIVER=0` (opt-in) |
| V4-14 (Telegram) | ✅ `telegram_bridge.py` complete — entity matching, Mention edges, briefing block | **Done** — audit confirmed completeness |
| V4-17 (STIX/TAXII) | `stix_export.py` exists (FtM→STIX mapping, 23 tests) | Partially implemented — needs TAXII client → Sprint 1 |
| V4-19 (Predictive) | ✅ `predictive_analytics.py` shipped — LightGBM forecaster + briefing integration | **Done** — `WORLDBASE_PREDICTIVE=0` (opt-in) |

### Next Sprint Priorities (Sprint 1 — Intelligence & Infrastructure)

| # | V4 Item | New File(s) | Est. LOC | Status |
|---|---------|-------------|----------|--------|
| S1.1 | V4-23 Anomaly Detection | `anomaly_detector.py` + briefing integration | ~300 | ✅ Shipped |
| S1.2 | V4-24 Graph Algorithms | `graph_algorithms.py` + NetworkX | ~250 | ⬜ TODO |
| S1.3 | V4-35 CKAN Harvester | `ckan_harvester.py` + YAML config | ~250 | ⬜ TODO |
| S1.4 | V4-41 DR Automation | `scripts/backup_auto.py` + S3 | ~200 | ⬜ TODO |
| S1.5 | V4-16 ACLED Connector | `acled_bridge.py` + briefing block | ~200 | ⬜ TODO |
| S1.6 | V4-17 STIX/TAXII | `stix_taxii.py` + TAXII server | ~300 | ⬜ TODO |
| S1.7 | V4-43 Country Instability Index | `cii_engine.py` + briefing + Cesium layer | ~400 | ⬜ TODO |
| S1.8 | V4-44 MCP outputSchema + JMESPath | `mcp_schema.py` + `mcp_jmespath.py` | ~150 | ✅ Shipped |
| S1.9 | V4-45 Bootstrap Hydration | `bootstrap.py` + Redis cache | ~200 | ✅ Shipped |
| S1.10 | V4-64 Feed Circuit Breaker | `feed_circuit_breaker.py` + ETag | ~200 | ✅ Shipped |
| S1.11 | V4-55 OSM Critical Infrastructure | `osm_bridge.py` + Overpass API | ~200 | ⬜ TODO |
| S1.12 | V4-56 Multi-Day Weather Forecast | `weather_forecast_bridge.py` | ~150 | ⬜ TODO |

**Pick order:** S1.1 → S1.2 (both depend on V4-09 ✅ + V4-05 ✅, both shipped) → S1.8 (quick win, ~150 LOC) → S1.9 (quick win, ~200 LOC) → S1.10 (feed resilience, ~200 LOC) → S1.12 (weather, ~150 LOC quick win) → S1.11 (OSM POIs, ~200 LOC) → S1.3 → S1.4 → S1.5 → S1.6 → S1.7 (CII, highest impact but ~400 LOC)

### Dependency Chain (Sprint A — ✅ Shipped)

```
Phase A:  A1 (Model Router) ──────┐ ✅ Shipped
          A2 (CUDA Reranker)      ├── all independent, parallel-safe ✅
          A3 (FTS5 Search) ───────┘ ✅

Phase B:  B1 (DuckDB 1.6) ─────────── independent ✅
          B2 (Snapshot Archiver) ──── independent ✅

Phase C:  C1 (Telegram) ───────────── independent (audit) ✅
          C2 (Predictive) ─────────── depends on B2 (✅) ✅
```

### Dependency Chain (Sprint 1 — Next)

```
S1.1 (Anomaly Detection) ──── depends on V4-09 (✅) + feed time series (shipped)
S1.2 (Graph Algo) ─────────── depends on V4-05 (✅) + FtM graph (shipped)
S1.3 (CKAN Harvester) ─────── no deps
S1.4 (DR Automation) ──────── no deps
S1.5 (ACLED) ──────────────── no deps
S1.6 (STIX/TAXII) ─────────── no deps → unblocks V4-38 (Federation)
S1.7 (CII) ────────────────── depends on GDELT (shipped) + NewsData (shipped) + V4-09 (✅)
S1.8 (MCP outputSchema) ───── depends on mcp_server.py (shipped)
S1.9 (Bootstrap Hydration) ── depends on Redis (shipped) + existing endpoints
S1.10 (Circuit Breaker) ───── depends on feed autopilot (shipped) → unblocks V4-64
S1.11 (OSM POIs) ──────────── no deps → enhances Track 2 corroboration
S1.12 (Weather Forecast) ──── no deps → enhances Track 1 anticipation
```

### Architecture Decision Record — Language & Pattern Choices

> **ADR-001: Python remains the primary language. No Rust/C++ rewrite.**

**Context:** WorldBase is ~90% I/O-bound (feed fetching, LLM waiting, DB queries). All CPU-bound workloads (ML, graph, spatial) already use C++/Cython backends under the hood (scikit-learn, DuckDB, Splink, ONNX, Torch). Python is the orchestration layer, not the compute layer.

**Decision:** Keep Python for all application code. Only consider Rust/C++ when a **measurable** bottleneck exceeds:

| Trigger | Threshold | Action |
|---------|-----------|--------|
| Feed ingest throughput | >10,000 events/sec sustained | Rust ingest microservice (Tokio) |
| AIS stream | >10,000 positions/sec | Rust actor pipeline |
| Graph algorithms | >1M nodes, <100ms PageRank | Rust `petgraph` service |
| Custom ML inference | <10ms latency, >500MB model | Rust + ONNX Runtime |
| Edge device | <512MB RAM | Rust binary (Pi Zero class) |

**Current loads:** 30 feeds / 10 min, ~74 AIS positions / min, ~45k FtM entities. Python is never the bottleneck.

> **ADR-002: No hexagonal architecture rewrite. Pragmatic module isolation instead.**

**Context:** WorldBase has ~260 `.py` files with informal layering (config → routes → domain → infra). Hexagonal (Ports & Adapters) would cost 6–12 months for zero measurable performance gain, complicate fail-soft patterns, and conflict with the feature-flag architecture.

**Decision:** Use **pragmatic module isolation** for new features instead of a full hexagonal rewrite:

```
New feature module structure (guideline, not enforced):
  domain/  — pure logic, no I/O imports (testable in isolation)
  infra/   — HTTP, SQLite, DuckDB, FtM adapters
  api/     — FastAPI router, request/response models
```

**When to revisit hexagonal:**
- Team grows beyond 3 active developers
- More than 3 storage backends in simultaneous use
- Domain-test coverage target >95% with <2s suite runtime
- WorldBase core extracted as a public SDK

**Current state:** 1281+ tests pass with the existing structure. Module isolation is sufficient.

### Deliberately Excluded (with rationale)

| Item | Reason |
|------|--------|
| ~~V4-02 (RBAC)~~ | ✅ Shipped — already implemented, config tuning only |
| V4-04 (Embedding GPU) | Low priority — Ollama CPU embeddings work fine → Sprint 2 |
| V4-06/V4-07 (GDPR/Retention) | Single-user station, low compliance urgency → Sprint 5 |
| V4-10 (Classification) | Only needed for Federation (V4-38, explicitly NO-GO) → Sprint 5 |
| V4-11 (Self-Consistency) | 3× LLM cost, marginal quality gain → Sprint 3 |
| V4-12 (LoRA) | Experimental, overnight VRAM schedule complexity → Sprint 3 |
| V4-13 (Speculative Decoding) | Complex (400-600 LOC), Ollama support unclear → Sprint 3 |
| V4-22 (ColQwen2) | Cannot coexist with 14B in VRAM, needs microservice → Sprint 3 |
| V4-38 (Federation) | Explicitly NO-GO — experiment, not production → Sprint 6 |
| V4-47 (Route Explorer) | Complex (~500 LOC), needs chokepoint config — Sprint 3 |
| V4-50 (Dual Map) | Overlaps with V4-31, bundle-size concern — Sprint 6 |
| V4-65 (Temporal Replay) | ~1000 LOC FE, luxury feature — Sprint 5 |
| V4-67 (vec1 Benchmark) | Research only, sqlite-vec fine at <100k — Sprint 4 |
| V4-68 (LLM A/B) | Research only, no production impact — Sprint 4 |
| V4-69 (Grafana Dashboard) | Visualisierung, nicht kritisch für Single-User — Sprint 5 |
| V4-70 (Social OSINT) | ToS/Ethik-Risiko, GDELT deckt teilweise ab — Sprint 6+ |

### Instance Handoff Protocol

> **For future LLM instances:** Read this section before starting work.

1. **Check Sprint 1 priorities** — pick the first item with `⬜ TODO` status in the Next Sprint Priorities table above.
2. **Read the item spec** in this document (search for `V4-XX` heading above).
3. **Read the codebase audit row** to understand what already exists.
4. **Implement** following WorldBase conventions (fail-soft, feature flag default off, venv Python, unit tests required).
5. **Update the status column** to `✅ DONE` with commit hash + date.
6. **Log session** in `progress.txt` with what was done, files changed, test results.
7. **If blocked:** Set status to `⛔ BLOCKED` with reason. Next instance can skip or unblock.

### Status Legend

- `⬜ TODO` — not started
- `🔄 IN PROGRESS` — actively being worked on (include instance ID + date)
- `✅ DONE` — completed (include commit hash + date)
- `⛔ BLOCKED` — blocked by dependency or external issue (include reason)
