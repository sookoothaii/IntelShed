# Intelligence layer — FtM graph, ingest, feeds, resolution

WorldBase’s **canonical entity graph** lives in DuckDB (`backend/data/entities.duckdb`, gitignored). The **DATA → INTEL** tab is the operator surface: document ingest, live feed sync, entity resolution, and Cytoscape visualization.

The Raspberry Pi **never** runs GLiNER, Splink, or feed ingest — it only pulls finished briefings via `/api/node/pull`.

**License summary:** default OSS install uses **GLiNER (Apache-2.0)** only. **GLiREL (CC BY-NC-SA)** is opt-in. See [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

---

## Architecture (PR 1 → T2)

| Layer | Module | What it does |
|-------|--------|--------------|
| **Spine** | `ftm_store.py` | FtM entities / statements / edges on DuckDB; provenance on every fact |
| **Document ingest** | `intel_ingest.py` | GLiNER (+ optional GLiREL) from text/PDF/EML |
| **Feed ingest (T2)** | `feed_ingest.py` + `ingest/mappings/*.yml` | GDACS, GDELT, EONET, AIS, aircraft anomalies → FtM |
| **Resolution (PR 3)** | `entity_resolution.py` | Splink + exact keys → `sameAs` edges with confidence |
| **UI** | `IntelGraphPanel.tsx` | Cytoscape graph against `/api/entity/{id}/graph` and overview |

---

## UI — DATA → INTEL

| Control | Action |
|---------|--------|
| **INGEST** | Paste text or upload PDF/EML → entities + `mentions` (+ GLiREL relations if enabled) |
| **SYNC FEEDS** | Pull live feeds into FtM, then **auto-load overview graph** |
| **OVERVIEW** | Show up to ~120 recent feed/ingest entities (no root id required) |
| **LOAD** | BFS graph from entity id in the input field |
| **RESOLVE** | Run Splink entity resolution → `sameAs` edges |
| **Click node** | Re-root BFS graph on that entity |

**Graph modes**

- **Overview** — many nodes, often **0 edges** (feed entities are mostly isolated until INGEST or RESOLVE links them).
- **Ingest graph** — purple Document hub + `mentions` fan + semantic relations (GLiREL opt-in).
- **Detail BFS** — expand from any node; `sameAs` edges colored by confidence (hover for provenance).

Status line shows GPU, GLiREL mode, Splink version, and FtM entity/edge counts.

---

## API reference

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/intel/stats` | Entity/statement/edge roll-up |
| GET | `/api/intel/graph/overview` | Recent entities for feed overview (`limit`, `datasets`, `schemas`) |
| GET | `/api/entity/{id}/graph` | BFS subgraph (`depth`, `limit`) |
| GET | `/api/entity/{id}` | Full FtM JSON |
| GET | `/api/intel/ingest/status` | GLiNER/GLiREL; `?load=1` warms models |
| POST | `/api/intel/ingest/text` | Document text ingest |
| POST | `/api/intel/ingest/document` | PDF / EML / TXT upload |
| GET | `/api/intel/feeds/status` | Feed ingest autopilot + last run |
| POST | `/api/intel/feeds/run` | Sync GDACS, GDELT, EONET, AIS, anomalies |
| GET | `/api/intel/resolution/status` | Splink availability + `sameAs` count |
| POST | `/api/intel/resolution/run` | Entity resolution batch |

Feed sources (T2): `gdacs`, `gdelt_geo`, `gdelt_pulse`, `eonet`, `maritime`, `anomalies`.

YAML mappings: `backend/ingest/mappings/` (`gdelt_events`, `gdacs_alerts`, `eonet_events`, `ais_vessels`, `osint_pins`).

---

## Install

### OSS-safe default (entities + mentions only)

From `backend/` with venv active:

```powershell
pip install "torch>=2.6" --index-url https://download.pytorch.org/whl/cu124
pip install gliner pdfplumber mail-parser
pip install "transformers>=4.51.3,<5" "huggingface_hub<1.0"
```

### Optional: GLiREL relations (personal / NC opt-in)

```env
# backend/.env (local — do not commit secrets)
WORLDBASE_INTEL_GLIREL=1
```

```powershell
pip install glirel loguru
```

### Optional: Splink entity resolution

```powershell
pip install "splink>=4.0,<5"
```

### Feed ingest

No extra packages beyond `PyYAML` (already pulled by dependencies). Runs automatically when `WORLDBASE_FEED_INGEST_AUTOPILOT=1` (default) every 600 s in the phase-1 background loop.

---

## Env (intel-related)

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORLDBASE_INTEL_GLIREL` | `0` | `1` = GLiREL (NC license) |
| `WORLDBASE_INTEL_DEVICE` | `auto` | `cuda` / `cpu` / `auto` |
| `WORLDBASE_GLINER_THRESHOLD` | `0.45` | NER cutoff |
| `WORLDBASE_GLIREL_THRESHOLD` | `0.50` | Relation cutoff |
| `WORLDBASE_FEED_INGEST_AUTOPILOT` | `1` | Background feed → FtM sync |
| `WORLDBASE_FEED_INGEST_INTERVAL` | `600` | Seconds between syncs |
| `WORLDBASE_ENTITY_RESOLUTION_AUTOPILOT` | `0` | Nightly Splink run |
| `WORLDBASE_ENTITY_RESOLUTION_THRESHOLD` | `0.85` | Splink match cutoff |
| `WORLDBASE_OPERATOR_REGION` | `thailand` | GDELT local feed bbox |

See `backend/.env.example` for full list.

---

## Tests (no network)

```powershell
cd backend
python -m unittest test_ftm_store test_entity_resolution test_feed_ingest -v
```

Stack: `.\scripts\smoke-test.ps1` (25 checks).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| SYNC FEEDS OK but empty graph | Hard-refresh UI; click **OVERVIEW** or re-run **SYNC FEEDS** (overview loads automatically after fix) |
| Overview shows dots, no lines | Expected for feeds alone — use **INGEST** or **RESOLVE** for edges |
| `503 model load failed` | Install GLiNER stack; check `/api/intel/ingest/status` |
| No semantic edges | Set `WORLDBASE_INTEL_GLIREL=1` locally + `pip install glirel loguru` |
| RESOLVE disabled | `pip install "splink>=4.0,<5"` |
| EONET errors in feed sync | Fail-soft; other sources still ingest |
| Windows torch crash on GLiNER import | Fixed in code (pyarrow pre-import); torch ≥ 2.6 for GLiREL `.bin` |
