# WorldBase backend — multi-stage build (build deps → slim runtime, non-root)
#
# Builder: install build tools (libicu-dev, pkg-config, gcc) + pip install
# Runtime: copy site-packages, install only runtime libs (libicu72, curl for healthcheck)

# --- Stage 1: builder ---
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libicu-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --target=/install -r requirements.txt

# Optional dependencies (lazy-imported by backend but needed for full stack):
# splink (entity resolution), gliner+transformers (NER),
# pdfplumber (PDF extract), onnxruntime+optimum+sentence-transformers (RAG reranker),
# pyarrow (Splink/arrow), loguru (glirel).
RUN pip install --target=/install \
    "splink>=4.0,<5" \
    "gliner>=0.2.27" \
    "transformers>=4.51.3,<5" \
    "huggingface_hub<1.0" \
    "pdfplumber>=0.11" \
    "onnxruntime>=1.16" \
    "optimum>=2.0" \
    "sentence-transformers>=3.0" \
    "pyarrow>=15.0" \
    "loguru>=0.7"

# Torch CPU-only (separate index to avoid overriding PyPI for other packages)
RUN pip install --target=/install \
    "torch>=2.6" \
    --index-url https://download.pytorch.org/whl/cpu

# --- Stage 2: runtime ---
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WORLDBASE_DB_PATH=/data/worldbase.db \
    PYTHONPATH=/app:/install

WORKDIR /app

# curl: healthcheck; libicu76: runtime for pyicu/followthemoney (Debian Trixie)
# libgomp1: OpenMP runtime for torch/onnxruntime in CPU mode
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libicu76 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /install

# Copy application source
COPY . .

# Persistent SQLite lives in /data (named volume); run unprivileged
RUN useradd --create-home --uid 10001 worldbase \
    && mkdir -p /data \
    && chown -R worldbase:worldbase /app /data
USER worldbase

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8002/api/health/ping || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
