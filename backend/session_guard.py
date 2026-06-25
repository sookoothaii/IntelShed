"""Layer 2 — Cross-Turn Session Guard.

Tracks multi-turn social engineering attacks via SQLite-persisted session state.
Individual turns may be harmless, but accumulated patterns (role-play → persona → override)
trigger escalating actions: warn → block → lock.

Integration point: at the start of chat_proxy._prepare_chat_messages() or chat endpoint.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from structured_log import get_logger

log = get_logger("session_guard")


def _db_path() -> str:
    return os.getenv("WORLDBASE_DB_PATH") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
    )


def _enabled() -> bool:
    return os.getenv("WORLDBASE_SESSION_GUARD", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


@dataclass
class TurnSignal:
    roleplay_score: float
    game_score: float
    authority_score: float
    emotional_score: float
    instruction_count: int


_ROLEPLAY_PATTERNS = [
    "act as",
    "pretend",
    "you are now",
    "you are a",
    "roleplay",
    "you're a",
]
_GAME_PATTERNS = ["let's play", "game", "imagine", "different ai", "called", "freeai"]
_AUTHORITY_PATTERNS = [
    "admin",
    "developer",
    "override",
    "maintenance mode",
    "command you",
    "administrator",
]
_EMOTIONAL_PATTERNS = [
    "desperate",
    "life depends",
    "please ignore",
    "just this once",
    "i beg",
    "urgent",
]
_INSTRUCTION_STARTS = [
    "ignore",
    "disregard",
    "override",
    "forget",
    "do not follow",
    "bypass",
]


class SessionGuard:
    """Stateful multi-turn attack detector with SQLite persistence."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or _db_path()
        self._init_table()

    def _init_table(self) -> None:
        try:
            conn = sqlite3.connect(self._db_path, timeout=3.0)
            conn.execute("PRAGMA busy_timeout=3000")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS session_guard_state (
                    session_id  TEXT PRIMARY KEY,
                    total_score REAL DEFAULT 0,
                    turn_count  INTEGER DEFAULT 0,
                    last_turn   REAL DEFAULT 0,
                    flags       TEXT DEFAULT '{}'
                )
                """
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            log.warning("session_guard_init_failed", error=str(exc))

    def _analyze_turn(self, message: str) -> TurnSignal:
        """Extract suspicious signals from a single turn."""
        msg_lower = message.lower()

        roleplay = sum(1 for p in _ROLEPLAY_PATTERNS if p in msg_lower) * 0.3
        game = sum(1 for p in _GAME_PATTERNS if p in msg_lower) * 0.3
        authority = sum(1 for p in _AUTHORITY_PATTERNS if p in msg_lower) * 0.4
        emotional = sum(1 for p in _EMOTIONAL_PATTERNS if p in msg_lower) * 0.25

        sentences = msg_lower.split(".")
        instruction_count = sum(
            1
            for s in sentences
            if any(s.strip().startswith(w) for w in _INSTRUCTION_STARTS)
        )

        return TurnSignal(
            roleplay_score=min(roleplay, 1.0),
            game_score=min(game, 1.0),
            authority_score=min(authority, 1.0),
            emotional_score=min(emotional, 1.0),
            instruction_count=instruction_count,
        )

    def check_session(self, session_id: str, message: str) -> dict[str, Any]:
        """Main entry. Called on every chat turn.

        Returns: {action, session_score, turn_score, turn_count, signal}
        action ∈ {"pass", "warn", "block", "lock"}
        """
        if not _enabled():
            return {
                "action": "pass",
                "session_score": 0,
                "turn_score": 0,
                "turn_count": 0,
                "signal": {},
            }

        signal = self._analyze_turn(message)
        turn_score = (
            signal.roleplay_score
            + signal.game_score
            + signal.authority_score
            + signal.emotional_score
            + signal.instruction_count * 0.2
        )

        now = time.time()
        try:
            conn = sqlite3.connect(self._db_path, timeout=3.0)
            conn.execute("PRAGMA busy_timeout=3000")
            row = conn.execute(
                "SELECT total_score, turn_count, last_turn FROM session_guard_state WHERE session_id = ?",
                (session_id,),
            ).fetchone()

            if row:
                total_score, turn_count, last_turn = row
                # Exponential decay: score halves every 10 minutes
                time_factor = 0.5 ** ((now - last_turn) / 600)
                total_score = total_score * time_factor + turn_score
                turn_count += 1
            else:
                total_score = turn_score
                turn_count = 1

            action = "pass"
            if total_score >= 3.0:
                action = "lock"
            elif total_score >= 2.0:
                action = "block"
            elif total_score >= 1.0:
                action = "warn"

            conn.execute(
                """INSERT OR REPLACE INTO session_guard_state
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    session_id,
                    total_score,
                    turn_count,
                    now,
                    json.dumps({"action": action}),
                ),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            log.debug("session_guard_db_error", error=str(exc))
            total_score = turn_score
            turn_count = 1
            action = (
                "block"
                if total_score >= 2.0
                else ("warn" if total_score >= 1.0 else "pass")
            )

        if action in ("warn", "block", "lock"):
            log.warning(
                "session_guard_triggered",
                session_id=session_id,
                action=action,
                session_score=round(total_score, 2),
                turn_score=round(turn_score, 2),
                turn_count=turn_count,
            )

        return {
            "action": action,
            "session_score": round(total_score, 2),
            "turn_score": round(turn_score, 2),
            "turn_count": turn_count,
            "signal": {
                "roleplay": signal.roleplay_score,
                "game": signal.game_score,
                "authority": signal.authority_score,
                "emotional": signal.emotional_score,
                "instructions": signal.instruction_count,
            },
        }

    def reset_session(self, session_id: str) -> None:
        """Clear session state (e.g. after lock expires)."""
        try:
            conn = sqlite3.connect(self._db_path, timeout=3.0)
            conn.execute("PRAGMA busy_timeout=3000")
            conn.execute(
                "DELETE FROM session_guard_state WHERE session_id = ?", (session_id,)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass


_guard: SessionGuard | None = None


def get_guard() -> SessionGuard:
    global _guard
    if _guard is None:
        _guard = SessionGuard()
    return _guard
