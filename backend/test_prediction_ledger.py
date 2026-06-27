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
        q = score_briefing(
            text="LOCAL\n- test", sources={"digest": {"local_count": 1}}, created_at=now
        )
        self.assertEqual(q["meta"]["prediction_sample_30d"], 1)
        self.assertEqual(q["meta"]["prediction_accuracy_30d"], 1.0)

    def test_resolve_fusion_hit_by_score(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        self._insert_row(
            issued_at=old,
            prefix="fusion_delta",
            claim="Rising fusion cell (Δ+0.90): Flood Warning",
            sources='["hazard"]',
            cell_id="37.00,-97.00",
        )
        fusion_cells = [
            {
                "cell_id": "37.00,-97.00",
                "lat": 37.0,
                "lon": -97.0,
                "score": 0.68,
                "delta_score": 0.1,
            }
        ]
        result = pl.resolve_pending({}, fusion_cells)
        self.assertEqual(result["hits"], 1)

    def test_resolve_fusion_miss_cooled(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        self._insert_row(
            issued_at=old,
            prefix="fusion_delta",
            claim="Rising fusion cell (Δ+0.90): Flood Warning",
            sources='["hazard"]',
            cell_id="37.00,-97.00",
        )
        fusion_cells = [
            {
                "cell_id": "37.00,-97.00",
                "lat": 37.0,
                "lon": -97.0,
                "score": 0.2,
                "delta_score": 0.05,
            }
        ]
        result = pl.resolve_pending({}, fusion_cells)
        self.assertEqual(result["misses"], 1)

    def test_resolve_maritime_hit(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        self._insert_row(
            issued_at=old,
            prefix="maritime",
            claim="Maritime corridor density — 18 vessels tracked",
            sources='["maritime"]',
            horizon_h=48,
        )
        snap = {
            "maritime": {
                "vessels": [
                    {"region": "malacca"},
                    {"region": "laem_chabang"},
                    {"region": "bangkok_port"},
                ]
                * 5
            }
        }
        result = pl.resolve_pending(snap, [])
        self.assertEqual(result["hits"], 1)

    def test_resolve_maritime_miss(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()
        self._insert_row(
            issued_at=old,
            prefix="maritime",
            claim="Maritime corridor density — 18 vessels tracked",
            sources='["maritime"]',
            horizon_h=48,
        )
        snap = {
            "maritime": {
                "vessels": [
                    {"region": "malacca"},
                    {"region": "hamburg"},
                ]
            }
        }
        result = pl.resolve_pending(snap, [])
        self.assertEqual(result["misses"], 1)

    def test_resolve_hdx_hit(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
        self._insert_row(
            issued_at=old,
            prefix="hdx",
            claim="Humanitarian watch — Myanmar displacement datasets",
            sources='["humanitarian"]',
            horizon_h=72,
        )
        snap = {
            "humanitarian": {
                "datasets": [
                    {"title": "Myanmar displacement datasets Q2 2026"},
                    {"title": "Thailand refugee support"},
                    {"title": "ASEAN crisis funding"},
                ]
            }
        }
        result = pl.resolve_pending(snap, [])
        self.assertEqual(result["hits"], 1)

    def test_resolve_hdx_miss(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=80)).isoformat()
        self._insert_row(
            issued_at=old,
            prefix="hdx",
            claim="Humanitarian watch — Myanmar displacement datasets",
            sources='["humanitarian"]',
            horizon_h=72,
        )
        snap = {"humanitarian": {"datasets": [{"title": "Unrelated nutrition survey"}]}}
        result = pl.resolve_pending(snap, [])
        self.assertEqual(result["misses"], 1)

    def test_resolve_alert_gdacs_hit(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        self._insert_row(
            issued_at=old,
            prefix="alert",
            claim="25 GDACS humanitarian alerts active.",
            sources='["alerts"]',
            horizon_h=24,
        )
        snap = {"gdacs": {"count": 18, "alerts": [{}] * 18}}
        result = pl.resolve_pending(snap, [])
        self.assertEqual(result["hits"], 1)

    def test_resolve_alert_gdacs_miss(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        self._insert_row(
            issued_at=old,
            prefix="alert",
            claim="25 GDACS humanitarian alerts active.",
            sources='["alerts"]',
            horizon_h=24,
        )
        snap = {"gdacs": {"count": 2, "alerts": [{}, {}]}}
        result = pl.resolve_pending(snap, [])
        self.assertEqual(result["misses"], 1)

    def test_list_predictions_pending_and_resolved(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        future = datetime.now(timezone.utc).isoformat()
        self._insert_row(watch_id="resolved1", issued_at=old, prefix="gdelt")
        self._insert_row(watch_id="pending1", issued_at=future, prefix="cams")
        pl.resolve_pending(
            {
                "gdelt_pulse_local": {"articles": [{}, {}, {}, {}]},
                "gdelt_geo_local": {"events": [{}, {}, {}]},
            },
            [],
        )
        out = pl.list_predictions(pending_limit=5, resolved_limit=5)
        self.assertEqual(out["stats"]["pending"], 1)
        self.assertEqual(len(out["resolved_recent"]), 1)
        self.assertEqual(out["resolved_recent"][0]["hit"], 1)
        self.assertEqual(len(out["pending"]), 1)
        self.assertFalse(out["pending"][0]["overdue"])

    def test_list_watches_for_rag_orders_pending_first(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()
        self._insert_row(watch_id="resolved1", issued_at=old, prefix="gdelt")
        self._insert_row(watch_id="pending1", issued_at=future, prefix="cams")
        pl.resolve_pending(
            {
                "gdelt_pulse_local": {"articles": [{}, {}, {}, {}]},
                "gdelt_geo_local": {"events": [{}, {}, {}]},
            },
            [],
        )
        rows = pl.list_watches_for_rag(limit=10)
        self.assertGreaterEqual(len(rows), 2)
        self.assertIsNone(rows[0]["hit"])
        self.assertIsNotNone(rows[1]["hit"])

    def test_calibration_curve_empty(self):
        curve = pl.calibration_curve()
        self.assertEqual(curve["total_resolved"], 0)
        self.assertEqual(curve["bins"], [])
        self.assertIsNone(curve["calibration_error"])

    def test_calibration_curve_well_calibrated(self):
        """All predictions at confidence 0.8, all hit → gap near 0.2 (overconfident)."""
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        for i in range(5):
            self._insert_row(
                watch_id=f"cal_hit_{i}",
                issued_at=old,
                prefix="gdelt",
            )
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "UPDATE briefing_predictions SET confidence = 0.8 WHERE watch_id = ?",
                    (f"cal_hit_{i}",),
                )
                conn.commit()
        pl.resolve_pending(
            {
                "gdelt_pulse_local": {"articles": [{}, {}, {}, {}, {}]},
                "gdelt_geo_local": {"events": [{}, {}, {}]},
            },
            [],
        )
        curve = pl.calibration_curve(n_bins=5)
        self.assertEqual(curve["total_resolved"], 5)
        self.assertEqual(curve["overall_accuracy"], 1.0)
        # All in the 0.8-1.0 bin
        high_bin = [b for b in curve["bins"] if b["bin_low"] == 0.8][0]
        self.assertEqual(high_bin["count"], 5)
        self.assertEqual(high_bin["hits"], 5)
        self.assertEqual(high_bin["actual_accuracy"], 1.0)
        self.assertAlmostEqual(high_bin["mean_confidence"], 0.8)
        # Gap = 0.8 - 1.0 = -0.2 (underconfident)
        self.assertAlmostEqual(high_bin["calibration_gap"], -0.2)

    def test_calibration_curve_overconfident(self):
        """Predictions at confidence 0.9 but all miss → gap = 0.9 (overconfident)."""
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        for i in range(3):
            self._insert_row(
                watch_id=f"cal_miss_{i}",
                issued_at=old,
                prefix="gdelt",
            )
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "UPDATE briefing_predictions SET confidence = 0.9 WHERE watch_id = ?",
                    (f"cal_miss_{i}",),
                )
                conn.commit()
        pl.resolve_pending(
            {
                "gdelt_pulse_local": {"articles": [{}]},
                "gdelt_geo_local": {"events": []},
            },
            [],
        )
        curve = pl.calibration_curve(n_bins=5)
        self.assertEqual(curve["overall_accuracy"], 0.0)
        high_bin = [b for b in curve["bins"] if b["bin_low"] == 0.8][0]
        self.assertEqual(high_bin["count"], 3)
        self.assertEqual(high_bin["misses"], 3)
        self.assertAlmostEqual(high_bin["calibration_gap"], 0.9)

    def test_calibration_curve_ece(self):
        """Expected Calibration Error: weighted average of |gap|."""
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        # 2 hits at conf 0.5, 2 misses at conf 0.5
        for i in range(4):
            self._insert_row(
                watch_id=f"ece_{i}",
                issued_at=old,
                prefix="gdelt",
            )
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "UPDATE briefing_predictions SET confidence = 0.5 WHERE watch_id = ?",
                    (f"ece_{i}",),
                )
                conn.commit()
        # 2 hit, 2 miss → actual accuracy 0.5, gap = 0.0
        # Resolve first 2 as hits
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(
                "UPDATE briefing_predictions SET hit = 1, outcome = 'hit' WHERE watch_id IN ('ece_0', 'ece_1')"
            )
            conn.execute(
                "UPDATE briefing_predictions SET hit = 0, outcome = 'miss' WHERE watch_id IN ('ece_2', 'ece_3')"
            )
            conn.commit()
        curve = pl.calibration_curve(n_bins=5)
        # All in 0.4-0.6 bin, accuracy 0.5, conf 0.5, gap 0.0
        mid_bin = [b for b in curve["bins"] if b["bin_low"] == 0.4][0]
        self.assertEqual(mid_bin["count"], 4)
        self.assertAlmostEqual(mid_bin["calibration_gap"], 0.0)
        self.assertAlmostEqual(curve["calibration_error"], 0.0)

    def test_record_watch_items_stores_confidence(self):
        issued = datetime.now(timezone.utc).isoformat()
        items = [
            {
                "id": "conf001",
                "prefix": "gdelt",
                "title": "Test confidence storage",
                "horizon_h": 24,
                "confidence": 0.75,
                "sources": ["gdelt_pulse_local"],
                "bucket": "local",
            }
        ]
        pl.record_watch_items(items, issued)
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT confidence FROM briefing_predictions WHERE watch_id = ?",
                ("conf001",),
            ).fetchone()
            self.assertAlmostEqual(row[0], 0.75)

    def test_calibration_map_empty(self):
        """No resolved predictions → all bins have factor=1.0."""
        cmap = pl.calibration_map()
        self.assertEqual(cmap["total_resolved"], 0)
        for b in cmap["bins"]:
            self.assertFalse(b["samples_sufficient"])

    def test_calibration_map_overconfident_bin(self):
        """Bin with high confidence but low accuracy → factor < 1.0."""
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        # 10 predictions at confidence 0.9, all miss
        for i in range(10):
            self._insert_row(
                watch_id=f"map_miss_{i}",
                issued_at=old,
                prefix="gdelt",
            )
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "UPDATE briefing_predictions SET confidence = 0.9 WHERE watch_id = ?",
                    (f"map_miss_{i}",),
                )
                conn.commit()
        pl.resolve_pending(
            {
                "gdelt_pulse_local": {"articles": [{}]},
                "gdelt_geo_local": {"events": []},
            },
            [],
        )
        cmap = pl.calibration_map(n_bins=5)
        high_bin = [b for b in cmap["bins"] if b["bin_low"] == 0.8][0]
        self.assertEqual(high_bin["count"], 10)
        self.assertEqual(high_bin["actual_accuracy"], 0.0)
        self.assertTrue(high_bin["samples_sufficient"])
        # adjusted = (10*0 + 5*0.9) / (10+5) = 4.5/15 = 0.3
        self.assertAlmostEqual(high_bin["adjusted_confidence"], 0.3)
        # factor = 0.3 / 0.9 = 0.333
        self.assertAlmostEqual(high_bin["adjustment_factor"], 0.333, places=2)

    def test_adjust_confidence_no_data(self):
        """No resolved predictions → adjust_confidence returns raw."""
        result = pl.adjust_confidence(0.8)
        self.assertAlmostEqual(result, 0.8)

    def test_adjust_confidence_overconfident(self):
        """With calibration data showing overconfidence, adjust down."""
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        # 15 predictions at confidence 0.9, all miss → bin is overconfident
        for i in range(15):
            self._insert_row(
                watch_id=f"adj_miss_{i}",
                issued_at=old,
                prefix="gdelt",
            )
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "UPDATE briefing_predictions SET confidence = 0.9 WHERE watch_id = ?",
                    (f"adj_miss_{i}",),
                )
                conn.commit()
        pl.resolve_pending(
            {
                "gdelt_pulse_local": {"articles": [{}]},
                "gdelt_geo_local": {"events": []},
            },
            [],
        )
        # Raw 0.9 should be adjusted down
        adjusted = pl.adjust_confidence(0.9)
        self.assertLess(adjusted, 0.9)
        self.assertGreater(adjusted, 0.0)

    def test_adjust_confidence_insufficient_samples(self):
        """With < min_samples, adjust_confidence returns raw."""
        old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
        # Only 2 predictions — below _CAL_MIN_SAMPLES (10)
        for i in range(2):
            self._insert_row(
                watch_id=f"insuf_{i}",
                issued_at=old,
                prefix="gdelt",
            )
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    "UPDATE briefing_predictions SET confidence = 0.9 WHERE watch_id = ?",
                    (f"insuf_{i}",),
                )
                conn.commit()
        pl.resolve_pending(
            {
                "gdelt_pulse_local": {"articles": [{}]},
                "gdelt_geo_local": {"events": []},
            },
            [],
        )
        result = pl.adjust_confidence(0.9)
        self.assertAlmostEqual(result, 0.9)

    def test_adjust_confidence_none(self):
        """None input → None output."""
        self.assertIsNone(pl.adjust_confidence(None))


if __name__ == "__main__":
    unittest.main()
