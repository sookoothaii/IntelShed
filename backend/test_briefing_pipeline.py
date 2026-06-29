"""Tests for briefing_pipeline module — Kanban pipeline state management."""

from __future__ import annotations

import os
import tempfile

import pytest

# Override DB_PATH before importing briefing_pipeline
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["WORLDBASE_DB_PATH"] = _tmp.name

import briefing_pipeline  # noqa: E402
import sqlite_bootstrap  # noqa: E402

# Re-point the module's DB_PATH to our temp file
briefing_pipeline.DB_PATH = _tmp.name
sqlite_bootstrap.DB_PATH = _tmp.name


@pytest.fixture(autouse=True)
def _fresh_db():
    briefing_pipeline.init_pipeline_db()
    yield
    briefing_pipeline.clear_pipeline()


def _sample_briefing() -> dict:
    return {
        "watch_items": [
            {
                "id": "watch:gdacs:EQ123",
                "prefix": "gdacs",
                "title": "M5.2 earthquake near Sumatra",
                "confidence": 0.82,
                "sources": ["gdacs", "usgs"],
                "lat": 2.5,
                "lon": 96.0,
                "bucket": "regional",
            },
            {
                "id": "watch:gdelt:ABC",
                "prefix": "gdelt",
                "title": "Political unrest in Bangkok",
                "confidence": 0.65,
                "sources": ["gdelt"],
                "lat": 13.75,
                "lon": 100.5,
                "bucket": "local",
            },
        ],
        "insights": [
            {
                "id": "insight:2.5,96.0",
                "cell_id": "2.5,96.0",
                "headline": "Escalating cluster — Sumatra: seismic activity",
                "confidence": 0.71,
                "sources": ["gdacs", "usgs"],
                "center": {"lat": 2.5, "lon": 96.0, "place": "Sumatra"},
            },
        ],
        "alerts": [
            {
                "id": "alert:maritime1",
                "title": "AIS anomaly detected",
                "confidence": 0.55,
                "sources": ["maritime"],
                "lat": 1.3,
                "lon": 104.0,
            },
        ],
        "fusion_hotspots": [
            {
                "cell_id": "13.75,100.5",
                "lat": 13.75,
                "lon": 100.5,
                "score": 0.42,
                "sources": ["gdelt", "newsdata"],
            },
        ],
    }


class TestInitPipelineDb:
    def test_creates_table(self):
        import sqlite3

        conn = sqlite3.connect(briefing_pipeline.DB_PATH)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='briefing_pipeline'"
        ).fetchall()
        conn.close()
        assert len(tables) == 1

    def test_idempotent(self):
        briefing_pipeline.init_pipeline_db()
        briefing_pipeline.init_pipeline_db()
        # Should not raise


class TestStages:
    def test_stages_are_five(self):
        assert len(briefing_pipeline.STAGES) == 5

    def test_stage_order(self):
        assert briefing_pipeline.STAGE_ORDER["INGEST"] == 0
        assert briefing_pipeline.STAGE_ORDER["PUBLISHED"] == 4

    def test_stages_contain_expected_names(self):
        assert "INGEST" in briefing_pipeline.STAGES
        assert "ANALYZE" in briefing_pipeline.STAGES
        assert "CORROBORATE" in briefing_pipeline.STAGES
        assert "SYNTHESIZE" in briefing_pipeline.STAGES
        assert "PUBLISHED" in briefing_pipeline.STAGES


class TestExtractItems:
    def test_extracts_watch_items(self):
        items = briefing_pipeline._extract_items_from_briefing(_sample_briefing())
        watch = [i for i in items if i["item_type"] == "watch"]
        assert len(watch) == 2
        assert watch[0]["item_id"] == "watch:gdacs:EQ123"
        assert watch[0]["title"] == "M5.2 earthquake near Sumatra"

    def test_extracts_insights(self):
        items = briefing_pipeline._extract_items_from_briefing(_sample_briefing())
        insights = [i for i in items if i["item_type"] == "insight"]
        assert len(insights) == 1
        assert insights[0]["item_id"] == "insight:2.5,96.0"

    def test_extracts_alerts(self):
        items = briefing_pipeline._extract_items_from_briefing(_sample_briefing())
        alerts = [i for i in items if i["item_type"] == "alert"]
        assert len(alerts) == 1

    def test_extracts_hotspots(self):
        items = briefing_pipeline._extract_items_from_briefing(_sample_briefing())
        hotspots = [i for i in items if i["item_type"] == "hotspot"]
        assert len(hotspots) == 1
        assert hotspots[0]["item_id"] == "hotspot:13.75,100.5"

    def test_empty_briefing(self):
        items = briefing_pipeline._extract_items_from_briefing({})
        assert items == []

    def test_briefing_with_none_fields(self):
        items = briefing_pipeline._extract_items_from_briefing(
            {
                "watch_items": None,
                "insights": None,
                "alerts": None,
                "fusion_hotspots": None,
            }
        )
        assert items == []


class TestSyncFromBriefing:
    def test_sync_inserts_new_items(self):
        count = briefing_pipeline.sync_from_briefing(_sample_briefing())
        assert count == 5  # 2 watch + 1 insight + 1 alert + 1 hotspot

    def test_sync_new_items_at_ingest_stage(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        pipeline = briefing_pipeline.get_pipeline()
        assert len(pipeline["INGEST"]) == 5
        assert len(pipeline["ANALYZE"]) == 0

    def test_sync_preserves_existing_stage(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        briefing_pipeline.move_item("watch:gdacs:EQ123", "ANALYZE")

        # Re-sync — item should stay at ANALYZE
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        pipeline = briefing_pipeline.get_pipeline()
        ingest_ids = [i["item_id"] for i in pipeline["INGEST"]]
        analyze_ids = [i["item_id"] for i in pipeline["ANALYZE"]]
        assert "watch:gdacs:EQ123" not in ingest_ids
        assert "watch:gdacs:EQ123" in analyze_ids

    def test_sync_removes_stale_items(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        # Sync with a briefing missing one watch item
        briefing_data = _sample_briefing()
        briefing_data["watch_items"] = [briefing_data["watch_items"][0]]
        briefing_pipeline.sync_from_briefing(briefing_data)

        flat = briefing_pipeline.get_pipeline_flat()
        ids = [i["item_id"] for i in flat]
        assert "watch:gdelt:ABC" not in ids

    def test_sync_preserves_published_items(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        briefing_pipeline.move_item("watch:gdelt:ABC", "PUBLISHED")

        # Sync with a briefing missing that item
        briefing_data = _sample_briefing()
        briefing_data["watch_items"] = [briefing_data["watch_items"][0]]
        briefing_pipeline.sync_from_briefing(briefing_data)

        flat = briefing_pipeline.get_pipeline_flat()
        ids = [i["item_id"] for i in flat]
        assert "watch:gdelt:ABC" in ids  # PUBLISHED items are kept

    def test_sync_empty_briefing(self):
        count = briefing_pipeline.sync_from_briefing({})
        assert count == 0

    def test_sync_updates_metadata(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        # Sync again with updated title
        briefing_data = _sample_briefing()
        briefing_data["watch_items"][0]["title"] = "UPDATED TITLE"
        briefing_pipeline.sync_from_briefing(briefing_data)

        flat = {i["item_id"]: i for i in briefing_pipeline.get_pipeline_flat()}
        assert flat["watch:gdacs:EQ123"]["title"] == "UPDATED TITLE"


class TestGetPipeline:
    def test_returns_all_stages(self):
        pipeline = briefing_pipeline.get_pipeline()
        for stage in briefing_pipeline.STAGES:
            assert stage in pipeline
            assert isinstance(pipeline[stage], list)

    def test_empty_pipeline(self):
        pipeline = briefing_pipeline.get_pipeline()
        for stage in briefing_pipeline.STAGES:
            assert pipeline[stage] == []

    def test_items_have_required_fields(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        pipeline = briefing_pipeline.get_pipeline()
        item = pipeline["INGEST"][0]
        assert "item_id" in item
        assert "stage" in item
        assert "title" in item
        assert "item_type" in item
        assert "confidence" in item
        assert "sources" in item
        assert "lat" in item
        assert "lon" in item
        assert "bucket" in item
        assert "created_at" in item
        assert "updated_at" in item
        assert "payload" in item


class TestMoveItem:
    def test_move_forward(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        result = briefing_pipeline.move_item("watch:gdacs:EQ123", "ANALYZE")
        assert result["old_stage"] == "INGEST"
        assert result["new_stage"] == "ANALYZE"

    def test_move_to_published(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        briefing_pipeline.move_item("watch:gdacs:EQ123", "ANALYZE")
        briefing_pipeline.move_item("watch:gdacs:EQ123", "CORROBORATE")
        result = briefing_pipeline.move_item("watch:gdacs:EQ123", "PUBLISHED")
        assert result["new_stage"] == "PUBLISHED"

    def test_move_backward(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        briefing_pipeline.move_item("watch:gdacs:EQ123", "SYNTHESIZE")
        result = briefing_pipeline.move_item("watch:gdacs:EQ123", "INGEST")
        assert result["old_stage"] == "SYNTHESIZE"
        assert result["new_stage"] == "INGEST"

    def test_move_invalid_stage_raises(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        with pytest.raises(ValueError, match="Invalid stage"):
            briefing_pipeline.move_item("watch:gdacs:EQ123", "INVALID")

    def test_move_nonexistent_item_raises(self):
        with pytest.raises(ValueError, match="Item not found"):
            briefing_pipeline.move_item("nonexistent", "ANALYZE")

    def test_move_updates_stage_in_db(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        briefing_pipeline.move_item("watch:gdacs:EQ123", "CORROBORATE")
        pipeline = briefing_pipeline.get_pipeline()
        corroborate_ids = [i["item_id"] for i in pipeline["CORROBORATE"]]
        ingest_ids = [i["item_id"] for i in pipeline["INGEST"]]
        assert "watch:gdacs:EQ123" in corroborate_ids
        assert "watch:gdacs:EQ123" not in ingest_ids


class TestClearPipeline:
    def test_clear_removes_all(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        count = briefing_pipeline.clear_pipeline()
        assert count == 5
        assert len(briefing_pipeline.get_pipeline_flat()) == 0

    def test_clear_empty(self):
        count = briefing_pipeline.clear_pipeline()
        assert count == 0


class TestGetPipelineFlat:
    def test_returns_flat_list(self):
        briefing_pipeline.sync_from_briefing(_sample_briefing())
        flat = briefing_pipeline.get_pipeline_flat()
        assert len(flat) == 5

    def test_empty_returns_empty(self):
        flat = briefing_pipeline.get_pipeline_flat()
        assert flat == []
