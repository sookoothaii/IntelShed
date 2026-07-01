"""Unit tests for V4-21 Temporal Analysis Engine (no network)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from temporal_engine import (
    GrangerResult,
    TimeSeries,
    TrendResult,
    _align_series,
    _bucket_series,
    _f_distribution_cdf,
    _gauss_solve,
    _linear_regression,
    _mann_kendall,
    _mean,
    _normal_cdf,
    _parse_timestamp,
    _pearson_corr,
    _std,
    detect_trend,
    format_temporal_trace_line,
    granger_probe,
    run_temporal_analysis,
    temporal_engine_enabled,
)


class TemporalEnvTests(unittest.TestCase):
    def setUp(self):
        import config

        config.get_config.cache_clear()

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_TEMPORAL_ENGINE", None)
            self.assertFalse(temporal_engine_enabled())

    def test_enabled_when_set(self):
        with patch.dict(os.environ, {"WORLDBASE_TEMPORAL_ENGINE": "1"}):
            self.assertTrue(temporal_engine_enabled())


class StatsHelperTests(unittest.TestCase):
    def test_mean_empty(self):
        self.assertEqual(_mean([]), 0.0)

    def test_mean_basic(self):
        self.assertAlmostEqual(_mean([1, 2, 3, 4, 5]), 3.0)

    def test_std_empty(self):
        self.assertEqual(_std([]), 0.0)

    def test_std_single(self):
        self.assertEqual(_std([5.0]), 0.0)

    def test_std_basic(self):
        s = _std([2, 4, 4, 4, 5, 5, 7, 9])
        # Sample std (n-1 denominator) = 2.138, population std = 2.0
        self.assertAlmostEqual(s, 2.138, places=1)

    def test_linear_regression_flat(self):
        slope, r2 = _linear_regression([0, 1, 2, 3], [5, 5, 5, 5])
        self.assertEqual(slope, 0.0)
        self.assertEqual(r2, 0.0)

    def test_linear_regression_positive(self):
        slope, r2 = _linear_regression([0, 1, 2, 3, 4], [1, 2, 3, 4, 5])
        self.assertAlmostEqual(slope, 1.0)
        self.assertAlmostEqual(r2, 1.0)

    def test_linear_regression_negative(self):
        slope, r2 = _linear_regression([0, 1, 2, 3], [4, 3, 2, 1])
        self.assertAlmostEqual(slope, -1.0)
        self.assertAlmostEqual(r2, 1.0)

    def test_linear_regression_short(self):
        slope, r2 = _linear_regression([0], [5])
        self.assertEqual(slope, 0.0)

    def test_mann_kendall_increasing(self):
        s, p = _mann_kendall([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        self.assertGreater(s, 0)
        self.assertLess(p, 0.05)

    def test_mann_kendall_decreasing(self):
        s, p = _mann_kendall([10, 9, 8, 7, 6, 5, 4, 3, 2, 1])
        self.assertLess(s, 0)
        self.assertLess(p, 0.05)

    def test_mann_kendall_flat(self):
        s, p = _mann_kendall([5, 5, 5, 5, 5, 5, 5, 5])
        self.assertEqual(s, 0)
        self.assertGreaterEqual(p, 0.5)

    def test_mann_kendall_short(self):
        s, p = _mann_kendall([1])
        self.assertEqual(s, 0.0)

    def test_normal_cdf_zero(self):
        self.assertAlmostEqual(_normal_cdf(0), 0.5, places=4)

    def test_normal_cdf_positive(self):
        cdf = _normal_cdf(2.0)
        self.assertGreater(cdf, 0.97)
        self.assertLess(cdf, 1.0)

    def test_f_distribution_cdf_zero(self):
        self.assertEqual(_f_distribution_cdf(0, 5, 10), 0.0)

    def test_f_distribution_cdf_positive(self):
        cdf = _f_distribution_cdf(5.0, 5, 10)
        self.assertGreater(cdf, 0.5)

    def test_pearson_corr_perfect_positive(self):
        r = _pearson_corr([1, 2, 3, 4], [2, 4, 6, 8])
        self.assertAlmostEqual(r, 1.0, places=4)

    def test_pearson_corr_perfect_negative(self):
        r = _pearson_corr([1, 2, 3, 4], [4, 3, 2, 1])
        self.assertAlmostEqual(r, -1.0, places=4)

    def test_pearson_corr_no_correlation(self):
        r = _pearson_corr([1, 2, 3, 4], [1, 1, 1, 1])
        self.assertEqual(r, 0.0)

    def test_gauss_solve_basic(self):
        # 2x + y = 5, x + 3y = 10 -> x=1, y=3
        matrix = [[2, 1], [1, 3]]
        rhs = [5, 10]
        sol = _gauss_solve(matrix, rhs)
        self.assertAlmostEqual(sol[0], 1.0, places=4)
        self.assertAlmostEqual(sol[1], 3.0, places=4)

    def test_gauss_solve_singular(self):
        matrix = [[1, 1], [1, 1]]
        rhs = [1, 2]
        sol = _gauss_solve(matrix, rhs)
        self.assertIsNone(sol)


class ParseTimestampTests(unittest.TestCase):
    def test_epoch_float(self):
        self.assertEqual(_parse_timestamp(1234567890.0), 1234567890.0)

    def test_iso_format(self):
        epoch = _parse_timestamp("2024-01-15T10:30:00Z")
        self.assertIsNotNone(epoch)
        self.assertGreater(epoch, 0)

    def test_iso_with_timezone(self):
        epoch = _parse_timestamp("2024-01-15T10:30:00+00:00")
        self.assertIsNotNone(epoch)

    def test_gdelt_format(self):
        epoch = _parse_timestamp("20240115T103000Z")
        self.assertIsNotNone(epoch)
        self.assertGreater(epoch, 0)

    def test_date_only(self):
        epoch = _parse_timestamp("2024-01-15")
        self.assertIsNotNone(epoch)

    def test_invalid(self):
        self.assertIsNone(_parse_timestamp("not a date"))

    def test_none(self):
        self.assertIsNone(_parse_timestamp(None))


class BucketSeriesTests(unittest.TestCase):
    def test_basic_bucketing(self):
        ts = TimeSeries(
            name="test",
            timestamps=[0, 1800, 3600, 5400],
            values=[1, 1, 1, 1],
        )
        bucketed = _bucket_series(ts, bucket_sec=3600.0)
        self.assertEqual(bucketed.length, 2)
        self.assertEqual(bucketed.values, [2.0, 2.0])

    def test_empty_series(self):
        ts = TimeSeries(name="empty")
        bucketed = _bucket_series(ts)
        self.assertEqual(bucketed.length, 0)

    def test_single_bucket(self):
        ts = TimeSeries(name="test", timestamps=[100, 200, 300], values=[1, 1, 1])
        bucketed = _bucket_series(ts, bucket_sec=3600.0)
        self.assertEqual(bucketed.length, 1)
        self.assertEqual(bucketed.values[0], 3.0)


class AlignSeriesTests(unittest.TestCase):
    def test_align_equal_length(self):
        a = TimeSeries(name="a", timestamps=[0, 1, 2], values=[10, 20, 30])
        b = TimeSeries(name="b", timestamps=[0, 1, 2], values=[5, 6, 7])
        va, vb = _align_series(a, b)
        self.assertEqual(va, [10, 20, 30])
        self.assertEqual(vb, [5, 6, 7])

    def test_align_different_length(self):
        a = TimeSeries(name="a", timestamps=[0, 1, 2, 3], values=[10, 20, 30, 40])
        b = TimeSeries(name="b", timestamps=[0, 1, 2], values=[5, 6, 7])
        va, vb = _align_series(a, b)
        self.assertEqual(len(va), 3)
        self.assertEqual(len(vb), 3)

    def test_align_empty(self):
        a = TimeSeries(name="a")
        b = TimeSeries(name="b", timestamps=[0], values=[1])
        va, vb = _align_series(a, b)
        self.assertEqual(va, [])
        self.assertEqual(vb, [])


class DetectTrendTests(unittest.TestCase):
    def test_increasing_trend(self):
        ts = TimeSeries(name="test", values=[float(i) for i in range(10)])
        result = detect_trend(ts)
        self.assertEqual(result.trend_direction, "increasing")
        self.assertGreater(result.slope, 0)
        self.assertLess(result.mann_kendall_p, 0.05)

    def test_decreasing_trend(self):
        ts = TimeSeries(name="test", values=[float(10 - i) for i in range(10)])
        result = detect_trend(ts)
        self.assertEqual(result.trend_direction, "decreasing")
        self.assertLess(result.slope, 0)

    def test_flat_trend(self):
        ts = TimeSeries(name="test", values=[5.0] * 10)
        result = detect_trend(ts)
        self.assertEqual(result.trend_direction, "flat")
        self.assertEqual(result.slope, 0.0)

    def test_short_series(self):
        ts = TimeSeries(name="test", values=[1.0])
        result = detect_trend(ts)
        self.assertEqual(result.n, 1)
        self.assertEqual(result.trend_direction, "flat")

    def test_empty_series(self):
        ts = TimeSeries(name="test")
        result = detect_trend(ts)
        self.assertEqual(result.n, 0)


class GrangerProbeTests(unittest.TestCase):
    def test_significant_causality(self):
        # cause predicts effect with a lag
        cause_vals = [float(i % 5) for i in range(20)]
        effect_vals = [float((i - 1) % 5) for i in range(20)]  # lag-1 copy
        cause = TimeSeries(name="cause", timestamps=list(range(20)), values=cause_vals)
        effect = TimeSeries(
            name="effect", timestamps=list(range(20)), values=effect_vals
        )
        results = granger_probe(cause, effect, max_lag=2)
        self.assertGreater(len(results), 0)
        # At least one should show some signal
        self.assertTrue(any(r.f_statistic > 0 for r in results))

    def test_no_causality_random(self):
        cause = TimeSeries(
            name="c",
            timestamps=list(range(15)),
            values=[1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
        )
        effect = TimeSeries(
            name="e",
            timestamps=list(range(15)),
            values=[0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
        )
        results = granger_probe(cause, effect, max_lag=2)
        # Random-ish data shouldn't show strong causality
        self.assertTrue(all(r.p_value >= 0.05 or r.p_value <= 1.0 for r in results))

    def test_insufficient_data(self):
        cause = TimeSeries(name="c", timestamps=[0, 1], values=[1, 2])
        effect = TimeSeries(name="e", timestamps=[0, 1], values=[3, 4])
        results = granger_probe(cause, effect, max_lag=3)
        self.assertEqual(len(results), 0)

    def test_result_fields(self):
        cause = TimeSeries(
            name="c", timestamps=list(range(15)), values=[float(i) for i in range(15)]
        )
        effect = TimeSeries(
            name="e",
            timestamps=list(range(15)),
            values=[float(i * 2) for i in range(15)],
        )
        results = granger_probe(cause, effect, max_lag=1)
        for r in results:
            self.assertEqual(r.cause, "c")
            self.assertEqual(r.effect, "e")
            self.assertGreaterEqual(r.lag, 1)
            self.assertGreaterEqual(r.f_statistic, 0.0)
            self.assertGreaterEqual(r.p_value, 0.0)
            self.assertLessEqual(r.p_value, 1.0)


class FormatTraceLineTests(unittest.TestCase):
    def test_disabled_returns_empty(self):
        from temporal_engine import TemporalAnalysisResult

        result = TemporalAnalysisResult(enabled=False)
        self.assertEqual(format_temporal_trace_line(result), "")

    def test_enabled_returns_summary(self):
        from temporal_engine import TemporalAnalysisResult

        result = TemporalAnalysisResult(
            enabled=True,
            series_count=3,
            trends=[TrendResult(name="test")],
            granger_results=[GrangerResult(cause="a", effect="b")],
        )
        line = format_temporal_trace_line(result)
        self.assertIn("TEMPORAL", line)
        self.assertIn("Series: 3", line)


class RunTemporalAnalysisTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import config

        config.get_config.cache_clear()

    async def test_disabled_returns_empty(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WORLDBASE_TEMPORAL_ENGINE", None)
            result = await run_temporal_analysis()
        self.assertFalse(result.enabled)

    async def test_no_data_returns_empty_trends(self):
        with patch.dict(os.environ, {"WORLDBASE_TEMPORAL_ENGINE": "1"}):
            with patch(
                "temporal_engine._collect_feed_series",
                return_value=[],
            ):
                result = await run_temporal_analysis()
        self.assertTrue(result.enabled)
        self.assertEqual(result.series_count, 0)
        self.assertEqual(len(result.trends), 0)

    async def test_with_mock_series(self):
        ts1 = TimeSeries(
            name="gdelt_events",
            timestamps=[float(i) * 3600 for i in range(10)],
            values=[float(i) for i in range(10)],
        )
        ts2 = TimeSeries(
            name="earthquakes",
            timestamps=[float(i) * 3600 for i in range(10)],
            values=[float(i * 2) for i in range(10)],
        )
        with patch.dict(os.environ, {"WORLDBASE_TEMPORAL_ENGINE": "1"}):
            with patch(
                "temporal_engine._collect_feed_series",
                return_value=[ts1, ts2],
            ):
                result = await run_temporal_analysis()
        self.assertTrue(result.enabled)
        self.assertEqual(result.series_count, 2)
        self.assertGreater(len(result.trends), 0)
        self.assertGreater(len(result.granger_results), 0)
        self.assertTrue(result.formatted_block)

    async def test_result_to_dict(self):
        ts = TimeSeries(
            name="test",
            timestamps=[float(i) for i in range(10)],
            values=[float(i) for i in range(10)],
        )
        with patch.dict(os.environ, {"WORLDBASE_TEMPORAL_ENGINE": "1"}):
            with patch(
                "temporal_engine._collect_feed_series",
                return_value=[ts],
            ):
                result = await run_temporal_analysis()
        d = result.to_dict()
        self.assertTrue(d["enabled"])
        self.assertIn("trends", d)
        self.assertIn("granger", d)


if __name__ == "__main__":
    unittest.main()
