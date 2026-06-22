"""Track 4 — append-only watch-item prediction ledger with rule-based outcomes."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

_DB_PATH = os.getenv("WORLDBASE_DB_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "worldbase.db"
)
_WINDOW_DAYS = int(os.getenv("WORLDBASE_PREDICTION_WINDOW_DAYS", "30") or "30")
_RESOLVE_INTERVAL_S = float(os.getenv("WORLDBASE_PREDICTION_RESOLVE_INTERVAL_S", "3600"))


def autopilot_on() -> bool:
    return os.getenv("WORLDBASE_PREDICTION_LEDGER", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def resolve_interval_s() -> float:
    return max(300.0, _RESOLVE_INTERVAL_S)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_prediction_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS briefing_predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                watch_id TEXT NOT NULL,
                prefix TEXT,
                issued_at TEXT NOT NULL,
                horizon_h INTEGER NOT NULL,
                claim TEXT NOT NULL,
                sources TEXT NOT NULL,
                cell_id TEXT,
                bucket TEXT,
                outcome TEXT,
                outcome_at TEXT,
                hit INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_briefing_pred_issued
                ON briefing_predictions(issued_at);
            CREATE INDEX IF NOT EXISTS idx_briefing_pred_pending
                ON briefing_predictions(hit, issued_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_briefing_pred_watch_issue
                ON briefing_predictions(watch_id, issued_at);
        """)
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


def _parse_cell_id(cell_id: str | None) -> tuple[float, float] | None:
    if not cell_id or "," not in cell_id:
        return None
    try:
        lat_s, lon_s = cell_id.split(",", 1)
        return float(lat_s), float(lon_s)
    except (TypeError, ValueError):
        return None


def _near_point(
    lat: float | None,
    lon: float | None,
    cell_id: str | None,
    *,
    km: float = 250.0,
) -> bool:
    if lat is None or lon is None:
        return True
    anchor = _parse_cell_id(cell_id)
    if anchor is None:
        return True
    from operator_briefing import haversine_km

    return haversine_km(lat, lon, anchor[0], anchor[1]) <= km


def record_watch_items(watch_items: list[dict[str, Any]], issued_at: str) -> int:
    """Append watch items from a briefing cycle (dedupe watch_id + issued_at)."""
    if not watch_items or not issued_at:
        return 0
    init_prediction_db()
    inserted = 0
    with _conn() as conn:
        for item in watch_items:
            watch_id = str(item.get("id") or "").strip()
            if not watch_id:
                continue
            claim = str(item.get("title") or "")[:200]
            if not claim:
                continue
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO briefing_predictions (
                        watch_id, prefix, issued_at, horizon_h, claim, sources,
                        cell_id, bucket, outcome, outcome_at, hit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)
                    """,
                    (
                        watch_id,
                        item.get("prefix"),
                        issued_at,
                        max(24, min(72, int(item.get("horizon_h") or 48))),
                        claim,
                        json.dumps(list(item.get("sources") or [])),
                        item.get("cell_id"),
                        item.get("bucket"),
                    ),
                )
                if conn.total_changes:
                    inserted += 1
            except Exception:
                continue
        conn.commit()
    return inserted


def _eval_cams(row: sqlite3.Row, snap: dict[str, Any]) -> tuple[bool, str]:
    cities = (snap.get("cams_haze") or {}).get("cities") or []
    claim = row["claim"] or ""
    city_hint = ""
    if "—" in claim:
        tail = claim.split("—", 1)[1]
        city_hint = tail.split(":", 1)[0].strip().lower()
    matched: list[dict] = []
    for row_city in cities:
        name = str(row_city.get("city") or "").lower()
        if city_hint and city_hint not in name and name not in city_hint:
            continue
        if row["cell_id"] and not _near_point(
            row_city.get("lat"), row_city.get("lon"), row["cell_id"], km=120.0
        ):
            continue
        matched.append(row_city)
    if not matched and cities and row["cell_id"]:
        matched = [
            c
            for c in cities
            if _near_point(c.get("lat"), c.get("lon"), row["cell_id"], km=120.0)
        ]
    if not matched:
        return False, "no haze data for watch cell"
    peak_pm25 = max(float(c.get("pm25") or 0) for c in matched)
    sev_high = any((c.get("severity") or "").lower() == "high" for c in matched)
    if peak_pm25 >= 55 or sev_high:
        return True, f"PM2.5 peak {peak_pm25:.0f} µg/m³ (high haze persisted)"
    if peak_pm25 >= 35:
        return True, f"PM2.5 peak {peak_pm25:.0f} µg/m³ (moderate haze persisted)"
    if peak_pm25 < 25:
        return False, f"PM2.5 eased to {peak_pm25:.0f} µg/m³"
    return False, f"PM2.5 {peak_pm25:.0f} µg/m³ below watch threshold"


def _eval_quake(row: sqlite3.Row, snap: dict[str, Any]) -> tuple[bool, str]:
    quakes = (snap.get("earthquakes") or {}).get("earthquakes") or []
    best_mag = 0.0
    for q in quakes:
        mag = float(q.get("mag") or q.get("magnitude") or 0)
        if mag < 5.0:
            continue
        if not _near_point(q.get("lat"), q.get("lon"), row["cell_id"], km=250.0):
            continue
        best_mag = max(best_mag, mag)
    if best_mag >= 5.0:
        return True, f"M{best_mag:.1f} within watch cell"
    return False, "no M≥5 quake in watch cell"


def _eval_gdacs(row: sqlite3.Row, snap: dict[str, Any]) -> tuple[bool, str]:
    alerts = (snap.get("gdacs") or {}).get("alerts") or []
    claim_low = (row["claim"] or "").lower()
    for alert in alerts:
        title = str(alert.get("title") or "").lower()
        if claim_low and title and title[:40] not in claim_low and claim_low[:40] not in title:
            if row["cell_id"] and not _near_point(
                alert.get("lat"), alert.get("lon"), row["cell_id"], km=300.0
            ):
                continue
        level = str(alert.get("alertlevel") or alert.get("severity") or "").lower()
        if "red" in level or "orange" in level:
            return True, f"GDACS alert active ({level or 'elevated'})"
        if _near_point(alert.get("lat"), alert.get("lon"), row["cell_id"], km=300.0):
            return True, "GDACS alert still in watch area"
    return False, "no GDACS alert in watch area"


def _eval_gdelt(row: sqlite3.Row, snap: dict[str, Any]) -> tuple[bool, str]:
    pulse_n = len((snap.get("gdelt_pulse_local") or {}).get("articles") or [])
    geo_n = len((snap.get("gdelt_geo_local") or {}).get("events") or [])
    if pulse_n >= 4 or geo_n >= 3:
        return True, f"media attention elevated ({pulse_n} pulse, {geo_n} geo)"
    if pulse_n < 3 and geo_n < 2:
        return False, f"media attention eased ({pulse_n} pulse, {geo_n} geo)"
    return False, f"media attention mixed ({pulse_n} pulse, {geo_n} geo)"


_THAI_CORRIDOR_REGIONS = ("malacca", "laem_chabang", "bangkok_port", "phuket")
_MARITIME_DENSITY_MIN = 12


def _thai_corridor_vessel_count(snap: dict[str, Any]) -> int:
    vessels = (snap.get("maritime") or {}).get("vessels") or []
    return sum(
        1
        for v in vessels
        if (v.get("region") or "") in _THAI_CORRIDOR_REGIONS
    )


def _eval_maritime(row: sqlite3.Row, snap: dict[str, Any]) -> tuple[bool, str]:
    count = _thai_corridor_vessel_count(snap)
    claim = row["claim"] or ""
    baseline: int | None = None
    if "—" in claim:
        tail = claim.split("—", 1)[1]
        digits = "".join(ch if ch.isdigit() else " " for ch in tail).split()
        if digits:
            try:
                baseline = int(digits[0])
            except ValueError:
                baseline = None
    if count >= _MARITIME_DENSITY_MIN:
        if baseline and count >= int(baseline * 0.75):
            return True, f"corridor density sustained ({count} vessels)"
        if baseline is None:
            return True, f"corridor density sustained ({count} vessels)"
        return True, f"corridor still active ({count} vs baseline {baseline})"
    if baseline and count >= max(8, int(baseline * 0.5)):
        return True, f"moderate corridor traffic ({count} vessels)"
    return False, f"corridor density eased ({count} vessels)"


def _eval_hdx(row: sqlite3.Row, snap: dict[str, Any]) -> tuple[bool, str]:
    datasets = (snap.get("humanitarian") or {}).get("datasets") or []
    claim = row["claim"] or ""
    title_hint = ""
    if "—" in claim:
        title_hint = claim.split("—", 1)[1].strip().lower()
    if not title_hint and "watch" in claim.lower():
        tail = claim.split("watch", 1)[-1].strip(" —-")
        title_hint = tail.lower()
    if title_hint:
        for ds in datasets:
            title = str(ds.get("title") or "").lower()
            if not title:
                continue
            if title_hint in title or title[:60] in title_hint or title_hint[:40] in title:
                return True, f"HDX dataset still listed ({str(ds.get('title') or '')[:60]})"
    if len(datasets) >= 3:
        return True, f"regional humanitarian activity persists ({len(datasets)} datasets)"
    if datasets and not title_hint:
        return True, f"humanitarian feed active ({len(datasets)} datasets)"
    return False, "watched HDX dataset no longer in feed"


def _eval_alert(row: sqlite3.Row, snap: dict[str, Any]) -> tuple[bool, str]:
    from node_sync import _compile_alerts

    claim = (row["claim"] or "").strip()
    claim_low = claim.lower()
    if not claim_low:
        return False, "empty alert claim"
    for alert in _compile_alerts(snap):
        text = str(alert.get("text") or "")
        text_low = text.lower()
        if not text_low:
            continue
        if row["cell_id"] and not _near_point(
            alert.get("lat"), alert.get("lon"), row["cell_id"], km=300.0
        ):
            continue
        if claim_low == text_low or claim_low in text_low or text_low in claim_low:
            sev = (alert.get("severity") or "elevated").lower()
            return True, f"alert still active ({sev})"
        if claim_low[:50] in text_low or text_low[:50] in claim_low:
            return True, "matching alert still in feed"
    if "gdacs" in claim_low:
        n = int((snap.get("gdacs") or {}).get("count") or 0)
        if n >= 5:
            return True, f"GDACS feed still active ({n} alerts)"
        return False, f"GDACS count eased ({n})"
    if any(k in claim_low for k in ("nws", "meteoalarm", "tornado", "flood warning", "hazard")):
        n = int((snap.get("hazards") or {}).get("count") or 0)
        if n >= 10:
            return True, f"hazards feed still active ({n} alerts)"
        return False, f"hazards count eased ({n})"
    if "earthquake" in claim_low or claim_low.startswith("m"):
        return _eval_quake(row, snap)
    if "kev" in claim_low or "cve-" in claim_low:
        cves = (snap.get("cve") or {}).get("vulnerabilities") or []
        if cves:
            return True, f"KEV catalog still active ({len(cves)} entries)"
        return False, "KEV feed empty"
    if "outage" in claim_low or "ioda" in claim_low:
        n = int((snap.get("outages") or {}).get("count") or 0)
        if n >= 1:
            return True, f"outage signals still present ({n})"
        return False, "outage signals cleared"
    return False, "alert condition no longer present"


def _eval_fusion(
    row: sqlite3.Row,
    fusion_cells: list[dict[str, Any]] | None,
) -> tuple[bool, str]:
    cells = fusion_cells or []
    target = row["cell_id"]
    for cell in cells:
        cid = cell.get("cell_id")
        if target and cid != target:
            if not _near_point(cell.get("lat"), cell.get("lon"), target, km=120.0):
                continue
        score = float(cell.get("score") or 0)
        delta = cell.get("delta_score")
        delta_f = float(delta) if delta is not None else None
        if score >= 0.45:
            return True, f"fusion cell score {score:.2f} still elevated"
        if delta_f is not None and delta_f >= 0.12:
            return True, f"fusion delta {delta_f:+.2f} still rising"
    return False, "fusion cell cooled below threshold"


def _eval_spacewx(row: sqlite3.Row, snap: dict[str, Any]) -> tuple[bool, str]:
    sw = snap.get("spaceweather") or {}
    kp = sw.get("kp_index")
    if kp is None:
        return False, "space weather feed unavailable"
    kp_f = float(kp)
    if kp_f >= 5.0:
        return True, f"Kp {kp_f:.1f} still elevated"
    if kp_f < 4.0:
        return False, f"Kp eased to {kp_f:.1f}"
    return False, f"Kp {kp_f:.1f} below storm threshold"


def _evaluate_row(
    row: sqlite3.Row,
    snap: dict[str, Any],
    fusion_cells: list[dict[str, Any]] | None,
) -> tuple[bool, str]:
    prefix = (row["prefix"] or "").strip().lower()
    sources = []
    try:
        sources = json.loads(row["sources"] or "[]")
    except Exception:
        sources = []

    if prefix in ("cams",) or "cams_haze" in sources:
        return _eval_cams(row, snap)
    if prefix in ("quake",) or "earthquakes" in sources:
        return _eval_quake(row, snap)
    if prefix in ("gdacs",) or "gdacs" in sources:
        return _eval_gdacs(row, snap)
    if prefix in ("gdelt",) or "gdelt_pulse_local" in sources or "gdelt_geo_local" in sources:
        return _eval_gdelt(row, snap)
    if prefix in ("fusion", "fusion_delta") or "fusion" in sources:
        return _eval_fusion(row, fusion_cells)
    if prefix in ("spacewx",) or "spaceweather" in sources:
        return _eval_spacewx(row, snap)
    if prefix in ("maritime",) or "maritime" in sources:
        return _eval_maritime(row, snap)
    if prefix in ("hdx",) or "humanitarian" in sources:
        return _eval_hdx(row, snap)
    if prefix in ("alert",) or "alerts" in sources:
        return _eval_alert(row, snap)

    return False, f"unsupported watch prefix={prefix or 'unknown'}"


def resolve_pending(
    snap: dict[str, Any],
    fusion_cells: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve matured predictions (issued_at + horizon_h <= now)."""
    init_prediction_db()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    resolved = 0
    hits = 0
    misses = 0
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM briefing_predictions WHERE hit IS NULL ORDER BY issued_at ASC"
        ).fetchall()
        for row in rows:
            issued = _parse_ts(row["issued_at"])
            if issued is None:
                continue
            due = issued + timedelta(hours=int(row["horizon_h"] or 48))
            if now < due:
                continue
            hit, outcome = _evaluate_row(row, snap, fusion_cells)
            conn.execute(
                """
                UPDATE briefing_predictions
                SET hit = ?, outcome = ?, outcome_at = ?
                WHERE id = ?
                """,
                (1 if hit else 0, outcome[:500], now_iso, row["id"]),
            )
            resolved += 1
            if hit:
                hits += 1
            else:
                misses += 1
        conn.commit()
    return {"resolved": resolved, "hits": hits, "misses": misses}


def accuracy_30d(*, window_days: int | None = None) -> dict[str, Any]:
    """Hit rate over resolved predictions in the rolling window."""
    init_prediction_db()
    days = window_days if window_days is not None else _WINDOW_DAYS
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as conn:
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM briefing_predictions WHERE hit IS NULL"
        ).fetchone()
        resolved = conn.execute(
            """
            SELECT
                SUM(CASE WHEN hit = 1 THEN 1 ELSE 0 END) AS hits,
                SUM(CASE WHEN hit = 0 THEN 1 ELSE 0 END) AS misses
            FROM briefing_predictions
            WHERE hit IS NOT NULL AND issued_at >= ?
            """,
            (cutoff,),
        ).fetchone()
    hit_n = int(resolved["hits"] or 0) if resolved else 0
    miss_n = int(resolved["misses"] or 0) if resolved else 0
    sample = hit_n + miss_n
    accuracy = round(hit_n / sample, 3) if sample else None
    return {
        "window_days": days,
        "accuracy": accuracy,
        "hits": hit_n,
        "misses": miss_n,
        "sample_size": sample,
        "pending": int(pending["n"] or 0) if pending else 0,
    }


def _serialize_row(row: sqlite3.Row) -> dict[str, Any]:
    issued = _parse_ts(row["issued_at"])
    horizon = int(row["horizon_h"] or 48)
    due = (issued + timedelta(hours=horizon)) if issued else None
    now = datetime.now(timezone.utc)
    hit = row["hit"]
    overdue = bool(due and now >= due and hit is None)
    sources: list[str] = []
    try:
        sources = json.loads(row["sources"] or "[]")
    except Exception:
        sources = []
    return {
        "id": int(row["id"]),
        "watch_id": row["watch_id"],
        "prefix": row["prefix"],
        "claim": row["claim"],
        "issued_at": row["issued_at"],
        "due_at": due.isoformat() if due else None,
        "horizon_h": horizon,
        "bucket": row["bucket"],
        "cell_id": row["cell_id"],
        "sources": sources,
        "overdue": overdue,
        "hit": hit,
        "outcome": row["outcome"],
        "outcome_at": row["outcome_at"],
    }


def list_predictions(
    *,
    pending_limit: int = 8,
    resolved_limit: int = 5,
) -> dict[str, Any]:
    """Pending + recently resolved watch outcomes for HUD / trust."""
    init_prediction_db()
    stats = accuracy_30d()
    now = datetime.now(timezone.utc)
    pending_cap = max(1, min(int(pending_limit), 50))
    resolved_cap = max(1, min(int(resolved_limit), 30))
    with _conn() as conn:
        pending_rows = conn.execute(
            """
            SELECT * FROM briefing_predictions
            WHERE hit IS NULL
            ORDER BY issued_at ASC
            LIMIT ?
            """,
            (pending_cap,),
        ).fetchall()
        resolved_rows = conn.execute(
            """
            SELECT * FROM briefing_predictions
            WHERE hit IS NOT NULL
            ORDER BY outcome_at DESC
            LIMIT ?
            """,
            (resolved_cap,),
        ).fetchall()
        all_pending = conn.execute(
            """
            SELECT issued_at, horizon_h FROM briefing_predictions
            WHERE hit IS NULL
            """
        ).fetchall()
    overdue_count = 0
    due_next: str | None = None
    for row in all_pending:
        issued = _parse_ts(row["issued_at"])
        if issued is None:
            continue
        due = issued + timedelta(hours=int(row["horizon_h"] or 48))
        if now >= due:
            overdue_count += 1
        elif due_next is None or due < _parse_ts(due_next):
            due_next = due.isoformat()
    return {
        "stats": stats,
        "pending": [_serialize_row(r) for r in pending_rows],
        "resolved_recent": [_serialize_row(r) for r in resolved_rows],
        "overdue_count": overdue_count,
        "due_next": due_next,
    }


def list_watches_for_rag(*, limit: int = 150) -> list[dict[str, Any]]:
    """Pending + recently resolved watch items for RAG indexing (Track R0.3)."""
    init_prediction_db()
    cap = max(1, min(int(limit), 500))
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM briefing_predictions
            ORDER BY
                CASE WHEN hit IS NULL THEN 0 ELSE 1 END,
                issued_at DESC
            LIMIT ?
            """,
            (cap,),
        ).fetchall()
    return [_serialize_row(r) for r in rows]


def enrich_quality_meta(quality: dict[str, Any] | None) -> dict[str, Any] | None:
    """Merge live 30d ledger stats into stored briefing quality.meta."""
    if not quality:
        return quality
    stats = accuracy_30d()
    out = dict(quality)
    meta = dict(out.get("meta") or {})
    meta["prediction_accuracy_30d"] = stats.get("accuracy")
    meta["prediction_sample_30d"] = stats.get("sample_size")
    meta["prediction_pending"] = stats.get("pending")
    out["meta"] = meta
    return out


def format_accuracy_line(lang: str | None = None) -> str:
    """One-line calibration hint for the LLM prompt."""
    stats = accuracy_30d()
    sample = int(stats.get("sample_size") or 0)
    acc = stats.get("accuracy")
    if sample <= 0 or acc is None:
        lang_norm = (lang or "en").strip().lower()
        if lang_norm.startswith("de"):
            return (
                "Prognose-Kalibration: noch keine ausgewerteten Watch-Treffer "
                f"(offen: {stats.get('pending', 0)})."
            )
        return (
            f"Forecast calibration: no resolved watch outcomes yet "
            f"(pending: {stats.get('pending', 0)})."
        )
    pct = round(float(acc) * 100)
    lang_norm = (lang or "en").strip().lower()
    if lang_norm.startswith("de"):
        return f"30-Tage-Watch-Trefferquote: {pct}% (n={sample}) — keine Überbewertung."
    return f"30d watch hit rate: {pct}% (n={sample}) — do not overclaim beyond this track record."
