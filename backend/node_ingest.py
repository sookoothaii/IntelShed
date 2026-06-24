"""WorldBase — node ingest layer (Pi -> PC telemetry, commands, SSE, mesh).

Extracted from node_sync.py (Phase 2). Handles:
- Edge node telemetry ingestion with HMAC auth
- Sensor alert detection and history
- Command queue (PC -> Pi bidirectional control)
- SSE streaming for real-time node updates
- Mesh node aggregation for globe rendering
"""

from __future__ import annotations

import json
import os
import sqlite3
import asyncio
import hmac as _hmac
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

from fastapi import APIRouter, Header, HTTPException, Query, Request, Depends
from fastapi.responses import JSONResponse, Response, StreamingResponse

from auth.security import (
    verify_lan_auth,
    require_admin_token,
    lan_exposed,
    verify_legacy_hmac_bytes,
    check_replay_attack,
    INGEST_TOKEN,
    ADMIN_TOKEN,
)
from models.node import CommandPayload
from middleware.rate_limit import (
    rate_limit_node_ingest,
    rate_limit_node_pull,
    rate_limit_node_command,
)

router = APIRouter(prefix="/api", tags=["node-sync"])

DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)

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


@contextmanager
def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


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
    raw_bytes = await request.body()

    if INGEST_TOKEN:
        if not verify_legacy_hmac_bytes(raw_bytes, x_node_token, INGEST_TOKEN):
            raise HTTPException(status_code=403, detail="Invalid node token")

        if x_node_nonce and x_node_timestamp:
            try:
                ts = int(x_node_timestamp)
                if check_replay_attack(x_node_nonce, ts):
                    raise HTTPException(status_code=403, detail="Request replay detected")
            except ValueError:
                pass

    try:
        raw_body = json.loads(raw_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    if not isinstance(raw_body, dict):
        raise HTTPException(status_code=400, detail="JSON object expected")

    node_id = (raw_body.get("node_id") or "unknown").strip()
    now = datetime.now(timezone.utc).isoformat()

    payload_dict = raw_body

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
                if val <= cfg["critical"]:
                    severity = "critical"
                    threshold = cfg["critical"]
                elif val <= cfg["warn"]:
                    severity = "warning"
                    threshold = cfg["warn"]
            else:
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

    _store_sensors(node_id, all_sensors)

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
        pass

    return {"status": "ok", "node_id": node_id, "updated_at": now, "alerts": alerts_generated}


@router.get("/nodes")
async def list_nodes(_auth: str | None = Depends(verify_lan_auth)):
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
# COMMAND QUEUE — PC -> Pi bidirectional control
# ---------------------------------------------------------------------------
@router.post("/node/{node_id}/command")
@rate_limit_node_command()
async def queue_command(
    request: Request,
    node_id: str,
    payload: CommandPayload,
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
_node_update_queues: dict[str, asyncio.Queue] = {}


def _notify_node_update(node_id: str, data: dict):
    """Notify all SSE subscribers of a node update."""
    for queue in _node_update_queues.values():
        try:
            queue.put_nowait({"node_id": node_id, "data": data})
        except asyncio.QueueFull:
            pass


async def _node_update_generator(
    node_id: str | None = None,
    heartbeat_interval: int = 30,
) -> AsyncIterator[str]:
    """Generate SSE events for node updates."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)
    client_id = f"{node_id or 'all'}_{id(queue)}"
    _node_update_queues[client_id] = queue

    try:
        yield f"event: connected\ndata: {json.dumps({'client_id': client_id, 'node_id': node_id, 'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"

        last_heartbeat = datetime.now(timezone.utc)

        while True:
            try:
                timeout = heartbeat_interval - (datetime.now(timezone.utc) - last_heartbeat).total_seconds()
                if timeout <= 0:
                    yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
                    last_heartbeat = datetime.now(timezone.utc)
                    continue

                message = await asyncio.wait_for(queue.get(), timeout=max(1, timeout))

                if node_id and message.get("node_id") != node_id:
                    continue

                yield f"event: node-update\ndata: {json.dumps(message['data'])}\n\n"

            except asyncio.TimeoutError:
                yield f"event: heartbeat\ndata: {json.dumps({'timestamp': datetime.now(timezone.utc).isoformat()})}\n\n"
                last_heartbeat = datetime.now(timezone.utc)

    except asyncio.CancelledError:
        pass
    finally:
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
            "X-Accel-Buffering": "no",
        },
    )
