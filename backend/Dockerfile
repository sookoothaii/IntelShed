# WorldBase backend — multi-stage build (build deps → slim runtime, non-root)
#
# Builder: create venv, install build tools + pip install
# Runtime: copy venv, install only runtime libs (libicu76, curl for healthcheck)

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

# Create venv so pip can see already-installed packages across RUN layers
RUN python -m venv /venv
ENV PATH="/venv/bin:${PATH}"

COPY requirements.txt ./
RUN pip install -r requirements.txt

# Torch CPU-only (must be installed before optional deps that depend on torch)
RUN pip install \
    "torch>=2.6" \
    --index-url https://download.pytorch.org/whl/cpu

# Optional dependencies (lazy-imported by backend but needed for full stack):
# splink (entity resolution), gliner+transformers (NER),
# pdfplumber (PDF extract), onnxruntime+optimum+sentence-transformers (RAG reranker),
# pyarrow (Splink/arrow), loguru (glirel), piper-tts (TTS bridge).
# torch CPU is already in venv — gliner/sentence-transformers/piper-tts will reuse it.
RUN pip install \
    "splink>=4.0,<5" \
    "gliner>=0.2.27" \
    "transformers>=4.51.3,<5" \
    "huggingface_hub<1.0" \
    "pdfplumber>=0.11" \
    "onnxruntime>=1.16" \
    "optimum>=2.0" \
    "sentence-transformers>=3.0" \
    "pyarrow>=15.0" \
    "loguru>=0.7" \
    "piper-tts>=1.3.0"

# --- Stage 2: runtime ---
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    WORLDBASE_DB_PATH=/data/worldbase.db \
    PYTHONPATH=/app \
    PATH="/venv/bin:${PATH}"

WORKDIR /app

# curl: healthcheck; libicu76: runtime for pyicu/followthemoney (Debian Trixie)
# libgomp1: OpenMP runtime for torch/onnxruntime in CPU mode
# espeak-ng: phonemization for piper-tts
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libicu76 libgomp1 espeak-ng \
    && rm -rf /var/lib/apt/lists/*

# Copy venv from builder (includes all installed packages)
COPY --from=builder /venv /venv

# Copy application source
COPY . .

# Create user, download Piper voice model, and set ownership in one layer
RUN useradd --create-home --uid 10001 worldbase \
    && mkdir -p /data /app/models/tts \
    && python -m piper.download_voices --data-dir /app/models/tts en_US-lessac-medium \
    && chown -R worldbase:worldbase /app /data

USER worldbase

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=15s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8002/api/health/ping || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
