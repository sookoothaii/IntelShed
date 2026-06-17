# Document intel ingest (GLiNER + GLiREL)

Optional **PC-only** pipeline: paste text or upload PDF/EML → zero-shot entity + relation extraction → FollowTheMoney graph in DuckDB. The Raspberry Pi edge node never runs these models; it only consumes finished briefings via `/api/node/pull`.

## UI

1. Open **DATA** → tab **INTEL**.
2. Paste text (or **UPLOAD PDF/EML**) → **INGEST**.
3. The Cytoscape graph loads automatically from the ingest root. Or paste an entity id and **LOAD**.
4. Click a node to re-root the graph (`depth=2` BFS via `/api/entity/{id}/graph`).

## API

| Method | Path | Body |
|--------|------|------|
| GET | `/api/intel/ingest/status` | optional `?load=1` to warm models |
| POST | `/api/intel/ingest/text` | JSON `{ "text", "dataset?", "source_ref?", "threshold?", "relation_threshold?" }` |
| POST | `/api/intel/ingest/document` | `multipart/form-data`: `file`, optional `dataset` |
| GET | `/api/entity/{id}/graph` | query `depth`, `limit` |

OpenAPI: http://127.0.0.1:8002/docs

## Install (Windows dev PC with NVIDIA GPU)

From `backend/` with venv active:

```powershell
pip install "torch>=2.6" --index-url https://download.pytorch.org/whl/cu124
pip install gliner glirel pdfplumber mail-parser loguru
pip install "transformers>=4.51.3,<5" "huggingface_hub<1.0"
```

Notes:

- **torch ≥ 2.6** — `transformers` refuses GLiREL's `.bin` checkpoint on older torch (CVE-2025-32434).
- **transformers &lt; 5, huggingface_hub &lt; 1.0** — GLiREL 1.2.1 breaks on hub 1.x mixin API.
- **loguru** — required by GLiREL but not declared as its dependency.
- Models download from Hugging Face on first ingest (~minutes once).

Backend starts fine **without** these packages; ingest routes return HTTP 503 until installed.

## Env (optional)

See `backend/.env.example`:

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORLDBASE_INTEL_DEVICE` | `auto` | `cuda` / `cpu` / `auto` |
| `WORLDBASE_GLINER_MODEL` | `urchade/gliner_multi-v2.1` | multilingual NER |
| `WORLDBASE_GLIREL_MODEL` | `jackboyla/glirel-large-v0` | zero-shot relations |
| `WORLDBASE_GLINER_THRESHOLD` | `0.45` | entity cutoff |
| `WORLDBASE_GLIREL_THRESHOLD` | `0.50` | relation cutoff (raise to reduce false edges) |
| `WORLDBASE_INTEL_MAX_CHARS` | `60000` | per-request text cap |
| `WORLDBASE_INTEL_CHUNK_CHARS` | `1400` | chunk size for model calls |

## Licenses

| Component | License | Note |
|-----------|---------|------|
| GLiNER multi-v2.1 | Apache-2.0 | OK for OSS/commercial |
| GLiREL | CC BY-NC-SA 4.0 | fine for local operator use; review before commercial product |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `503 model load failed` | Install optional deps above; check `GET /api/intel/ingest/status` |
| Windows access violation on first ingest | Known torch↔pyarrow order bug — fixed in code (pyarrow preloaded before torch) |
| Graph empty after ingest | Check `/api/intel/stats` — `edges` should be &gt; 0; reload graph with returned `root_id` |
| Too many wrong relations | Raise `WORLDBASE_GLIREL_THRESHOLD` (e.g. `0.60`) |

## Verify

```powershell
# status (no model load)
Invoke-RestMethod http://127.0.0.1:8002/api/intel/ingest/status

# quick ingest
$body = @{ text = "Apple Inc. was founded by Steve Jobs in Cupertino." } | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:8002/api/intel/ingest/text -Method Post -Body $body -ContentType application/json
```

Full stack: `.\scripts\smoke-test.ps1` (25 checks).
