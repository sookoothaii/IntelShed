"""B-03 — ground-truth pilot for prediction ledger outcome rules.

Fixed watch-item + snapshot pairs with expected hit/miss. Run offline (no network)
or live against the current feed snapshot to resolve overdue pending rows.

Usage:
  python prediction_ground_truth.py --fixtures
  python prediction_ground_truth.py --live
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
from dataclasses import dataclass
from typing import Any

import prediction_ledger as pl


@dataclass(frozen=True)
class GroundTruthCase:
    case_id: str
    prefix: str
    claim: str
    sources: list[str]
    cell_id: str | None
    snap: dict[str, Any]
    fusion_cells: list[dict[str, Any]] | None
    expect_hit: bool
    note: str


def _row_from_case(case: GroundTruthCase) -> sqlite3.Row:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE briefing_predictions (
            id INTEGER PRIMARY KEY,
            watch_id TEXT, prefix TEXT, issued_at TEXT, horizon_h INTEGER,
            claim TEXT, sources TEXT, cell_id TEXT, bucket TEXT,
            outcome TEXT, outcome_at TEXT, hit INTEGER
        )
        """
    )
    conn.execute(
        """
        INSERT INTO briefing_predictions (
            watch_id, prefix, issued_at, horizon_h, claim, sources,
            cell_id, bucket, outcome, outcome_at, hit
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'local', NULL, NULL, NULL)
        """,
        (
            case.case_id,
            case.prefix,
            "2026-01-01T00:00:00+00:00",
            48,
            case.claim,
            json.dumps(case.sources),
            case.cell_id,
        ),
    )
    row = conn.execute("SELECT * FROM briefing_predictions WHERE id = 1").fetchone()
    conn.close()
    if row is None:
        raise RuntimeError(f"fixture row missing: {case.case_id}")
    return row


GROUND_TRUTH_CASES: tuple[GroundTruthCase, ...] = (
    GroundTruthCase(
        "gt-gdelt-hit",
        "gdelt",
        "Elevated media attention in operator region",
        ["gdelt_pulse_local"],
        None,
        {
            "gdelt_pulse_local": {"articles": [{}, {}, {}, {}, {}]},
            "gdelt_geo_local": {"events": [{}, {}]},
        },
        None,
        True,
        "GDELT pulse/geo above watch threshold",
    ),
    GroundTruthCase(
        "gt-gdelt-miss",
        "gdelt",
        "Elevated media attention in operator region",
        ["gdelt_pulse_local"],
        None,
        {
            "gdelt_pulse_local": {"articles": [{}]},
            "gdelt_geo_local": {"events": []},
        },
        None,
        False,
        "GDELT attention eased",
    ),
    GroundTruthCase(
        "gt-quake-hit",
        "quake",
        "Seismic watch — M5+ near operator cell",
        ["earthquakes"],
        "13.75,100.50",
        {
            "earthquakes": {
                "earthquakes": [{"mag": 5.4, "lat": 13.8, "lon": 100.6}],
            }
        },
        None,
        True,
        "M≥5 quake within 250 km of cell",
    ),
    GroundTruthCase(
        "gt-gdacs-hit",
        "gdacs",
        "Cyclone watch — GDACS orange alert",
        ["gdacs"],
        "10.00,99.00",
        {
            "gdacs": {
                "alerts": [
                    {
                        "title": "Cyclone watch — GDACS orange alert",
                        "lat": 10.2,
                        "lon": 99.1,
                        "alertlevel": "Orange",
                    }
                ]
            }
        },
        None,
        True,
        "GDACS orange in watch area",
    ),
    GroundTruthCase(
        "gt-cams-hit",
        "cams",
        "Haze trajectory — Bangkok: PM2.5 40 µg/m³",
        ["cams_haze"],
        "13.75,100.50",
        {
            "cams_haze": {
                "cities": [
                    {
                        "city": "Bangkok",
                        "lat": 13.75,
                        "lon": 100.5,
                        "pm25": 62,
                        "severity": "high",
                    }
                ]
            }
        },
        None,
        True,
        "Bangkok PM2.5 high haze persisted",
    ),
    GroundTruthCase(
        "gt-cams-miss",
        "cams",
        "Haze trajectory — Chiang Mai: PM2.5 watch",
        ["cams_haze"],
        "18.80,98.98",
        {
            "cams_haze": {
                "cities": [
                    {
                        "city": "Chiang Mai",
                        "lat": 18.8,
                        "lon": 98.98,
                        "pm25": 18,
                        "severity": "low",
                    }
                ]
            }
        },
        None,
        False,
        "PM2.5 eased below watch threshold",
    ),
    GroundTruthCase(
        "gt-fusion-hit",
        "fusion_delta",
        "Rising fusion cell (Δ+0.90): Flood Warning",
        ["fusion"],
        "37.00,-97.00",
        {},
        [
            {
                "cell_id": "37.00,-97.00",
                "lat": 37.0,
                "lon": -97.0,
                "score": 0.72,
                "delta_score": 0.15,
            }
        ],
        True,
        "Fusion cell score still elevated",
    ),
    GroundTruthCase(
        "gt-fusion-miss",
        "fusion_delta",
        "Rising fusion cell (Δ+0.90): Flood Warning",
        ["fusion"],
        "37.00,-97.00",
        {},
        [
            {
                "cell_id": "37.00,-97.00",
                "lat": 37.0,
                "lon": -97.0,
                "score": 0.18,
                "delta_score": 0.02,
            }
        ],
        False,
        "Fusion cell cooled",
    ),
    GroundTruthCase(
        "gt-maritime-hit",
        "maritime",
        "Maritime corridor density — 18 vessels tracked",
        ["maritime"],
        None,
        {
            "maritime": {
                "vessels": [
                    {"region": r} for r in ("malacca", "laem_chabang", "bangkok_port")
                ]
                * 5
            }
        },
        None,
        True,
        "Thai corridor density ≥12 vessels",
    ),
    GroundTruthCase(
        "gt-hdx-hit",
        "hdx",
        "Humanitarian watch — Myanmar displacement datasets",
        ["humanitarian"],
        None,
        {
            "humanitarian": {
                "datasets": [
                    {"title": "Myanmar displacement datasets Q2 2026"},
                    {"title": "Thailand refugee support"},
                    {"title": "ASEAN crisis funding"},
                ]
            }
        },
        None,
        True,
        "HDX title match + regional activity",
    ),
)


def evaluate_case(case: GroundTruthCase) -> dict[str, Any]:
    row = _row_from_case(case)
    hit, outcome = pl._evaluate_row(row, case.snap, case.fusion_cells)
    ok = bool(hit) == case.expect_hit
    return {
        "case_id": case.case_id,
        "prefix": case.prefix,
        "expect_hit": case.expect_hit,
        "actual_hit": bool(hit),
        "ok": ok,
        "outcome": outcome,
        "note": case.note,
    }


def run_fixture_pilot() -> dict[str, Any]:
    """Run all fixed ground-truth cases (offline, no DB writes)."""
    results = [evaluate_case(case) for case in GROUND_TRUTH_CASES]
    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    return {
        "mode": "fixtures",
        "passed": passed,
        "total": total,
        "accuracy": round(passed / total, 3) if total else None,
        "results": results,
    }


async def run_live_pilot(*, force_snapshot: bool = False) -> dict[str, Any]:
    """Resolve overdue pending predictions against the live feed snapshot."""
    import fusion_heatmap
    import node_sync

    snap = await node_sync.warm_snapshot_cache(force=force_snapshot)
    fusion_cells: list[dict] = []
    try:
        grid = await fusion_heatmap.fusion_heatmap(
            cell_deg=2.0, top=60, include_geojson=0
        )
        fusion_cells = list(grid.get("cells") or [])
    except Exception:
        fusion_cells = []

    resolve_result = pl.resolve_pending(snap, fusion_cells)
    stats = pl.accuracy_30d()
    listing = pl.list_predictions(pending_limit=5, resolved_limit=5)
    return {
        "mode": "live",
        "resolve": resolve_result,
        "accuracy_30d": stats,
        "overdue_count": listing.get("overdue_count"),
        "pending_sample": listing.get("pending"),
        "resolved_recent": listing.get("resolved_recent"),
    }


def _print_report(report: dict[str, Any]) -> None:
    if report.get("mode") == "fixtures":
        print(f"Ground-truth fixtures: {report['passed']}/{report['total']} PASS")
        for row in report.get("results") or []:
            mark = "PASS" if row["ok"] else "FAIL"
            print(
                f"  [{mark}] {row['case_id']} ({row['prefix']}) "
                f"expect={row['expect_hit']} actual={row['actual_hit']} — {row['outcome'][:80]}"
            )
        if report["passed"] != report["total"]:
            raise SystemExit(1)
        return

    print("Live prediction pilot")
    res = report.get("resolve") or {}
    print(
        f"  resolved={res.get('resolved')} hits={res.get('hits')} misses={res.get('misses')} "
        f"overdue={report.get('overdue_count')}"
    )
    acc = report.get("accuracy_30d") or {}
    print(
        f"  30d accuracy={acc.get('accuracy')} sample={acc.get('sample_size')} "
        f"pending={acc.get('pending')}"
    )
    recent = report.get("resolved_recent") or []
    if recent:
        print("  recent outcomes:")
        for row in recent[:5]:
            hit = "HIT" if row.get("hit") else "MISS"
            print(
                f"    [{hit}] {row.get('prefix')} — {(row.get('outcome') or '')[:70]}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prediction ledger ground-truth pilot (B-03)"
    )
    parser.add_argument(
        "--fixtures",
        action="store_true",
        help="Run 10 offline fixture cases (default when no flag)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Resolve overdue pending rows against live feeds",
    )
    parser.add_argument(
        "--force-snapshot",
        action="store_true",
        help="Refresh feed snapshot before live resolve",
    )
    parser.add_argument(
        "--json", action="store_true", help="Print JSON instead of text"
    )
    args = parser.parse_args()

    if args.live:
        report = asyncio.run(run_live_pilot(force_snapshot=args.force_snapshot))
    else:
        report = run_fixture_pilot()

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)


if __name__ == "__main__":
    main()
