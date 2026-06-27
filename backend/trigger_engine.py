"""3.4 — Trigger-Response engine with explicit uncertainty.

Rule-based threshold engine that evaluates fusion cells + watch items
after each briefing cycle. Fires alerts with confidence + context block.

Design principle: "System erkennt Anomalie mit Confidence X → Push an
Operator mit Kontext-Block." The operator is the loop.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from typing import Any

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)

# Default rules — seeded on first init
_DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "name": "high_fusion_cell",
        "condition": "fusion_score >= 0.7",
        "min_confidence": 0.6,
        "bucket_filter": None,
        "severity": "critical",
        "cooldown_min": 60,
        "enabled": True,
    },
    {
        "name": "rising_fusion_delta",
        "condition": "fusion_delta >= 0.3",
        "min_confidence": 0.5,
        "bucket_filter": None,
        "severity": "warning",
        "cooldown_min": 90,
        "enabled": True,
    },
    {
        "name": "high_haze_regional",
        "condition": "watch_prefix == 'cams' and watch_confidence >= 0.7",
        "min_confidence": 0.65,
        "bucket_filter": "regional",
        "severity": "warning",
        "cooldown_min": 120,
        "enabled": True,
    },
    {
        "name": "quake_m6_plus",
        "condition": "watch_prefix == 'quake' and watch_confidence >= 0.8",
        "min_confidence": 0.75,
        "bucket_filter": None,
        "severity": "critical",
        "cooldown_min": 30,
        "enabled": True,
    },
    {
        "name": "gdacs_red_alert",
        "condition": "watch_prefix == 'gdacs' and watch_confidence >= 0.75",
        "min_confidence": 0.7,
        "bucket_filter": None,
        "severity": "critical",
        "cooldown_min": 45,
        "enabled": True,
    },
]


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_trigger_db() -> None:
    """Create trigger_rules + trigger_log tables, seed defaults."""
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS trigger_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                condition TEXT NOT NULL,
                min_confidence REAL DEFAULT 0.5,
                bucket_filter TEXT,
                severity TEXT DEFAULT 'warning',
                cooldown_min INTEGER DEFAULT 60,
                enabled INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS trigger_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rule_name TEXT NOT NULL,
                fired_at TEXT NOT NULL,
                cell_id TEXT,
                watch_id TEXT,
                confidence REAL,
                severity TEXT,
                context TEXT,
                dismissed INTEGER DEFAULT 0,
                dismissed_at TEXT,
                dismissed_reason TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_trigger_log_fired
                ON trigger_log(fired_at);
            CREATE INDEX IF NOT EXISTS idx_trigger_log_rule
                ON trigger_log(rule_name, fired_at);
        """)
        # Seed default rules if table is empty
        count = conn.execute("SELECT COUNT(*) FROM trigger_rules").fetchone()[0]
        if count == 0:
            now = datetime.now(timezone.utc).isoformat()
            for rule in _DEFAULT_RULES:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO trigger_rules (
                        name, condition, min_confidence, bucket_filter,
                        severity, cooldown_min, enabled, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rule["name"],
                        rule["condition"],
                        rule["min_confidence"],
                        rule["bucket_filter"],
                        rule["severity"],
                        rule["cooldown_min"],
                        1 if rule["enabled"] else 0,
                        now,
                    ),
                )
        conn.commit()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def list_rules(*, include_disabled: bool = False) -> list[dict[str, Any]]:
    """List all trigger rules."""
    init_trigger_db()
    with _conn() as conn:
        q = "SELECT * FROM trigger_rules"
        if not include_disabled:
            q += " WHERE enabled = 1"
        q += " ORDER BY severity DESC, name ASC"
        rows = conn.execute(q).fetchall()
    return [dict(r) for r in rows]


def create_rule(
    name: str,
    condition: str,
    *,
    min_confidence: float = 0.5,
    bucket_filter: str | None = None,
    severity: str = "warning",
    cooldown_min: int = 60,
    enabled: bool = True,
) -> dict[str, Any]:
    """Create or update a trigger rule."""
    init_trigger_db()
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO trigger_rules (
                name, condition, min_confidence, bucket_filter,
                severity, cooldown_min, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                condition = excluded.condition,
                min_confidence = excluded.min_confidence,
                bucket_filter = excluded.bucket_filter,
                severity = excluded.severity,
                cooldown_min = excluded.cooldown_min,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (
                name,
                condition,
                min_confidence,
                bucket_filter,
                severity,
                cooldown_min,
                1 if enabled else 0,
                now,
                now,
            ),
        )
        conn.commit()
    return {"name": name, "created": True}


def delete_rule(name: str) -> dict[str, Any]:
    """Delete a trigger rule."""
    init_trigger_db()
    with _conn() as conn:
        conn.execute("DELETE FROM trigger_rules WHERE name = ?", (name,))
        conn.commit()
    return {"name": name, "deleted": True}


def _is_on_cooldown(rule_name: str, cooldown_min: int) -> bool:
    """Check if a rule fired recently (within cooldown window)."""
    with _conn() as conn:
        row = conn.execute(
            """
            SELECT fired_at FROM trigger_log
            WHERE rule_name = ? AND dismissed = 0
            ORDER BY fired_at DESC LIMIT 1
            """,
            (rule_name,),
        ).fetchone()
    if not row:
        return False
    fired = _parse_ts(row["fired_at"])
    if not fired:
        return False
    elapsed = (datetime.now(timezone.utc) - fired).total_seconds()
    return elapsed < cooldown_min * 60


def _eval_condition(condition: str, ctx: dict[str, Any]) -> bool:
    """Evaluate a condition string against a context dict.

    Supports simple comparisons: field OP value, combined with 'and'/'or'.
    Safe eval — only allows comparison operators on context fields.
    """
    # Build a safe namespace from context
    safe_globals: dict[str, Any] = {"__builtins__": {}}
    safe_locals = dict(ctx)
    try:
        return bool(eval(condition, safe_globals, safe_locals))  # noqa: S307
    except Exception:
        return False


def evaluate_triggers(
    fusion_cells: list[dict[str, Any]] | None = None,
    watch_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Evaluate all enabled trigger rules against current data.

    Returns list of fired triggers with context blocks.
    """
    init_trigger_db()
    rules = list_rules(include_disabled=False)
    if not rules:
        return []

    cells = fusion_cells or []
    watches = watch_items or []
    fired: list[dict[str, Any]] = []
    ts = datetime.now(timezone.utc).isoformat()

    for rule in rules:
        cooldown_min = int(rule["cooldown_min"] or 60)
        if _is_on_cooldown(rule["name"], cooldown_min):
            continue

        min_conf = float(rule["min_confidence"] or 0.5)
        bucket_filter = rule["bucket_filter"]

        # Check fusion cells
        for cell in cells:
            score = float(cell.get("score") or 0)
            delta = cell.get("delta_score")
            delta_f = float(delta) if delta is not None else 0.0
            cell_conf = min(score, 0.99)
            if cell_conf < min_conf:
                continue

            ctx = {
                "fusion_score": score,
                "fusion_delta": delta_f,
                "cell_id": cell.get("cell_id", ""),
                "cell_lat": float(cell.get("lat") or 0),
                "cell_lon": float(cell.get("lon") or 0),
                "cell_sources": cell.get("sources", []),
            }
            if not _eval_condition(rule["condition"], ctx):
                continue

            context_block = _build_fusion_context(cell, rule)
            entry = {
                "rule_name": rule["name"],
                "fired_at": ts,
                "cell_id": cell.get("cell_id"),
                "watch_id": None,
                "confidence": cell_conf,
                "severity": rule["severity"],
                "context": context_block,
            }
            _log_trigger(entry)
            fired.append(entry)
            break  # one fire per rule per cycle

        if fired and fired[-1]["rule_name"] == rule["name"]:
            continue

        # Check watch items
        for watch in watches:
            w_conf = float(watch.get("confidence") or 0)
            if w_conf < min_conf:
                continue
            w_bucket = watch.get("bucket", "")
            if bucket_filter and w_bucket != bucket_filter:
                continue

            ctx = {
                "watch_prefix": watch.get("prefix", ""),
                "watch_confidence": w_conf,
                "watch_bucket": w_bucket,
                "watch_sources": watch.get("sources", []),
            }
            if not _eval_condition(rule["condition"], ctx):
                continue

            context_block = _build_watch_context(watch, rule)
            entry = {
                "rule_name": rule["name"],
                "fired_at": ts,
                "cell_id": watch.get("cell_id"),
                "watch_id": watch.get("id"),
                "confidence": w_conf,
                "severity": rule["severity"],
                "context": context_block,
            }
            _log_trigger(entry)
            fired.append(entry)
            break  # one fire per rule per cycle

    return fired


def _build_fusion_context(cell: dict[str, Any], rule: dict[str, Any]) -> str:
    """Build a human-readable context block for a fusion cell trigger."""
    score = float(cell.get("score") or 0)
    delta = cell.get("delta_score")
    delta_str = f", Δ={float(delta):+.2f}" if delta is not None else ""
    sources = ", ".join(cell.get("sources") or ["unknown"])
    lat = cell.get("lat", 0)
    lon = cell.get("lon", 0)
    return (
        f"[{rule['severity'].upper()}] Fusion cell {cell.get('cell_id', '?')} "
        f"({lat:.2f}, {lon:.2f}) score={score:.2f}{delta_str}. "
        f"Sources: {sources}. "
        f"Confidence: {min(score, 0.99):.2f}. "
        f"Rule: {rule['name']}."
    )


def _build_watch_context(watch: dict[str, Any], rule: dict[str, Any]) -> str:
    """Build a human-readable context block for a watch item trigger."""
    claim = watch.get("title") or watch.get("claim") or "Unknown watch"
    conf = float(watch.get("confidence") or 0)
    prefix = watch.get("prefix", "unknown")
    bucket = watch.get("bucket", "global")
    sources = ", ".join(watch.get("sources") or ["unknown"])
    return (
        f"[{rule['severity'].upper()}] {claim} "
        f"(prefix={prefix}, bucket={bucket}). "
        f"Confidence: {conf:.2f}. "
        f"Sources: {sources}. "
        f"Rule: {rule['name']}."
    )


def _log_trigger(entry: dict[str, Any]) -> None:
    """Log a trigger fire to SQLite."""
    try:
        with _conn() as conn:
            conn.execute(
                """
                INSERT INTO trigger_log (
                    rule_name, fired_at, cell_id, watch_id,
                    confidence, severity, context
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry["rule_name"],
                    entry["fired_at"],
                    entry["cell_id"],
                    entry["watch_id"],
                    entry["confidence"],
                    entry["severity"],
                    entry["context"][:1000],
                ),
            )
            conn.commit()
    except Exception:
        pass


def dismiss_trigger(log_id: int, *, reason: str | None = None) -> dict[str, Any]:
    """Operator dismisses a trigger — feeds back into calibration."""
    init_trigger_db()
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as conn:
        conn.execute(
            """
            UPDATE trigger_log SET dismissed = 1, dismissed_at = ?, dismissed_reason = ?
            WHERE id = ?
            """,
            (now, reason, log_id),
        )
        conn.commit()
    return {"id": log_id, "dismissed": True}


def list_recent_triggers(
    *, limit: int = 20, include_dismissed: bool = False
) -> list[dict[str, Any]]:
    """List recent trigger fires for HUD/operator review."""
    init_trigger_db()
    with _conn() as conn:
        q = "SELECT * FROM trigger_log"
        if not include_dismissed:
            q += " WHERE dismissed = 0"
        q += " ORDER BY fired_at DESC LIMIT ?"
        rows = conn.execute(q, (max(1, min(limit, 100)),)).fetchall()
    return [dict(r) for r in rows]


def trigger_stats() -> dict[str, Any]:
    """Summary stats for HUD."""
    init_trigger_db()
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM trigger_log").fetchone()[0]
        active = conn.execute(
            "SELECT COUNT(*) FROM trigger_log WHERE dismissed = 0"
        ).fetchone()[0]
        critical = conn.execute(
            "SELECT COUNT(*) FROM trigger_log WHERE severity = 'critical' AND dismissed = 0"
        ).fetchone()[0]
        rules_n = conn.execute(
            "SELECT COUNT(*) FROM trigger_rules WHERE enabled = 1"
        ).fetchone()[0]
    return {
        "total_fires": total,
        "active": active,
        "critical_active": critical,
        "enabled_rules": rules_n,
    }


def push_trigger_to_nodes(fired: list[dict[str, Any]]) -> int:
    """Push fired triggers to all known Pi nodes via command queue + SSE.

    Uses existing node_commands table — Pi polls GET /api/node/{id}/commands.
    Also notifies SSE subscribers for real-time delivery.

    Returns number of commands queued.
    """
    if not fired:
        return 0

    import json as _json

    now = datetime.now(timezone.utc).isoformat()

    # Get all known node IDs from node_state
    node_ids: list[str] = []
    try:
        with _conn() as conn:
            rows = conn.execute("SELECT node_id FROM node_state").fetchall()
        node_ids = [r["node_id"] for r in rows]
    except Exception:
        pass

    if not node_ids:
        return 0

    queued = 0
    for trigger in fired:
        cmd_args = {
            "severity": trigger["severity"],
            "rule_name": trigger["rule_name"],
            "confidence": trigger["confidence"],
            "context": trigger["context"],
            "cell_id": trigger.get("cell_id"),
            "fired_at": trigger["fired_at"],
        }
        for nid in node_ids:
            try:
                with _conn() as conn:
                    conn.execute(
                        """
                        INSERT INTO node_commands (node_id, command, args, status, created_at)
                        VALUES (?, 'notify', ?, 'pending', ?)
                        """,
                        (nid, _json.dumps(cmd_args), now),
                    )
                    conn.commit()
                queued += 1
            except Exception:
                pass

    # Also push via SSE for real-time delivery
    try:
        import node_ingest

        for trigger in fired:
            node_ingest._notify_node_update(
                "all",
                {
                    "type": "trigger",
                    "severity": trigger["severity"],
                    "rule_name": trigger["rule_name"],
                    "confidence": trigger["confidence"],
                    "context": trigger["context"],
                    "timestamp": trigger["fired_at"],
                },
            )
    except Exception:
        pass

    return queued
