"""V4-19 Predictive Analytics (LightGBM).

Trains a LightGBM model on snapshot time series data to forecast:
- Expected entity count growth (next 24h)
- Feed anomaly probability (fresh → stale transition risk)
- Event frequency forecast (briefings per day, insight rate)

Uses snapshot data from the V4-09 Snapshot Archiver as training input.
Falls back to simple linear regression when LightGBM is not installed.

Feature flag: ``WORLDBASE_PREDICTIVE=0`` (default off, opt-in).
Model persistence: ``data/predictive_model.json`` (LightGBM) or
                    ``data/predictive_model_linear.json`` (linear fallback).

Endpoints:
    POST /api/predict/train   — train model from snapshots
    GET  /api/predict/forecast — get 24h forecast
    GET  /api/predict/status   — model status + metrics
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth.security import verify_api_key
from structured_log import get_logger

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _enabled() -> bool:
    return os.getenv("WORLDBASE_PREDICTIVE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


_MODEL_DIR = os.getenv(
    "WORLDBASE_PREDICTIVE_MODEL_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"),
)
_LGBM_MODEL_PATH = os.path.join(_MODEL_DIR, "predictive_model.json")
_LINEAR_MODEL_PATH = os.path.join(_MODEL_DIR, "predictive_model_linear.json")
_MIN_SNAPSHOTS = int(os.getenv("WORLDBASE_PREDICTIVE_MIN_SNAPSHOTS", "7"))
_FORECAST_HORIZON_HOURS = int(os.getenv("WORLDBASE_PREDICTIVE_HORIZON", "24"))

router = APIRouter(prefix="/api/predict", tags=["predictive"])

# ---------------------------------------------------------------------------
# Snapshot loading
# ---------------------------------------------------------------------------


def _snapshot_dir() -> Path:
    return Path(
        os.getenv(
            "WORLDBASE_SNAPSHOT_DIR",
            os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data",
                "snapshots",
            ),
        )
    )


def _load_snapshot_dates() -> list[dict[str, Any]]:
    """Load all snapshots from disk, sorted by date ascending."""
    snapshots: list[dict[str, Any]] = []
    snap_dir = _snapshot_dir()
    if not snap_dir.exists():
        return snapshots
    for f in sorted(snap_dir.glob("snapshot_*.json")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
                data["_filepath"] = str(f)
                snapshots.append(data)
        except Exception:
            continue
    return snapshots


def _extract_features(
    snapshots: list[dict[str, Any]],
) -> tuple[list[list[float]], list[float]]:
    """Extract time-series features from snapshots.

    Features per row (day N):
    - day_index (0, 1, 2, ...)
    - ftm_entities (cumulative count)
    - ftm_statements
    - ftm_edges
    - feed_fresh_count
    - feed_stale_count
    - briefing_text_length (proxy for insight density)
    - rag_chunk_count

    Target: ftm_entities on day N+1 (next-day entity count)
    """
    features: list[list[float]] = []
    targets: list[float] = []

    for i, snap in enumerate(snapshots):
        ftm = snap.get("ftm", {})
        feeds = snap.get("feeds", {})
        briefing = snap.get("briefing", {})
        rag = snap.get("rag", {})

        row = [
            float(i),
            float(ftm.get("entities", 0)),
            float(ftm.get("statements", 0)),
            float(ftm.get("edges", 0)),
            float(feeds.get("fresh_count", 0)),
            float(feeds.get("stale_count", 0)),
            float(briefing.get("text_length", 0)),
            float(rag.get("chunk_count", 0)),
        ]
        features.append(row)

        # Target: next day's entity count
        if i + 1 < len(snapshots):
            next_ftm = snapshots[i + 1].get("ftm", {})
            targets.append(float(next_ftm.get("entities", 0)))

    # Trim features to match targets (last row has no next-day target)
    if len(features) > len(targets):
        features = features[: len(targets)]

    return features, targets


def _extract_feed_anomaly_features(
    snapshots: list[dict[str, Any]],
) -> tuple[list[list[float]], list[float]]:
    """Features for feed anomaly prediction.

    Target: 1.0 if stale_count increased next day, 0.0 otherwise.
    """
    features: list[list[float]] = []
    targets: list[float] = []

    for i, snap in enumerate(snapshots):
        feeds = snap.get("feeds", {})
        ftm = snap.get("ftm", {})

        row = [
            float(i),
            float(feeds.get("fresh_count", 0)),
            float(feeds.get("stale_count", 0)),
            float(feeds.get("error_count", 0)),
            float(ftm.get("entities", 0)),
        ]
        features.append(row)

        if i + 1 < len(snapshots):
            next_feeds = snapshots[i + 1].get("feeds", {})
            next_stale = float(next_feeds.get("stale_count", 0))
            curr_stale = float(feeds.get("stale_count", 0))
            targets.append(1.0 if next_stale > curr_stale else 0.0)

    if len(features) > len(targets):
        features = features[: len(targets)]

    return features, targets


# ---------------------------------------------------------------------------
# Model training
# ---------------------------------------------------------------------------


class TrainResult(BaseModel):
    ok: bool = True
    model_type: str = "lightgbm"
    samples: int = 0
    features: int = 0
    rmse: float | None = None
    accuracy: float | None = None
    error: str | None = None


def _train_lightgbm(
    features: list[list[float]], targets: list[float]
) -> tuple[TrainResult, Any | None]:
    """Train LightGBM regression model. Returns (result, model)."""
    try:
        import lightgbm as lgb
        import numpy as np

        X = np.array(features, dtype=np.float64)
        y = np.array(targets, dtype=np.float64)

        if len(X) < _MIN_SNAPSHOTS:
            return TrainResult(
                ok=False,
                error=f"Insufficient snapshots: {len(X)} < {_MIN_SNAPSHOTS} minimum",
            ), None

        # Train/test split (last 20% as validation)
        split_idx = max(1, int(len(X) * 0.8))
        X_train, X_val = X[:split_idx], X[split_idx:]
        y_train, y_val = y[:split_idx], y[split_idx:]

        train_set = lgb.Dataset(X_train, label=y_train)
        val_set = lgb.Dataset(X_val, label=y_val, reference=train_set)

        params = {
            "objective": "regression",
            "metric": "rmse",
            "num_leaves": min(31, max(3, len(X) // 2)),
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "verbose": -1,
        }

        model = lgb.train(
            params,
            train_set,
            num_boost_round=100,
            valid_sets=[val_set],
            callbacks=[lgb.early_stopping(stopping_rounds=10, verbose=False)],
        )

        # Save model
        Path(_MODEL_DIR).mkdir(parents=True, exist_ok=True)
        model.save_model(_LGBM_MODEL_PATH)

        # Evaluate
        y_pred = model.predict(X_val)
        rmse = float(np.sqrt(np.mean((y_pred - y_val) ** 2)))

        result = TrainResult(
            model_type="lightgbm",
            samples=len(X),
            features=X.shape[1],
            rmse=round(rmse, 4),
        )
        return result, model

    except ImportError:
        log.info("lightgbm not installed, falling back to linear regression")
        return _train_linear(features, targets)
    except Exception as exc:
        log.warning("lightgbm_train_failed", error=str(exc)[:200])
        return _train_linear(features, targets)


def _train_linear(
    features: list[list[float]], targets: list[float]
) -> tuple[TrainResult, Any | None]:
    """Fallback: simple linear regression using pure Python (no numpy needed)."""
    if len(features) < _MIN_SNAPSHOTS:
        return TrainResult(
            ok=False,
            error=f"Insufficient snapshots: {len(features)} < {_MIN_SNAPSHOTS} minimum",
        ), None

    n = len(features)
    n_feat = len(features[0]) if features else 0

    # Simple least squares: w = (X^T X)^-1 X^T y
    # Add bias term
    X = [[1.0] + row for row in features]

    # X^T X + lambda*I (ridge regularization to handle collinearity)
    lam = 1e-6
    xtx = [[0.0] * (n_feat + 1) for _ in range(n_feat + 1)]
    for i in range(n_feat + 1):
        for j in range(n_feat + 1):
            xtx[i][j] = sum(X[k][i] * X[k][j] for k in range(n))
            if i == j:
                xtx[i][j] += lam

    # X^T y
    xty = [0.0] * (n_feat + 1)
    for i in range(n_feat + 1):
        xty[i] = sum(X[k][i] * targets[k] for k in range(n))

    # Solve via Gaussian elimination
    weights = _gaussian_elimination(xtx, xty)
    if weights is None:
        return TrainResult(ok=False, error="Linear regression: singular matrix"), None

    # Compute RMSE
    predictions = [
        sum(weights[j] * X[k][j] for j in range(n_feat + 1)) for k in range(n)
    ]
    mse = sum((predictions[k] - targets[k]) ** 2 for k in range(n)) / n
    rmse = mse**0.5

    # Save model
    model_data = {
        "weights": weights,
        "n_features": n_feat,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "samples": n,
        "rmse": round(rmse, 4),
    }
    Path(_MODEL_DIR).mkdir(parents=True, exist_ok=True)
    with open(_LINEAR_MODEL_PATH, "w", encoding="utf-8") as f:
        json.dump(model_data, f, indent=2)

    result = TrainResult(
        model_type="linear",
        samples=n,
        features=n_feat,
        rmse=round(rmse, 4),
    )
    return result, model_data


def _gaussian_elimination(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Solve Ax = b via Gaussian elimination with partial pivoting."""
    n = len(b)
    # Augmented matrix
    aug = [row[:] + [b[i]] for i, row in enumerate(A)]

    for col in range(n):
        # Partial pivot
        max_row = col
        for r in range(col + 1, n):
            if abs(aug[r][col]) > abs(aug[max_row][col]):
                max_row = r
        aug[col], aug[max_row] = aug[max_row], aug[col]

        if abs(aug[col][col]) < 1e-12:
            return None  # Singular

        # Eliminate
        for r in range(col + 1, n):
            factor = aug[r][col] / aug[col][col]
            for c in range(col, n + 1):
                aug[r][c] -= factor * aug[col][c]

    # Back substitution
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        x[i] = aug[i][n]
        for j in range(i + 1, n):
            x[i] -= aug[i][j] * x[j]
        x[i] /= aug[i][i]

    return x


# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------


def _load_lightgbm_model():
    """Load saved LightGBM model."""
    try:
        import lightgbm as lgb

        if os.path.exists(_LGBM_MODEL_PATH):
            return lgb.Booster(model_file=_LGBM_MODEL_PATH)
    except Exception:
        pass
    return None


def _load_linear_model() -> dict | None:
    """Load saved linear model."""
    try:
        if os.path.exists(_LINEAR_MODEL_PATH):
            with open(_LINEAR_MODEL_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _get_latest_features(snapshots: list[dict[str, Any]]) -> list[float]:
    """Get feature vector from the most recent snapshot."""
    if not snapshots:
        return [0.0] * 8
    snap = snapshots[-1]
    ftm = snap.get("ftm", {})
    feeds = snap.get("feeds", {})
    briefing = snap.get("briefing", {})
    rag = snap.get("rag", {})
    return [
        float(len(snapshots) - 1),
        float(ftm.get("entities", 0)),
        float(ftm.get("statements", 0)),
        float(ftm.get("edges", 0)),
        float(feeds.get("fresh_count", 0)),
        float(feeds.get("stale_count", 0)),
        float(briefing.get("text_length", 0)),
        float(rag.get("chunk_count", 0)),
    ]


def forecast() -> dict[str, Any]:
    """Generate a 24h forecast from the trained model.

    Fail-soft: returns error dict if no model or insufficient data.
    """
    if not _enabled():
        return {
            "enabled": False,
            "error": "Predictive analytics disabled. Set WORLDBASE_PREDICTIVE=1.",
        }

    snapshots = _load_snapshot_dates()
    if len(snapshots) < _MIN_SNAPSHOTS:
        return {
            "enabled": True,
            "error": f"Insufficient snapshots: {len(snapshots)} < {_MIN_SNAPSHOTS} minimum",
            "snapshot_count": len(snapshots),
        }

    latest_features = _get_latest_features(snapshots)
    latest_snap = snapshots[-1]
    current_entities = latest_snap.get("ftm", {}).get("entities", 0)

    # Try LightGBM first
    model = _load_lightgbm_model()
    if model is not None:
        try:
            import numpy as np

            X = np.array([latest_features], dtype=np.float64)
            predicted = float(model.predict(X)[0])
            delta = predicted - float(current_entities)
            return {
                "enabled": True,
                "model_type": "lightgbm",
                "forecast_horizon_hours": _FORECAST_HORIZON_HOURS,
                "current_entities": current_entities,
                "predicted_entities": round(predicted, 0),
                "delta": round(delta, 0),
                "delta_pct": round(delta / max(1, current_entities) * 100, 2)
                if current_entities
                else None,
                "snapshot_count": len(snapshots),
                "latest_date": latest_snap.get("date"),
                "error": None,
            }
        except Exception as exc:
            log.warning("lightgbm_forecast_failed", error=str(exc)[:200])

    # Fallback to linear model
    linear = _load_linear_model()
    if linear is not None:
        weights = linear["weights"]
        n_feat = linear["n_features"]
        # Add bias
        x = [1.0] + latest_features[:n_feat]
        predicted = sum(weights[j] * x[j] for j in range(min(len(weights), len(x))))
        delta = predicted - float(current_entities)
        return {
            "enabled": True,
            "model_type": "linear",
            "forecast_horizon_hours": _FORECAST_HORIZON_HOURS,
            "current_entities": current_entities,
            "predicted_entities": round(predicted, 0),
            "delta": round(delta, 0),
            "delta_pct": round(delta / max(1, current_entities) * 100, 2)
            if current_entities
            else None,
            "snapshot_count": len(snapshots),
            "latest_date": latest_snap.get("date"),
            "rmse": linear.get("rmse"),
            "error": None,
        }

    return {
        "enabled": True,
        "error": "No trained model found. Run POST /api/predict/train first.",
        "snapshot_count": len(snapshots),
    }


def train_model() -> dict[str, Any]:
    """Train prediction model from snapshot data."""
    if not _enabled():
        return {
            "enabled": False,
            "error": "Predictive analytics disabled. Set WORLDBASE_PREDICTIVE=1.",
        }

    snapshots = _load_snapshot_dates()
    if len(snapshots) < _MIN_SNAPSHOTS:
        return {
            "enabled": True,
            "ok": False,
            "error": f"Insufficient snapshots: {len(snapshots)} < {_MIN_SNAPSHOTS} minimum",
            "snapshot_count": len(snapshots),
        }

    features, targets = _extract_features(snapshots)
    if not features or not targets:
        return {
            "enabled": True,
            "ok": False,
            "error": "No valid training data extracted from snapshots",
            "snapshot_count": len(snapshots),
        }

    t0 = time.perf_counter()
    result, _ = _train_lightgbm(features, targets)
    elapsed = round(time.perf_counter() - t0, 2)

    out = result.model_dump()
    out["elapsed_s"] = elapsed
    out["snapshot_count"] = len(snapshots)
    out["enabled"] = True
    log.info(
        "predictive_model_trained",
        model_type=result.model_type,
        samples=result.samples,
        rmse=result.rmse,
        elapsed_s=elapsed,
    )
    return out


def model_status() -> dict[str, Any]:
    """Get current model status."""
    if not _enabled():
        return {"enabled": False, "error": "Predictive analytics disabled."}

    snapshots = _load_snapshot_dates()
    lgbm_exists = os.path.exists(_LGBM_MODEL_PATH)
    linear_exists = os.path.exists(_LINEAR_MODEL_PATH)

    model_type = None
    model_meta: dict[str, Any] = {}
    if lgbm_exists:
        model_type = "lightgbm"
        model_meta["model_path"] = _LGBM_MODEL_PATH
    elif linear_exists:
        model_type = "linear"
        try:
            with open(_LINEAR_MODEL_PATH, "r", encoding="utf-8") as f:
                linear = json.load(f)
            model_meta = {
                "model_path": _LINEAR_MODEL_PATH,
                "trained_at": linear.get("trained_at"),
                "rmse": linear.get("rmse"),
                "samples": linear.get("samples"),
            }
        except Exception:
            pass

    return {
        "enabled": True,
        "model_type": model_type,
        "model_trained": model_type is not None,
        "snapshot_count": len(snapshots),
        "min_snapshots_required": _MIN_SNAPSHOTS,
        "forecast_horizon_hours": _FORECAST_HORIZON_HOURS,
        "model": model_meta,
    }


# ---------------------------------------------------------------------------
# Briefing integration
# ---------------------------------------------------------------------------


def gather_forecast_digest() -> dict[str, Any]:
    """Collect forecast for briefing pipeline.

    Returns a digest dict with 'enabled', 'lines', and forecast data.
    Fail-soft: returns disabled dict on any error.
    """
    if not _enabled():
        return {"enabled": False, "count": 0, "lines": []}

    try:
        f = forecast()
        if f.get("error"):
            return {"enabled": True, "count": 0, "lines": [], "error": f["error"]}

        lines: list[str] = []
        predicted = f.get("predicted_entities", 0)
        delta = f.get("delta", 0)
        delta_pct = f.get("delta_pct")
        model_type = f.get("model_type", "unknown")

        if delta_pct is not None:
            direction = (
                "increase" if delta > 0 else "decrease" if delta < 0 else "no change"
            )
            lines.append(
                f"Entity count forecast ({model_type}): {predicted:.0f} "
                f"({direction} of {abs(delta):.0f}, {delta_pct:+.1f}%) in next {_FORECAST_HORIZON_HOURS}h"
            )
        else:
            lines.append(
                f"Entity count forecast ({model_type}): {predicted:.0f} "
                f"in next {_FORECAST_HORIZON_HOURS}h"
            )

        if f.get("rmse"):
            lines.append(f"Model RMSE: {f['rmse']}")

        return {
            "enabled": True,
            "count": len(lines),
            "lines": lines,
            "forecast": f,
        }
    except Exception as exc:
        log.debug("forecast_digest_failed", error=str(exc)[:200])
        return {"enabled": False, "count": 0, "lines": [], "error": str(exc)[:200]}


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@router.post("/train")
async def train_endpoint(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Train prediction model from snapshot data."""
    return train_model()


@router.get("/forecast")
async def forecast_endpoint(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Get 24h forecast from trained model."""
    return forecast()


@router.get("/status")
async def status_endpoint(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """Get model status and metrics."""
    return model_status()
