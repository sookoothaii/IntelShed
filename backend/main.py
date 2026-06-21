"""WorldBase API — FastAPI backend, SQLite cache, no Docker."""

from __future__ import annotations

import os

import mcp_server
from bootstrap_env import load_env, log_security_startup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from lifespan import register_lifecycle
from middleware.rate_limit import setup_rate_limiting
from middleware.security_headers import SecurityHeadersMiddleware
from routes.registry import register_routers

load_env()
log_security_startup()

app = FastAPI(title="WorldBase API", version="0.1.0", redirect_slashes=False)

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
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
setup_rate_limiting(app)

register_routers(app)
mcp_server.mount_worldbase_mcp(app)

for r in app.routes:
    if hasattr(r, "redirect_slashes"):
        r.redirect_slashes = False

register_lifecycle(app)

# Compat re-exports for globe_snapshot, mcp_server, fusion_heatmap.
from routes.core_feeds import (  # noqa: E402
    get_earthquakes,
    get_events,
    get_iss,
    get_satellites,
    get_world,
)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
