# Intelligence layer — FtM graph, ingest, feeds, resolution

WorldBase’s **canonical entity graph** lives in DuckDB (`backend/data/entities.duckdb`, gitignored). The **DATA → INTEL** tab is the operator surface: document ingest, live feed sync, entity resolution, and Cytoscape visualization.

Ranked FtM entities (who/what) also feed the **24h security briefing** via `intel_briefing.py` → LOCAL / REGION / GLOBAL digest buckets. See [`AGENTS.md`](../AGENTS.md) → Briefing pipeline.

The Raspberry Pi **never** runs GLiNER, Splink, or feed ingest — it only pulls finished briefings via `/api/node/pull`.

**License summary:** default OSS install uses **GLiNER (Apache-2.0)** only. **GLiREL (CC BY-NC-SA)** is opt-in. See [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

---

## Architecture (PR 1 → T2 → briefing)

| Layer | Module | What it does |
|-------|--------|--------------|
| **Spine** | `ftm_store.py` | FtM entities / statements / edges on DuckDB; provenance on every fact; fail-soft open on lock |
| **Document ingest** | `intel_ingest.py` | GLiNER (+ optional GLiREL) from text/PDF/EML |
| **Feed ingest (T2)** | `feed_ingest.py` + `ingest/mappings/*.yml` | GDACS, GDELT, EONET, AIS, aircraft anomalies → FtM |
| **Resolution (PR 3)** | `entity_resolution.py` | Deterministic exact + token-subset → `sameAs`; optional Splink fuzzy stage |
| **Briefing bridge** | `intel_briefing.py` | Rank geolocated FtM entities into operator digest + LLM prompt |
| **UI** | `IntelGraphPanel.tsx` | Cytoscape graph, schema-filtered overview, feed sync + resolve |

---

## Entity resolution (three stages)

| Stage | Method | Default | Notes |
|-------|--------|---------|-------|
| 1 Exact | `exact:name_country`, `exact:imo`, … | on | High confidence (0.98) |
| 2 Subset | `subset:token` | on | Contiguous partial names (e.g. `Erdogan` ↔ `Recep Tayyip Erdogan`); rejects generic tokens |
| 3 Splink | `splink` | **off** | `WORLDBASE_ENTITY_RESOLUTION_SPLINK=1`; fuzzy full-name — use only when calibrated |

Run manually: **RESOLVE** in UI or `POST /api/intel/resolution/run`. Optional auto-run after feed sync: `WORLDBASE_ENTITY_RESOLUTION_AFTER_FEEDS=1`.

Inspect sameAs provenance via `GET /api/entity/{id}` (full JSON includes edge `properties.method` and per-entity `datasets`). Operational script: `scripts/_inspect_subset_edges_http.py` (HTTP-only, no DuckDB lock).

---

## UI — DATA → INTEL

| Control | Action |
|---------|--------|
| **INGEST** | Paste text or upload PDF/EML → entities + `mentions` (+ GLiREL relations if enabled) |
| **SYNC FEEDS** | Pull live feeds into FtM, then **auto-load overview graph** |
| **Schema pills** | Filter **OVERVIEW** by FtM schema (default: Event, Vessel, Person, Organization — excludes Airplane) |
| **OVERVIEW** | Show up to ~120 recent feed/ingest entities (`schemas`, `datasets` query params) |
| **LOAD** | BFS graph from entity id in the input field |
| **RESOLVE** | Run entity resolution → `sameAs` edges (exact + subset; Splink if enabled) |
| **Click node** | Re-root BFS graph on that entity; globe focus when lat/lon present |

**Graph modes**

- **Overview** — many nodes, often **0 edges** (feed entities are mostly isolated until INGEST or RESOLVE links them).
- **Ingest graph** — purple Document hub + `mentions` fan + semantic relations (GLiREL opt-in).
- **Detail BFS** — expand from any node; `sameAs` edges colored by confidence (hover for provenance).

Status line shows GPU, GLiREL mode, Splink version, and FtM entity/edge counts.

---

## API reference

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/health` | Includes `ftm.ready`, `ftm.entities`, `ftm.error` |
| GET | `/api/intel/stats` | Entity/statement/edge roll-up |
| GET | `/api/intel/entities` | Recent entities list (`limit`, `dataset`) |
| GET | `/api/intel/graph/stats` | Stats + graph counters + endpoint hints (compat alias) |
| GET | `/api/intel/graph/overview` | Feed overview (`limit`, `datasets`, `schemas`) |
| GET | `/api/entity/{id}` | Full FtM JSON + edges with `properties` (use for resolution provenance) |
| GET | `/api/entity/{id}/graph` | BFS subgraph (`depth`, `limit`) — edges omit `properties` |
| GET | `/api/intel/ingest/status` | GLiNER/GLiREL; `?load=1` warms models |
| POST | `/api/intel/ingest/text` | Document text ingest |
| POST | `/api/intel/ingest/document` | PDF / EML / TXT upload |
| GET | `/api/intel/feeds/status` | Feed autopilot, `resolve_after_feeds`, last run |
| POST | `/api/intel/feeds/run` | Sync feeds; runs resolution when `WORLDBASE_ENTITY_RESOLUTION_AFTER_FEEDS=1` |
| GET | `/api/intel/resolution/status` | `splink_enabled`, `resolution_edges`, `last_run` |
| POST | `/api/intel/resolution/run` | Entity resolution batch |
| GET | `/api/briefing` | Latest briefing text + `digest` + `intel` + `fusion_hotspots` |

Feed sources (T2): `gdacs`, `gdelt_geo`, `gdelt_pulse`, `eonet`, `maritime`, `anomalies`.

YAML mappings: `backend/ingest/mappings/` — `gdelt_events`, `gdacs_alerts`, `eonet_events`, `ais_vessels`, plus **`osint_pins`** (mapping exists; **not yet wired** in `FEED_SOURCES` — needs browser→API pin push).

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

### Optional: Splink (library required for status; fuzzy stage opt-in)

```powershell
pip install "splink>=4.0,<5"
```

Deterministic resolution (exact + subset) runs without Splink installed.

### Feed ingest

No extra packages beyond `PyYAML` (already pulled by dependencies). Runs automatically when `WORLDBASE_FEED_INGEST_AUTOPILOT=1` (default) every 600 s in the phase-1 background loop.

---

## Env (intel-related)

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORLDBASE_BRIEFING_INTEL` | `1` | FtM entities in 24h digest |
| `WORLDBASE_BRIEFING_INTEL_EXCLUDE_SCHEMAS` | `Airplane,Thing` | Noise schemas excluded from briefing |
| `WORLDBASE_BRIEFING_INTEL_PER_BUCKET` | `4` | Max FtM lines per LOCAL/REGION/GLOBAL |
| `WORLDBASE_INTEL_GLIREL` | `0` | `1` = GLiREL (NC license) |
| `WORLDBASE_INTEL_DEVICE` | `auto` | `cuda` / `cpu` / `auto` |
| `WORLDBASE_GLINER_THRESHOLD` | `0.45` | NER cutoff |
| `WORLDBASE_GLIREL_THRESHOLD` | `0.50` | Relation cutoff |
| `WORLDBASE_FEED_INGEST_AUTOPILOT` | `1` | Background feed → FtM sync |
| `WORLDBASE_FEED_INGEST_INTERVAL` | `600` | Seconds between syncs |
| `WORLDBASE_ENTITY_RESOLUTION_AUTOPILOT` | `0` | Nightly resolution run |
| `WORLDBASE_ENTITY_RESOLUTION_AFTER_FEEDS` | `0` | `1` = RESOLVE after each feed sync |
| `WORLDBASE_ENTITY_RESOLUTION_SPLINK` | `0` | `1` = enable fuzzy Splink stage |
| `WORLDBASE_ENTITY_RESOLUTION_THRESHOLD` | `0.85` | Splink match cutoff (when enabled) |
| `WORLDBASE_OPERATOR_REGION` | `thailand` | GDELT local feed bbox + briefing buckets |

See `backend/.env.example` for full list.

---

## Tests (no network)

```powershell
cd backend
python -m unittest test_ftm_store test_entity_resolution test_feed_ingest test_intel_briefing test_operator_briefing -v
```

Stack: `.\scripts\smoke-test.ps1` (25 checks).

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| SYNC FEEDS OK but empty graph | Hard-refresh UI; click **OVERVIEW** or re-run **SYNC FEEDS** |
| Overview flooded with aircraft | Use schema pills; default excludes Airplane |
| Overview shows dots, no lines | Expected for feeds alone — use **INGEST** or **RESOLVE** for edges |
| `503 model load failed` | Install GLiNER stack; check `/api/intel/ingest/status` |
| No semantic edges | Set `WORLDBASE_INTEL_GLIREL=1` locally + `pip install glirel loguru` |
| RESOLVE button disabled | `pip install "splink>=4.0,<5"` (library needed for status UI) |
| API startup / DuckDB lock | Only one process may hold `entities.duckdb`; kill stale Python; API starts fail-soft — `ftm.ready: false` until restart |
| Briefing has no FtM names | `POST /api/briefing/generate`; check `GET /api/briefing` → `intel.count` |
| EONET errors in feed sync | Fail-soft; other sources still ingest |
| Windows torch crash on GLiNER import | Fixed in code (pyarrow pre-import); torch ≥ 2.6 for GLiREL `.bin` |
