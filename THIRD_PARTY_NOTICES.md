# Third-party notices (optional components)

intelshed core is released under the **MIT License** (see README). Some **optional** features pull in separate Python packages and ML models that are **not** bundled in this repository. You install them yourself into your local virtualenv.

## Default intel ingest (OSS-safe)

When you install the optional intel stack **without** GLiREL, ingest uses:

| Component | Role | License |
|-----------|------|---------|
| [GLiNER](https://github.com/urchade/GLiNER) `urchade/gliner_multi-v2.1` | zero-shot entity extraction | **Apache-2.0** |
| [PyTorch](https://pytorch.org/) | GPU/CPU runtime | BSD-style (see PyTorch license) |
| `pdfplumber`, `mail-parser` | document text extraction | MIT / compatible |

This mode writes **entities** and **mentions** edges (document → entity). It does **not** import GLiREL.

## Optional semantic relations (NOT enabled by default)

| Component | Role | License |
|-----------|------|---------|
| [GLiREL](https://github.com/jackboyla/GLiREL) `jackboyla/glirel-large-v0` | zero-shot relation extraction | **CC BY-NC-SA 4.0** |

**Why it is off by default:** CC BY-NC-SA is *non-commercial* and *share-alike*. That is a poor fit for a general-purpose MIT project on GitHub where others may fork, ship binaries, or use the stack commercially—even if WorldBase itself stays MIT.

**If you are a private operator** (personal / non-commercial use) and accept the GLiREL license, opt in locally:

```env
# backend/.env — never commit secrets; this flag is your choice
WORLDBASE_INTEL_GLIREL=1
```

Then install GLiREL separately:

```powershell
pip install glirel loguru
pip install "transformers>=4.51.3,<5" "huggingface_hub<1.0"
```

WorldBase does **not** redistribute GLiREL weights or code. Downloading the model from Hugging Face is between you and the model license.

## Other optional data sources

OpenSanctions CSV, STAC imagery, external feeds, etc. have their own terms—see feed-specific docs in `LLM_HANDOFF.md` and source URLs in the API responses.

## AI models — stepfun-ai / step-3.7-flash

WorldBase's chat and entity-analysis pipeline is powered in part by **[stepfun-ai/step-3.7-flash](https://github.com/stepfun-ai)**, a ~37B-parameter reasoning model available **free of charge** via the [NVIDIA NIM API](https://build.nvidia.com/).

We are grateful to the stepfun-ai team for:
- Making step-3.7-flash freely accessible through NVIDIA's hosted inference — no local GPU required for high-quality reasoning.
- Excellent instruction-following and tool-use capabilities, which made it straightforward to integrate as a sixth chat provider in WorldBase.
- Fast response times (~6–8 s for globe geocoding, 30–90 s for full context-grounded analysis with CTX/🔍/TOOLS enabled).
- The flexibility to work within a strict anti-hallucination protocol — when given a positive "RAW DATA INTERPRETER" role with explicit context-block listing, the model reliably grounds its output in provided data and flags data gaps honestly.

This model has been instrumental in building WorldBase's intelligence workstation workflow, and we sincerely thank stepfun-ai for their contribution to the open AI ecosystem.

## Standing on the shoulders of giants

WorldBase is not a standalone invention. It is glue, configuration, and operator workflow on top of decades of open-source and open-data labour. We are deeply humbled by that fact and **profoundly grateful** to everyone who wrote the code, published the datasets, and answered questions in issue trackers so strangers could build on their work.

**To the giants whose shoulders we stand on: thank you.**

### Lineage & UX inspiration

| Project / person | Why we are grateful |
|------------------|---------------------|
| **[Bilawal Sidhu](https://www.youtube.com/watch?v=rXvU7bPJ8n4)** · *WorldView* | The original spark — tactical globe UX, vision modes, and multi-feed fusion on Cesium. |
| **[K-AI-STACK/WorldView](https://github.com/K-AI-STACK/WorldView)** | Open layer catalog and Cesium-first OSINT dashboard structure. |
| **[kevtoe/worldview](https://github.com/kevtoe/worldview)** | Full-stack proxy pattern, tactical UI tokens, Resium + Vite references. |
| **[petieclark/worldview](https://github.com/petieclark/worldview)** | Backend key proxying, health endpoints, Docker deployment patterns. |
| **[Reconurge/Flowsint](https://github.com/reconurge/flowsint)** | OSINT graph visualization — threat intel made approachable. |

### Core stack (we would not run without these)

| Project | Role in WorldBase |
|---------|-------------------|
| **[CesiumJS](https://cesium.com/)** & **[MapLibre](https://maplibre.org/)** | 3D/2D globe and offline map rendering. |
| **[React](https://react.dev/)** & **[Vite](https://vite.dev/)** | HUD, panels, dev server. |
| **[FastAPI](https://fastapi.tiangolo.com/)**, **[Pydantic](https://docs.pydantic.dev/)**, **[Uvicorn](https://www.uvicorn.org/)** | API, validation, async server. |
| **[SQLite](https://sqlite.org/)** & **[sqlite-vec](https://github.com/asg017/sqlite-vec)** | Local cache, briefing store, hybrid vector + FTS RAG — no cloud lock-in. |
| **[DuckDB](https://duckdb.org/)** | FtM entity graph storage when intel ingest is enabled. |
| **[Ollama](https://ollama.com/)** & **[Qwen](https://qwenlm.github.io/)** | Local LLM chat and briefing generation on operator hardware. |
| **[NVIDIA NIM](https://build.nvidia.com/)** & **[stepfun-ai](https://github.com/stepfun-ai)** | Cloud reasoning models (step-3.7-flash) via free NIM API — no local GPU required. |
| **[FollowTheMoney](https://followthemoney.tech/)** / **[aleph](https://github.com/alephdata/aleph)** ecosystem | Entity schema and graph patterns for OSINT ingest. |
| **[sentence-transformers](https://www.sbert.net/)** & **[BAAI/bge-reranker](https://huggingface.co/BAAI/bge-reranker-base)** | Optional CPU reranker after RRF (Track R0). |
| **[GLiNER](https://github.com/urchade/GLiNER)** (optional) | Zero-shot entity extraction for document intel — Apache-2.0. |

### Open data & civic APIs

We do not own the feeds. We fetch, cache, and fuse what others maintain — often on volunteer or public budget:

**USGS**, **NASA** (EONET, FIRMS, GIBS), **NOAA SWPC**, **GDACS**, **GDELT Project**, **SMARD**, **IODA**, **Open-Meteo**, **CAMS**, **HDX / UN OCHA**, **CelesTrak**, **adsb.lol / adsb.fi**, **Element84 STAC**, **Pegelonline**, **OpenSanctions**, **ReliefWeb**, and every engineer keeping civic endpoints alive. **You are the lifeblood of situational awareness.**

### Matching & compliance

| Project | Role |
|---------|------|
| **[OpenSanctions](https://www.opensanctions.org/)** & **[Yente](https://github.com/opensanctions/yente)** | Public CC-BY datasets and entity matching — transparency work we do not take for granted. |

### Maps & tiles

| Project | Role |
|---------|------|
| **[Protomaps](https://protomaps.com/)** / **PMTiles** | Offline regional and planet-scale basemaps. |

If we missed a dependency you rely on, please open an issue — attribution should be complete and honest.

## Disclaimer

This file is engineering guidance, not legal advice. If you ship a product built on WorldBase, review licenses for every optional dependency you enable.
