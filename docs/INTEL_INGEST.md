# Document intel ingest (GLiNER; optional GLiREL)

Optional **PC-only** pipeline: paste text or upload PDF/EML → zero-shot entity extraction → FollowTheMoney graph in DuckDB. The Raspberry Pi never runs these models.

**License summary:** default install uses **GLiNER (Apache-2.0)** only — entities + `mentions` edges. **GLiREL (CC BY-NC-SA)** is **off by default** so the MIT repo stays safe on GitHub. See [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

## UI

1. Open **DATA** → tab **INTEL**.
2. Paste text (or **UPLOAD PDF/EML**) → **INGEST**.
3. Graph loads from the ingest root, or paste an entity id → **LOAD**.

Status pill shows GPU + `relations_mode` (`disabled` = entities only, `glirel` = semantic edges enabled).

## API

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/intel/ingest/status` | `relations_mode`, `glirel_enabled`; `?load=1` warms GLiNER |
| POST | `/api/intel/ingest/text` | JSON body with `text` |
| POST | `/api/intel/ingest/document` | PDF / EML / TXT upload |
| GET | `/api/entity/{id}/graph` | Cytoscape BFS view |

## Install (OSS-safe default)

From `backend/` with venv active:

```powershell
pip install "torch>=2.6" --index-url https://download.pytorch.org/whl/cu124
pip install gliner pdfplumber mail-parser
pip install "transformers>=4.51.3,<5" "huggingface_hub<1.0"
```

Ingest works after this — **entities + mentions**, no semantic relation labels.

## Optional: GLiREL relations (personal / non-commercial opt-in)

Only if you accept [GLiREL's CC BY-NC-SA license](https://github.com/jackboyla/GLiREL):

```env
# backend/.env (local only — do not commit if it contains secrets)
WORLDBASE_INTEL_GLIREL=1
```

```powershell
pip install glirel loguru
```

Restart backend. Status should show `relations_mode: "glirel"`.

## Env

| Variable | Default | Purpose |
|----------|---------|---------|
| `WORLDBASE_INTEL_GLIREL` | `0` | `1` = opt into GLiREL (NC license) |
| `WORLDBASE_INTEL_DEVICE` | `auto` | `cuda` / `cpu` / `auto` |
| `WORLDBASE_GLINER_MODEL` | `urchade/gliner_multi-v2.1` | NER model |
| `WORLDBASE_GLIREL_MODEL` | `jackboyla/glirel-large-v0` | RE model (only if GLiREL enabled) |
| `WORLDBASE_GLINER_THRESHOLD` | `0.45` | entity cutoff |
| `WORLDBASE_GLIREL_THRESHOLD` | `0.50` | relation cutoff |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `503 model load failed` | Install GLiNER stack; check `/api/intel/ingest/status` |
| Ingest OK but no semantic edges | Expected when `relations_mode: disabled` — set `WORLDBASE_INTEL_GLIREL=1` locally |
| `relations_mode: unavailable` | GLiREL enabled but package missing — `pip install glirel loguru` |
| Too many wrong relations | Raise `WORLDBASE_GLIREL_THRESHOLD` (e.g. `0.60`) |

Full stack: `.\scripts\smoke-test.ps1` (25 checks).
