"""WorldBase — node sync layer (PC brain <-> Pi edge as one organism).

The Pi pushes its edge telemetry (sensors, mesh nodes, Pi-hole, health, GPS)
into WorldBase; the globe renders the Pi as a live entity. In return the Pi
pulls a fused world-situation briefing (written by the local LLM on the PC)
plus critical alerts, so the off-grid portal shows global awareness offline.
"""

import os
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["node-sync"])

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db")
SELF_URL = os.getenv("WORLDBASE_SELF", "http://localhost:8000").rstrip("/")
OLLAMA_HOSTS = os.getenv("OLLAMA_HOST", "localhost:11434").split(",")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:14b")


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
        """)
        conn.commit()


# ---------------------------------------------------------------------------
# Pi -> PC : ingest edge telemetry
# ---------------------------------------------------------------------------
@router.post("/node/ingest")
async def node_ingest(payload: dict):
    """Upsert a node's live state. The Pi POSTs this periodically.

    Expected (all optional except node_id):
      { "node_id": "offgrid-pi", "name": "Off-Grid Pi", "lat": ..., "lon": ...,
        "sensors": {"temp_c":..,"humidity":..,"battery_v":..},
        "mesh": [{"id":..,"name":..,"lat":..,"lon":..,"snr":..}, ...],
        "pihole": {"queries":..,"blocked":..,"percent":..},
        "health": {"cpu_temp":..,"disk_pct":..,"services":{...}} }
    """
    node_id = (payload.get("node_id") or "unknown").strip()
    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        conn.execute(
            """INSERT INTO node_state (node_id, name, lat, lon, updated_at, payload)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(node_id) DO UPDATE SET
                 name=excluded.name, lat=excluded.lat, lon=excluded.lon,
                 updated_at=excluded.updated_at, payload=excluded.payload""",
            (
                node_id,
                payload.get("name", node_id),
                payload.get("lat"),
                payload.get("lon"),
                now,
                json.dumps(payload),
            ),
        )
        conn.commit()
    return {"status": "ok", "node_id": node_id, "updated_at": now}


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


# ---------------------------------------------------------------------------
# Fusion : gather feeds -> compile critical alerts
# ---------------------------------------------------------------------------
async def _gather_snapshot() -> dict:
    """Pull key feeds from our own API into one compact snapshot."""
    snap: dict = {}
    async with httpx.AsyncClient(timeout=20.0) as client:
        async def grab(name, path):
            try:
                r = await client.get(f"{SELF_URL}{path}")
                if r.status_code == 200:
                    snap[name] = r.json()
            except Exception:
                pass
        await grab("earthquakes", "/api/earthquakes?period=day&magnitude=4.5")
        await grab("spaceweather", "/api/spaceweather")
        await grab("events", "/api/events?limit=40")
        await grab("markets", "/api/markets")
        await grab("geopolitics", "/api/geopolitics?limit=20")
        await grab("military", "/api/military")
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

    return alerts


# ---------------------------------------------------------------------------
# PC -> Pi : LLM situation briefing
# ---------------------------------------------------------------------------
async def _ollama_chat(prompt: str) -> str:
    for host in OLLAMA_HOSTS:
        host = host.strip()
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                r = await client.post(
                    f"http://{host}/api/chat",
                    json={
                        "model": OLLAMA_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                )
                if r.status_code == 200:
                    return r.json().get("message", {}).get("content", "").strip()
        except Exception:
            continue
    return ""


@router.post("/briefing/generate")
async def generate_briefing():
    """Fuse all feeds and have the local LLM write a world-situation report.

    Stored in SQLite; the Pi pulls it via /api/node/pull for offline display.
    """
    snap = await _gather_snapshot()
    alerts = _compile_alerts(snap)

    alert_lines = "\n".join(f"- {a['text']}" for a in alerts) or "- No critical alerts."
    sw = snap.get("spaceweather", {})
    mk = snap.get("markets", {}).get("crypto", {})
    prompt = (
        "You are the situational-awareness officer of a small off-grid intelligence "
        "node. Write a concise (max 150 words) world-situation briefing in plain text "
        "for a field operator. Be factual, calm, no markdown headers. "
        "Use only the data below.\n\n"
        f"Space weather: Kp={sw.get('kp_index')} ({sw.get('scale')}).\n"
        f"Crypto (USD): {json.dumps(mk)[:300]}\n"
        f"Critical alerts:\n{alert_lines}\n\n"
        "Briefing:"
    )
    text = await _ollama_chat(prompt)
    if not text:
        text = "LLM unavailable. Raw alerts:\n" + alert_lines

    now = datetime.now(timezone.utc).isoformat()
    with _db() as conn:
        conn.execute(
            "INSERT INTO briefings (created_at, text, sources) VALUES (?,?,?)",
            (now, text, json.dumps({"alerts": alerts})),
        )
        conn.commit()
    return {"created_at": now, "text": text, "alerts": alerts}


@router.get("/briefing")
async def latest_briefing():
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
    return {"created_at": row["created_at"], "text": row["text"], "alerts": sources.get("alerts", [])}


@router.get("/node/pull")
async def node_pull():
    """Single payload the Pi pulls: latest briefing + live critical alerts.

    Designed so the off-grid portal can show global situational awareness even
    when the Pi itself has no upstream internet — the PC did the heavy lifting.
    """
    brief = await latest_briefing()
    # also recompute fresh alerts if feeds are reachable (best-effort)
    try:
        snap = await _gather_snapshot()
        alerts = _compile_alerts(snap)
    except Exception:
        alerts = brief.get("alerts", [])
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "briefing": brief.get("text"),
        "briefing_at": brief.get("created_at"),
        "alerts": alerts,
    }
