"""Tests for V4-19 Predictive Analytics (LightGBM / linear fallback)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import predictive_analytics as pa


def _make_snapshots(n: int = 10) -> list[dict]:
    """Generate n synthetic snapshots with growing entity counts."""
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    snaps = []
    for i in range(n):
        snaps.append(
            {
                "date": (base + timedelta(days=i)).strftime("%Y-%m-%d"),
                "timestamp": (base + timedelta(days=i)).isoformat(),
                "ftm": {
                    "entities": 100 + i * 15,
                    "statements": 200 + i * 30,
                    "edges": 10 + i * 2,
                },
                "feeds": {
                    "fresh_count": 20 - i % 3,
                    "stale_count": 2 + i % 4,
                    "error_count": 0,
                },
                "briefing": {"text_length": 5000 + i * 100},
                "rag": {"chunk_count": 50 + i * 5},
            }
        )
    return snaps


class TestPredictiveConfig(unittest.TestCase):
    def test_default_disabled(self):
        os.environ.pop("WORLDBASE_PREDICTIVE", None)
        self.assertFalse(pa._enabled())

    def test_enabled_flag(self):
        os.environ["WORLDBASE_PREDICTIVE"] = "1"
        try:
            self.assertTrue(pa._enabled())
        finally:
            os.environ.pop("WORLDBASE_PREDICTIVE", None)

    def test_enabled_flag_truthy(self):
        for val in ("true", "yes", "on", "TRUE", "Yes"):
            os.environ["WORLDBASE_PREDICTIVE"] = val
            try:
                self.assertTrue(pa._enabled())
            finally:
                os.environ.pop("WORLDBASE_PREDICTIVE", None)


class TestFeatureExtraction(unittest.TestCase):
    def test_extract_features_basic(self):
        snaps = _make_snapshots(10)
        features, targets = pa._extract_features(snaps)
        self.assertEqual(len(features), 9)  # last row has no next-day target
        self.assertEqual(len(targets), 9)
        self.assertEqual(len(features[0]), 8)  # 8 feature columns
        # First target should be day 1 entity count
        self.assertEqual(targets[0], 115.0)

    def test_extract_features_empty(self):
        features, targets = pa._extract_features([])
        self.assertEqual(features, [])
        self.assertEqual(targets, [])

    def test_extract_features_single(self):
        features, targets = pa._extract_features(_make_snapshots(1))
        self.assertEqual(len(features), 0)
        self.assertEqual(len(targets), 0)

    def test_extract_feed_anomaly_features(self):
        snaps = _make_snapshots(10)
        features, targets = pa._extract_feed_anomaly_features(snaps)
        self.assertEqual(len(features), 9)
        self.assertEqual(len(targets), 9)
        # All targets should be 0.0 or 1.0
        for t in targets:
            self.assertIn(t, (0.0, 1.0))


class TestLinearTraining(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._old_model_dir = pa._MODEL_DIR
        pa._MODEL_DIR = self.tmpdir
        pa._LINEAR_MODEL_PATH = os.path.join(
            self.tmpdir, "predictive_model_linear.json"
        )
        pa._LGBM_MODEL_PATH = os.path.join(self.tmpdir, "predictive_model.json")

    def tearDown(self):
        pa._MODEL_DIR = self._old_model_dir
        pa._LINEAR_MODEL_PATH = os.path.join(
            self._old_model_dir, "predictive_model_linear.json"
        )
        pa._LGBM_MODEL_PATH = os.path.join(self._old_model_dir, "predictive_model.json")

    def test_train_linear_sufficient_data(self):
        snaps = _make_snapshots(10)
        features, targets = pa._extract_features(snaps)
        result, model = pa._train_linear(features, targets)
        self.assertTrue(result.ok)
        self.assertEqual(result.model_type, "linear")
        self.assertEqual(result.samples, 9)
        self.assertIsNotNone(result.rmse)
        self.assertIsNotNone(model)
        self.assertIn("weights", model)

    def test_train_linear_insufficient_data(self):
        features = [[1.0, 2.0]]
        targets = [10.0]
        result, model = pa._train_linear(features, targets)
        self.assertFalse(result.ok)
        self.assertIsNone(model)
        self.assertIn("Insufficient", result.error)

    def test_linear_model_persisted(self):
        snaps = _make_snapshots(10)
        features, targets = pa._extract_features(snaps)
        pa._train_linear(features, targets)
        self.assertTrue(os.path.exists(pa._LINEAR_MODEL_PATH))
        with open(pa._LINEAR_MODEL_PATH, "r") as f:
            data = json.load(f)
        self.assertIn("weights", data)
        self.assertIn("rmse", data)


class TestGaussianElimination(unittest.TestCase):
    def test_simple_system(self):
        A = [[2.0, 1.0], [1.0, 3.0]]
        b = [5.0, 10.0]
        x = pa._gaussian_elimination(A, b)
        self.assertIsNotNone(x)
        self.assertAlmostEqual(x[0], 1.0, places=6)
        self.assertAlmostEqual(x[1], 3.0, places=6)

    def test_singular_matrix(self):
        A = [[1.0, 1.0], [1.0, 1.0]]
        b = [1.0, 2.0]
        x = pa._gaussian_elimination(A, b)
        self.assertIsNone(x)

    def test_3x3_system(self):
        A = [[1.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 3.0]]
        b = [1.0, 4.0, 9.0]
        x = pa._gaussian_elimination(A, b)
        self.assertIsNotNone(x)
        self.assertAlmostEqual(x[0], 1.0, places=6)
        self.assertAlmostEqual(x[1], 2.0, places=6)
        self.assertAlmostEqual(x[2], 3.0, places=6)


class TestForecast(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._old_model_dir = pa._MODEL_DIR
        pa._MODEL_DIR = self.tmpdir
        pa._LINEAR_MODEL_PATH = os.path.join(
            self.tmpdir, "predictive_model_linear.json"
        )
        pa._LGBM_MODEL_PATH = os.path.join(self.tmpdir, "predictive_model.json")
        self._old_snap_dir = os.environ.get("WORLDBASE_SNAPSHOT_DIR", "")

    def tearDown(self):
        pa._MODEL_DIR = self._old_model_dir
        pa._LINEAR_MODEL_PATH = os.path.join(
            self._old_model_dir, "predictive_model_linear.json"
        )
        pa._LGBM_MODEL_PATH = os.path.join(self._old_model_dir, "predictive_model.json")
        if self._old_snap_dir:
            os.environ["WORLDBASE_SNAPSHOT_DIR"] = self._old_snap_dir
        else:
            os.environ.pop("WORLDBASE_SNAPSHOT_DIR", None)

    def test_forecast_disabled(self):
        os.environ.pop("WORLDBASE_PREDICTIVE", None)
        result = pa.forecast()
        self.assertFalse(result["enabled"])

    def test_forecast_no_model(self):
        os.environ["WORLDBASE_PREDICTIVE"] = "1"
        snapdir = tempfile.mkdtemp()
        os.environ["WORLDBASE_SNAPSHOT_DIR"] = snapdir
        # Create minimal snapshots
        from pathlib import Path

        for i, snap in enumerate(_make_snapshots(10)):
            Path(snapdir, f"snapshot_{snap['date']}.json").write_text(
                json.dumps(snap), encoding="utf-8"
            )
        try:
            result = pa.forecast()
            self.assertTrue(result["enabled"])
            self.assertIn("No trained model", result["error"])
        finally:
            os.environ.pop("WORLDBASE_PREDICTIVE", None)

    def test_forecast_with_linear_model(self):
        os.environ["WORLDBASE_PREDICTIVE"] = "1"
        snapdir = tempfile.mkdtemp()
        os.environ["WORLDBASE_SNAPSHOT_DIR"] = snapdir
        from pathlib import Path

        snaps = _make_snapshots(10)
        for snap in snaps:
            Path(snapdir, f"snapshot_{snap['date']}.json").write_text(
                json.dumps(snap), encoding="utf-8"
            )
        # Train linear model
        features, targets = pa._extract_features(snaps)
        pa._train_linear(features, targets)
        try:
            result = pa.forecast()
            self.assertTrue(result["enabled"])
            self.assertEqual(result["model_type"], "linear")
            self.assertIn("predicted_entities", result)
            self.assertIn("current_entities", result)
        finally:
            os.environ.pop("WORLDBASE_PREDICTIVE", None)

    def test_forecast_insufficient_snapshots(self):
        os.environ["WORLDBASE_PREDICTIVE"] = "1"
        snapdir = tempfile.mkdtemp()
        os.environ["WORLDBASE_SNAPSHOT_DIR"] = snapdir
        from pathlib import Path

        for snap in _make_snapshots(3):
            Path(snapdir, f"snapshot_{snap['date']}.json").write_text(
                json.dumps(snap), encoding="utf-8"
            )
        try:
            result = pa.forecast()
            self.assertTrue(result["enabled"])
            self.assertIn("Insufficient", result["error"])
        finally:
            os.environ.pop("WORLDBASE_PREDICTIVE", None)


class TestTrainModel(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._old_model_dir = pa._MODEL_DIR
        pa._MODEL_DIR = self.tmpdir
        pa._LINEAR_MODEL_PATH = os.path.join(
            self.tmpdir, "predictive_model_linear.json"
        )
        pa._LGBM_MODEL_PATH = os.path.join(self.tmpdir, "predictive_model.json")
        self._old_snap_dir = os.environ.get("WORLDBASE_SNAPSHOT_DIR", "")

    def tearDown(self):
        pa._MODEL_DIR = self._old_model_dir
        pa._LINEAR_MODEL_PATH = os.path.join(
            self._old_model_dir, "predictive_model_linear.json"
        )
        pa._LGBM_MODEL_PATH = os.path.join(self._old_model_dir, "predictive_model.json")
        if self._old_snap_dir:
            os.environ["WORLDBASE_SNAPSHOT_DIR"] = self._old_snap_dir
        else:
            os.environ.pop("WORLDBASE_SNAPSHOT_DIR", None)

    def test_train_disabled(self):
        os.environ.pop("WORLDBASE_PREDICTIVE", None)
        result = pa.train_model()
        self.assertFalse(result["enabled"])

    def test_train_with_snapshots(self):
        os.environ["WORLDBASE_PREDICTIVE"] = "1"
        snapdir = tempfile.mkdtemp()
        os.environ["WORLDBASE_SNAPSHOT_DIR"] = snapdir
        from pathlib import Path

        for snap in _make_snapshots(10):
            Path(snapdir, f"snapshot_{snap['date']}.json").write_text(
                json.dumps(snap), encoding="utf-8"
            )
        try:
            result = pa.train_model()
            self.assertTrue(result["enabled"])
            self.assertTrue(result["ok"])
            self.assertIn(result["model_type"], ("lightgbm", "linear"))
            self.assertGreater(result["samples"], 0)
        finally:
            os.environ.pop("WORLDBASE_PREDICTIVE", None)

    def test_train_insufficient_snapshots(self):
        os.environ["WORLDBASE_PREDICTIVE"] = "1"
        snapdir = tempfile.mkdtemp()
        os.environ["WORLDBASE_SNAPSHOT_DIR"] = snapdir
        from pathlib import Path

        for snap in _make_snapshots(3):
            Path(snapdir, f"snapshot_{snap['date']}.json").write_text(
                json.dumps(snap), encoding="utf-8"
            )
        try:
            result = pa.train_model()
            self.assertTrue(result["enabled"])
            self.assertFalse(result["ok"])
        finally:
            os.environ.pop("WORLDBASE_PREDICTIVE", None)


class TestModelStatus(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._old_model_dir = pa._MODEL_DIR
        pa._MODEL_DIR = self.tmpdir
        pa._LINEAR_MODEL_PATH = os.path.join(
            self.tmpdir, "predictive_model_linear.json"
        )
        pa._LGBM_MODEL_PATH = os.path.join(self.tmpdir, "predictive_model.json")

    def tearDown(self):
        pa._MODEL_DIR = self._old_model_dir
        pa._LINEAR_MODEL_PATH = os.path.join(
            self._old_model_dir, "predictive_model_linear.json"
        )
        pa._LGBM_MODEL_PATH = os.path.join(self._old_model_dir, "predictive_model.json")

    def test_status_disabled(self):
        os.environ.pop("WORLDBASE_PREDICTIVE", None)
        result = pa.model_status()
        self.assertFalse(result["enabled"])

    def test_status_no_model(self):
        os.environ["WORLDBASE_PREDICTIVE"] = "1"
        try:
            result = pa.model_status()
            self.assertTrue(result["enabled"])
            self.assertFalse(result["model_trained"])
        finally:
            os.environ.pop("WORLDBASE_PREDICTIVE", None)

    def test_status_with_linear_model(self):
        os.environ["WORLDBASE_PREDICTIVE"] = "1"
        snaps = _make_snapshots(10)
        features, targets = pa._extract_features(snaps)
        pa._train_linear(features, targets)
        try:
            result = pa.model_status()
            self.assertTrue(result["enabled"])
            self.assertTrue(result["model_trained"])
            self.assertEqual(result["model_type"], "linear")
        finally:
            os.environ.pop("WORLDBASE_PREDICTIVE", None)


class TestForecastDigest(unittest.TestCase):
    def test_disabled_returns_empty(self):
        os.environ.pop("WORLDBASE_PREDICTIVE", None)
        result = pa.gather_forecast_digest()
        self.assertFalse(result["enabled"])
        self.assertEqual(result["count"], 0)

    def test_enabled_but_no_model(self):
        os.environ["WORLDBASE_PREDICTIVE"] = "1"
        snapdir = tempfile.mkdtemp()
        old_dir = os.environ.get("WORLDBASE_SNAPSHOT_DIR", "")
        os.environ["WORLDBASE_SNAPSHOT_DIR"] = snapdir
        from pathlib import Path

        for snap in _make_snapshots(10):
            Path(snapdir, f"snapshot_{snap['date']}.json").write_text(
                json.dumps(snap), encoding="utf-8"
            )
        try:
            result = pa.gather_forecast_digest()
            self.assertTrue(result["enabled"])
            self.assertEqual(result["count"], 0)
        finally:
            os.environ.pop("WORLDBASE_PREDICTIVE", None)
            if old_dir:
                os.environ["WORLDBASE_SNAPSHOT_DIR"] = old_dir
            else:
                os.environ.pop("WORLDBASE_SNAPSHOT_DIR", None)


class TestSnapshotLoading(unittest.TestCase):
    def test_load_from_temp_dir(self):
        snapdir = tempfile.mkdtemp()
        from pathlib import Path

        snaps = _make_snapshots(5)
        for snap in snaps:
            Path(snapdir, f"snapshot_{snap['date']}.json").write_text(
                json.dumps(snap), encoding="utf-8"
            )
        old_dir = os.environ.get("WORLDBASE_SNAPSHOT_DIR", "")
        os.environ["WORLDBASE_SNAPSHOT_DIR"] = snapdir
        try:
            loaded = pa._load_snapshot_dates()
            self.assertEqual(len(loaded), 5)
            self.assertEqual(loaded[0]["date"], snaps[0]["date"])
        finally:
            if old_dir:
                os.environ["WORLDBASE_SNAPSHOT_DIR"] = old_dir
            else:
                os.environ.pop("WORLDBASE_SNAPSHOT_DIR", None)

    def test_load_empty_dir(self):
        snapdir = tempfile.mkdtemp()
        old_dir = os.environ.get("WORLDBASE_SNAPSHOT_DIR", "")
        os.environ["WORLDBASE_SNAPSHOT_DIR"] = snapdir
        try:
            loaded = pa._load_snapshot_dates()
            self.assertEqual(loaded, [])
        finally:
            if old_dir:
                os.environ["WORLDBASE_SNAPSHOT_DIR"] = old_dir
            else:
                os.environ.pop("WORLDBASE_SNAPSHOT_DIR", None)

    def test_load_nonexistent_dir(self):
        old_dir = os.environ.get("WORLDBASE_SNAPSHOT_DIR", "")
        os.environ["WORLDBASE_SNAPSHOT_DIR"] = "/nonexistent/path/xyz"
        try:
            loaded = pa._load_snapshot_dates()
            self.assertEqual(loaded, [])
        finally:
            if old_dir:
                os.environ["WORLDBASE_SNAPSHOT_DIR"] = old_dir
            else:
                os.environ.pop("WORLDBASE_SNAPSHOT_DIR", None)


if __name__ == "__main__":
    unittest.main()
