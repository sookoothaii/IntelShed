"""Blitzortung.org — Real-time lightning strike data.

Public GeoJSON endpoint was retired (404). Use operator credentials:
  BLITZORTUNG_USER / BLITZORTUNG_PASSWORD in .env
Get access via https://www.blitzortung.org/ (active station operator).
"""

import json
import os
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["lightning"])

_BLITZ_CACHE = {}
_BLITZ_TTL = 60  # 1 minute — lightning is very dynamic

BLITZ_USER = os.getenv("BLITZORTUNG_USER", "").strip()
BLITZ_PASS = os.getenv("BLITZORTUNG_PASSWORD", "").strip()


def _parse_strike_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        row = json.loads(line)
    except json.JSONDecodeError:
        return None
    lat = row.get("lat")
    lon = row.get("lon")
    if lat is None or lon is None:
        return None
    ts_ns = row.get("time") or 0
    try:
        ts_ms = int(ts_ns) / 1_000_000
        iso = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        iso = None
    sig = row.get("sig") or []
    return {
        "lon": float(lon),
        "lat": float(lat),
        "time": iso,
        "deviation": row.get("mds"),
        "status": row.get("status"),
        "stations": len(sig),
        "participants": len(sig),
    }


@router.get("/lightning")
async def get_lightning():
    """Recent lightning strikes. Cached 1 minute."""
    now = datetime.now(timezone.utc).timestamp()
    cached = _BLITZ_CACHE.get("strikes")
    if cached and (now - cached["ts"]) < _BLITZ_TTL:
        return cached["data"]

    if not BLITZ_USER or not BLITZ_PASS:
        return {
            "count": 0,
            "updated": datetime.now(timezone.utc).isoformat(),
            "strikes": [],
            "error": "Blitzortung credentials missing",
            "hint": "Set BLITZORTUNG_USER and BLITZORTUNG_PASSWORD in .env (station operator account)",
        }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(
                "https://data.blitzortung.org/Data/Protected/last_strikes.php",
                auth=(BLITZ_USER, BLITZ_PASS),
                params={"number": 800},
                headers={"User-Agent": "WorldBase/1.0 (research)"},
            )
            r.raise_for_status()
            text = r.text
    except Exception as e:
        return {
            "count": 0,
            "updated": datetime.now(timezone.utc).isoformat(),
            "strikes": [],
            "error": str(e),
            "hint": "Verify BLITZORTUNG_USER / BLITZORTUNG_PASSWORD (Blitzortung station operator)",
        }

    strikes = []
    for line in text.splitlines():
        strike = _parse_strike_line(line)
        if strike:
            strikes.append(strike)

    result = {
        "count": len(strikes),
        "updated": datetime.now(timezone.utc).isoformat(),
        "strikes": strikes,
    }

    _BLITZ_CACHE["strikes"] = {"ts": now, "data": result}
    return result


def gather_lightning_digest() -> dict:
    """Synchronous digest for briefing integration (reads in-memory cache)."""
    cached = _BLITZ_CACHE.get("strikes")
    if not cached:
        return {"enabled": False, "count": 0, "lines": []}
    data = cached.get("data") or {}
    if data.get("error"):
        return {"enabled": False, "count": 0, "lines": [], "error": data["error"]}
    strikes = data.get("strikes") or []
    if not strikes:
        return {"enabled": True, "count": 0, "lines": []}

    # Summarize: count + most recent strikes
    lines: list[str] = []
    recent = sorted(strikes, key=lambda s: s.get("time") or "", reverse=True)[:10]
    for s in recent:
        t = s.get("time") or "?"
        lines.append(
            f"Strike at ({s.get('lat'):.2f}, {s.get('lon'):.2f}) "
            f"stations={s.get('stations', 0)} time={t}"
        )
    return {
        "enabled": True,
        "count": len(strikes),
        "lines": lines[:10],
    }
