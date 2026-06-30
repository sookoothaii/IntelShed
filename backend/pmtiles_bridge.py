"""PMTiles offline basemap — multi-file stack + range-aware static serve.

Two access paths:

1. ``GET /api/pmtiles/status`` — manifest, sizes, paths.
2. ``GET /api/pmtiles/file/{name}.pmtiles`` — Range-aware stream so MapLibre's
   ``pmtiles://`` protocol handler can read the archive directly via HTTP byte
   ranges. No external ``pmtiles serve`` process required.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

router = APIRouter(prefix="/api/pmtiles", tags=["pmtiles"])

_DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "pmtiles"
_SERVE = os.getenv("PMTILES_SERVE_URL", "http://127.0.0.1:8088").rstrip("/")
_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
_CHUNK = 1 << 16  # 64 KiB stream chunks


def _list_archives() -> list[dict]:
    d = _DEFAULT_DIR
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*.pmtiles"), key=lambda p: -p.stat().st_size):
        out.append(
            {
                "name": f.stem,
                "path": str(f),
                "size_mb": round(f.stat().st_size / 1_048_576, 1),
                # MapLibre via pmtiles:// protocol, Range-served by FastAPI
                "pmtiles_url": f"/api/pmtiles/file/{f.stem}.pmtiles",
                # Optional ZXY/MVT endpoint when `pmtiles serve` is running
                "tilejson": f"{_SERVE}/{f.stem}.json",
                "tiles": f"{_SERVE}/{f.stem}/{{z}}/{{x}}/{{y}}.mvt",
            }
        )
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


def _safe_pmtiles_path(name: str) -> Path:
    """Resolve a PMTiles archive name safely inside _DEFAULT_DIR.

    Accepts ``planet_z6`` or ``planet_z6.pmtiles``. Rejects anything that
    escapes the directory or points at a non-pmtiles file.
    """
    if not name:
        raise HTTPException(400, "missing archive name")
    cleaned = name.strip().strip("/")
    if "/" in cleaned or "\\" in cleaned or ".." in cleaned:
        raise HTTPException(400, "invalid archive name")
    if not cleaned.lower().endswith(".pmtiles"):
        cleaned = f"{cleaned}.pmtiles"
    target = (_DEFAULT_DIR / cleaned).resolve()
    try:
        target.relative_to(_DEFAULT_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(400, "archive outside data dir") from exc
    if not target.exists() or not target.is_file():
        raise HTTPException(404, f"PMTiles archive not found: {cleaned}")
    return target


def _parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    if not header:
        return None
    match = _RANGE_RE.match(header.strip().lower())
    if not match:
        return None
    start_s, end_s = match.group(1), match.group(2)
    if not start_s and not end_s:
        return None
    if not start_s:
        # suffix length: bytes=-N -> last N bytes
        length = int(end_s)
        start = max(size - length, 0)
        end = size - 1
    else:
        start = int(start_s)
        end = int(end_s) if end_s else size - 1
    end = min(end, size - 1)
    if start > end or start < 0:
        return None
    return start, end


def _iter_file(path: Path, start: int, end: int):
    remaining = end - start + 1
    with path.open("rb") as fp:
        fp.seek(start)
        while remaining > 0:
            chunk = fp.read(min(_CHUNK, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/file/{name}")
def pmtiles_file(name: str, request: Request):
    """Serve a local ``.pmtiles`` archive with HTTP Range support.

    Used by MapLibre's ``pmtiles://`` protocol handler. CORS-friendly via
    the existing FastAPI CORS middleware. Cached aggressively because each
    archive is content-addressable by name + mtime.
    """
    target = _safe_pmtiles_path(name)
    size = target.stat().st_size
    mtime = int(target.stat().st_mtime)
    etag = f'"pmtiles-{name}-{size}-{mtime}"'

    if_none_match = request.headers.get("if-none-match")
    if if_none_match and if_none_match.strip() == etag:
        return Response(status_code=304)

    common_headers = {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Cache-Control": "public, max-age=86400, immutable",
        "Content-Type": "application/vnd.pmtiles",
    }

    rng = _parse_range(request.headers.get("range"), size)
    if rng is None:
        return StreamingResponse(
            _iter_file(target, 0, size - 1),
            status_code=200,
            headers={**common_headers, "Content-Length": str(size)},
        )

    start, end = rng
    length = end - start + 1
    with target.open("rb") as fp:
        fp.seek(start)
        data = fp.read(length)
    return Response(
        content=data,
        status_code=206,
        headers={
            **common_headers,
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(length),
        },
    )


@router.head("/file/{name}")
def pmtiles_file_head(name: str):
    """HEAD probe so MapLibre/PMTiles can discover size before ranging."""
    target = _safe_pmtiles_path(name)
    size = target.stat().st_size
    return Response(
        status_code=200,
        headers={
            "Accept-Ranges": "bytes",
            "Content-Length": str(size),
            "Content-Type": "application/vnd.pmtiles",
            "Cache-Control": "public, max-age=86400, immutable",
        },
    )
