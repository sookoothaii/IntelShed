"""MCP per-tool quota tracking and enforcement (E-06).

Tracks per-tool invocations in SQLite `mcp_quota` table with daily and hourly
windows. Enforces configurable limits with hard stop at 100%.

Feature flag: WORLDBASE_MCP_QUOTA=1 (default off — opt-in).

Integrates into _gate_mcp_tool in mcp_server.py:
    from mcp_quota import check_and_record
    await check_and_record(tool_name)  # raises QuotaExceeded on limit hit
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from structured_log import get_logger

log = get_logger("mcp_quota")


class QuotaExceeded(Exception):
    """Raised when a tool has hit its daily or hourly limit."""

    def __init__(self, tool: str, window: str, count: int, limit: int) -> None:
        self.tool = tool
        self.window = window
        self.count = count
        self.limit = limit
        super().__init__(f"MCP quota exceeded for '{tool}' ({window}): {count}/{limit}")


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def quota_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_MCP_QUOTA", "0"))


_ALERT_THRESHOLD = float(os.getenv("WORLDBASE_MCP_QUOTA_ALERT_THRESHOLD", "0.8"))

# Default per-tool daily limits. Override via WORLDBASE_MCP_QUOTA_DAILY_{TOOL_SHORT}.
# Tool short name = tool name without 'worldbase_' prefix, uppercased.
_DEFAULT_DAILY_LIMITS: dict[str, int] = {
    "BRIEFING_GENERATE": 20,
    "CHAT": 100,
    "ORCHESTRATE": 50,
    "DARKWEB_SEARCH": 30,
    "DOMAIN_INTEL": 50,
    "BREACH_CHECK_PASSWORD": 20,
    "CYBER_IP_LOOKUP": 100,
}

# Default per-tool hourly limits. Override via WORLDBASE_MCP_QUOTA_HOURLY_{TOOL_SHORT}.
_DEFAULT_HOURLY_LIMITS: dict[str, int] = {
    "BRIEFING_GENERATE": 5,
    "CHAT": 20,
    "ORCHESTRATE": 10,
    "DARKWEB_SEARCH": 10,
}


def _db_path() -> str:
    custom = os.getenv("WORLDBASE_DB_PATH", "").strip()
    if custom:
        return custom
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "worldbase.db")


def _tool_short(tool_name: str) -> str:
    if tool_name.startswith("worldbase_"):
        return tool_name[len("worldbase_") :]
    return tool_name


def _get_daily_limit(tool: str) -> int:
    short = _tool_short(tool).upper()
    env_val = os.getenv(f"WORLDBASE_MCP_QUOTA_DAILY_{short}")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    return _DEFAULT_DAILY_LIMITS.get(short, 0)


def _get_hourly_limit(tool: str) -> int:
    short = _tool_short(tool).upper()
    env_val = os.getenv(f"WORLDBASE_MCP_QUOTA_HOURLY_{short}")
    if env_val:
        try:
            return int(env_val)
        except ValueError:
            pass
    return _DEFAULT_HOURLY_LIMITS.get(short, 0)


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_hour() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")


def init_quota_db() -> None:
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_quota (
                tool        TEXT NOT NULL,
                window      TEXT NOT NULL,
                window_key  TEXT NOT NULL,
                count       INTEGER DEFAULT 0,
                limit_val   INTEGER DEFAULT 0,
                last_call_at REAL DEFAULT 0,
                PRIMARY KEY (tool, window, window_key)
            )
            """
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("mcp_quota_init_failed", error=str(exc))


def _get_count(tool: str, window: str, window_key: str) -> tuple[int, int]:
    """Return (current_count, limit) for a tool/window/key. Fail-soft → (0, 0)."""
    if window == "daily":
        limit = _get_daily_limit(tool)
    else:
        limit = _get_hourly_limit(tool)
    if limit <= 0:
        return 0, 0
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        row = conn.execute(
            "SELECT count FROM mcp_quota WHERE tool = ? AND window = ? AND window_key = ?",
            (tool, window, window_key),
        ).fetchone()
        conn.close()
        return (row[0] if row else 0), limit
    except Exception:
        return 0, limit


def _increment(tool: str, window: str, window_key: str, limit: int) -> None:
    try:
        now = time.time()
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute(
            """
            INSERT INTO mcp_quota (tool, window, window_key, count, limit_val, last_call_at)
            VALUES (?, ?, ?, 1, ?, ?)
            ON CONFLICT(tool, window, window_key)
            DO UPDATE SET count = count + 1, last_call_at = ?
            """,
            (tool, window, window_key, limit, now, now),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.debug("mcp_quota_increment_failed", error=str(exc))


async def check_and_record(tool_name: str) -> None:
    """Check quota for a tool and record the call. Raises QuotaExceeded if over limit.

    Fail-soft: if quota is disabled or DB errors occur, the call proceeds.
    """
    if not quota_enabled():
        return

    # Check daily
    day = _utc_day()
    daily_count, daily_limit = _get_count(tool_name, "daily", day)
    if daily_limit > 0 and daily_count >= daily_limit:
        log.warning(
            "mcp_quota_exceeded",
            tool=tool_name,
            window="daily",
            count=daily_count,
            limit=daily_limit,
        )
        raise QuotaExceeded(tool_name, "daily", daily_count, daily_limit)

    # Check hourly
    hour = _utc_hour()
    hourly_count, hourly_limit = _get_count(tool_name, "hourly", hour)
    if hourly_limit > 0 and hourly_count >= hourly_limit:
        log.warning(
            "mcp_quota_exceeded",
            tool=tool_name,
            window="hourly",
            count=hourly_count,
            limit=hourly_limit,
        )
        raise QuotaExceeded(tool_name, "hourly", hourly_count, hourly_limit)

    # Record
    if daily_limit > 0:
        _increment(tool_name, "daily", day, daily_limit)
    if hourly_limit > 0:
        _increment(tool_name, "hourly", hour, hourly_limit)


def get_tool_usage(tool: str) -> dict[str, Any]:
    """Get current usage for a specific tool (daily + hourly)."""
    day = _utc_day()
    hour = _utc_hour()
    daily_count, daily_limit = _get_count(tool, "daily", day)
    hourly_count, hourly_limit = _get_count(tool, "hourly", hour)
    return {
        "tool": tool,
        "daily": {
            "window_key": day,
            "count": daily_count,
            "limit": daily_limit,
            "remaining": max(0, daily_limit - daily_count) if daily_limit > 0 else -1,
            "pct": round(daily_count / daily_limit, 4) if daily_limit > 0 else 0.0,
            "exceeded": daily_count >= daily_limit if daily_limit > 0 else False,
        },
        "hourly": {
            "window_key": hour,
            "count": hourly_count,
            "limit": hourly_limit,
            "remaining": max(0, hourly_limit - hourly_count)
            if hourly_limit > 0
            else -1,
            "pct": round(hourly_count / hourly_limit, 4) if hourly_limit > 0 else 0.0,
            "exceeded": hourly_count >= hourly_limit if hourly_limit > 0 else False,
        },
    }


def get_quota_status() -> dict[str, Any]:
    """Full MCP quota dashboard: all configured tools, daily + hourly usage."""
    tools = set(_DEFAULT_DAILY_LIMITS.keys()) | set(_DEFAULT_HOURLY_LIMITS.keys())
    # Also include any tools seen in the DB
    try:
        conn = sqlite3.connect(_db_path(), timeout=3.0)
        conn.execute("PRAGMA busy_timeout=3000")
        rows = conn.execute("SELECT DISTINCT tool FROM mcp_quota").fetchall()
        conn.close()
        for r in rows:
            tools.add(r[0])
    except Exception:
        pass

    status = []
    exceeded = []
    for tool in sorted(tools):
        usage = get_tool_usage(
            f"worldbase_{tool.lower()}" if not tool.startswith("worldbase_") else tool
        )
        status.append(usage)
        if usage["daily"]["exceeded"] or usage["hourly"]["exceeded"]:
            exceeded.append(usage["tool"])

    return {
        "enabled": quota_enabled(),
        "alert_threshold": _ALERT_THRESHOLD,
        "tools": status,
        "quota_exceeded": exceeded,
    }


def check_alerts() -> list[dict[str, Any]]:
    """Check for 80% threshold alerts across all configured tools."""
    if not quota_enabled():
        return []
    fired: list[dict[str, Any]] = []
    tools = set(_DEFAULT_DAILY_LIMITS.keys()) | set(_DEFAULT_HOURLY_LIMITS.keys())
    for tool_short in sorted(tools):
        tool = f"worldbase_{tool_short.lower()}"
        usage = get_tool_usage(tool)
        for window in ("daily", "hourly"):
            w = usage[window]
            if w["limit"] <= 0:
                continue
            if w["exceeded"]:
                fired.append(
                    {
                        "alert": "mcp_quota_exceeded",
                        "severity": "critical",
                        "tool": tool,
                        "window": window,
                        "count": w["count"],
                        "limit": w["limit"],
                        "message": f"MCP quota for {tool} ({window}) exceeded: {w['count']}/{w['limit']}",
                    }
                )
            elif w["pct"] >= _ALERT_THRESHOLD:
                fired.append(
                    {
                        "alert": "mcp_quota_80_percent",
                        "severity": "warning",
                        "tool": tool,
                        "window": window,
                        "count": w["count"],
                        "limit": w["limit"],
                        "pct": w["pct"],
                        "message": f"MCP quota for {tool} ({window}) at {w['pct']:.0%}: {w['count']}/{w['limit']}",
                    }
                )
    return fired
