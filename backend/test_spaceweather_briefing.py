"""Tests for spaceweather_briefing bridge."""

from __future__ import annotations

from spaceweather_briefing import (
    build_spaceweather_watch_items,
    gather_spaceweather_digest,
)


def test_digest_disabled_when_empty_snapshot():
    digest = gather_spaceweather_digest({})
    assert digest["enabled"] is False
    assert digest["lines"] == []


def test_digest_disabled_when_error_only():
    digest = gather_spaceweather_digest({"spaceweather": {"error": "upstream timeout"}})
    assert digest["enabled"] is False


def test_digest_enabled_with_kp_only():
    digest = gather_spaceweather_digest({"spaceweather": {"kp_index": 3.0}})
    assert digest["enabled"] is True
    assert len(digest["lines"]) == 1
    assert "Kp=3.00" in digest["lines"][0]
    assert digest["scale"] == "unknown"


def test_digest_includes_solar_wind_and_dst():
    digest = gather_spaceweather_digest(
        {
            "spaceweather": {
                "kp_index": 4.33,
                "scale": "active",
                "dst": -45.0,
                "solar_wind": {"speed_km_s": 450.0, "density_p_cc": 5.2},
                "protons": {"gt_10_mev": 0.12},
            }
        }
    )
    assert digest["enabled"] is True
    assert len(digest["lines"]) == 1
    line = digest["lines"][0]
    assert "Kp=4.33" in line
    assert "Dst=-45.00" in line
    assert "solar wind 450.00" in line
    assert "protons >10 MeV 0.12" in line


def test_digest_alerts_and_forecast():
    digest = gather_spaceweather_digest(
        {
            "spaceweather": {
                "kp_index": 5.67,
                "scale": "minor-moderate storm (G1-G2)",
                "alerts": [
                    {
                        "message": "G2 storm warning issued",
                        "severity": "moderate",
                    }
                ],
                "forecast": [
                    {"time": "2026-06-27T00:00:00", "kp": 5.0},
                    {"time": "2026-06-27T03:00:00", "kp": 4.0},
                ],
            }
        }
    )
    assert digest["enabled"] is True
    assert any("G2 storm warning" in line for line in digest["lines"])
    assert any("Kp forecast" in line for line in digest["lines"])


def test_watch_items_only_for_significant_conditions():
    digest = gather_spaceweather_digest({"spaceweather": {"kp_index": 3.0}})
    items = build_spaceweather_watch_items(digest)
    assert items == []


def test_watch_item_for_storm():
    digest = gather_spaceweather_digest({"spaceweather": {"kp_index": 6.0}})
    items = build_spaceweather_watch_items(digest)
    assert len(items) == 1
    assert items[0]["title"] == "Space weather — Kp 6.00"
    assert items[0]["bucket"] == "global"
    assert items[0]["sources"] == ["spaceweather"]


def test_watch_items_for_alerts():
    digest = gather_spaceweather_digest(
        {
            "spaceweather": {
                "kp_index": 3.0,
                "alerts": [{"message": "Radio blackout warning", "severity": "strong"}],
            }
        }
    )
    items = build_spaceweather_watch_items(digest)
    assert any("Radio blackout warning" in item["title"] for item in items)
