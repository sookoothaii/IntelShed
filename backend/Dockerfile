# WorldBase backend — FastAPI + SQLite (no system services, runs as non-root)
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    WORLDBASE_DB_PATH=/data/worldbase.db

WORKDIR /app

# curl is used by the container healthcheck
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

# Persistent SQLite lives in /data (named volume); run unprivileged
RUN useradd --create-home --uid 10001 worldbase \
    && mkdir -p /data \
    && chown -R worldbase:worldbase /app /data
USER worldbase

EXPOSE 8002

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8002/api/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
