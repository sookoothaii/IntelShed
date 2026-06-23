"""WorldBase — node sync layer (PC brain <-> Pi edge as one organism).

The Pi pushes its edge telemetry (sensors, mesh nodes, Pi-hole, health, GPS)
into WorldBase; the globe renders the Pi as a live entity. In return the Pi
pulls a fused world-situation briefing (written by the local LLM on the PC)
plus critical alerts, so the off-grid portal shows global awareness offline.
"""

import os
import json
import hashlib
import sqlite3
import asyncio
import time
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request, Depends
from fastapi.responses import JSONResponse, Response, StreamingResponse

from auth.security import verify_api_key, verify_lan_auth, require_admin_token, lan_exposed

# Pydantic Models for type-safe validation
from models.node import (
    NodeIngestPayload,
    NodeBriefing,
    NodeAlert,
    NodeStatus,
    NodeListResponse,
    SensorHistoryResponse,
    CommandPayload,
)

# Rate limiting
from middleware.rate_limit import (
    rate_limit_node_ingest,
    rate_limit_node_pull,
    rate_limit_node_command,
    rate_limit_general
)

# Enhanced Security (timing-safe HMAC, replay protection)
from auth.security import (
    verify_hmac_signature,
    verify_legacy_hmac,
    verify_legacy_hmac_bytes,
    generate_hmac_signature,
    check_replay_attack,
    verify_request_auth,
    require_admin_token,
    create_signed_request,
    INGEST_TOKEN,
    ADMIN_TOKEN,
)

router = APIRouter(prefix="/api", tags=["node-sync"])

DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
SELF_URL = os.getenv("WORLDBASE_SELF", "http://localhost:8002").rstrip("/")
OLLAMA_HOSTS = os.getenv("OLLAMA_HOST", "localhost:11434").split(",")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")

# ---------------------------------------------------------------------------
# Alert thresholds (positive prepper mindset: protect, not attack)
# ---------------------------------------------------------------------------
SENSOR_THRESHOLDS = {
    "cpu_temp_c": {"warn": 55, "critical": 70, "message": "CPU temperature elevated — consider ventilation"},
    "battery_v": {"warn": 3.5, "critical": 3.3, "message": "Battery voltage low — consider charging or solar input", "invert": True},
    "battery_pct": {"warn": 30, "critical": 15, "message": "Battery capacity low — conserve power", "invert": False},
    "co2_ppm": {"warn": 1000, "critical": 2000, "message": "CO2 level elevated — improve ventilation"},
    "radiation_usv_h": {"warn": 0.5, "critical": 1.0, "message": "Radiation level above baseline — check sensor placement"},
    "pm25_ug_m3": {"warn": 35, "critical": 75, "message": "Air quality degraded — consider filter or seal"},
    "disk_pct": {"warn": 85, "critical": 92, "message": "Root disk nearly full — run: sudo bash pi-disk-maintenance.sh"},
    "ram_pct": {"warn": 88, "critical": 95, "message": "RAM usage high — close heavy processes"},
}

_BRIEFING_LOCK = asyncio.Lock()
_ALERT_SEVERITY = {"critical": 0, "high": 1, "warning": 2, "medium": 3, "low": 4}

_SNAPSHOT_CACHE: dict | None = None
_SNAPSHOT_CACHE_AT: float = 0.0
_SNAPSHOT_CACHE_LOCK = asyncio.Lock()


def _snapshot_cache_ttl_sec() -> float:
    try:
        return max(30.0, min(300.0, float(os.getenv("WORLDBASE_SNAPSHOT_CACHE_SEC", "90") or "90")))
    except ValueError:
        return 90.0


def invalidate_snapshot_cache() -> None:
    """Drop cached feed snapshot (tests, forced refresh)."""
    global _SNAPSHOT_CACHE, _SNAPSHOT_CACHE_AT
    _SNAPSHOT_CACHE = None
    _SNAPSHOT_CACHE_AT = 0.0


def snapshot_cache_age_sec() -> float | None:
    """Seconds since last snapshot cache fill, or None if empty."""
    if _SNAPSHOT_CACHE is None or not _SNAPSHOT_CACHE_AT:
        return None
    return max(0.0, time.monotonic() - _SNAPSHOT_CACHE_AT)


async def warm_snapshot_cache(*, force: bool = False) -> dict:
    """Pre-fill snapshot cache after stack warmup (shared by briefing generate)."""
    return await _gather_snapshot(force=force)

# Note: HMAC functions now imported from auth.security module
# which provides timing-safe comparison, replay protection, and token expiration

import hmac as _hmac


def _verify_node_secret(x_node_token: str = "") -> None:
    """Shared secret for GET/pull/poll (header X-Node-Token) — plain token, constant-time."""
    if not INGEST_TOKEN:
        return
    if not _hmac.compare_digest(INGEST_TOKEN, (x_node_token or "")):
        raise HTTPException(status_code=403, detail="Invalid or missing node token")


def _verify_admin_secret(x_admin_token: str = "") -> None:
    if not ADMIN_TOKEN:
        return
    if not _hmac.compare_digest(ADMIN_TOKEN, (x_admin_token or "")):
        raise HTTPException(status_code=403, detail="Invalid or missing admin token")


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_node_db():
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS node_state (
                node_id TEXT PRIMARY KEY,
                name TEXT,
                lat REAL,
                lon REAL,
                updated_at TEXT,
                payload TEXT
            );
            CREATE TABLE IF NOT EXISTS briefings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                text TEXT,
                sources TEXT
            );
            CREATE TABLE IF NOT EXISTS sensor_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT,
                sensor TEXT,
                severity TEXT,
                value REAL,
                threshold REAL,
                message TEXT,
                created_at TEXT
            );
        """)
        conn.commit()


# ---------------------------------------------------------------------------
# Pi -> PC : ingest edge telemetry
# ---------------------------------------------------------------------------
@router.post("/node/ingest")
@rate_limit_node_ingest()
async def node_ingest(
    request: Request,
    x_node_token: str = Header(default=""),
    x_node_nonce: str = Header(default=""),
    x_node_timestamp: str = Header(default=""),
):
    """Upsert a node's live state. The Pi POSTs this periodically.

    Optional HMAC: set NODE_INGEST_TOKEN env var. Pi sends SHA-256 HMAC
    of the JSON body as X-Node-Token header (legacy format, unchanged).

    Expected (all optional except node_id):
      { "node_id": "offgrid-pi", "name": "Off-Grid Pi", "lat": ..., "lon": ...,
        "sensors": {"temp_c":..,"humidity":..,"battery_v":..},
        "mesh": [{"id":..,"name":..,"lat":..,"lon":..,"snr":..}, ...],
        "pihole": {"queries":..,"blocked":..,"percent":..},
        "health": {"cpu_temp":..,"disk_pct":..,"services":{...}} }
    """
    # Read the *raw* request bytes so the HMAC is verified against exactly what
    # the Pi signed. Re-serializing a parsed dict (json.dumps) is fragile: the
    # Pi signs with ensure_ascii=False (raw UTF-8) while a re-dump defaults to
    # ensure_ascii=True, so any non-ASCII byte (mesh names, Pi-hole hostnames,
    # degree symbols, …) would flip the signature and cause spurious 403s.
    raw_bytes = await request.body()

    # HMAC over the original body bytes — legacy-compatible with existing Pi clients
    if INGEST_TOKEN:
        if not verify_legacy_hmac_bytes(raw_bytes, x_node_token, INGEST_TOKEN):
            raise HTTPException(status_code=403, detail="Invalid node token")

        # Optional replay protection if Pi sends nonce/timestamp headers
        if x_node_nonce and x_node_timestamp:
            try:
                ts = int(x_node_timestamp)
                if check_replay_attack(x_node_nonce, ts):
                    raise HTTPException(status_code=403, detail="Request replay detected")
            except ValueError:
                pass  # Invalid timestamp format, but HMAC already verified

    # Parse the (already-authenticated) body. Pydantic model_dump() would add
    # default fields, so we keep the raw dict for storage compatibility.
    try:
        raw_body = json.loads(raw_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(raw_body, dict):
        raise HTTPException(status_code=400, detail="JSON object expected")

    node_id = (raw_body.get("node_id") or "unknown").strip()
    now = datetime.now(timezone.utc).isoformat()

    # Keep the original payload for storage (legacy-compatible)
    payload_dict = raw_body

    # Sensor alert detection (now using Pydantic-validated data)
    sensors = payload_dict.get("sensors") or {}
    health = payload_dict.get("health") or {}
    all_sensors = {**sensors}
    if "cpu_temp" in health:
        all_sensors["cpu_temp_c"] = health["cpu_temp"]
    if "cpu_temp_c" in sensors:
        all_sensors["cpu_temp_c"] = sensors["cpu_temp_c"]
    if health.get("disk_pct") is not None:
        all_sensors["disk_pct"] = health["disk_pct"]
    if health.get("ram_pct") is not None:
        all_sensors["ram_pct"] = health["ram_pct"]

    alerts_generated = []
    with _db() as conn:
        for sensor_name, cfg in SENSOR_THRESHOLDS.items():
            val = all_sensors.get(sensor_name)
            if val is None:
                continue
            threshold = None
            severity = None
            invert = cfg.get("invert", False)
            if invert:
                # Lower is worse (battery voltage)
                if val <= cfg["critical"]:
                    severity = "critical"
                    threshold = cfg["critical"]
                elif val <= cfg["warn"]:
                    severity = "warning"
                    threshold = cfg["warn"]
            else:
                # Higher is worse (temperature, radiation)
                if val >= cfg["critical"]:
                    severity = "critical"
                    threshold = cfg["critical"]
                elif val >= cfg["warn"]:
                    severity = "warning"
                    threshold = cfg["warn"]
            if severity:
                conn.execute(
                    "INSERT INTO sensor_alerts (node_id, sensor, severity, value, threshold, message, created_at) VALUES (?,?,?,?,?,?,?)",
                    (node_id, sensor_name, severity, val, threshold, cfg["message"], now),
                )
                alerts_generated.append({"sensor": sensor_name, "severity": severity, "value": val})

        conn.execute(
            """INSERT INTO node_state (node_id, name, lat, lon, updated_at, payload)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(node_id) DO UPDATE SET
                 name=excluded.name, lat=excluded.lat, lon=excluded.lon,
                 updated_at=excluded.updated_at, payload=excluded.payload""",
            (
                node_id,
                payload_dict.get("name", node_id),
                payload_dict.get("lat"),
                payload_dict.get("lon"),
                now,
                json.dumps(payload_dict),
            ),
        )
        conn.commit()

    # Store sensor history for time-series graphs
    _store_sensors(node_id, all_sensors)

    # Broadcast to SSE subscribers (/api/node/stream)
    try:
        _notify_node_update(
            node_id,
            {
                "node_id": node_id,
                "name": payload_dict.get("name", node_id),
                "lat": payload_dict.get("lat"),
                "lon": payload_dict.get("lon"),
                "sensors": sensors,
                "health": health,
                "alerts": alerts_generated,
                "timestamp": now,
            },
        )
    except Exception:
        pass  # SSE broadcast is best-effort

    return {"status": "ok", "node_id": node_id, "updated_at": now, "alerts": alerts_generated}


@router.get("/nodes")
async def list_nodes():
    """All known nodes with their last state — for globe entities + UI."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT node_id, name, lat, lon, updated_at, payload FROM node_state"
        ).fetchall()
    nodes = []
    now = datetime.now(timezone.utc)
    for r in rows:
        try:
            payload = json.loads(r["payload"]) if r["payload"] else {}
        except Exception:
            payload = {}
        age = None
        try:
            age = (now - datetime.fromisoformat(r["updated_at"])).total_seconds()
        except Exception:
            pass
        nodes.append({
            "node_id": r["node_id"],
            "name": r["name"],
            "lat": r["lat"],
            "lon": r["lon"],
            "updated_at": r["updated_at"],
            "age_seconds": age,
            "online": age is not None and age < 300,
            "sensors": payload.get("sensors", {}),
            "mesh": payload.get("mesh", []),
            "pihole": payload.get("pihole", {}),
            "health": payload.get("health", {}),
        })
    return {"count": len(nodes), "nodes": nodes}


@router.get("/alerts")
async def list_sensor_alerts(node_id: str = "", limit: int = 50):
    """Latest sensor alerts from all nodes or a specific node."""
    with _db() as conn:
        if node_id:
            rows = conn.execute(
                "SELECT * FROM sensor_alerts WHERE node_id = ? ORDER BY id DESC LIMIT ?",
                (node_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sensor_alerts ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    alerts = []
    for r in rows:
        alerts.append({
            "id": r["id"],
            "node_id": r["node_id"],
            "sensor": r["sensor"],
            "severity": r["severity"],
            "value": r["value"],
            "threshold": r["threshold"],
            "message": r["message"],
            "created_at": r["created_at"],
        })
    return {"count": len(alerts), "alerts": alerts}


def _gdelt_snapshot_meta(snap: dict) -> dict:
    """Compact GDELT feed counts for briefing quality scoring."""
    import gdelt_bridge

    local = gdelt_bridge.finalize_local_pulse(snap.get("gdelt_pulse_local") or {})
    geo_local = snap.get("gdelt_geo_local") or {}
    pulse = snap.get("gdelt_pulse") or {}
    geo = snap.get("gdelt_geo") or {}
    from briefing_quality import _gdelt_block_volume

    return {
        "local_pulse_count": _gdelt_block_volume(local, list_key="articles"),
        "geo_local_count": _gdelt_block_volume(geo_local, list_key="events"),
        "pulse_count": _gdelt_block_volume(pulse, list_key="articles"),
        "geo_count": _gdelt_block_volume(geo, list_key="events"),
        "feed_operator_available": _gdelt_block_volume(local, list_key="articles")
        + _gdelt_block_volume(geo_local, list_key="events"),
        "stale": bool(local.get("stale") or geo_local.get("stale")),
        "error": local.get("error") or geo_local.get("error"),
    }


# ---------------------------------------------------------------------------
# Fusion : gather feeds -> compile critical alerts
# ---------------------------------------------------------------------------
async def _gather_snapshot_uncached() -> dict:
    """Pull key feeds from our own API into one compact snapshot (parallel)."""
    snap: dict = {}
    feeds = (
        ("earthquakes", "/api/earthquakes?period=day&magnitude=4.5"),
        ("spaceweather", "/api/spaceweather"),
        ("events", "/api/events?limit=40"),
        ("markets", "/api/markets"),
        ("markets_crypto", "/api/markets/crypto"),
        ("markets_stocks", "/api/markets/stocks"),
        ("geopolitics", "/api/geopolitics?limit=20"),
        ("military", "/api/military"),
        ("gdacs", "/api/gdacs"),
        ("hazards", "/api/hazards?limit=40"),
        ("gdelt_pulse_local", "/api/gdelt/pulse/local"),
        ("gdelt_geo_local", "/api/gdelt/geo/local?timespan=1d&maxrecords=40"),
        ("gdelt_geo", "/api/gdelt/geo?timespan=1d&maxrecords=30"),
        ("river", "/api/anomalies/river"),
        ("outages", "/api/outages?limit=20"),
        ("volcanoes", "/api/volcanoes?active_only=true&limit=30"),
        ("cve", "/api/cve?limit=15"),
        ("nodes", "/api/nodes"),
        ("gdelt_pulse", "/api/gdelt/pulse"),
        ("airquality", "/api/airquality"),
        ("cams_haze", "/api/cams/haze"),
        ("humanitarian", "/api/humanitarian?limit=15"),
        ("newsdata", "/api/newsdata?limit=10"),
        ("maritime", "/api/maritime"),
    )

    async with httpx.AsyncClient(timeout=45.0) as client:
        async def grab(name: str, path: str) -> tuple[str, dict | None]:
            try:
                r = await client.get(f"{SELF_URL}{path}")
                if r.status_code == 200:
                    return name, r.json()
            except Exception:
                pass
            return name, None

        results = await asyncio.gather(*(grab(n, p) for n, p in feeds))
        for name, data in results:
            if data is not None:
                snap[name] = data
    return snap


async def _gather_snapshot(*, force: bool = False) -> dict:
    """Cached wrapper — TTL WORLDBASE_SNAPSHOT_CACHE_SEC (default 90s)."""
    global _SNAPSHOT_CACHE, _SNAPSHOT_CACHE_AT
    ttl = _snapshot_cache_ttl_sec()
    async with _SNAPSHOT_CACHE_LOCK:
        now = time.monotonic()
        if (
            not force
            and _SNAPSHOT_CACHE is not None
            and _SNAPSHOT_CACHE_AT
            and (now - _SNAPSHOT_CACHE_AT) < ttl
        ):
            return _SNAPSHOT_CACHE
        snap = await _gather_snapshot_uncached()
        _SNAPSHOT_CACHE = snap
        _SNAPSHOT_CACHE_AT = now
        return snap


def _compile_alerts(snap: dict) -> list:
    """Turn raw feeds into a ranked list of human-readable critical alerts."""
    alerts = []

    sw = snap.get("spaceweather", {})
    if sw.get("kp_index") is not None and sw["kp_index"] >= 5:
        alerts.append({
            "severity": "high" if sw["kp_index"] >= 7 else "medium",
            "kind": "space_weather",
            "text": f"Geomagnetic {sw.get('scale','storm')} (Kp={sw['kp_index']}). "
                    f"HF radio/GPS may degrade.",
        })

    # Market regime stress — only surfaced when elevated, so it reads as a
    # correlatable signal next to outages / GDELT escalation, not noise.
    try:
        import markets_bridge
        stress = markets_bridge.summarize_market_stress(
            snap.get("markets_crypto"), snap.get("markets_stocks")
        )
        if stress and markets_bridge._LEVEL_ORDER.get(stress.get("overall_level"), 0) >= 2:
            line = markets_bridge.format_market_stress_line(stress)
            if line:
                alerts.append({
                    "severity": markets_bridge.market_stress_severity(stress["overall_level"]),
                    "kind": "market_stress",
                    "text": line,
                })
    except Exception:
        pass

    quakes = (snap.get("earthquakes", {}) or {}).get("earthquakes", [])
    big = sorted(
        [q for q in quakes if (q.get("mag") or 0) >= 5.5],
        key=lambda q: q.get("mag") or 0, reverse=True,
    )[:5]
    for q in big:
        alerts.append({
            "severity": "high" if (q.get("mag") or 0) >= 6.5 else "medium",
            "kind": "earthquake",
            "text": f"M{q.get('mag')} earthquake — {q.get('place')}",
            "lat": q.get("lat"), "lon": q.get("lon"),
        })

    events = (snap.get("events", {}) or {}).get("events", [])
    for ev in events[:6]:
        alerts.append({
            "severity": "low",
            "kind": "natural_event",
            "text": f"{ev.get('category')}: {ev.get('title')}",
            "lat": ev.get("lat"), "lon": ev.get("lon"),
        })

    mil = (snap.get("military", {}) or {}).get("count")
    if mil:
        alerts.append({
            "severity": "low",
            "kind": "military_air",
            "text": f"{mil} military/interesting aircraft currently tracked.",
        })

    gdacs_n = (snap.get("gdacs", {}) or {}).get("count") or 0
    if gdacs_n:
        alerts.append({
            "severity": "medium",
            "kind": "gdacs",
            "text": f"{gdacs_n} GDACS humanitarian alerts active.",
        })

    haz_n = (snap.get("hazards", {}) or {}).get("count") or 0
    if haz_n:
        top = ((snap.get("hazards", {}) or {}).get("alerts") or [])[:3]
        sample = "; ".join((a.get("event") or "")[:50] for a in top if a.get("event"))
        alerts.append({
            "severity": "medium",
            "kind": "weather_hazard",
            "text": f"{haz_n} NWS/Meteoalarm alerts active. {sample}".strip(),
        })

    for sig in (snap.get("river", {}) or {}).get("anomalies") or []:
        alerts.append({
            "severity": "high",
            "kind": "feed_anomaly",
            "text": f"River anomaly: {sig.get('feed')} value={sig.get('value')} score={sig.get('score')}",
        })

    out_n = (snap.get("outages", {}) or {}).get("count") or 0
    if out_n:
        top = ((snap.get("outages", {}) or {}).get("items") or [])[:2]
        sample = "; ".join((i.get("title") or "")[:40] for i in top)
        alerts.append({
            "severity": "medium",
            "kind": "internet_outage",
            "text": f"{out_n} IODA/CF outage signals. {sample}".strip(),
        })

    act_v = (snap.get("volcanoes", {}) or {}).get("active_count") or 0
    if act_v:
        alerts.append({
            "severity": "low",
            "kind": "volcano",
            "text": f"{act_v} volcanoes with recent/observed activity (Smithsonian GVP).",
        })

    cve_items = (snap.get("cve", {}) or {}).get("vulnerabilities", [])[:5]
    for v in cve_items:
        sev = "high" if v.get("ransomware") == "Known" else "medium"
        alerts.append({
            "severity": sev,
            "kind": "cve",
            "text": f"KEV {v.get('cve_id')}: {v.get('vendor')} {v.get('product')}",
        })

    nodes = (snap.get("nodes", {}) or {}).get("nodes", [])
    for n in nodes:
        disk = (n.get("health") or {}).get("disk_pct")
        if disk is not None and disk >= 85:
            alerts.append({
                "severity": "critical" if disk >= 92 else "warning",
                "kind": "disk_space",
                "text": f"{n.get('name', n.get('node_id'))}: root disk {disk}% full — run pi-disk-maintenance.sh on Pi",
                "lat": n.get("lat"),
                "lon": n.get("lon"),
            })
    offline = [n for n in nodes if not n.get("online")]
    for n in offline[:2]:
        alerts.append({
            "severity": "medium",
            "kind": "node_offline",
            "text": f"Edge node {n.get('name', n.get('node_id'))} offline ({int(n.get('age_seconds') or 0)}s stale).",
            "lat": n.get("lat"),
            "lon": n.get("lon"),
        })

    return alerts


# ---------------------------------------------------------------------------
# PC -> Pi : LLM situation briefing
# ---------------------------------------------------------------------------
async def _ollama_briefing(prompt: str) -> str:
    """Single-shot briefing via local Ollama — capped tokens, no Qwen3 thinking."""
    body: dict = {
        "model": OLLAMA_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "keep_alive": __import__("ollama_config").keep_alive(),
        "options": {"num_predict": 420, "temperature": 0.35},
    }
    if "qwen3" in OLLAMA_MODEL.lower():
        body["think"] = False
    for host in OLLAMA_HOSTS:
        host = host.strip()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                r = await client.post(f"http://{host}/api/chat", json=body)
                if r.status_code == 200:
                    return r.json().get("message", {}).get("content", "").strip()
        except Exception:
            continue
    return ""


@router.post("/briefing/generate")
@rate_limit_general()
async def generate_briefing(
    request: Request,
    lang: str | None = None,
    api_key: str = Depends(verify_api_key),
):
    """Fuse all feeds and have the local LLM write a world-situation report.

    Optional ``lang`` query parameter (``en`` or ``de``) overrides the
    ``WORLDBASE_BRIEFING_LANG`` env default for this request only. Result is
    stored in SQLite; the Pi pulls it via /api/node/pull for offline display.
    Open on the LAN — local Ollama only; destructive node commands stay admin-gated.
    Set ``force=1`` to bypass the snapshot cache (default uses TTL cache).
    """
    force_snap = request.query_params.get("force", "").strip().lower() in ("1", "true", "yes")
    return await generate_briefing_internal(lang=lang, force_snapshot=force_snap)


async def generate_briefing_internal(lang: str | None = None, *, force_snapshot: bool = False):
    """Actual briefing generation logic (no auth). Used by route + autopilot."""
    async with _BRIEFING_LOCK:
        return await _generate_briefing_unlocked(lang=lang, force_snapshot=force_snapshot)


async def _generate_briefing_unlocked(lang: str | None = None, *, force_snapshot: bool = False):
    import fusion_heatmap
    import intel_briefing
    from operator_briefing import (
        build_security_advisor_prompt,
        format_digest_sections,
        format_fallback_protocol,
    )

    snap = await _gather_snapshot(force=force_snapshot)
    alerts = _compile_alerts(snap)
    fusion_hotspots, fusion_lines, fusion_deltas = await fusion_heatmap.top_hotspots_for_llm(top=3)
    intel_meta = await asyncio.to_thread(intel_briefing.gather_for_briefing)
    digest = format_digest_sections(
        snap,
        alerts,
        fusion_lines,
        fusion_hotspots,
        fusion_deltas=fusion_deltas,
        intel_meta=intel_meta,
        lang=lang,
    )
    from briefing_agentic import run_briefing_agentic_loop

    digest, agentic_meta = await run_briefing_agentic_loop(digest, snap=snap)
    prompt = build_security_advisor_prompt(digest, lang=lang)
    text = await _ollama_briefing(prompt)
    if not text:
        text = format_fallback_protocol(digest, lang=lang)

    now = datetime.now(timezone.utc).isoformat()
    intel_src = digest.get("intel") or {}
    from briefing_quality import gdelt_digest_pipeline_meta

    gdelt_meta = _gdelt_snapshot_meta(snap)
    gdelt_meta.update(gdelt_digest_pipeline_meta(snap, digest))
    sources_payload = {
        "alerts": alerts,
        "fusion_hotspots": fusion_hotspots,
        "intel": {
            "enabled": intel_src.get("enabled"),
            "count": intel_src.get("count", 0),
            "by_bucket": intel_src.get("by_bucket") or {},
            "window_hours": intel_src.get("window_hours"),
            "entities": intel_src.get("entities") or [],
            "prompt_metrics": intel_src.get("prompt_metrics") or {},
        },
        "digest": {
            "region": digest.get("region"),
            "region_label": digest.get("region_label"),
            "window": digest.get("window"),
            "lang": digest.get("lang"),
            "local_count": len(digest.get("local") or []),
            "regional_count": len(digest.get("regional") or []),
            "global_count": len(digest.get("global") or []),
            "intel_count": intel_src.get("count", 0),
        },
        "_digest_sections": {
            "local": digest.get("local") or [],
            "regional": digest.get("regional") or [],
            "global": digest.get("global") or [],
        },
        "gdelt": gdelt_meta,
        "style": "security_advisor_24h",
        "watch_items": digest.get("watch_items") or [],
        "digest_line_meta": digest.get("digest_line_meta") or [],
        "agentic": agentic_meta,
    }
    from briefing_quality import attach_quality_to_sources

    sources_payload = attach_quality_to_sources(sources_payload, text=text, created_at=now)
    with _db() as conn:
        conn.execute(
            "INSERT INTO briefings (created_at, text, sources) VALUES (?,?,?)",
            (now, text, json.dumps(sources_payload)),
        )
        conn.commit()
    try:
        import rag_memory
        await rag_memory.ingest_briefing(text, now)
    except Exception:
        pass
    try:
        import prediction_ledger

        if prediction_ledger.autopilot_on():
            await asyncio.to_thread(
                prediction_ledger.record_watch_items,
                digest.get("watch_items") or [],
                now,
            )
    except Exception:
        pass
    try:
        import intel_graph_export

        if intel_graph_export.enabled():
            await asyncio.to_thread(intel_graph_export.export_operator_subgraph)
    except Exception:
        pass
    return {
        "created_at": now,
        "text": text,
        "alerts": alerts,
        "fusion_hotspots": fusion_hotspots,
        "digest": sources_payload.get("digest"),
        "quality": sources_payload.get("quality"),
        "watch_items": digest.get("watch_items") or [],
        "digest_line_meta": digest.get("digest_line_meta") or sources_payload.get("digest_line_meta") or [],
        "agentic": agentic_meta,
    }


@router.get("/briefing")
async def latest_briefing(_auth: str | None = Depends(verify_lan_auth)):
    """Latest stored situation briefing."""
    with _db() as conn:
        row = conn.execute(
            "SELECT created_at, text, sources FROM briefings ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if not row:
        return {"created_at": None, "text": "No briefing yet. POST /api/briefing/generate.", "alerts": []}
    sources = {}
    try:
        sources = json.loads(row["sources"]) if row["sources"] else {}
    except Exception:
        pass
    quality = sources.get("quality")
    if not quality and row["text"]:
        try:
            from briefing_quality import score_briefing

            quality = score_briefing(
                text=row["text"],
                sources=sources,
                created_at=row["created_at"],
            )
        except Exception:
            quality = None
    try:
        import prediction_ledger

        quality = prediction_ledger.enrich_quality_meta(quality)
    except Exception:
        pass
    from operator_briefing import enrich_watch_items_coords

    watch_items = enrich_watch_items_coords(sources.get("watch_items") or [])
    return {
        "created_at": row["created_at"],
        "text": row["text"],
        "alerts": sources.get("alerts", []),
        "fusion_hotspots": sources.get("fusion_hotspots", []),
        "intel": sources.get("intel"),
        "digest": sources.get("digest"),
        "quality": quality,
        "style": sources.get("style"),
        "watch_items": watch_items,
        "digest_line_meta": sources.get("digest_line_meta") or [],
        "agentic": sources.get("agentic"),
    }


@router.get("/predictions")
async def predictions_status(
    pending_limit: int = Query(8, ge=1, le=50),
    resolved_limit: int = Query(5, ge=1, le=30),
):
    """Track 4 — pending watch outcomes and recent resolved samples."""
    import prediction_ledger

    if not prediction_ledger.autopilot_on():
        return {
            "enabled": False,
            "stats": {},
            "pending": [],
            "resolved_recent": [],
            "overdue_count": 0,
            "due_next": None,
        }
    out = prediction_ledger.list_predictions(
        pending_limit=pending_limit,
        resolved_limit=resolved_limit,
    )
    out["enabled"] = True
    return out


def _compress_briefing(text: str, alerts: list) -> str:
    """Shrink briefing to <230 bytes for Meshtastic/LoRa TX.
    Format: [SEV]alert1|[SEV]alert2|...|brief_snippet
    """
    parts = []
    for a in alerts[:3]:
        sev = a.get("severity", "low")[0].upper()
        txt = a.get("text", "")[:40]
        parts.append(f"[{sev}]{txt}")
    alert_str = "|".join(parts)
    remaining = 230 - len(alert_str) - 2
    brief_snippet = text[:max(remaining, 60)] if remaining > 0 else ""
    return f"{alert_str}|{brief_snippet}" if brief_snippet else alert_str


def _pull_payload_digest(payload: dict) -> str:
    """SHA-256 of canonical JSON — excludes volatile keys and content_sha256."""
    skip = frozenset({"content_sha256", "generated_at"})
    base = {k: v for k, v in payload.items() if k not in skip}
    canonical = json.dumps(base, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@router.get("/node/pull")
@rate_limit_node_pull()
async def node_pull(request: Request, mesh: bool = False, x_node_token: str = Header(default="")):
    """Single payload the Pi pulls: latest briefing + live critical alerts.

    Designed so the off-grid portal can show global situational awareness even
    when the Pi itself has no upstream internet — the PC did the heavy lifting.
    Set ?mesh=1 for a <230 byte payload suitable for Meshtastic/LoRa relay.

    When NODE_INGEST_TOKEN is set, send the same value as header X-Node-Token.
    """
    _verify_node_secret(x_node_token)
    brief = await latest_briefing()
    # Alerts + fusion from last generate — avoid _gather_snapshot() (~25 feeds, ~50s).
    alerts = brief.get("alerts") or []
    fusion_hotspots = brief.get("fusion_hotspots") or []

    if mesh:
        compressed = _compress_briefing(brief.get("text", ""), alerts)
        return {
            "t": datetime.now(timezone.utc).strftime("%H:%M"),
            "b": compressed,
            "a": len(alerts),
            "s": len(compressed),
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "worldbase-pc",
        "payload_version": 2,
        "briefing": brief.get("text"),
        "briefing_at": brief.get("created_at"),
        "alerts": alerts,
        "fusion_hotspots": fusion_hotspots,
        "quality": brief.get("quality"),
        "digest": brief.get("digest"),
        "watch_items": brief.get("watch_items") or [],
    }
    try:
        import intel_graph_export

        if intel_graph_export.enabled():
            payload["intel_subgraph"] = await asyncio.to_thread(intel_graph_export.compact_for_pull)
    except Exception:
        payload["intel_subgraph"] = {"available": False}
    digest = _pull_payload_digest(payload)
    payload["content_sha256"] = digest

    inm = request.headers.get("if-none-match", "").strip().strip('"')
    if inm and inm == digest:
        return Response(status_code=304, headers={"ETag": f'"{digest}"', "X-Content-SHA256": digest})

    return JSONResponse(
        payload,
        headers={"ETag": f'"{digest}"', "X-Content-SHA256": digest},
    )


@router.get("/node/pull/mesh")
@rate_limit_node_pull()
async def node_pull_mesh(request: Request, x_node_token: str = Header(default="")):
    """Dedicated endpoint: always returns compressed <230 byte briefing for LoRa."""
    return await node_pull(request=request, mesh=True, x_node_token=x_node_token)


# ---------------------------------------------------------------------------
# COMMAND QUEUE — PC -> Pi bidirectional control
# ---------------------------------------------------------------------------

def init_command_db():
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS node_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                command TEXT NOT NULL,
                args TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                acked_at TEXT,
                result TEXT
            );
            CREATE TABLE IF NOT EXISTS sensor_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL,
                sensor TEXT NOT NULL,
                value REAL,
                recorded_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_sensor_history_node_sensor ON sensor_history(node_id, sensor);
            CREATE INDEX IF NOT EXISTS idx_sensor_history_time ON sensor_history(recorded_at);
        """)
        conn.commit()


@router.post("/node/{node_id}/command")
@rate_limit_node_command()
async def queue_command(
    request: Request,
    node_id: str,
    payload: CommandPayload,  # Now using Pydantic model
    x_admin_token: str = Header(default=""),
):
    """Queue a command for a specific Pi node. PC calls this to control the Pi.

    Commands: reboot, shutdown, restart_service, update_config, exec

    When NODE_ADMIN_TOKEN or NODE_INGEST_TOKEN is set, require header X-Admin-Token.
    """
    _verify_admin_secret(x_admin_token)
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        conn.execute(
            "INSERT INTO node_commands (node_id, command, args, status, created_at) VALUES (?,?,?,?,?)",
            (node_id, payload.command, json.dumps(payload.args), "pending", now),
        )
        conn.commit()
        cmd_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {"status": "queued", "command_id": cmd_id, "node_id": node_id}


@router.get("/node/{node_id}/commands")
@rate_limit_node_pull()
async def poll_commands(
    request: Request,
    node_id: str,
    limit: int = 10,
    x_node_token: str = Header(default=""),
):
    """Pi polls this to fetch pending commands."""
    _verify_node_secret(x_node_token)
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, command, args, created_at FROM node_commands WHERE node_id = ? AND status = 'pending' ORDER BY id LIMIT ?",
            (node_id, limit),
        ).fetchall()
    commands = []
    for r in rows:
        try:
            args = json.loads(r["args"]) if r["args"] else {}
        except Exception:
            args = {}
        commands.append({"id": r["id"], "command": r["command"], "args": args, "created_at": r["created_at"]})
    return {"node_id": node_id, "pending": len(commands), "commands": commands}


@router.post("/node/command/{command_id}/ack")
@rate_limit_node_ingest()
async def ack_command(
    request: Request,
    command_id: int,
    payload: dict,
    x_node_token: str = Header(default=""),
):
    """Pi acks a command after execution."""
    _verify_node_secret(x_node_token)
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        conn.execute(
            "UPDATE node_commands SET status = ?, acked_at = ?, result = ? WHERE id = ?",
            (payload.get("status", "done"), now, payload.get("result"), command_id),
        )
        conn.commit()
    return {"status": "acknowledged", "command_id": command_id}


@router.get("/node/{node_id}/command-history")
async def command_history(
    request: Request,
    node_id: str,
    limit: int = 20,
):
    """Show recent commands for a node (PC-side view)."""
    if lan_exposed():
        require_admin_token(request)
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, command, status, created_at, acked_at, result FROM node_commands WHERE node_id = ? ORDER BY id DESC LIMIT ?",
            (node_id, limit),
        ).fetchall()
    return {
        "node_id": node_id,
        "commands": [
            {
                "id": r["id"],
                "command": r["command"],
                "status": r["status"],
                "created_at": r["created_at"],
                "acked_at": r["acked_at"],
                "result": r["result"],
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# SENSOR HISTORY — time-series storage for graphs
# ---------------------------------------------------------------------------

def _store_sensors(node_id: str, sensors: dict):
    """Store sensor readings as time-series. Called during ingest."""
    if not sensors:
        return
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        for key, val in sensors.items():
            if isinstance(val, (int, float)):
                conn.execute(
                    "INSERT INTO sensor_history (node_id, sensor, value, recorded_at) VALUES (?,?,?,?)",
                    (node_id, key, float(val), now),
                )
        conn.commit()


@router.get("/node/{node_id}/sensors/history")
async def sensor_history(node_id: str, sensor: str = "", hours: int = 24):
    """Return sensor time-series for plotting."""
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with _db() as conn:
        if sensor:
            rows = conn.execute(
                "SELECT sensor, value, recorded_at FROM sensor_history WHERE node_id = ? AND sensor = ? AND recorded_at > ? ORDER BY recorded_at",
                (node_id, sensor, cutoff),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT sensor, value, recorded_at FROM sensor_history WHERE node_id = ? AND recorded_at > ? ORDER BY recorded_at",
                (node_id, cutoff),
            ).fetchall()
    data: dict = {}
    for r in rows:
        key = r["sensor"]
        if key not in data:
            data[key] = []
        data[key].append({"t": r["recorded_at"], "v": r["value"]})
    return {"node_id": node_id, "sensor": sensor or "all", "hours": hours, "series": data}


@router.get("/node/{node_id}/sensors/latest")
async def latest_sensors(node_id: str):
    """Latest value for each sensor."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT sensor, value, recorded_at FROM sensor_history WHERE node_id = ? AND recorded_at = (SELECT MAX(recorded_at) FROM sensor_history WHERE node_id = ? AND sensor = s.sensor)",
            (node_id, node_id),
        ).fetchall()
    return {"node_id": node_id, "sensors": {r["sensor"]: {"value": r["value"], "at": r["recorded_at"]} for r in rows}}


# ---------------------------------------------------------------------------
# MESH NODES — globe endpoint
# ---------------------------------------------------------------------------

@router.get("/mesh/nodes")
async def mesh_nodes():
    """Return all mesh nodes from all Pis for globe rendering."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT node_id, payload FROM node_state"
        ).fetchall()
    all_nodes = []
    for r in rows:
        try:
            payload = json.loads(r["payload"]) if r["payload"] else {}
        except Exception:
            continue
        mesh = payload.get("mesh", [])
        for n in mesh:
            if n.get("lat") is not None and n.get("lon") is not None:
                all_nodes.append({
                    "pi_node": r["node_id"],
                    "id": n.get("id", "?"),
                    "name": n.get("name", "?"),
                    "lat": n.get("lat"),
                    "lon": n.get("lon"),
                    "snr": n.get("snr"),
                    "last_seen": n.get("last_seen"),
                })
    return {"count": len(all_nodes), "nodes": all_nodes}


# ---------------------------------------------------------------------------
# SSE STREAMING — Real-time node updates
# ---------------------------------------------------------------------------

import asyncio
from typing import AsyncIterator

# Event queue for node updates (simple in-memory pub/sub)
_node_update_queues: dict[str, asyncio.Queue] = {}


def _notify_node_update(node_id: str, data: dict):
    """Notify all SSE subscribers of a node update."""
    for queue in _node_update_queues.values():
        try:
            queue.put_nowait({"node_id": node_id, "data": data})
        except asyncio.QueueFull:
            pass  # Drop message if queue is full


async def _node_update_generator(
    node_id: str | None = None,
    heartbeat_interval: int = 30,
) -> AsyncIterator[str]:
    """Generate SSE events for node updates."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    client_id = f"{node_id or 'all'}_{id(queue)}"
    _node_update_queues[client_id] = queue
    
    try:
        # Send initial connection event
        yield f"event: connected\ndata: {json.dumps({'client_id': client_id, 'node_id': node_id, 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
        
        last_heartbeat = datetime.now(timezone.utc)
        
        while True:
            try:
                # Wait for update or heartbeat
                timeout = heartbeat_interval - (datetime.now(timezone.utc) - last_heartbeat).total_seconds()
                if timeout <= 0:
                    # Send heartbeat
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
                    last_heartbeat = datetime.now(timezone.utc)
                    continue
                
                # Wait for message with timeout
                message = await asyncio.wait_for(queue.get(), timeout=max(1, timeout))
                
                # Filter by node_id if specified
                if node_id and message.get("node_id") != node_id:
                    continue
                
                # Send update event
                yield f"event: node-update\ndata: {json.dumps(message['data'])}\n\n"
                
            except asyncio.TimeoutError:
                # Send heartbeat on timeout
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
                last_heartbeat = datetime.now(timezone.utc)
                
    except asyncio.CancelledError:
        # Client disconnected
        pass
    finally:
        # Cleanup
        if client_id in _node_update_queues:
            del _node_update_queues[client_id]


@router.get("/node/stream")
async def node_stream(
    node_id: str | None = None,
    x_node_token: str = Header(default=""),
):
    """SSE endpoint for real-time node updates.
    
    Stream live telemetry updates from edge nodes as they are ingested.
    Useful for real-time dashboards without polling.
    
    Query params:
        node_id: Optional filter for a specific node (default: all nodes)
    
    Headers:
        X-Node-Token: Required if NODE_INGEST_TOKEN is set
    
    Events:
        - connected: Initial connection established
        - node-update: New telemetry data from a node
        - heartbeat: Keep-alive every 30 seconds
    """
    _verify_node_secret(x_node_token)

    return StreamingResponse(
        _node_update_generator(node_id=node_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )


