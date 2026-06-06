"""PMTiles offline basemap — multi-file stack + local tile server."""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(prefix="/api/pmtiles", tags=["pmtiles"])

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "pmtiles"
_SERVE = os.getenv("PMTILES_SERVE_URL", "http://127.0.0.1:8088").rstrip("/")


def _list_archives() -> list[dict]:
    d = _DEFAULT_DIR
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.pmtiles"), key=lambda p: -p.stat().st_size):
        out.append({
            "name": f.stem,
            "path": str(f),
            "size_mb": round(f.stat().st_size / 1_048_576, 1),
            "tilejson": f"{_SERVE}/{f.stem}.json",
            "tiles": f"{_SERVE}/{f.stem}/{{z}}/{{x}}/{{y}}.mvt",
        })
    return out


def _resolve_primary() -> Path | None:
    raw = os.getenv("PMTILES_PATH", "").strip()
    if raw:
        p = Path(raw)
        if p.exists():
            return p
    archives = _list_archives()
    if not archives:
        return None
    # Prefer largest useful archive (thailand > planet_z10 > planet_z6)
    for prefer in ("planet_full", "planet_z10", "thailand", "asean", "planet_z6"):
        for a in archives:
            if a["name"] == prefer:
                return Path(a["path"])
    return Path(archives[0]["path"])


@router.get("/status")
def pmtiles_status():
    """Local PMTiles stack — global + regional archives, MapLibre via pmtiles serve."""
    p = _resolve_primary()
    archives = _list_archives()
    manifest = None
    mf = _DEFAULT_DIR / "manifest.json"
    if mf.exists():
        try:
            manifest = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "available": bool(archives),
        "primary": str(p) if p else None,
        "primary_size_mb": round(p.stat().st_size / 1_048_576, 1) if p else None,
        "archives": archives,
        "count": len(archives),
        "serve_url": _SERVE,
        "serve_script": "scripts/start-pmtiles-serve.ps1",
        "download_script": "scripts/download-pmtiles.ps1",
        "recommended": {
            "thailand_resident": "stack (planet_z6 + thailand)",
            "global_medium": "world-z10 (~1 GB)",
            "global_full": "world-full (~130 GB, -Force)",
        },
        "manifest": manifest,
        "docs": "https://docs.protomaps.com/pmtiles/",
    }
