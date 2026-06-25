"""B-05 — A/B pilot for flat INTEL ENTITIES vs subgraph INTEL SUBGRAPH prompt blocks.

Offline fixtures validate mode selection, caption overlap, and compression.
Live mode reads GET /api/briefing intel metrics and compares both blocks on the
running FtM store (no second LLM generate).

Usage:
  python subgraph_prompt_ground_truth.py --fixtures
  python subgraph_prompt_ground_truth.py --live
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from typing import Any

import ftm_connection
import ftm_store
import intel_briefing as ib
import intel_subgraph as sg


@dataclass(frozen=True)
class PromptAbCase:
    case_id: str
    intel_meta: dict[str, Any]
    expect_mode: str
    min_overlap_pct: float | None = None
    note: str = ""
    subgraph_env: str | None = None


def _caption_overlap(
    flat_items: list[dict[str, Any]], nodes: list[dict[str, Any]]
) -> float:
    """Share of flat item captions found in subgraph node captions (case-insensitive)."""
    flat_caps: list[str] = []
    for item in flat_items:
        text = (item.get("text") or "").strip()
        if ":" in text:
            text = text.split(":", 1)[1].strip()
        if text:
            flat_caps.append(text.lower())
    if not flat_caps:
        return 1.0
    node_caps = {(n.get("caption") or "").lower() for n in nodes}
    hits = sum(
        1 for cap in flat_caps if any(cap in nc or nc in cap for nc in node_caps if nc)
    )
    return hits / len(flat_caps)


def compare_prompt_ab(intel_meta: dict[str, Any], lang: str = "en") -> dict[str, Any]:
    """Side-by-side flat vs subgraph blocks (A/B metrics, no LLM)."""
    intel_meta = intel_meta or {}
    flat_block = ib._format_flat_intel_block(intel_meta, lang=lang)
    metrics = ib.intel_prompt_metrics(intel_meta, lang=lang)
    window = int(
        intel_meta.get("window_hours")
        or ib._env_int("WORLDBASE_BRIEFING_INTEL_WINDOW_HOURS", 24)
    )
    subgraph_raw = sg.build_subgraph(window_hours=window)
    subgraph_block = ""
    if subgraph_raw.get("available") and subgraph_raw.get("nodes"):
        subgraph_block = sg.format_subgraph_prompt_block(subgraph_raw, lang=lang)

    flat_chars = len(flat_block)
    subgraph_chars = len(subgraph_block)
    compression = round(subgraph_chars / flat_chars, 3) if flat_chars > 0 else None
    overlap = _caption_overlap(
        intel_meta.get("items") or [], subgraph_raw.get("nodes") or []
    )

    return {
        "active_mode": metrics.get("prompt_mode"),
        "subgraph_available": metrics.get("subgraph_available"),
        "flat_chars": flat_chars,
        "subgraph_chars": subgraph_chars,
        "active_chars": metrics.get("intel_active_chars"),
        "compression_ratio": compression,
        "char_ratio_subgraph_over_flat": compression,
        "caption_overlap_pct": round(overlap * 100, 1),
        "flat_item_count": len(intel_meta.get("items") or []),
        "subgraph_node_count": subgraph_raw.get("node_count") or 0,
        "subgraph_edge_count": subgraph_raw.get("edge_count") or 0,
    }


def _seed_graph(path: str) -> dict[str, str]:
    ftm_connection._CONN = None
    ftm_store.set_db_path(path)
    ftm_store.init_store()

    event = ftm_store.make_entity(
        "Event", ["flood-bkk"], {"name": ["Bangkok flooding alert"]}
    )
    event_id = ftm_store.upsert(event, dataset="gdacs", lat=13.75, lon=100.5)
    org = ftm_store.make_entity(
        "Organization", ["relief-th"], {"name": ["Thai Relief Org"]}
    )
    org_id = ftm_store.upsert(org, dataset="osint")
    ftm_store.add_edge(event_id, org_id, "linked", dataset="osint", confidence=0.9)
    return {"event_id": event_id, "org_id": org_id}


def evaluate_case(case: PromptAbCase, db_path: str | None = None) -> dict[str, Any]:
    old_sub = os.environ.get("WORLDBASE_BRIEFING_INTEL_SUBGRAPH")
    if case.subgraph_env is not None:
        os.environ["WORLDBASE_BRIEFING_INTEL_SUBGRAPH"] = case.subgraph_env

    path = db_path
    created_tmp = False
    if path is None:
        fd, path = tempfile.mkstemp(suffix=".duckdb")
        os.close(fd)
        os.remove(path)
        created_tmp = True
        _seed_graph(path)

    ftm_connection._CONN = None
    ftm_store.set_db_path(path)
    ftm_store.init_store()

    try:
        ab = compare_prompt_ab(case.intel_meta, lang="en")
        ok = ab["active_mode"] == case.expect_mode
        if (
            case.min_overlap_pct is not None
            and ab["caption_overlap_pct"] < case.min_overlap_pct
        ):
            ok = False
        return {
            "case_id": case.case_id,
            "ok": ok,
            "expect_mode": case.expect_mode,
            "active_mode": ab["active_mode"],
            "flat_chars": ab["flat_chars"],
            "subgraph_chars": ab["subgraph_chars"],
            "caption_overlap_pct": ab["caption_overlap_pct"],
            "compression_ratio": ab["compression_ratio"],
            "note": case.note,
        }
    finally:
        if old_sub is None:
            os.environ.pop("WORLDBASE_BRIEFING_INTEL_SUBGRAPH", None)
        else:
            os.environ["WORLDBASE_BRIEFING_INTEL_SUBGRAPH"] = old_sub
        if created_tmp:
            try:
                if ftm_connection._CONN is not None:
                    ftm_connection._CONN.close()
            finally:
                ftm_connection._CONN = None
            for ext in ("", ".wal"):
                try:
                    os.remove(path + ext)
                except OSError:
                    pass


def _fixture_cases() -> tuple[PromptAbCase, ...]:
    items = [
        {
            "bucket": "local",
            "text": "Event: Bangkok flooding alert (gdacs)",
            "severity": "medium",
        },
        {
            "bucket": "local",
            "text": "Organization: Thai Relief Org (osint)",
            "severity": "low",
        },
    ]
    intel_with_items = {
        "enabled": True,
        "window_hours": 48,
        "count": 2,
        "items": items,
    }
    return (
        PromptAbCase(
            "gt-subgraph-mode",
            intel_with_items,
            expect_mode="subgraph",
            min_overlap_pct=50.0,
            note="Seeded bbox graph — subgraph active, captions overlap flat list",
        ),
        PromptAbCase(
            "gt-flat-empty-graph",
            {"enabled": True, "window_hours": 48, "items": []},
            expect_mode="flat",
            note="No seeds in empty DB — flat fallback",
            subgraph_env="1",
        ),
        PromptAbCase(
            "gt-flat-when-disabled",
            intel_with_items,
            expect_mode="flat",
            subgraph_env="0",
            note="WORLDBASE_BRIEFING_INTEL_SUBGRAPH=0 forces flat even with graph",
        ),
    )


def run_fixture_pilot() -> dict[str, Any]:
    fd, shared_path = tempfile.mkstemp(suffix=".duckdb")
    os.close(fd)
    os.remove(shared_path)
    _seed_graph(shared_path)

    results: list[dict[str, Any]] = []
    try:
        for case in _fixture_cases():
            if case.case_id == "gt-flat-empty-graph":
                fd2, empty_path = tempfile.mkstemp(suffix=".duckdb")
                os.close(fd2)
                os.remove(empty_path)
                ftm_connection._CONN = None
                ftm_store.set_db_path(empty_path)
                ftm_store.init_store()
                results.append(evaluate_case(case, db_path=empty_path))
                try:
                    if ftm_connection._CONN is not None:
                        ftm_connection._CONN.close()
                finally:
                    ftm_connection._CONN = None
                for ext in ("", ".wal"):
                    try:
                        os.remove(empty_path + ext)
                    except OSError:
                        pass
            else:
                results.append(evaluate_case(case, db_path=shared_path))
    finally:
        try:
            if ftm_connection._CONN is not None:
                ftm_connection._CONN.close()
        finally:
            ftm_connection._CONN = None
        for ext in ("", ".wal"):
            try:
                os.remove(shared_path + ext)
            except OSError:
                pass

    passed = sum(1 for r in results if r["ok"])
    total = len(results)
    return {
        "mode": "fixtures",
        "passed": passed,
        "total": total,
        "accuracy": round(passed / total, 3) if total else None,
        "results": results,
    }


def compare_prompt_ab_from_api(
    intel: dict[str, Any],
    subgraph: dict[str, Any],
    lang: str = "en",
) -> dict[str, Any]:
    """Live A/B using briefing JSON + GET /api/intel/subgraph (no DuckDB open)."""
    pm = intel.get("prompt_metrics") or {}
    flat_chars = int(pm.get("intel_flat_chars") or 0)
    subgraph_chars = int(pm.get("intel_subgraph_chars") or 0)
    active_mode = pm.get("prompt_mode") or "flat"
    compression = round(subgraph_chars / flat_chars, 3) if flat_chars > 0 else None

    nodes = subgraph.get("nodes") or []
    overlap = _caption_overlap(intel.get("items") or [], nodes)

    # Recompute subgraph block length when API has graph (sanity vs stored metrics).
    subgraph_block_chars = 0
    if subgraph.get("available") and nodes:
        subgraph_block_chars = len(sg.format_subgraph_prompt_block(subgraph, lang=lang))

    return {
        "active_mode": active_mode,
        "subgraph_available": bool(
            pm.get("subgraph_available") or subgraph.get("available")
        ),
        "flat_chars": flat_chars,
        "subgraph_chars": subgraph_chars,
        "subgraph_block_chars_live": subgraph_block_chars,
        "active_chars": int(pm.get("intel_active_chars") or 0),
        "compression_ratio": compression,
        "char_ratio_subgraph_over_flat": compression,
        "caption_overlap_pct": round(overlap * 100, 1),
        "flat_item_count": len(intel.get("items") or []),
        "subgraph_node_count": subgraph.get("node_count") or len(nodes),
        "subgraph_edge_count": subgraph.get("edge_count")
        or len(subgraph.get("edges") or []),
    }


def _api_get_json(api_base: str, path: str, timeout: float = 60) -> dict[str, Any]:
    import urllib.error
    import urllib.request

    url = f"{api_base.rstrip('/')}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_live_pilot(*, api_base: str = "http://127.0.0.1:8002") -> dict[str, Any]:
    import urllib.error

    try:
        briefing = _api_get_json(api_base, "/api/briefing")
        subgraph = _api_get_json(api_base, "/api/intel/subgraph?hops=2")
    except urllib.error.URLError as exc:
        return {"mode": "live", "error": str(exc), "ok": False}

    intel = briefing.get("intel") or {}
    lang = (briefing.get("digest") or {}).get("lang") or "en"
    ab = compare_prompt_ab_from_api(intel, subgraph, lang=lang)
    quality = briefing.get("quality") or {}

    return {
        "mode": "live",
        "ok": True,
        "briefing_created_at": briefing.get("created_at"),
        "quality_score": quality.get("score"),
        "intel_count": intel.get("count"),
        "prompt_metrics": intel.get("prompt_metrics"),
        "ab": ab,
        "recommendation": _live_recommendation(ab),
    }


def _live_recommendation(ab: dict[str, Any]) -> str:
    if ab.get("active_mode") == "subgraph":
        ratio = ab.get("compression_ratio")
        if ratio is not None and ratio > 1.0:
            return "subgraph_active_larger_than_flat"
        if ratio is not None and ratio < 1.0:
            return "subgraph_active_smaller_than_flat"
        return "subgraph_active"
    if ab.get("subgraph_node_count", 0) > 0:
        return "subgraph_available_but_flat_active"
    return "flat_only_no_subgraph_seeds"


def _print_report(report: dict[str, Any]) -> None:
    if report.get("mode") == "fixtures":
        print(
            f"Subgraph prompt A/B fixtures: {report['passed']}/{report['total']} PASS"
        )
        for row in report.get("results") or []:
            mark = "PASS" if row["ok"] else "FAIL"
            print(
                f"  [{mark}] {row['case_id']} mode={row.get('active_mode')} "
                f"flat={row.get('flat_chars')} subgraph={row.get('subgraph_chars')} "
                f"overlap={row.get('caption_overlap_pct')}% — {row.get('note', '')[:60]}"
            )
        if report["passed"] != report["total"]:
            raise SystemExit(1)
        return

    if report.get("error"):
        print(f"Live subgraph A/B pilot FAILED: {report['error']}")
        raise SystemExit(1)

    ab = report.get("ab") or {}
    pm = report.get("prompt_metrics") or {}
    print("Live subgraph prompt A/B")
    print(
        f"  active_mode={ab.get('active_mode')} "
        f"flat_chars={ab.get('flat_chars')} subgraph_chars={ab.get('subgraph_chars')} "
        f"char_ratio={ab.get('compression_ratio')} (>1 = subgraph larger)"
    )
    print(
        f"  overlap={ab.get('caption_overlap_pct')}% "
        f"nodes={ab.get('subgraph_node_count')} edges={ab.get('subgraph_edge_count')} "
        f"intel_count={report.get('intel_count')}"
    )
    if ab.get("subgraph_block_chars_live"):
        print(f"  subgraph_block_chars_live={ab.get('subgraph_block_chars_live')}")
    print(
        f"  quality={report.get('quality_score')} "
        f"recommendation={report.get('recommendation')} "
        f"stored_metrics_mode={pm.get('prompt_mode')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Subgraph prompt A/B pilot (B-05)")
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
