"""Tests for V4-52 Fusion Delta Grid — 24h compare with delta_score."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest import mock

import pytest

# Ensure backend dir on path
_backend = Path(__file__).resolve().parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))


@pytest.fixture
def _isolation_env(monkeypatch, tmp_path):
    """Isolate fusion_delta with mocked fusion_heatmap."""
    monkeypatch.setenv("WORLDBASE_FUSION_DELTA_MIN", "0.12")
    monkeypatch.setenv("WORLDBASE_FUSION_DELTA_MAX_WATCH", "5")

    import fusion_delta

    fusion_delta._CACHE.clear() if hasattr(fusion_delta, "_CACHE") else None
    yield fusion_delta


def _make_cell(
    lat: float,
    lon: float,
    score: float,
    intensity: float,
    delta_score: float | None = None,
    baseline_score: float | None = None,
    sources: list[str] | None = None,
    cell_id: str | None = None,
) -> dict:
    """Helper to build a fusion cell dict."""
    cid = cell_id or f"{lat:.2f},{lon:.2f}"
    return {
        "lat": lat,
        "lon": lon,
        "score": score,
        "intensity": intensity,
        "sources": sources or ["quake"],
        "cell_id": cid,
        "delta_score": delta_score,
        "baseline_score": baseline_score,
    }


def _make_compare_meta(available: bool = True) -> dict:
    return {
        "hours": 24,
        "available": available,
        "baseline_at": "2026-06-29T00:00:00+00:00",
        "target_at": "2026-06-29T00:00:00+00:00",
        "snapshots_stored": 5,
        "top_delta": {
            "cell_id": "13.00,100.00",
            "delta_score": 0.45,
            "lat": 13.0,
            "lon": 100.0,
            "score": 0.8,
        },
    }


# ---------------------------------------------------------------------------
# Watch item generation tests
# ---------------------------------------------------------------------------


class TestWatchItems:
    def test_build_watch_items_basic(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        # Mock operator_briefing imports
        mock_mod = mock.MagicMock()
        mock_mod.OPERATOR_REGION = "thailand"
        mock_mod._region_bbox.return_value = (5.0, 95.0, 20.0, 110.0)
        mock_mod._ASEAN_BBOX = (-10.0, 95.0, 28.0, 140.0)
        mock_mod.classify_item.return_value = "local"
        monkeypatch.setitem(sys.modules, "operator_briefing", mock_mod)

        cells = [
            _make_cell(13.0, 100.0, 0.8, 5.0, delta_score=0.45),
            _make_cell(14.0, 101.0, 0.6, 3.0, delta_score=0.20),
        ]
        items = mod.build_delta_watch_items(cells)
        assert len(items) == 2
        assert items[0]["prefix"] == "fusion_delta"
        assert items[0]["delta_score"] == 0.45
        assert "Rising fusion cell" in items[0]["title"]

    def test_build_watch_items_filters_low_delta(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        mock_mod = mock.MagicMock()
        mock_mod.OPERATOR_REGION = "thailand"
        mock_mod._region_bbox.return_value = (5.0, 95.0, 20.0, 110.0)
        mock_mod._ASEAN_BBOX = (-10.0, 95.0, 28.0, 140.0)
        mock_mod.classify_item.return_value = "local"
        monkeypatch.setitem(sys.modules, "operator_briefing", mock_mod)

        cells = [
            _make_cell(13.0, 100.0, 0.8, 5.0, delta_score=0.05),
            _make_cell(14.0, 101.0, 0.6, 3.0, delta_score=0.20),
        ]
        items = mod.build_delta_watch_items(cells, min_delta=0.12)
        assert len(items) == 1
        assert items[0]["delta_score"] == 0.20

    def test_build_watch_items_max_items(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        mock_mod = mock.MagicMock()
        mock_mod.OPERATOR_REGION = "thailand"
        mock_mod._region_bbox.return_value = (5.0, 95.0, 20.0, 110.0)
        mock_mod._ASEAN_BBOX = (-10.0, 95.0, 28.0, 140.0)
        mock_mod.classify_item.return_value = "local"
        monkeypatch.setitem(sys.modules, "operator_briefing", mock_mod)

        cells = [
            _make_cell(float(i), 100.0 + i, 0.5, 3.0, delta_score=0.20 + i * 0.01)
            for i in range(10)
        ]
        items = mod.build_delta_watch_items(cells, max_items=3)
        assert len(items) == 3

    def test_build_watch_items_negative_delta_filtered(
        self, _isolation_env, monkeypatch
    ):
        mod = _isolation_env
        mock_mod = mock.MagicMock()
        mock_mod.OPERATOR_REGION = "thailand"
        mock_mod._region_bbox.return_value = (5.0, 95.0, 20.0, 110.0)
        mock_mod._ASEAN_BBOX = (-10.0, 95.0, 28.0, 140.0)
        mock_mod.classify_item.return_value = "local"
        monkeypatch.setitem(sys.modules, "operator_briefing", mock_mod)

        cells = [
            _make_cell(13.0, 100.0, 0.8, 5.0, delta_score=-0.30),
            _make_cell(14.0, 101.0, 0.6, 3.0, delta_score=0.20),
        ]
        items = mod.build_delta_watch_items(cells)
        assert len(items) == 1
        assert items[0]["delta_score"] == 0.20

    def test_build_watch_items_confidence(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        mock_mod = mock.MagicMock()
        mock_mod.OPERATOR_REGION = "thailand"
        mock_mod._region_bbox.return_value = (5.0, 95.0, 20.0, 110.0)
        mock_mod._ASEAN_BBOX = (-10.0, 95.0, 28.0, 140.0)
        mock_mod.classify_item.return_value = "local"
        monkeypatch.setitem(sys.modules, "operator_briefing", mock_mod)

        cell = _make_cell(13.0, 100.0, 0.8, 5.0, delta_score=0.45)
        items = mod.build_delta_watch_items([cell])
        # confidence = min(0.92, 0.5 + 0.45 + 0.8*0.25) = min(0.92, 1.15) = 0.92
        assert items[0]["confidence"] == pytest.approx(0.92, abs=0.01)

    def test_build_watch_items_no_delta_score(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        mock_mod = mock.MagicMock()
        mock_mod.OPERATOR_REGION = "thailand"
        mock_mod._region_bbox.return_value = (5.0, 95.0, 20.0, 110.0)
        mock_mod._ASEAN_BBOX = (-10.0, 95.0, 28.0, 140.0)
        mock_mod.classify_item.return_value = "local"
        monkeypatch.setitem(sys.modules, "operator_briefing", mock_mod)

        cell = _make_cell(13.0, 100.0, 0.8, 5.0, delta_score=None)
        items = mod.build_delta_watch_items([cell])
        assert len(items) == 0

    def test_build_watch_items_missing_lat_lon(self, _isolation_env, monkeypatch):
        mod = _isolation_env
        mock_mod = mock.MagicMock()
        mock_mod.OPERATOR_REGION = "thailand"
        mock_mod._region_bbox.return_value = (5.0, 95.0, 20.0, 110.0)
        mock_mod._ASEAN_BBOX = (-10.0, 95.0, 28.0, 140.0)
        mock_mod.classify_item.return_value = "local"
        monkeypatch.setitem(sys.modules, "operator_briefing", mock_mod)

        cell = {"delta_score": 0.5, "score": 0.8, "sources": ["quake"]}
        items = mod.build_delta_watch_items([cell])
        assert len(items) == 0


# ---------------------------------------------------------------------------
# compute_delta tests (mocked fusion_heatmap)
# ---------------------------------------------------------------------------


class TestComputeDelta:
    def test_compute_delta_basic(self, _isolation_env, monkeypatch):
        mod = _isolation_env

        mock_cells = [
            _make_cell(13.0, 100.0, 0.8, 5.0, delta_score=0.45, baseline_score=0.35),
            _make_cell(14.0, 101.0, 0.6, 3.0, delta_score=0.20, baseline_score=0.40),
            _make_cell(15.0, 102.0, 0.3, 1.0, delta_score=-0.10, baseline_score=0.40),
            _make_cell(16.0, 103.0, 0.5, 2.0, delta_score=None),
        ]
        mock_data = {
            "cells": mock_cells,
            "compare": _make_compare_meta(available=True),
            "scanned_at": "2026-06-30T12:00:00+00:00",
        }

        async def mock_fh(**kwargs):
            return mock_data

        monkeypatch.setattr("fusion_heatmap.fusion_heatmap", mock_fh)
        monkeypatch.setattr("fusion_heatmap.parse_compare_hours", lambda x: 24.0)

        result = asyncio.run(
            mod.compute_delta(cell_deg=2.0, compare_hours=24.0, top=20)
        )

        assert result["enabled"] is True
        assert result["available"] is True
        assert result["total_delta_cells"] == 3  # cells with delta_score
        assert result["returned"] <= 20
        # Sorted by abs(delta_score) descending
        assert result["cells"][0]["delta_score"] == 0.45

    def test_compute_delta_watch_items(self, _isolation_env, monkeypatch):
        mod = _isolation_env

        mock_mod = mock.MagicMock()
        mock_mod.OPERATOR_REGION = "thailand"
        mock_mod._region_bbox.return_value = (5.0, 95.0, 20.0, 110.0)
        mock_mod._ASEAN_BBOX = (-10.0, 95.0, 28.0, 140.0)
        mock_mod.classify_item.return_value = "local"
        monkeypatch.setitem(sys.modules, "operator_briefing", mock_mod)

        mock_cells = [
            _make_cell(13.0, 100.0, 0.8, 5.0, delta_score=0.45),
            _make_cell(14.0, 101.0, 0.6, 3.0, delta_score=0.20),
        ]
        mock_data = {
            "cells": mock_cells,
            "compare": _make_compare_meta(available=True),
            "scanned_at": "2026-06-30T12:00:00+00:00",
        }

        async def mock_fh(**kwargs):
            return mock_data

        monkeypatch.setattr("fusion_heatmap.fusion_heatmap", mock_fh)
        monkeypatch.setattr("fusion_heatmap.parse_compare_hours", lambda x: 24.0)

        result = asyncio.run(
            mod.compute_delta(cell_deg=2.0, compare_hours=24.0, top=20)
        )
        assert len(result["watch_items"]) == 2
        assert result["watch_items"][0]["delta_score"] == 0.45

    def test_compute_delta_no_baseline(self, _isolation_env, monkeypatch):
        mod = _isolation_env

        mock_cells = [
            _make_cell(13.0, 100.0, 0.8, 5.0, delta_score=0.45),
        ]
        mock_data = {
            "cells": mock_cells,
            "compare": _make_compare_meta(available=False),
            "scanned_at": "2026-06-30T12:00:00+00:00",
        }

        async def mock_fh(**kwargs):
            return mock_data

        monkeypatch.setattr("fusion_heatmap.fusion_heatmap", mock_fh)
        monkeypatch.setattr("fusion_heatmap.parse_compare_hours", lambda x: 24.0)

        result = asyncio.run(
            mod.compute_delta(cell_deg=2.0, compare_hours=24.0, top=20)
        )
        assert result["available"] is False

    def test_compute_delta_geojson(self, _isolation_env, monkeypatch):
        mod = _isolation_env

        mock_mod = mock.MagicMock()
        mock_mod.OPERATOR_REGION = "thailand"
        mock_mod._region_bbox.return_value = (5.0, 95.0, 20.0, 110.0)
        mock_mod._ASEAN_BBOX = (-10.0, 95.0, 28.0, 140.0)
        mock_mod.classify_item.return_value = "local"
        monkeypatch.setitem(sys.modules, "operator_briefing", mock_mod)

        mock_cells = [
            _make_cell(13.0, 100.0, 0.8, 5.0, delta_score=0.45, baseline_score=0.35),
        ]
        mock_data = {
            "cells": mock_cells,
            "compare": _make_compare_meta(available=True),
            "scanned_at": "2026-06-30T12:00:00+00:00",
        }

        async def mock_fh(**kwargs):
            return mock_data

        monkeypatch.setattr("fusion_heatmap.fusion_heatmap", mock_fh)
        monkeypatch.setattr("fusion_heatmap.parse_compare_hours", lambda x: 24.0)

        result = asyncio.run(
            mod.compute_delta(
                cell_deg=2.0, compare_hours=24.0, top=20, include_geojson=1
            )
        )
        assert result["geojson"] is not None
        assert result["geojson"]["type"] == "FeatureCollection"
        assert len(result["geojson"]["features"]) == 1
        feat = result["geojson"]["features"][0]
        assert feat["properties"]["delta_score"] == 0.45

    def test_compute_delta_empty_cells(self, _isolation_env, monkeypatch):
        mod = _isolation_env

        mock_data = {
            "cells": [],
            "compare": _make_compare_meta(available=False),
            "scanned_at": "2026-06-30T12:00:00+00:00",
        }

        async def mock_fh(**kwargs):
            return mock_data

        monkeypatch.setattr("fusion_heatmap.fusion_heatmap", mock_fh)
        monkeypatch.setattr("fusion_heatmap.parse_compare_hours", lambda x: 24.0)

        result = asyncio.run(
            mod.compute_delta(cell_deg=2.0, compare_hours=24.0, top=20)
        )
        assert result["total_delta_cells"] == 0
        assert result["cells"] == []
        assert result["watch_items"] == []


# ---------------------------------------------------------------------------
# Label helper tests
# ---------------------------------------------------------------------------


class TestLabelHelper:
    def test_lat_lon_label_north_east(self, _isolation_env):
        mod = _isolation_env
        label = mod._lat_lon_label(13.0, 100.0)
        assert "N" in label
        assert "E" in label

    def test_lat_lon_label_south_west(self, _isolation_env):
        mod = _isolation_env
        label = mod._lat_lon_label(-13.0, -100.0)
        assert "S" in label
        assert "W" in label
