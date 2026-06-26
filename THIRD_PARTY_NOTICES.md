# Third-party notices (optional components)

WorldBase core is released under the **MIT License** (see README). Some **optional** features pull in separate Python packages and ML models that are **not** bundled in this repository. You install them yourself into your local virtualenv.

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

## Disclaimer

This file is engineering guidance, not legal advice. If you ship a product built on WorldBase, review licenses for every optional dependency you enable.
