# WorldBase Roadmap 2026 — Spatial Intelligence Workstation

> **Status:** R0–R1.4 shipped · 318/318 tests · 33/33 smoke · Track R2 optional
>
> **Validated against:** ArXiv 2026 (Adaptive Query Routing), Gartner Top Trends 2026 (Digital Provenance),
> NullSec OSINT 2026, MoJ Splink Production 2026, SpaRAGraph ACM 2026, FtM 4.0 (OpenSanctions Jul 2025),
> TideWatch Maritime DWA, GraphRAG vs Hybrid RAG production data 2026.

---

## Architecture (current, live)

```
Live Feeds → T2 YAML Ingest → FtM Entities (DuckDB) → PR3 Splink (sameAs)
                              ↓                        ↓
                    RAG Memory (sqlite-vec + FTS5)   FtM Graph (edges)
                              ↓                        ↓
                    CRAG-lite Chat ←→ Briefing Agentic Loop (3-phase)
                              ↓                        ↓
                         Ollama qwen3:8b → SQLite briefings → Pi Edge Node
```

**What exists (do not rebuild):**

| Capability | Module | Status |
|------------|--------|--------|
| Hybrid RAG (vector + FTS5 + RRF + BGE rerank) | `rag_memory.py`, `rag_hybrid.py`, `rag_rerank.py` | ✅ R0 |
| Spatial RAG (geohash + bbox pre-filter) | `rag_spatial.py` | ✅ R1.1 |
| CRAG-lite chat (low confidence → situations + subgraph) | `rag_crag.py`, `chat_proxy.py` | ✅ R1.2 |
| Adaptive YAML chunking | `rag_chunking.py`, `ingest/mappings/*.yml` | ✅ R1.3 |
| Briefing agentic loop (3-phase: coverage → retrieve → corroboration) | `briefing_agentic.py` | ✅ R1.4 |
| FtM entity graph (DuckDB) | `ftm_store.py`, `ftm_connection.py`, `ftm_query.py` | ✅ |
| 2-hop subgraph BFS with bbox | `intel_subgraph.py` | ✅ |
| Spatial proximity edges (haversine) | `intel_proximity.py` | ✅ |
| Entity resolution (exact + subset + Splink fuzzy) | `entity_resolution.py` | ✅ PR3 |
| Feed ingest (YAML mappings, autopilot 600s) | `mapping_runner.py`, `feed_ingest.py` | ✅ T2 |
| Fusion heatmap (6+ feeds → grid) | `fusion_heatmap.py` | ✅ |
| Insight cards (fusion-ranked, LLM-narrated) | `insights.py` | ✅ Track A |
| MCP tools (13 tools, Streamable HTTP) | `mcp_server.py` | ✅ |
| Agent Bus (pub/sub → SSE → HUD) | `agent_bus.py` | ✅ |
| AIS maritime (AISstream WebSocket + fallbacks) | `ais_bridge.py` | ✅ |
| Briefing quality scoring (rule-based) | `briefing_quality.py` | ✅ |
| Prediction ledger (watch items + horizons) | `prediction_ledger.py` | ✅ B-03 |
| Corroboration scoring (multi-source digest) | `briefing_quality.py`, B-04 | ✅ |
| Feed drift (count-based freshness) | `feed_drift.py` | ✅ |
| Chat routing (provider fan-out, SSRF guard) | `chat_routing.py`, `chat_proxy.py` | ✅ |
| Chat context (briefing + nodes + feeds injection) | `chat_context.py` | ✅ |
| Prompt guard (0 VRAM baseline) | `prompt_guard.py` | ✅ |

---

## Roadmap phases (P1–P7)

### P1 — Query Router (vector / graph / spatial / hybrid) ✅ SHIPPED

**Why:** ArXiv Apr 2026 ("Adaptive Query Routing") bestätigt: Query-Routing ist der aktivste Forschungsgegenstand in Hybrid-RAG. WorldBase hat alle Retrieval-Pfade (vector, graph, spatial), aber kein Routing — CRAG-Lite macht nur post-hoc Fallback.

**Spec:**

```
User Query → classify_query() → route tag
  ├─ "vector"   → rag_memory.search() (sqlite-vec + FTS5 + RRF)
  ├─ "graph"    → intel_subgraph.build_subgraph() + format_subgraph_prompt_block()
  ├─ "spatial"  → rag_memory.search(bbox=operator_bbox) + intel_proximity edges
  ├─ "hybrid"   → vector + graph (parallel), merge by RRF
  └─ "live"     → situations + fusion_heatmap (no RAG)
```

**Classification (rule-based, 0 VRAM):**

| Signal | Route |
|--------|-------|
| Entity name ("who is X", "connection between X and Y") | `graph` |
| Geo keywords ("near", "within", "around", "border", "coordinates") | `spatial` |
| Relationship keywords ("related to", "connected", "links between") | `graph` |
| Temporal keywords ("latest", "today", "current situation") | `live` |
| Factual lookup ("what is", "summarize", "explain") | `vector` |
| Mixed signals | `hybrid` |

**Files:**
- **New:** `backend/query_router.py` — `classify_query(query: str) -> str`, `route_retrieval(query: str, route: str) -> list[dict]`
- **Modify:** `rag_crag.py` — `build_rag_crag_block()` calls `classify_query()` before retrieval; routes accordingly
- **Modify:** `chat_proxy.py:_prepare_chat_messages()` — passes route tag to system prompt ("Retrieval mode: GRAPH")
- **New test:** `test_query_router.py` — classification accuracy, route dispatch, hybrid merge

**Env:** `WORLDBASE_QUERY_ROUTER=1` (default on), `WORLDBASE_QUERY_ROUTER_FALLBACK=vector`

**Effort:** Klein (~200 LOC + tests)
**Dependencies:** Keine — nutzt existierende `rag_memory`, `intel_subgraph`, `rag_spatial`

**Success metrics:**
- Chat responses on graph queries include entity relationships (not just document chunks)
- Spatial queries return bbox-filtered results
- Classification accuracy >80% on manual test set of 50 queries

---

### P2 — Splink 2-Stufen Pipeline (pro-Feed dedupe → cross-Feed link)

**Why:** MoJ Production Blog Jan 2026: "Dedupe each dataset in isolation → generate cross-dataset edges → consolidate → cluster once." Aktuell macht `entity_resolution.py` `dedupe_only` in einem Run über alle Schemas gemischt. Feed-Entities sind disconnected (edges=0 in YAML mappings).

**Spec:**

```
Stage 1: Per-dataset dedupe
  for dataset in datasets:
    rows = list_entities_for_resolution(schemas, filter=dataset)
    edges_dedupe = run_splink(rows, link_type="dedupe_only")

Stage 2: Cross-dataset link
  for (dataset_a, dataset_b) in coherent_pairs:
    rows = merge(rows_a, rows_b)
    edges_cross = run_splink(rows, link_type="link_only")

Stage 3: Consolidate + cluster
  all_edges = edges_dedupe + edges_cross
  clusters = transitive_closure(all_edges)
  write sameAs edges with method="splink:dedupe" / "splink:cross"
```

**Files:**
- **Modify:** `entity_resolution.py` — `run_resolution()` bekommt `pipeline_mode` parameter (`"single"` | `"two_stage"`)
- **Modify:** `ftm_query.py` — `list_entities_for_resolution()` bekommt optional `dataset` filter
- **New test:** `test_entity_resolution_pipeline.py` — two-stage produces more cross-dataset edges than single-stage on same fixtures

**Env:** `WORLDBASE_ENTITY_RESOLUTION_PIPELINE=two_stage` (default `single` für backward compat)

**Effort:** Mittel (~400 LOC + tests)
**Dependencies:** P1 nicht erforderlich, aber P1 Query Router profitiert von mehr Edges

**Success metrics:**
- Cross-dataset sameAs edges >0 (aktuell 0)
- Feed entities im FtM Graph sind verbunden
- Briefing INTEL SUBGRAPH block zeigt Querverbindungen

---

### P3 — Agentic Loop für Chat ✅ SHIPPED

**Why:** NullSec Apr 2026: "Agentic investigation becomes the baseline. The question changes from 'what data can I find?' to 'what conclusions should I validate?'" Aktuell läuft der Agentic Loop (`briefing_agentic.py`) nur im Briefing-Pfad, nicht im Chat. Chat nutzt nur CRAG-Lite (post-hoc Fallback).

**Spec:**

```
Chat Query (CTX mode)
  → Phase 1: Coverage — hat der RAG-Block genug Daten für diese Query?
  → Phase 2: Retrieve — wenn Coverage gap, gezielte RAG-Suche mit Query-spezifischen Terms
  → Phase 3: Corroboration — mark weak claims, flag uncorroborated assertions
  → System Prompt: "Retrieval mode: AGENTIC. Phases run: [coverage, retrieve, corroboration]"
```

**Files:**
- **New:** `backend/chat_agentic.py` — `run_chat_agentic_loop(query: str, rag_block: str) -> str` (adapted from `briefing_agentic.py`)
- **Modify:** `chat_proxy.py:_prepare_chat_messages()` — wenn `WORLDBASE_CHAT_AGENTIC=1`, ersetzt `build_rag_crag_block()` durch `run_chat_agentic_loop()`
- **New test:** `test_chat_agentic.py` — coverage detection, retrieve augmentation, corroboration marking

**Env:** `WORLDBASE_CHAT_AGENTIC=1` (default off, opt-in), `WORLDBASE_CHAT_AGENTIC_MAX_ROUNDS=3`

**Effort:** Klein (~250 LOC + tests, da Logik aus `briefing_agentic.py` adaptiert wird)

**Success metrics:**
- Chat responses in CTX mode include RAG recall lines when initial context is thin
- Corroboration tags appear in chat responses ("[uncorroborated]" / "[2 sources]")

---

### P3+ — Multi-Agent Orchestration

**Why:** 2026 OSINT-Trend: nicht ein Agent, sondern ein Team von Spezialagenten. WorldBase hat bereits 13 MCP Tools + Agent Bus. Ein Orchestrator koordiniert diese.

**Spec:**

| Agent | Job | MCP Tool / Module | Wann aktiv |
|-------|-----|-------------------|-----------|
| **Coverage** | "Was wissen wir?" | `rag_memory.search` + `intel_subgraph` | Immer |
| **Retrieval** | Vector, Graph oder Spatial | P1 Query Router | Je nach Route |
| **Corroboration** | "Welche Quellen bestätigen das?" | `briefing_quality.corroboration_summary` | Bei Konflikt |
| **Spatial** | BBox/Radius/Topology | `intel_proximity` + `rag_spatial` | Bei Geo-Queries |
| **Synthesis** | Finale Antwort | Ollama | Immer |

**Implementation:** Jeder Agent ist ein MCP Tool-Aufruf. Der Orchestrator ist ein rule-based Dispatcher (kein LLM-Router — 0 VRAM). Nutzt existierenden Agent Bus für HUD-Updates (fly-to, layer toggle).

**Files:**
- **New:** `backend/agent_orchestrator.py` — `orchestrate(query: str, route: str) -> dict` (dispatches to agents, merges results)
- **Modify:** `mcp_server.py` — register 2 new tools: `worldbase_orchestrate`, `worldbase_agent_status`
- **New test:** `test_agent_orchestrator.py` — dispatch accuracy, agent invocation order, result merge

**Env:** `WORLDBASE_AGENT_ORCHESTRATOR=1` (default off), nutzt `WORLDBASE_AGENT_BUS=1`

**Effort:** Mittel (~400 LOC + tests)
**Dependencies:** P1 (Query Router) für korrektes Routing, P3 (Chat Agentic) für Coverage-Phase

**Success metrics:**
- Chat responses zeigen Agent-Trace ("Coverage → Retrieval(graph) → Corroboration → Synthesis")
- HUD zeigt aktive Agent-Phasen via Agent Bus

---

### P4 — Feed Fusion Scoring + Digital Provenance ✅ SHIPPED

**Why:** Gartner Top Strategic Trend 2026: "Digital Provenance — cryptographic provenance frameworks to verify integrity of all incoming and outgoing digital content." TideWatch: "layered scoring: proximity × behavioral anomaly × vessel type risk × time-of-day." WorldBase hat `briefing_quality.py` (rule-based scoring) und `corroboration_ground_truth.py` (B-04 pilot), aber keinen Integrity-Score pro Feed-Item.

**Spec:**

```python
provenance_score = f(
    source_reliability: float,     # 0.0-1.0, z.B. GDACS=0.9, GDELT=0.7, blog=0.3
    corroboration_count: int,      # wie viele andere Feeds bestätigen das?
    temporal_consistency: float,   # passt zum Zeitverlauf? (decay function)
    ingestion_chain: str,          # feed → mapping → ftm → rag (hash chain)
)
# 0.0-1.0, attached to every digest line and insight card

feed_fusion_score = f(
    proximity: float,              # distance to operator region (haversine)
    source_reliability: float,     # provenance_score
    temporal_freshness: float,     # age vs TTL (freshness.py classify_freshness)
    entity_type_risk: float,       # Vessel=0.3, Event=0.5, Person=0.7, Org=0.6
    escalation_delta: float,       # fusion_heatmap delta vs 24h baseline
)
```

**Files:**
- **New:** `backend/provenance.py` — `score_provenance(source, corroboration_count, age_sec, ingest_chain) -> float`, `source_reliability_table` (static mapping)
- **Modify:** `briefing_quality.py` — `build_digest_line_meta()` adds `integrity` field per line
- **Modify:** `insights.py` — `_confidence()` incorporates `provenance_score` into confidence calculation
- **Modify:** `fusion_heatmap.py` — cell scoring incorporates `source_reliability` weight (currently uniform)
- **New test:** `test_provenance.py` — score boundaries, corroboration boost, temporal decay

**Env:** `WORLDBASE_PROVENANCE=1` (default on)

**Effort:** Mittel (~350 LOC + tests)
**Dependencies:** Keine — erweitert existierende Scoring-Module

**Success metrics:**
- Jede Digest-Zeile hat `integrity` Score in `digest_line_meta`
- Insight cards zeigen `provenance` neben `confidence`
- Fusion heatmap gewichtet zuverlässige Quellen höher
- Briefing-Quality B-04 pilot korreliert mit Integrity-Score

---

### P5 — FtM 4.0 StatementEntity (per-value provenance)

**Why:** FtM 4.0 (OpenSanctions Jul 2025) führt `StatementEntity` mit per-value provenance ein: jede Property weiß, aus welcher Quelle sie stammt. `nomenklatura` macht graph-based dedup mit transitive judgements. Aktuell speichert WorldBase provenance nur auf Entity-Level (`datasets` array), nicht per-Statement.

**Spec:**

```
Current: Entity { id, schema, properties: {name: ["Alice"], country: ["TH"]}, datasets: ["feedA", "feedB"] }
Target:  Entity { id, schema, statements: [
           {prop: "name", value: "Alice", dataset: "feedA", first_seen: ..., last_seen: ...},
           {prop: "country", value: "TH", dataset: "feedB", first_seen: ..., last_seen: ...},
         ]}
```

**Migration path:**
1. Add `statements` table to DuckDB schema (parallel to existing `entities` table)
2. `ftm_store.upsert()` writes both `entities` (backward compat) and `statements` (new)
3. New query helpers: `get_statements(entity_id)`, `query_by_provenance(dataset, prop)`
4. P4 Provenance Score nutzt per-statement provenance statt entity-level `datasets`

**Files:**
- **Modify:** `ftm_connection.py` — schema migration: add `statements` table
- **Modify:** `ftm_store.py` — `upsert()` writes statements; new `get_statements()`, `query_by_provenance()`
- **Modify:** `ftm_query.py` — `list_entities_for_resolution()` includes statement-level provenance
- **Modify:** `entity_resolution.py` — Splink comparisons can use per-statement provenance for confidence weighting
- **New test:** `test_ftm_statements.py` — statement CRUD, provenance query, backward compat

**Env:** `WORLDBASE_FTM_STATEMENTS=1` (default off during migration, opt-in)

**Effort:** Groß (~800 LOC + migration + tests)
**Dependencies:** P4 (Provenance) profitiert direkt, P2 (Splink 2-Stufen) kann per-statement provenance nutzen

**Success metrics:**
- `statements` table populated for all new ingests
- `query_by_provenance("gdacs", "severity")` returns correct results
- Backward compat: existing `entities` table queries unchanged
- P4 Provenance Score nutzt per-statement data

---

### P5+ — Dynamic Knowledge Graph (Agent schreibt zurück)

**Why:** 2026 Trend: "Dynamic knowledge graphs that update from agent interactions. Your agent won't just search a static index. It will maintain a living knowledge graph that grows with each conversation." FtM 4.0 `StatementEntity` hat `external` flag für user-derived knowledge.

**Spec:**

```
User: "Was ist der Zusammenhang zwischen Vessel X und Event Y?"
Agent: findet keine direkte Verbindung im Graph
Agent: erzeugt Edge {source: Vessel X, target: Event Y, kind: "relatedTo",
                     dataset: "user-query", confidence: 0.6, external: true}
Agent: "Keine direkte Verbindung gefunden. Möglicher Zusammenhang: [Begründung]. 
        Ich habe diese Hypothese als external edge im Graph markiert."
```

**Guardrails:**
- `external: true` flag auf allen user-derived edges
- Confidence capped at 0.7 (human-confirmed = 0.9)
- Operator kann external edges review/approve/reject via `/api/intel/edges?external=1`
- Rejected edges werden gelöscht, approved edges bekommen `confirmed: true`

**Files:**
- **Modify:** `ftm_store.py` — `add_edge()` accepts `external: bool` and `confirmed: bool` properties
- **Modify:** `agent_orchestrator.py` (P3+) — Synthesis agent writes back external edges on graph gaps
- **New:** `backend/edge_review.py` — `list_external_edges()`, `approve_edge()`, `reject_edge()`
- **New route:** `GET /api/intel/edges?external=1`, `POST /api/intel/edges/{id}/approve|reject`
- **New test:** `test_edge_review.py` — external edge lifecycle, confidence cap, review flow

**Env:** `WORLDBASE_DYNAMIC_GRAPH=1` (default off), `WORLDBASE_DYNAMIC_GRAPH_MAX_CONFIDENCE=0.7`

**Effort:** Mittel (~300 LOC + tests)
**Dependencies:** P3+ (Multi-Agent) für Synthesis-Phase, P5 (StatementEntity) für `external` flag

**Success metrics:**
- External edges appear in graph view with distinct styling
- Operator review workflow functional
- Briefing INTEL SUBGRAPH includes external edges (marked as hypotheses)

---

### P6 — Spatial Reasoning Layer (NL → Spatial Operation)

**Why:** SpaRAGraph (ACM 2026): "graph traversal approach assisted by a spatial relation composition matrix." Spatial RAG ist nicht nur BBox-Filter — es braucht topologisches Reasoning (within, intersects, contains, near, upstream, downstream, visible-from). WorldBase hat `rag_spatial.py` (BBox) und `intel_proximity.py` (haversine nearby), aber keine NL→Spatial-Operation-Übersetzung.

**Spec:**

```
User: "Welche Entities sind innerhalb 50km von Bangkok?"
  → parse_spatial_query() → {operation: "within", center: Bangkok, radius_km: 50}
  → spatial_query() → intel_proximity + rag_spatial + fusion_heatmap cells

User: "Welche Events sind downstream vom Chao Phraya?"
  → parse_spatial_query() → {operation: "downstream", reference: Chao Phraya}
  → spatial_query() → river network traversal (needs river graph data)

User: "Was ist nahe der Grenze Thailand-Myanmar?"
  → parse_spatial_query() → {operation: "near", reference: border_polygon}
  → spatial_query() → bbox filter + proximity edges
```

**Spatial operations:**

| Operation | Implementation | Data needed |
|-----------|---------------|-------------|
| `within` | BBox + haversine radius | Entity coords |
| `near` | BBox expansion + proximity edges | Entity coords |
| `intersects` | BBox overlap | Entity + area polygons |
| `contains` | Point-in-polygon | Entity coords + area polygons |
| `adjacent` | Shared border detection | Admin boundary polygons |
| `downstream` | River network traversal | River graph (new data) |

**Files:**
- **New:** `backend/spatial_reasoning.py` — `parse_spatial_query(query: str) -> dict`, `execute_spatial_operation(op: dict) -> list[dict]`
- **New:** `backend/spatial_relations.py` — relation matrix (inspired by SpaRAGraph): composition rules for spatial operations
- **Modify:** `query_router.py` (P1) — `spatial` route calls `parse_spatial_query()` before retrieval
- **Modify:** `intel_proximity.py` — add `within_radius(center, radius_km)` function
- **New test:** `test_spatial_reasoning.py` — NL parsing accuracy, operation execution, relation composition

**Env:** `WORLDBASE_SPATIAL_REASONING=1` (default off, opt-in)

**Effort:** Groß (~600 LOC + tests, river graph data optional)
**Dependencies:** P1 (Query Router) für spatial route, P4 (Fusion Scoring) für proximity scoring

**Success metrics:**
- "within 50km of X" queries return correct entity sets
- Spatial reasoning trace appears in chat responses
- SpaRAGraph-style relation composition works for adjacent/contains queries

---

### P7 — Maritime Pattern-of-Life (Behavioral Anomaly Detection)

**Why:** MDA Markt $3.8B → $10.2B bis 2034. Killer-Use-Case ist nicht "Schiffe auf Karte" sondern "pattern-of-life analysis" und "dark vessel detection". WorldBase speichert AIS-Snapshots in `_STREAM["vessels"]` (in-memory, latest-only). Keine Trajectory-Historie, keine Anomalie-Erkennung.

**Spec:**

```python
# AIS-Buffer → Trajectory Features (rule-based, no ML)
vessel_features = {
    "mmsi": "259000420",
    "speed_variance_24h": float,       # plötzliche Beschleunigung?
    "mean_speed_24h": float,           # Durchschnittsgeschwindigkeit
    "anchorage_time_hours": float,     # lange im Hafen ohne Ankermeldung?
    "night_port_visits": int,          # Frontex: "how many times visited a port at night"
    "ais_gap_duration_sec": float,     # transponder off?
    "proximity_to_risk_zones": float,  # nahe Piraterie-Gebiet? (distance to known risk zones)
    "course_changes_24h": int,         # häufige Richtungswechsel?
    "region_transitions_24h": int,     # wie viele Regionen gewechselt?
}

# Anomaly Score (rule-based, weighted)
anomaly_score = (
    speed_variance * 0.15 +
    night_port_visits * 0.20 +
    ais_gap_duration_normalized * 0.25 +
    proximity_to_risk_zones * 0.25 +
    course_changes_normalized * 0.15
)
# 0.0-1.0, >0.6 = anomaly alert
```

**Data storage:** Rolling window in SQLite (not DuckDB — avoids lock contention with FtM graph). Table: `ais_trajectory` (mmsi, lat, lon, speed, course, timestamp). 24h retention, hourly compaction to features.

**Files:**
- **New:** `backend/ais_trajectory.py` — `store_position(vessel)`, `compute_features(mmsi)`, `detect_anomalies() -> list[dict]`
- **Modify:** `ais_bridge.py:_ingest_stream_message()` — also calls `ais_trajectory.store_position()` when trajectory tracking enabled
- **Modify:** `insights.py` — anomaly alerts feed into insight cards (new insight type: "maritime anomaly")
- **Modify:** `fusion_heatmap.py` — anomaly score contributes to cell weight (new input: maritime anomalies)
- **New test:** `test_ais_trajectory.py` — feature computation, anomaly detection thresholds, retention

**Env:** `WORLDBASE_MARITIME_TRAJECTORY=1` (default off), `WORLDBASE_MARITIME_ANOMALY_THRESHOLD=0.6`, `WORLDBASE_MARITIME_TRAJECTORY_RETENTION_H=24`

**Effort:** Mittel (~500 LOC + tests)
**Dependencies:** Keine — baut auf `ais_bridge.py` auf. P4 (Fusion Scoring) für integration in heatmap.

**Success metrics:**
- `GET /api/maritime/anomalies` returns flagged vessels with feature breakdown
- Insight cards show maritime anomaly alerts
- Fusion heatmap weights anomaly zones higher
- AIS gap detection works (vessel disappears >30min → flag)

---

## Implementation order + dependencies

```
P1 (Query Router) ────────────────────────────────────────────── no deps
P2 (Splink 2-Stufen) ────────────────────────────────────────── no deps
P3 (Agentic Chat) ───────────────────────────────────────────── no deps
P4 (Provenance + Fusion Scoring) ────────────────────────────── no deps
  │
  ├── P3+ (Multi-Agent) ← requires P1 + P3
  ├── P5 (FtM 4.0 StatementEntity) ← benefits from P4
  │     └── P5+ (Dynamic Graph) ← requires P3+ + P5
  ├── P6 (Spatial Reasoning) ← requires P1
  └── P7 (Maritime Pattern-of-Life) ← benefits from P4
```

**Recommended sequence:**
1. **P1** (Query Router) — höchster ROI, kleinster Aufwand, aktiviert P3+ und P6
2. **P4** (Provenance + Fusion Scoring) — Gartner Trend, erweitert existierende Scoring-Module
3. **P3** (Agentic Chat) — OSINT Baseline 2026, adaptiert briefing_agentic.py
4. **P2** (Splink 2-Stufen) — löst disconnected entities, MoJ Best Practice
5. **P7** (Maritime Pattern-of-Life) — MDA Markt, unabhängig, hoher Demo-Wert
6. **P3+** (Multi-Agent) — benötigt P1 + P3
7. **P5** (FtM 4.0) — größter Aufwand, Migration, aber Fundament für P5+
8. **P5+** (Dynamic Graph) — benötigt P3+ + P5
9. **P6** (Spatial Reasoning) — benötigt P1, größter Aufwand, aber differenziert WorldBase

---

## VRAM budget (16 GB RTX 3080 Ti)

| Workload | VRAM | Rule |
|----------|------|------|
| `qwen3:8b` chat | ~6 GB | Default |
| `nomic-embed-text` | ~0.5 GB | Short embed calls |
| BGE reranker | 0 (CPU) | Preferred |
| Query Router | 0 (rule-based) | P1 |
| Agentic Loop | 0 (rule-based) | P3 |
| Provenance Scoring | 0 (rule-based) | P4 |
| Maritime Anomaly | 0 (rule-based) | P7 |
| Splink 2-Stufen | 0 (DuckDB) | P2 |
| Spatial Reasoning | 0 (rule-based) | P6 |
| ColQwen2.5-4B (R2.2) | ~4 GB | Exclusive GPU job, not concurrent with chat |

**Alle P1-P7 sind 0 VRAM** — sie erweitern den rule-based / CPU-Stack. GPU bleibt für Ollama + optional R2.x.

---

## Explicit non-goals (unchanged)

- Kein RAGFlow als zweiter Stack
- Kein Microsoft GraphRAG (FtM **ist** der GraphRAG-Spine)
- Kein LangGraph Fleet (rule-based Orchestrator reicht)
- Kein Multimodal Vector RAG vor R0-Messung
- Keine DuckDB→Postgres Migration (DuckDB reicht für single-operator)
- Kein HAK_GAL LLM Firewall (:8001) unless explicitly asked

---

## Verification per phase

| Phase | Test command | API check |
|-------|-------------|-----------|
| P1 | `python -m unittest test_query_router -v` | `GET /api/chat` with classified query → route tag in response meta |
| P2 | `python -m unittest test_entity_resolution_pipeline -v` | `POST /api/intel/resolution/run?pipeline=two_stage` → cross-dataset edges >0 |
| P3 | `python -m unittest test_chat_agentic -v` | `POST /api/chat` with CTX → `agentic` trace in response |
| P3+ | `python -m unittest test_agent_orchestrator -v` | `POST /api/mcp` → `worldbase_orchestrate` tool |
| P4 | `python -m unittest test_provenance -v` | `GET /api/briefing` → `digest_line_meta[].integrity` |
| P5 | `python -m unittest test_ftm_statements -v` | `GET /api/intel/entities?provenance=1` → per-statement sources |
| P5+ | `python -m unittest test_edge_review -v` | `GET /api/intel/edges?external=1` → review queue |
| P6 | `python -m unittest test_spatial_reasoning -v` | `POST /api/chat` "within 50km of Bangkok" → spatial operation trace |
| P7 | `python -m unittest test_ais_trajectory -v` | `GET /api/maritime/anomalies` → anomaly list with features |

Full suite after each phase:
```powershell
cd backend
python -m unittest test_mcp_tools test_agent_bus ... test_ais_trajectory -v
.\scripts\smoke-test.ps1
```

---

## Changelog

| Date | Note |
|------|------|
| 2026-06-25 | Initial roadmap; P1-P7 defined, validated against 2026 industry research |
| 2026-06-25 | **P1 shipped** — Query Router (`query_router.py`): 5 routes (vector/graph/spatial/hybrid/live), rule-based classification, `build_routed_block()` in `rag_crag.py`, route tag in `chat_proxy.py` system prompt. 33 new tests, 0 regressions. Env: `WORLDBASE_QUERY_ROUTER=1` (default on) |
| 2026-06-25 | **P4 shipped** — Digital Provenance (`provenance.py`): source reliability table (30+ feeds), temporal decay (6h half-life), corroboration boost, conflict penalty, ingestion chain hash. Integrity field in `digest_line_meta`, provenance in insight cards, source-weighted fusion cells. 34 new tests, 0 regressions. Env: `WORLDBASE_PROVENANCE=1` (default on) |
| 2026-06-25 | **P3 shipped** — Agentic Chat Loop (`chat_agentic.py`): 3-phase state machine (coverage → retrieve → corroboration) for chat CTX mode. Coverage gap detection on RAG block, targeted retrieval via query router routes, corroboration tags (`[corroborated]`/`[uncorroborated]`) on source-tagged lines. Trace line in system prompt. 26 new tests, 0 regressions. Env: `WORLDBASE_CHAT_AGENTIC=1` (default off, opt-in) |
