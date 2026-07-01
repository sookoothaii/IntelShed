"""V4-21 — Temporal Analysis Engine (Granger-Causality Probe + Trend Detection).

Analyzes feed time-series data for trends and potential causal relationships.

Components:
  1. Time-series extraction from cached feed data (GDELT, quakes, events, etc.)
  2. Trend detection via linear regression slope + Mann-Kendall test
  3. Granger-causality probe: does one series help predict another?
     (lag-based F-test approximation, pure Python — no statsmodels dependency)

All statistics are computed with pure-Python implementations (0 external deps
beyond the standard library) to keep the module lightweight and deployable.

Env:
  WORLDBASE_TEMPORAL_ENGINE=1 (default off, opt-in)
  WORLDBASE_TEMPORAL_ENGINE_MAX_LAG=3 (max lag for Granger probe)
  WORLDBASE_TEMPORAL_ENGINE_MIN_POINTS=5 (minimum data points for analysis)
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from config import get_config


@dataclass
class TimeSeries:
    """A named time series with timestamps and values."""

    name: str
    timestamps: list[float] = field(default_factory=list)  # epoch seconds
    values: list[float] = field(default_factory=list)

    @property
    def length(self) -> int:
        return len(self.values)

    @property
    def is_valid(self) -> bool:
        return self.length >= 3


@dataclass
class TrendResult:
    """Trend analysis result for a single series."""

    name: str
    slope: float = 0.0
    trend_direction: str = "flat"  # "increasing", "decreasing", "flat"
    trend_strength: float = 0.0  # |slope| normalized
    r_squared: float = 0.0
    mann_kendall_s: float = 0.0
    mann_kendall_p: float = 1.0
    mean: float = 0.0
    std: float = 0.0
    n: int = 0


@dataclass
class GrangerResult:
    """Granger-causality probe result between two series."""

    cause: str
    effect: str
    lag: int = 0
    f_statistic: float = 0.0
    p_value: float = 1.0
    significant: bool = False
    direction: str = "none"  # "positive", "negative", "none"
    note: str = ""


@dataclass
class TemporalAnalysisResult:
    """Full temporal analysis result."""

    enabled: bool = True
    series_count: int = 0
    trends: list[TrendResult] = field(default_factory=list)
    granger_results: list[GrangerResult] = field(default_factory=list)
    formatted_block: str = ""
    total_duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "series_count": self.series_count,
            "trend_count": len(self.trends),
            "granger_count": len(self.granger_results),
            "total_duration_ms": self.total_duration_ms,
            "trends": [
                {
                    "name": t.name,
                    "direction": t.trend_direction,
                    "strength": round(t.trend_strength, 4),
                    "slope": round(t.slope, 6),
                    "r_squared": round(t.r_squared, 4),
                    "n": t.n,
                }
                for t in self.trends
            ],
            "granger": [
                {
                    "cause": g.cause,
                    "effect": g.effect,
                    "lag": g.lag,
                    "f_statistic": round(g.f_statistic, 4),
                    "p_value": round(g.p_value, 4),
                    "significant": g.significant,
                    "direction": g.direction,
                }
                for g in self.granger_results
            ],
        }


def temporal_engine_enabled() -> bool:
    return get_config().temporal_engine_enabled


def _max_lag() -> int:
    return get_config().temporal_engine_max_lag


def _min_points() -> int:
    return get_config().temporal_engine_min_points


# ---------------------------------------------------------------------------
# Statistics helpers (pure Python, no numpy/scipy)
# ---------------------------------------------------------------------------


def _mean(xs: list[float]) -> float:
    if not xs:
        return 0.0
    return sum(xs) / len(xs)


def _std(xs: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def _linear_regression(x: list[float], y: list[float]) -> tuple[float, float]:
    """Simple OLS regression. Returns (slope, r_squared)."""
    n = len(x)
    if n < 2:
        return 0.0, 0.0
    mx = _mean(x)
    my = _mean(y)
    sxx = sum((xi - mx) ** 2 for xi in x)
    sxy = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
    if sxx == 0:
        return 0.0, 0.0
    slope = sxy / sxx
    syy = sum((yi - my) ** 2 for yi in y)
    if syy == 0:
        return slope, 1.0 if sxy != 0 else 0.0
    r_squared = (sxy**2) / (sxx * syy) if sxx * syy != 0 else 0.0
    return slope, r_squared


def _mann_kendall(values: list[float]) -> tuple[float, float]:
    """Mann-Kendall trend test. Returns (S statistic, approximate p-value)."""
    n = len(values)
    if n < 3:
        return 0.0, 1.0

    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            if values[j] > values[i]:
                s += 1
            elif values[j] < values[i]:
                s -= 1

    # Variance of S (accounting for ties)
    var_s = n * (n - 1) * (2 * n + 5) / 18.0

    if var_s == 0:
        return float(s), 1.0

    # Normal approximation for p-value
    if s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0

    # Two-tailed p-value
    p = 2 * (1 - _normal_cdf(abs(z)))
    return float(s), p


def _normal_cdf(z: float) -> float:
    """Approximate normal CDF using error function."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _f_distribution_cdf(f: float, d1: int, d2: int) -> float:
    """Approximate F-distribution CDF via series expansion.

    Uses the regularized incomplete beta function approximation.
    For simplicity, we use a normal approximation when d1, d2 > 4.
    """
    if f <= 0:
        return 0.0
    if d1 <= 0 or d2 <= 0:
        return 0.5

    # Normal approximation for reasonable degrees of freedom
    mean_f = d2 / (d2 - 2) if d2 > 2 else 1.0
    if d2 > 4:
        var_f = (2 * d2**2 * (d1 + d2 - 2)) / (d1 * (d2 - 2) ** 2 * (d2 - 4))
        std_f = math.sqrt(var_f)
        if std_f > 0:
            z = (f - mean_f) / std_f
            return _normal_cdf(z)

    # Fallback: simple ratio-based approximation
    return min(1.0, f / (f + d2 / d1))


# ---------------------------------------------------------------------------
# Time-series extraction from feed caches
# ---------------------------------------------------------------------------


def _extract_series_from_articles(
    articles: list[dict],
    name: str,
) -> TimeSeries:
    """Extract a time series from article/event timestamps."""
    ts = TimeSeries(name=name)
    for article in articles:
        # Try various timestamp fields
        t = (
            article.get("seendate")
            or article.get("date")
            or article.get("timestamp")
            or article.get("created_at")
            or article.get("time")
        )
        if t is None:
            continue
        epoch = _parse_timestamp(t)
        if epoch is not None:
            ts.timestamps.append(epoch)
            ts.values.append(1.0)  # count as 1 event
    return ts


def _parse_timestamp(t: Any) -> float | None:
    """Parse various timestamp formats to epoch seconds."""
    if isinstance(t, (int, float)):
        return float(t)

    if not isinstance(t, str):
        return None

    # Try ISO format
    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        pass

    # Try GDELT format: YYYYMMDDTHHMMSSZ
    if len(t) >= 15 and t.endswith("Z"):
        try:
            dt = datetime.strptime(t[:15], "%Y%m%dT%H%M%S")
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass

    # Try common date formats
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(t, fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue

    return None


def _bucket_series(ts: TimeSeries, bucket_sec: float = 3600.0) -> TimeSeries:
    """Bucket a point-event series into time intervals (count per bucket).

    Returns a new TimeSeries with bucketed counts.
    """
    if not ts.timestamps:
        return TimeSeries(name=ts.name)

    buckets: dict[int, float] = {}
    for t in ts.timestamps:
        b = int(t // bucket_sec)
        buckets[b] = buckets.get(b, 0.0) + 1.0

    sorted_buckets = sorted(buckets.items())
    return TimeSeries(
        name=ts.name,
        timestamps=[float(b) * bucket_sec for b, _ in sorted_buckets],
        values=[v for _, v in sorted_buckets],
    )


def _align_series(
    series_a: TimeSeries,
    series_b: TimeSeries,
) -> tuple[list[float], list[float]]:
    """Align two series to common time indices (nearest-neighbor).

    Returns (values_a, values_b) at aligned time points.
    """
    if not series_a.timestamps or not series_b.timestamps:
        return [], []

    # Use the series with fewer points as the reference
    ref = series_a if series_a.length <= series_b.length else series_b
    other = series_b if ref is series_a else series_a

    aligned_ref: list[float] = []
    aligned_other: list[float] = []

    for i, t in enumerate(ref.timestamps):
        # Find nearest in other
        best_j = 0
        best_dist = abs(other.timestamps[0] - t)
        for j, t2 in enumerate(other.timestamps[1:], 1):
            dist = abs(t2 - t)
            if dist < best_dist:
                best_dist = dist
                best_j = j
        aligned_ref.append(ref.values[i])
        aligned_other.append(other.values[best_j])

    if ref is series_a:
        return aligned_ref, aligned_other
    return aligned_other, aligned_ref


# ---------------------------------------------------------------------------
# Trend detection
# ---------------------------------------------------------------------------


def detect_trend(series: TimeSeries) -> TrendResult:
    """Analyze a single time series for trends."""
    n = series.length
    if n < 2:
        return TrendResult(name=series.name, n=n)

    x = list(range(n))
    y = series.values

    slope, r_sq = _linear_regression(x, y)
    mk_s, mk_p = _mann_kendall(y)
    m = _mean(y)
    s = _std(y)

    # Determine direction
    if mk_p < 0.05 and mk_s > 0:
        direction = "increasing"
    elif mk_p < 0.05 and mk_s < 0:
        direction = "decreasing"
    elif abs(slope) > 0.01 * max(abs(m), 1.0):
        direction = "increasing" if slope > 0 else "decreasing"
    else:
        direction = "flat"

    # Normalize strength
    strength = min(abs(slope) / max(abs(m), 1.0), 1.0) if m != 0 else abs(slope)

    return TrendResult(
        name=series.name,
        slope=slope,
        trend_direction=direction,
        trend_strength=strength,
        r_squared=r_sq,
        mann_kendall_s=mk_s,
        mann_kendall_p=mk_p,
        mean=m,
        std=s,
        n=n,
    )


# ---------------------------------------------------------------------------
# Granger-causality probe
# ---------------------------------------------------------------------------


def granger_probe(
    cause: TimeSeries,
    effect: TimeSeries,
    max_lag: int | None = None,
) -> list[GrangerResult]:
    """Probe Granger-causality between two series at multiple lags.

    Uses a simplified lagged regression approach:
    1. Regress effect on its own past (restricted model)
    2. Regress effect on its own past + cause's past (unrestricted model)
    3. F-test: does adding cause's past significantly improve the fit?

    Returns one GrangerResult per lag tested.
    """
    lag_limit = max_lag or _max_lag()
    results: list[GrangerResult] = []

    # Align series first
    eff_vals, cause_vals = _align_series(effect, cause)
    n = len(eff_vals)

    min_pts = _min_points()
    if n < min_pts + lag_limit:
        return results

    for lag in range(1, lag_limit + 1):
        if n - lag < min_pts:
            break

        # Build lagged variables
        y = eff_vals[lag:]
        # Restricted: y[t] ~ y[t-lag]
        x_restricted = [[eff_vals[t]] for t in range(len(y))]
        # Unrestricted: y[t] ~ y[t-lag] + cause[t-lag]
        x_unrestricted = [[eff_vals[t], cause_vals[t]] for t in range(len(y))]

        # Compute R² for both models
        r2_restricted = _r2_multi(y, x_restricted)
        r2_unrestricted = _r2_multi(y, x_unrestricted)

        # F-test
        p_unrestricted = 2  # parameters in unrestricted
        p_restricted = 1  # parameters in restricted
        n_obs = len(y)

        df1 = p_unrestricted - p_restricted
        df2 = n_obs - p_unrestricted

        if df2 <= 0 or r2_unrestricted < r2_restricted:
            f_stat = 0.0
            p_val = 1.0
        else:
            numerator = (r2_unrestricted - r2_restricted) / df1
            denominator = (1 - r2_unrestricted) / df2
            if denominator == 0:
                f_stat = 0.0
                p_val = 1.0
            else:
                f_stat = numerator / denominator
                # P-value from F-distribution
                p_val = 1.0 - _f_distribution_cdf(f_stat, df1, df2)

        significant = p_val < 0.10  # relaxed threshold for probe
        direction = "none"
        if significant:
            # Determine direction from correlation of cause and effect at this lag
            cause_lagged = cause_vals[: len(y)]
            eff_current = y
            corr = _pearson_corr(cause_lagged, eff_current)
            direction = "positive" if corr > 0 else "negative"

        results.append(
            GrangerResult(
                cause=cause.name,
                effect=effect.name,
                lag=lag,
                f_statistic=f_stat,
                p_value=p_val,
                significant=significant,
                direction=direction,
                note=f"R² restricted={r2_restricted:.3f}, unrestricted={r2_unrestricted:.3f}",
            )
        )

    return results


def _r2_multi(y: list[float], x: list[list[float]]) -> float:
    """Compute R² for multiple regression (OLS, pure Python)."""
    n = len(y)
    if n < 2:
        return 0.0

    k = len(x[0]) if x else 0
    if k == 0 or n <= k:
        return 0.0

    # Build normal equations: (X'X) beta = X'y
    # X'X
    xtx = [[0.0] * (k + 1) for _ in range(k + 1)]
    xty = [0.0] * (k + 1)

    for i in range(n):
        row = [1.0] + x[i]  # intercept + features
        for a in range(k + 1):
            xty[a] += row[a] * y[i]
            for b in range(k + 1):
                xtx[a][b] += row[a] * row[b]

    # Solve via Gaussian elimination
    beta = _gauss_solve(xtx, xty)
    if beta is None:
        return 0.0

    # Compute predicted values
    y_mean = _mean(y)
    ss_tot = sum((yi - y_mean) ** 2 for yi in y)
    if ss_tot == 0:
        return 0.0

    ss_res = 0.0
    for i in range(n):
        pred = beta[0] + sum(beta[j + 1] * x[i][j] for j in range(k))
        ss_res += (y[i] - pred) ** 2

    return max(0.0, 1.0 - ss_res / ss_tot)


def _gauss_solve(matrix: list[list[float]], rhs: list[float]) -> list[float] | None:
    """Solve a linear system via Gaussian elimination with partial pivoting."""
    n = len(rhs)
    # Make augmented matrix
    aug = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]

    for col in range(n):
        # Partial pivot
        max_row = col
        for r in range(col + 1, n):
            if abs(aug[r][col]) > abs(aug[max_row][col]):
                max_row = r
        aug[col], aug[max_row] = aug[max_row], aug[col]

        if abs(aug[col][col]) < 1e-12:
            return None  # singular

        # Eliminate
        for r in range(col + 1, n):
            factor = aug[r][col] / aug[col][col]
            for c in range(col, n + 1):
                aug[r][c] -= factor * aug[col][c]

    # Back-substitute
    solution = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = aug[i][n]
        for j in range(i + 1, n):
            s -= aug[i][j] * solution[j]
        solution[i] = s / aug[i][i]

    return solution


def _pearson_corr(a: list[float], b: list[float]) -> float:
    """Pearson correlation coefficient."""
    n = min(len(a), len(b))
    if n < 2:
        return 0.0
    ma = _mean(a[:n])
    mb = _mean(b[:n])
    sxy = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    sxx = sum((a[i] - ma) ** 2 for i in range(n))
    syy = sum((b[i] - mb) ** 2 for i in range(n))
    if sxx == 0 or syy == 0:
        return 0.0
    return sxy / math.sqrt(sxx * syy)


# ---------------------------------------------------------------------------
# Feed data collection
# ---------------------------------------------------------------------------


def _collect_feed_series() -> list[TimeSeries]:
    """Collect time series from cached feed data."""
    series_list: list[TimeSeries] = []

    try:
        from runtime_cache import cache_get_stale

        # GDELT articles
        gdelt = cache_get_stale("pulse:local:thailand")
        if gdelt and isinstance(gdelt, dict):
            articles = gdelt.get("articles") or []
            if articles:
                ts = _extract_series_from_articles(articles, "gdelt_events")
                bucketed = _bucket_series(ts, bucket_sec=3600.0)  # hourly
                if bucketed.is_valid:
                    series_list.append(bucketed)

        # Earthquakes
        quakes = cache_get_stale("quakes:day:2.5")
        if quakes and isinstance(quakes, dict):
            features = quakes.get("features") or []
            ts = _extract_series_from_features(features, "earthquakes")
            bucketed = _bucket_series(ts, bucket_sec=3600.0)
            if bucketed.is_valid:
                series_list.append(bucketed)

        # EONET natural events
        eonet = cache_get_stale("eonet")
        if eonet and isinstance(eonet, dict):
            events = eonet.get("events") or []
            ts = _extract_series_from_articles(events, "natural_events")
            bucketed = _bucket_series(ts, bucket_sec=3600.0)
            if bucketed.is_valid:
                series_list.append(bucketed)

        # Aircraft count (scalar time series from cache timestamps)
        ac = cache_get_stale("aircraft")
        if ac and isinstance(ac, dict):
            states = ac.get("states") or []
            ts = TimeSeries(
                name="aircraft_count",
                timestamps=[time.time()],
                values=[float(len(states))],
            )
            # Can't build a trend from a single point, but keep for Granger
            if ts.length >= 1:
                series_list.append(ts)

    except Exception:
        pass

    return series_list


def _extract_series_from_features(
    features: list[dict],
    name: str,
) -> TimeSeries:
    """Extract time series from GeoJSON-like features."""
    ts = TimeSeries(name=name)
    for f in features:
        if not isinstance(f, dict):
            continue
        props = f.get("properties") or f
        t = props.get("time") or props.get("timestamp") or props.get("date")
        if t is None:
            continue
        epoch = _parse_timestamp(t)
        if epoch is not None:
            ts.timestamps.append(epoch)
            mag = props.get("mag") or props.get("magnitude") or 1.0
            ts.values.append(float(mag))
    return ts


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def _format_trend(t: TrendResult) -> str:
    """Format a trend result for prompt injection."""
    arrow = {"increasing": "↑", "decreasing": "↓", "flat": "→"}
    return (
        f"  {t.name}: {arrow.get(t.trend_direction, '?')} {t.trend_direction} "
        f"(slope={t.slope:.4f}, R²={t.r_squared:.3f}, MK p={t.mann_kendall_p:.3f}, n={t.n})"
    )


def _format_granger(g: GrangerResult) -> str:
    """Format a Granger result for prompt injection."""
    sig = "***" if g.p_value < 0.05 else ("**" if g.p_value < 0.10 else "")
    return (
        f"  {g.cause} → {g.effect} (lag={g.lag}): "
        f"F={g.f_statistic:.3f}, p={g.p_value:.3f} {sig} "
        f"[{g.direction}]"
    )


def _format_result(result: TemporalAnalysisResult) -> str:
    """Format the full temporal analysis for prompt injection."""
    if not result.trends and not result.granger_results:
        return ""

    parts = ["=== TEMPORAL ANALYSIS ==="]

    if result.trends:
        parts.append("\nTRENDS:")
        for t in result.trends:
            parts.append(_format_trend(t))

    if result.granger_results:
        parts.append("\nGRANGER CAUSALITY PROBES:")
        for g in result.granger_results:
            parts.append(_format_granger(g))

    parts.append(
        f"\nSeries analyzed: {result.series_count} | "
        f"Trends: {len(result.trends)} | "
        f"Granger probes: {len(result.granger_results)}"
    )

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run_temporal_analysis() -> TemporalAnalysisResult:
    """Run temporal analysis on available feed time-series data.

    Collects feed data, extracts time series, runs trend detection and
    Granger-causality probes, then formats the result for prompt injection.
    """
    if not temporal_engine_enabled():
        return TemporalAnalysisResult(enabled=False)

    start = time.monotonic()

    # Collect time series from feeds
    series_list = _collect_feed_series()

    if len(series_list) < 1:
        return TemporalAnalysisResult(
            enabled=True,
            series_count=0,
            total_duration_ms=int((time.monotonic() - start) * 1000),
        )

    # Trend detection for each series
    trends = [detect_trend(s) for s in series_list if s.is_valid]

    # Granger-causality probes between pairs (if we have 2+ valid series)
    granger_results: list[GrangerResult] = []
    valid_series = [s for s in series_list if s.length >= _min_points()]
    if len(valid_series) >= 2:
        for i, cause_s in enumerate(valid_series):
            for j, effect_s in enumerate(valid_series):
                if i == j:
                    continue
                probes = granger_probe(cause_s, effect_s)
                granger_results.extend(probes)

    # Format result
    result = TemporalAnalysisResult(
        enabled=True,
        series_count=len(series_list),
        trends=trends,
        granger_results=granger_results,
        total_duration_ms=int((time.monotonic() - start) * 1000),
    )
    result.formatted_block = _format_result(result)

    return result


def format_temporal_trace_line(result: TemporalAnalysisResult) -> str:
    """Format result as a single line for system prompt injection."""
    if not result.enabled:
        return ""
    return (
        f"TEMPORAL. Series: {result.series_count}, "
        f"Trends: {len(result.trends)}, "
        f"Granger probes: {len(result.granger_results)}"
    )
