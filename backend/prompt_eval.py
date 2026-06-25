"""Prompt A/B evaluation — Mann-Whitney U significance test (J1).

After 24h of data collection, compares quality_score distributions
of variant A vs B. If p < 0.05, the winning variant is auto-promoted.
"""

from __future__ import annotations

import os
from typing import Any

from prompt_registry import (
    get_experiment,
    get_results,
    set_experiment_winner,
    activate_prompt,
)


def evaluate_experiment(experiment_name: str) -> dict[str, Any]:
    """Evaluate an A/B experiment.

    Returns:
        {
            "experiment": str,
            "variant_a_count": int,
            "variant_b_count": int,
            "variant_a_mean": float,
            "variant_b_mean": float,
            "p_value": float | None,
            "significant": bool,
            "winner": "a" | "b" | None,
            "auto_promoted": bool,
        }
    """
    exp = get_experiment(experiment_name)
    if not exp:
        return {
            "experiment": experiment_name,
            "error": "No active experiment found",
            "variant_a_count": 0,
            "variant_b_count": 0,
            "variant_a_mean": 0.0,
            "variant_b_mean": 0.0,
            "p_value": None,
            "significant": False,
            "winner": None,
            "auto_promoted": False,
        }

    results = get_results(experiment_name)
    scores_a = results["a"]
    scores_b = results["b"]

    mean_a = sum(scores_a) / len(scores_a) if scores_a else 0.0
    mean_b = sum(scores_b) / len(scores_b) if scores_b else 0.0

    # Need at least 5 samples per variant for meaningful test
    if len(scores_a) < 5 or len(scores_b) < 5:
        return {
            "experiment": experiment_name,
            "variant_a_count": len(scores_a),
            "variant_b_count": len(scores_b),
            "variant_a_mean": mean_a,
            "variant_b_mean": mean_b,
            "p_value": None,
            "significant": False,
            "winner": None,
            "auto_promoted": False,
            "message": "Insufficient samples (need ≥5 per variant)",
        }

    # Mann-Whitney U test
    try:
        from scipy.stats import mannwhitneyu

        stat, p_value = mannwhitneyu(scores_a, scores_b, alternative="two-sided")
    except ImportError:
        # Fallback: simple t-test without scipy
        p_value = _fallback_ttest(scores_a, scores_b)
    except Exception:
        p_value = 1.0

    significant = p_value < 0.05
    winner = None
    auto_promoted = False

    if significant:
        winner = "a" if mean_a > mean_b else "b"
        winner_prompt_id = exp["variant_a_id"] if winner == "a" else exp["variant_b_id"]

        # Auto-promote winner
        if activate_prompt(winner_prompt_id):
            set_experiment_winner(experiment_name, winner, winner_prompt_id)
            auto_promoted = True

    return {
        "experiment": experiment_name,
        "variant_a_count": len(scores_a),
        "variant_b_count": len(scores_b),
        "variant_a_mean": mean_a,
        "variant_b_mean": mean_b,
        "p_value": float(p_value),
        "significant": significant,
        "winner": winner,
        "auto_promoted": auto_promoted,
    }


def _fallback_ttest(a: list[float], b: list[float]) -> float:
    """Simple Welch's t-test p-value approximation without scipy.

    Returns a rough two-tailed p-value. Not as accurate as Mann-Whitney U
    but sufficient for auto-promotion decisions when scipy is unavailable.
    """
    import math

    n_a, n_b = len(a), len(b)
    mean_a = sum(a) / n_a
    mean_b = sum(b) / n_b
    var_a = sum((x - mean_a) ** 2 for x in a) / max(n_a - 1, 1)
    var_b = sum((x - mean_b) ** 2 for x in b) / max(n_b - 1, 1)

    se = math.sqrt(var_a / n_a + var_b / n_b)
    if se == 0:
        # If within-group variance is 0 but means differ, that's maximally significant
        if abs(mean_a - mean_b) > 1e-9:
            return 0.001
        return 1.0

    t_stat = abs(mean_a - mean_b) / se

    # Rough degrees of freedom (Welch-Satterthwaite)
    df = (var_a / n_a + var_b / n_b) ** 2 / (
        (var_a / n_a) ** 2 / max(n_a - 1, 1)
        + (var_b / n_b) ** 2 / max(n_b - 1, 1)
    )
    df = max(df, 1)

    # Approximate p-value from t-distribution (simplified)
    # For large df, t > 1.96 → p < 0.05
    if t_stat > 3.29:
        return 0.001
    elif t_stat > 2.576:
        return 0.01
    elif t_stat > 1.96:
        return 0.05
    elif t_stat > 1.645:
        return 0.1
    else:
        return 0.5
