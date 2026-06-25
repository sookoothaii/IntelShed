"""B-04 — ground-truth pilot for digest corroboration rules.

Offline fixture cases validate corroborate_digest_item / build_digest_line_meta.
Live mode reads GET /api/briefing digest_line_meta from a running stack.

Usage:
  python corroboration_ground_truth.py --fixtures
  python corroboration_ground_truth.py --live
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Any

from briefing_quality import (
    build_digest_line_meta,
    corroborate_digest_item,
    corroboration_summary,
)


@dataclass(frozen=True)
class CorroborationCase:
    case_id: str
    item: dict[str, Any]
    pool: list[dict[str, Any]]
    min_corroboration: float | None = None
    max_corroboration: float | None = None
    expect_label: str | None = None
    expect_blocker: str | None = None
    note: str = ""


def _quake_item(**kwargs: Any) -> dict[str, Any]:
    base = {
        "severity": "medium",
        "text": "M5.4 — 10 km NE of Bangkok",
        "bucket": "local",
        "sources": ["earthquakes"],
        "lat": 13.75,
        "lon": 100.5,
    }
    base.update(kwargs)
    return base


def _gdacs_item(**kwargs: Any) -> dict[str, Any]:
    base = {
        "severity": "medium",
        "text": "Orange earthquake alert Thailand",
        "bucket": "local",
        "sources": ["gdacs"],
        "lat": 13.75,
        "lon": 100.5,
    }
    base.update(kwargs)
    return base


GROUND_TRUTH_CASES: tuple[CorroborationCase, ...] = (
    CorroborationCase(
        "gt-quake-gdacs-dual",
        _quake_item(),
        [_quake_item(), _gdacs_item()],
        min_corroboration=0.8,
        expect_label="corroborated",
        note="Known dual-source event — USGS + GDACS same geo bucket",
    ),
    CorroborationCase(
        "gt-quake-single",
        _quake_item(),
        [_quake_item()],
        max_corroboration=0.5,
        expect_label="single-source",
        note="Single feed family only",
    ),
    CorroborationCase(
        "gt-gdacs-from-pool",
        _gdacs_item(),
        [_quake_item(), _gdacs_item()],
        min_corroboration=0.8,
        expect_label="corroborated",
        note="GDACS row corroborated when quake peer present",
    ),
    CorroborationCase(
        "gt-conflict-severity",
        _quake_item(severity="high"),
        [
            _quake_item(severity="high"),
            _gdacs_item(severity="low", text="Green earthquake alert Thailand"),
        ],
        expect_label="contradictory",
        note="Matching geo with diverging severity -> conflict flag",
    ),
    CorroborationCase(
        "gt-single-source-blocker",
        {
            "severity": "low",
            "text": "Air quality Bangkok: PM2.5 12 µg/m³",
            "bucket": "local",
            "sources": ["airquality"],
            "lat": 13.75,
            "lon": 100.5,
        },
        [],
        expect_blocker="single_source_local",
        note="Three same-family local lines trigger blocker via build_digest_line_meta",
    ),
    CorroborationCase(
        "gt-newsdata-gdelt-dual",
        {
            "severity": "low",
            "text": "News: US-Iran peace talks continue in Switzerland",
            "bucket": "global",
            "sources": ["newsdata"],
        },
        [
            {
                "severity": "low",
                "text": "Local news: Iran US negotiations continue Switzerland talks",
                "bucket": "global",
                "sources": ["gdelt_pulse_local"],
            },
            {
                "severity": "low",
                "text": "News: US-Iran peace talks continue in Switzerland",
                "bucket": "global",
                "sources": ["newsdata"],
            },
        ],
        min_corroboration=0.75,
        expect_label="corroborated",
        note="NewsData + GDELT families on overlapping Iran/Switzerland headline",
    ),
    CorroborationCase(
        "gt-newsdata-single",
        {
            "severity": "low",
            "text": "News: Firework sales expected for America 250 celebrations",
            "bucket": "global",
            "sources": ["newsdata"],
        },
        [
            {
                "severity": "low",
                "text": "News: Firework sales expected for America 250 celebrations",
                "bucket": "global",
                "sources": ["newsdata"],
            },
        ],
        max_corroboration=0.5,
        expect_label="single-source",
        note="NewsData-only line — separate corroboration family from gdelt",
    ),
)


def evaluate_case(case: CorroborationCase) -> dict[str, Any]:
    if case.expect_blocker:
        picked = [dict(case.item) for _ in range(3)]
        meta = build_digest_line_meta(picked, {"local": picked})
        summary = corroboration_summary(meta)
        ok = summary.get("corroboration_blocker") == case.expect_blocker
        return {
            "case_id": case.case_id,
            "ok": ok,
            "corroboration": summary.get("corroboration_avg_local"),
            "label": summary.get("corroboration_blocker"),
            "sources": [],
            "note": case.note,
        }

    pool = case.pool if case.pool else [case.item]
    row = corroborate_digest_item(case.item, pool)
    score = float(row.get("corroboration") or 0)
    ok = True
    if case.min_corroboration is not None and score < case.min_corroboration:
        ok = False
    if case.max_corroboration is not None and score > case.max_corroboration:
        ok = False
    if case.expect_label and row.get("label") != case.expect_label:
        ok = False
    return {
        "case_id": case.case_id,
        "ok": ok,
        "corroboration": score,
        "label": row.get("label"),
        "sources": row.get("sources"),
        "note": case.note,
    }


def run_fixture_pilot() -> dict[str, Any]:
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


def run_live_pilot(*, api_base: str = "http://127.0.0.1:8002") -> dict[str, Any]:
    import urllib.error
    import urllib.request

    url = f"{api_base.rstrip('/')}/api/briefing"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            briefing = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        return {"mode": "live", "error": str(exc), "ok": False}

    meta = briefing.get("digest_line_meta") or []
    local_rows = [r for r in meta if r.get("bucket") == "local"]
    summary = corroboration_summary(meta)
    corroborated = [r for r in local_rows if float(r.get("corroboration") or 0) >= 0.8]
    return {
        "mode": "live",
        "ok": True,
        "digest_line_meta_count": len(meta),
        "local_lines": len(local_rows),
        "corroborated_local": len(corroborated),
        "corroboration_avg_local": summary.get("corroboration_avg_local"),
        "corroboration_blocker": summary.get("corroboration_blocker"),
        "sample_corroborated": corroborated[:3],
        "quality_score": (briefing.get("quality") or {}).get("score"),
    }


def _print_report(report: dict[str, Any]) -> None:
    if report.get("mode") == "fixtures":
        print(f"Corroboration fixtures: {report['passed']}/{report['total']} PASS")
        for row in report.get("results") or []:
            mark = "PASS" if row["ok"] else "FAIL"
            print(
                f"  [{mark}] {row['case_id']} score={row.get('corroboration')} "
                f"label={row.get('label')} — {row.get('note', '')[:70]}"
            )
        if report["passed"] != report["total"]:
            raise SystemExit(1)
        return

    if report.get("error"):
        print(f"Live corroboration pilot FAILED: {report['error']}")
        raise SystemExit(1)

    print("Live corroboration pilot")
    print(
        f"  meta_lines={report.get('digest_line_meta_count')} "
        f"local={report.get('local_lines')} corroborated_local={report.get('corroborated_local')}"
    )
    print(
        f"  avg_local={report.get('corroboration_avg_local')} "
        f"blocker={report.get('corroboration_blocker')} quality={report.get('quality_score')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Corroboration ground-truth pilot (B-04)"
    )
    parser.add_argument("--fixtures", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--api-base", default="http://127.0.0.1:8002")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    if args.live:
        report = run_live_pilot(api_base=args.api_base)
    else:
        report = run_fixture_pilot()

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        _print_report(report)


if __name__ == "__main__":
    main()
