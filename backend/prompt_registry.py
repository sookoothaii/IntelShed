"""Prompt Registry — SQLite-backed prompt versioning + A/B testing (J1).

Stores prompt templates in SQLite with version history, default activation,
and A/B branch support. When WORLDBASE_PROMPT_REGISTRY=0 (default), callers
get hardcoded fallback prompts (backward compatible).

Tables:
  prompts: id, name, template, version, created_at, is_default
  prompt_variants: id, experiment_name, variant_a_id, variant_b_id,
                   traffic_split, created_at, status, winner_id
  prompt_results: id, experiment_name, variant, quality_score, created_at
"""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

_DB_PATH = os.getenv("WORLDBASE_DB_PATH", "") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)


def _truthy(val: str | None) -> bool:
    return str(val or "").strip().lower() in {"1", "true", "yes", "on"}


def prompt_registry_enabled() -> bool:
    return _truthy(os.getenv("WORLDBASE_PROMPT_REGISTRY", "0"))


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


def init_prompt_db() -> None:
    """Create tables if not exist."""
    try:
        conn = _get_conn()
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS prompts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                template TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                is_default INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_prompts_name ON prompts(name);
            CREATE INDEX IF NOT EXISTS idx_prompts_default ON prompts(is_default);

            CREATE TABLE IF NOT EXISTS prompt_variants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_name TEXT NOT NULL,
                variant_a_id INTEGER NOT NULL,
                variant_b_id INTEGER NOT NULL,
                traffic_split REAL DEFAULT 0.5,
                created_at TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                winner_id INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_variants_experiment ON prompt_variants(experiment_name);

            CREATE TABLE IF NOT EXISTS prompt_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                experiment_name TEXT NOT NULL,
                variant TEXT NOT NULL,
                quality_score REAL NOT NULL,
                briefing_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_results_experiment ON prompt_results(experiment_name);
            """
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def save_prompt(name: str, template: str, set_default: bool = False) -> int:
    """Save a new prompt version. Returns the prompt id."""
    init_prompt_db()
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    # Get next version number
    row = conn.execute(
        "SELECT MAX(version) as max_v FROM prompts WHERE name = ?", (name,)
    ).fetchone()
    version = (row["max_v"] or 0) + 1

    cursor = conn.execute(
        "INSERT INTO prompts (name, template, version, created_at, is_default) VALUES (?, ?, ?, ?, ?)",
        (name, template, version, now, 1 if set_default else 0),
    )
    prompt_id = cursor.lastrowid

    if set_default:
        # Unset other defaults for this name
        conn.execute(
            "UPDATE prompts SET is_default = 0 WHERE name = ? AND id != ?",
            (name, prompt_id),
        )

    conn.commit()
    conn.close()
    return prompt_id


def get_active(name: str) -> str | None:
    """Get the default prompt template by name.

    Returns None if registry disabled or no prompt found.
    """
    if not prompt_registry_enabled():
        return None

    init_prompt_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT template FROM prompts WHERE name = ? AND is_default = 1 ORDER BY version DESC LIMIT 1",
        (name,),
    ).fetchone()
    conn.close()
    return row["template"] if row else None


def get_active_id(name: str) -> int | None:
    """Get the default prompt id by name."""
    if not prompt_registry_enabled():
        return None
    init_prompt_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT id FROM prompts WHERE name = ? AND is_default = 1 ORDER BY version DESC LIMIT 1",
        (name,),
    ).fetchone()
    conn.close()
    return row["id"] if row else None


def activate_prompt(prompt_id: int) -> bool:
    """Set a prompt as the default for its name. Returns True on success."""
    init_prompt_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT name FROM prompts WHERE id = ?", (prompt_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    name = row["name"]
    conn.execute(
        "UPDATE prompts SET is_default = 0 WHERE name = ?", (name,)
    )
    conn.execute(
        "UPDATE prompts SET is_default = 1 WHERE id = ?", (prompt_id,)
    )
    conn.commit()
    conn.close()
    return True


def list_prompts(name: str | None = None) -> list[dict[str, Any]]:
    """List all prompts, optionally filtered by name."""
    init_prompt_db()
    conn = _get_conn()
    if name:
        rows = conn.execute(
            "SELECT * FROM prompts WHERE name = ? ORDER BY version DESC", (name,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM prompts ORDER BY name, version DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_experiment(
    experiment_name: str,
    variant_a_id: int,
    variant_b_id: int,
    traffic_split: float = 0.5,
) -> int:
    """Create an A/B experiment. Returns experiment id."""
    init_prompt_db()
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    cursor = conn.execute(
        "INSERT INTO prompt_variants (experiment_name, variant_a_id, variant_b_id, traffic_split, created_at) VALUES (?, ?, ?, ?, ?)",
        (experiment_name, variant_a_id, variant_b_id, traffic_split, now),
    )
    exp_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return exp_id


def get_experiment(experiment_name: str) -> dict[str, Any] | None:
    """Get active experiment by name."""
    init_prompt_db()
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM prompt_variants WHERE experiment_name = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
        (experiment_name,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def select_variant(experiment_name: str) -> str:
    """Select which variant to use for this run (A or B).

    Uses traffic_split probability. Returns 'a' or 'b'.
    """
    exp = get_experiment(experiment_name)
    if not exp:
        return "a"
    import random

    return "a" if random.random() < exp["traffic_split"] else "b"


def record_result(
    experiment_name: str, variant: str, quality_score: float, briefing_id: str = ""
) -> None:
    """Record a quality score for an experiment variant."""
    init_prompt_db()
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    conn.execute(
        "INSERT INTO prompt_results (experiment_name, variant, quality_score, briefing_id, created_at) VALUES (?, ?, ?, ?, ?)",
        (experiment_name, variant, quality_score, briefing_id, now),
    )
    conn.commit()
    conn.close()


def get_results(experiment_name: str) -> dict[str, list[float]]:
    """Get all quality scores grouped by variant for an experiment."""
    init_prompt_db()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT variant, quality_score FROM prompt_results WHERE experiment_name = ?",
        (experiment_name,),
    ).fetchall()
    conn.close()
    results: dict[str, list[float]] = {"a": [], "b": []}
    for r in rows:
        v = r["variant"]
        if v in results:
            results[v].append(r["quality_score"])
    return results


def set_experiment_winner(experiment_name: str, variant: str, winner_prompt_id: int) -> None:
    """Mark experiment as concluded with a winner."""
    init_prompt_db()
    conn = _get_conn()
    conn.execute(
        "UPDATE prompt_variants SET status = 'concluded', winner_id = ? WHERE experiment_name = ? AND status = 'active'",
        (winner_prompt_id, experiment_name),
    )
    conn.commit()
    conn.close()


def list_experiments() -> list[dict[str, Any]]:
    """List all experiments."""
    init_prompt_db()
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM prompt_variants ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
