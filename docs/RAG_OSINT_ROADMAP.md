# RAG / OSINT enhancement roadmap (Track R)

> **For the next agent instance.** Extends WorldBase in place — no RAGFlow, no Microsoft GraphRAG fork.  
> Operator hardware: RTX 3080 Ti 16 GB + Intel i9-12900HX (CPU-first rerank/chunking, GPU for Ollama + embeddings).

Public agent entry: [`AGENTS.md`](../AGENTS.md). Intel graph baseline: [`INTEL_INGEST.md`](INTEL_INGEST.md).

---

## One sentence

**Track R** evolves WorldBase from hybrid RAG + FtM graph into a **spatial, corroborated, local-first** OSINT retrieval stack — reusing `rag_memory.py`, `ftm_store`, briefing quality, and live feeds instead of replacing them.

---

## Entry checklist (always)

1. Read [`AGENTS.md`](../AGENTS.md).
2. `GET /api/health/ping`
3. Operator prefs / uncommitted work: `LLM_HANDOFF.md` (local only, never commit).
4. Pilots if touching briefing/RAG: `.\scripts\prediction-ground-truth-pilot.ps1 -Live`, `.\scripts\fusion-baseline-status.ps1`.

---

## What already exists (do not rebuild)

| Capability | Module / surface | Notes |
|------------|------------------|-------|
| Hybrid RAG | `rag_memory.py`, `rag_hybrid.py`, `rag_rerank.py` | sqlite-vec + FTS5 + RRF + optional BGE rerank (CPU) |
| Spatial RAG | `rag_spatial.py` | geohash in chunk `meta`, operator bbox pre-filter (`RAG_SPATIAL=1`) |
| CRAG-lite chat | `rag_crag.py`, `routes/chat.py` | low RAG score → situations + FtM subgraph in CTX mode |
| NEWS + ledger RAG | `rag_memory.py` ingest paths | GDELT local/global, NewsData, `prediction_watch` chunks |
| Entity graph | `ftm_store.py`, `intel_ingest.py`, `entity_resolution.py` | DuckDB FtM — this **is** your GraphRAG spine |
| Subgraph + spatial | `intel_subgraph.py`, `intel_proximity.py` | 2-hop bbox, `nearby` edges |
| Corroboration | `briefing_quality.py`, B-04 pilot | Multi-source digest scoring |
| Prediction ledger | `prediction_ledger.py`, B-03 pilot | Watch items + horizons |
| Feed drift (count) | `feed_drift.py` | Snapshots in `/api/trust` |
| Agent tools | `mcp_server.py`, `chat_tools.py`, Agent Bus | Light agentic layer |
| NEWS HUD | `NewsPanel.tsx` | NewsData + GDELT local/global |
| GDELT global persist | `gdelt_bridge.py` | Disk key `gdelt_pulse_global`, `warmup_global_pulse()` |

**Out of scope by default:** RAGFlow, full LangGraph fleet, HAK_GAL firewall R&D, Pi full vector RAG, DuckDB→Postgres migration.

---

## Shipped (2026-06-22)

| Track | Status | Notes |
|-------|--------|-------|
| **R0.1–R0.4** | **Done** | BGE reranker, chunk prefixes, ledger→RAG, NEWS ingest |
| **R1.1–R1.3** | **Done** | Spatial bbox filter + CRAG-lite in chat CTX + adaptive YAML chunking |
| **Dev reload** | **Done** | `start.ps1` excludes SQLite/DuckDB from `--reload` watch |

**Verify:** `GET /api/memory/stats` → `rerank_enabled`, `spatial_enabled`, `adaptive_chunking`; `python -m unittest test_rag_chunking -v`.

---

## Parallel tracks (do not block R0)

| Track | Action | Success |
|-------|--------|---------|
| **B-03** | `prediction-ground-truth-pilot.ps1 -Live` | `prediction_accuracy_30d` is a number |
| **B-06** | `fusion-baseline-status.ps1` | `snapshots_stored` grows; `fusion_compare.available` after ~24 h |

---

## Track R phases

### R0 — High impact, low effort ✅ shipped

| ID | Deliverable | Files | Hardware | Tests |
|----|-------------|-------|----------|-------|
| **R0.1** | **BGE reranker** after RRF in `search()` | `rag_rerank.py`, `rag_memory.py`, `.env.example` | **CPU** (`RAG_RERANK=1`) | `test_rag_rerank.py` |
| **R0.2** | **Contextual chunk prefixes** on upsert | `rag_hybrid.py`, `rag_memory.py` | CPU | `test_rag_memory.py` |
| **R0.3** | **Prediction ledger → RAG** | `prediction_ledger.py`, `rag_memory.py`, `lifespan.py` | CPU embed | `test_prediction_ledger.py` |
| **R0.4** | **NEWS ingest** — GDELT local/global + NewsData | `rag_memory.py` (`ingest_news_sources`) | CPU | `/api/memory/search` |

### R1 — Spatial + adaptive (R1.3 shipped)

| ID | Deliverable | Files | Status |
|----|-------------|-------|--------|
| **R1.1** | **Spatial-RAG** — geohash + bbox pre-filter | `rag_spatial.py`, `rag_memory.py` | ✅ |
| **R1.2** | **CRAG-lite chat** — low score → situations + subgraph | `rag_crag.py`, `routes/chat.py` | ✅ |
| **R1.3** | **Adaptive chunking** per feed type in `ingest/mappings/*.yml` | `rag_chunking.py`, `feed_ingest.py`, YAML mappings | ✅ |
| **R1.4** | **Briefing agentic loop** (max 3 rounds) | `operator_briefing.py` | pending |

### R2 — Optional (operator “go” only)

| ID | Deliverable | Constraint |
|----|-------------|------------|
| **R2.1** | qwen3 relation triplets on doc ingest (LightStash-light) | Only if GLiREL stays off |
| **R2.2** | ColQwen2.5-4B PDF page ingest | Exclusive GPU job; unload chat model |
| **R2.3** | Embedding drift on top of `feed_drift.py` | Extend, do not replace count drift |
| **R2.4** | DSPy briefing prompt compile | After B-03 has resolved samples |
| **R2.5** | Pi degraded keyword index in pull payload | Separate Pi track |

---

## VRAM budget (16 GB)

| Workload | VRAM | Rule |
|----------|------|------|
| `qwen3:8b` chat | ~6 GB | Default |
| `nomic-embed-text` | ~0.5 GB | Short embed calls |
| BGE reranker | **0** (CPU) | Preferred |
| GLiNER ingest | variable | Do not run with ColQwen |
| ColQwen2.5-4B | ~4 GB | `OLLAMA_KEEP_ALIVE=0`, batch only |

---

## Explicit non-goals

- Replacing FtM with Microsoft GraphRAG communities
- Shipping RAGFlow as a second stack
- Multimodal vector RAG before R0 is measured
- Autonomous multi-hour web scraping agents
- New `briefs/*.md` unless operator requests a plan (this file lives in `docs/` as the committed roadmap)

---

## Verification commands

```powershell
# Stack
.\start.ps1
GET http://127.0.0.1:8002/api/health/ping

# RAG (R0 + R1.1/1.2)
cd backend
.\venv\Scripts\python.exe -m unittest test_rag_rerank test_rag_spatial test_rag_crag test_rag_memory test_prediction_ledger -v
GET http://127.0.0.1:8002/api/memory/stats
GET http://127.0.0.1:8002/api/memory/search?q=Thailand+flood&spatial=1

# Pilots
.\scripts\smoke-test.ps1
.\scripts\prediction-ground-truth-pilot.ps1 -Live
.\scripts\fusion-baseline-status.ps1

# GDELT global disk
python -c "import feed_registry; print(feed_registry.read('gdelt_pulse_global'))"
```

---

## Suggested first message to next instance

```text
Read AGENTS.md + docs/RAG_OSINT_ROADMAP.md.
ping → GET /api/memory/stats (rerank + spatial flags).
R0/R1.1/R1.2 shipped — next: R1.3 adaptive chunking or R1.4 briefing loop (operator go).
Parallel: B-03/B-06 pilots. No RAGFlow/LangGraph without explicit go.
```

---

## Changelog

| Date | Note |
|------|------|
| 2026-06-22 | Initial roadmap; NEWS tab + GDELT global warmup |
| 2026-06-22 | R0.1–R0.4 + R1.1/R1.2 shipped; `start.ps1` reload excludes SQLite WAL |
