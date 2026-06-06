"""WorldBase — node sync layer (PC brain <-> Pi edge as one organism).

The Pi pushes its edge telemetry (sensors, mesh nodes, Pi-hole, health, GPS)
into WorldBase; the globe renders the Pi as a live entity. In return the Pi
pulls a fused world-situation briefing (written by the local LLM on the PC)
plus critical alerts, so the off-grid portal shows global awareness offline.
"""

import os
import json
import sqlite3
import hmac
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Header, HTTPException

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

INGEST_TOKEN = os.getenv("NODE_INGEST_TOKEN", "")
ADMIN_TOKEN = os.getenv("NODE_ADMIN_TOKEN", "") or INGEST_TOKEN


def _node_hmac(body: dict) -> str:
    body_bytes = json.dumps(body, separators=(",", ":")).encode()
    return hmac.new(INGEST_TOKEN.encode(), body_bytes, hashlib.sha256).hexdigest()


def _verify_node_hmac(payload: dict, x_node_token: str) -> None:
    if not INGEST_TOKEN:
        return
    expected = _node_hmac(payload)
    if not hmac.compare_digest(expected, (x_node_token or "")):
        raise HTTPException(status_code=403, detail="Invalid node token")


def _verify_node_secret(x_node_token: str = "") -> None:
    """Shared secret for GET/pull/poll (header X-Node-Token)."""
    if not INGEST_TOKEN:
        return
    if not hmac.compare_digest(INGEST_TOKEN, (x_node_token or "")):
        raise HTTPException(status_code=403, detail="Invalid or missing node token")


def _verify_admin_secret(x_admin_token: str = "") -> None:
    if not ADMIN_TOKEN:
        return
    if not hmac.compare_digest(ADMIN_TOKEN, (x_admin_token or "")):
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
async def node_ingest(payload: dict, x_node_token: str = Header(default="")):
    """Upsert a node's live state. The Pi POSTs this periodically.

    Optional HMAC: set NODE_INGEST_TOKEN env var. Pi sends SHA-256 HMAC
    of the JSON body as X-Node-Token header.

    Expected (all optional except node_id):
      { "node_id": "offgrid-pi", "name": "Off-Grid Pi", "lat": ..., "lon": ...,
        "sensors": {"temp_c":..,"humidity":..,"battery_v":..},
        "mesh": [{"id":..,"name":..,"lat":..,"lon":..,"snr":..}, ...],
        "pihole": {"queries":..,"blocked":..,"percent":..},
        "health": {"cpu_temp":..,"disk_pct":..,"services":{...}} }
    """
    _verify_node_hmac(payload, x_node_token)

    node_id = (payload.get("node_id") or "unknown").strip()
    now = datetime.now(timezone.utc).isoformat()

    # Sensor alert detection
    sensors = payload.get("sensors") or {}
    health = payload.get("health") or {}
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
                payload.get("name", node_id),
                payload.get("lat"),
                payload.get("lon"),
                now,
                json.dumps(payload),
            ),
        )
        conn.commit()

    # Store sensor history for time-series graphs
    _store_sensors(node_id, all_sensors)

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
        await grab("gdacs", "/api/gdacs")
        await grab("hazards", "/api/hazards?limit=40")
        await grab("gdelt_geo", "/api/gdelt/geo?timespan=1d&maxrecords=30")
        await grab("river", "/api/anomalies/river")
        await grab("outages", "/api/outages?limit=20")
        await grab("volcanoes", "/api/volcanoes?active_only=true&limit=30")
        await grab("cve", "/api/cve?limit=15")
        await grab("nodes", "/api/nodes")
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
                        "keep_alive": __import__("ollama_config").keep_alive(),
                    },
                )
                if r.status_code == 200:
                    return r.json().get("message", {}).get("content", "").strip()
        except Exception:
            continue
    return ""


@router.post("/briefing/generate")
async def generate_briefing(x_admin_token: str = Header(default="")):
    """Fuse all feeds and have the local LLM write a world-situation report.

    Stored in SQLite; the Pi pulls it via /api/node/pull for offline display.
    This route is admin-protected (heavy LLM call). The background autopilot
    calls generate_briefing_internal() directly and is not affected.
    """
    _verify_admin_secret(x_admin_token)
    return await generate_briefing_internal()


async def generate_briefing_internal():
    """Actual briefing generation logic (no auth). Used by route + autopilot."""
    snap = await _gather_snapshot()
    alerts = _compile_alerts(snap)

    alert_lines = "\n".join(f"- {a['text']}" for a in alerts) or "- No critical alerts."
    sw = snap.get("spaceweather", {})
    mk = snap.get("markets", {}).get("crypto", {})
    cve_lines = "\n".join(
        f"- {v.get('cve_id')}: {v.get('vendor')} {v.get('product')} (due {v.get('due_date', '?')})"
        for v in (snap.get("cve", {}) or {}).get("vulnerabilities", [])[:5]
    ) or "- none"
    nodes = (snap.get("nodes", {}) or {}).get("nodes", [])
    node_lines = "\n".join(
        f"- {n.get('name')}: {'online' if n.get('online') else 'OFFLINE'}, CPU {n.get('health', {}).get('cpu_temp_c', '?')}C"
        for n in nodes[:3]
    ) or "- none"
    prompt = (
        "You are the situational-awareness officer of a small off-grid intelligence "
        "node. Write a concise (max 150 words) world-situation briefing in plain text "
        "for a field operator. Be factual, calm, no markdown headers. "
        "Use only the data below.\n\n"
        f"Space weather: Kp={sw.get('kp_index')} ({sw.get('scale')}).\n"
        f"Crypto (USD): {json.dumps(mk)[:300]}\n"
        f"Edge nodes:\n{node_lines}\n"
        f"CISA KEV (exploited CVEs):\n{cve_lines}\n"
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
    try:
        import rag_memory
        await rag_memory.ingest_briefing(text, now)
    except Exception:
        pass
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


@router.get("/node/pull")
async def node_pull(mesh: bool = False, x_node_token: str = Header(default="")):
    """Single payload the Pi pulls: latest briefing + live critical alerts.

    Designed so the off-grid portal can show global situational awareness even
    when the Pi itself has no upstream internet — the PC did the heavy lifting.
    Set ?mesh=1 for a <230 byte payload suitable for Meshtastic/LoRa relay.

    When NODE_INGEST_TOKEN is set, send the same value as header X-Node-Token.
    """
    _verify_node_secret(x_node_token)
    brief = await latest_briefing()
    try:
        snap = await _gather_snapshot()
        alerts = _compile_alerts(snap)
    except Exception:
        alerts = brief.get("alerts", [])

    if mesh:
        compressed = _compress_briefing(brief.get("text", ""), alerts)
        return {
            "t": datetime.now(timezone.utc).strftime("%H:%M"),
            "b": compressed,
            "a": len(alerts),
            "s": len(compressed),
        }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "briefing": brief.get("text"),
        "briefing_at": brief.get("created_at"),
        "alerts": alerts,
    }


@router.get("/node/pull/mesh")
async def node_pull_mesh(x_node_token: str = Header(default="")):
    """Dedicated endpoint: always returns compressed <230 byte briefing for LoRa."""
    return await node_pull(mesh=True, x_node_token=x_node_token)


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
async def queue_command(
    node_id: str,
    payload: dict,
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
            (node_id, payload.get("command"), json.dumps(payload.get("args", {})), "pending", now),
        )
        conn.commit()
        cmd_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    return {"status": "queued", "command_id": cmd_id, "node_id": node_id}


@router.get("/node/{node_id}/commands")
async def poll_commands(
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
async def ack_command(
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
async def command_history(node_id: str, limit: int = 20):
    """Show recent commands for a node (PC-side view)."""
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
