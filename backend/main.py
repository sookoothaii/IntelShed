"""WorldBase API — FastAPI backend, SQLite cache, no Docker."""

from __future__ import annotations

import os

import mcp_server
from bootstrap_env import load_env, log_security_startup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from lifespan import register_lifecycle
from middleware.rate_limit import setup_rate_limiting
from middleware.security_headers import SecurityHeadersMiddleware
from routes.registry import register_routers

load_env()
log_security_startup()

app = FastAPI(title="WorldBase API", version="0.1.0", redirect_slashes=False)

# I8: GZip compression for Pi pull payload (delta sync + bandwidth savings)
app.add_middleware(GZipMiddleware, minimum_size=500)

_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5176",
    "http://127.0.0.1:5176",
    "https://localhost",
    "https://127.0.0.1",
]
_extra_origins = os.getenv("WORLDBASE_CORS_ORIGINS", "")
if _extra_origins:
    _CORS_ORIGINS.extend(o.strip() for o in _extra_origins.split(",") if o.strip())

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-API-Key",
        "X-Node-Token",
        "X-Request-Timestamp",
        "X-Request-Nonce",
    ],
)
app.add_middleware(SecurityHeadersMiddleware)
setup_rate_limiting(app)

# I4: OpenTelemetry tracing (opt-in via OTEL_EXPORTER_OTLP_ENDPOINT + WORLDBASE_OTEL=1)
try:
    import telemetry_otel

    if telemetry_otel.setup_otel(app):
        print("[OTEL] tracing enabled", flush=True)
except Exception:
    pass


# I4: Health check latency histogram middleware
@app.middleware("http")
async def health_check_timing(request, call_next):
    import time as _time

    start = _time.perf_counter()
    response = await call_next(request)
    if request.url.path in ("/api/health", "/api/health/ping"):
        try:
            import metrics as _metrics

            _metrics.record_health_check_duration(_time.perf_counter() - start)
        except Exception:
            pass
    return response


register_routers(app)
mcp_server.mount_worldbase_mcp(app)

for r in app.routes:
    if hasattr(r, "redirect_slashes"):
        r.redirect_slashes = False

register_lifecycle(app)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_excludes=[
            "worldbase.db",
            "worldbase.db-wal",
            "worldbase.db-shm",
            "data/entities.duckdb",
            "data/entities.duckdb.wal",
            "data/ais_trajectory.db",
            "data/ais_trajectory.db-wal",
            "data/ais_trajectory.db-shm",
            "data/intel_subgraph_latest.json",
        ],
    )
