"""Unit tests for prediction_ledger (Track 4, no network)."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import prediction_ledger as pl


class PredictionLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self._db_path = self.tmp.name
        self._orig = pl._DB_PATH
        pl._DB_PATH = self._db_path
        pl.init_prediction_db()

    def tearDown(self):
        pl._DB_PATH = self._orig
        try:
            os.unlink(self._db_path)
        except OSError:
            pass

    def _insert_row(
        self,
        *,
        watch_id: str = "abc123",
        prefix: str = "gdelt",
        issued_at: str,
        horizon_h: int = 24,
        claim: str = "Elevated media attention",
        sources: str = '["gdelt_pulse_local"]',
        cell_id: str | None = None,
    ) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                """
                INSERT INTO briefing_predictions (
                    watch_id, prefix, issued_at, horizon_h, claim, sources,
                    cell_id, bucket, outcome, outcome_at, hit
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'local', NULL, NULL, NULL)
                """,
                (watch_id, prefix, issued_at, horizon_h, claim, sources, cell_id),
            )
            conn.commit()

    def test_record_watch_items_dedupes_same_issue(self):
        issued = datetime.now(timezone.utc).isoformat()
        items = [
            {
                "id": "watch001",
                "prefix": "gdelt",
                "title": "Elevated media attention",
                "horizon_h": 24,
                "confidence": 0.7,
                "sources": ["gdelt_pulse_local"],
                "bucket": "local",
            }
        ]
        n1 = pl.record_watch_items(items, issued)
        n2 = pl.record_watch_items(items, issued)
        self.assertEqual(n1, 1)
        self.assertEqual(n2, 0)

    def test_resolve_gdelt_hit(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        self._insert_row(issued_at=old, prefix="gdelt")
        snap = {
            "gdelt_pulse_local": {"articles": [{}, {}, {}, {}, {}]},
            "gdelt_geo_local": {"events": [{}, {}]},
        }
        result = pl.resolve_pending(snap, [])
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(result["hits"], 1)
        stats = pl.accuracy_30d()
        self.assertEqual(stats["sample_size"], 1)
        self.assertEqual(stats["accuracy"], 1.0)

    def test_resolve_gdelt_miss(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        self._insert_row(issued_at=old, prefix="gdelt")
        snap = {
            "gdelt_pulse_local": {"articles": [{}]},
            "gdelt_geo_local": {"events": []},
        }
        result = pl.resolve_pending(snap, [])
        self.assertEqual(result["resolved"], 1)
        self.assertEqual(result["misses"], 1)

    def test_resolve_cams_hit(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
        self._insert_row(
            issued_at=old,
            prefix="cams",
            claim="Haze trajectory — Bangkok: PM2.5 40 µg/m³",
            sources='["cams_haze"]',
            cell_id="13.75,100.50",
        )
        snap = {
            "cams_haze": {
                "cities": [
                    {
                        "city": "Bangkok",
                        "lat": 13.75,
                        "lon": 100.5,
                        "pm25": 58,
                        "severity": "high",
                    }
                ]
            }
        }
        result = pl.resolve_pending(snap, [])
        self.assertEqual(result["hits"], 1)

    def test_pending_not_counted_in_accuracy(self):
        future = datetime.now(timezone.utc).isoformat()
        self._insert_row(watch_id="pending1", issued_at=future, prefix="gdelt")
        stats = pl.accuracy_30d()
        self.assertEqual(stats["pending"], 1)
        self.assertIsNone(stats["accuracy"])
        self.assertEqual(stats["sample_size"], 0)

    def test_format_accuracy_line_en(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        self._insert_row(watch_id="hit1", issued_at=old, prefix="gdelt")
        pl.resolve_pending(
            {
                "gdelt_pulse_local": {"articles": [{}, {}, {}, {}]},
                "gdelt_geo_local": {"events": [{}, {}, {}]},
            },
            [],
        )
        line = pl.format_accuracy_line(lang="en")
        self.assertIn("30d watch hit rate", line)
        self.assertIn("n=1", line)

    def test_format_accuracy_line_de_no_data(self):
        line = pl.format_accuracy_line(lang="de")
        self.assertIn("Prognose-Kalibration", line)

    def test_quality_meta_includes_prediction_fields(self):
        from briefing_quality import score_briefing

        now = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        self._insert_row(watch_id="q1", issued_at=old, prefix="gdelt")
        pl.resolve_pending(
            {
                "gdelt_pulse_local": {"articles": [{}, {}, {}, {}]},
                "gdelt_geo_local": {"events": [{}, {}, {}]},
            },
            [],
        )
        q = score_briefing(text="LOCAL\n- test", sources={"digest": {"local_count": 1}}, created_at=now)
        self.assertEqual(q["meta"]["prediction_sample_30d"], 1)
        self.assertEqual(q["meta"]["prediction_accuracy_30d"], 1.0)


if __name__ == "__main__":
    unittest.main()
