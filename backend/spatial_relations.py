"""Spatial Relations — Composition Matrix (P6).

SpaRAGraph-inspired composition rules for combining spatial operations.
Determines how to compose two spatial operations based on their types
and the connector (AND, OR, THEN).

Composition is NOT commutative: downstream THEN within ≠ within AND downstream.
"""

from __future__ import annotations

from typing import Any


# Composition rules: (op1, connector, op2) → strategy
_COMPOSITION_RULES: dict[tuple[str, str, str], str] = {
    # AND = intersection
    ("within", "AND", "within"): "intersect_bbox",
    ("within", "AND", "near"): "intersect_bbox",
    ("near", "AND", "within"): "intersect_bbox",
    ("near", "AND", "near"): "intersect_bbox",
    ("near", "AND", "border"): "intersect_bbox",
    ("border", "AND", "near"): "intersect_bbox",
    ("contains", "AND", "within"): "intersect_bbox",
    ("within", "AND", "contains"): "intersect_bbox",
    # OR = union
    ("within", "OR", "within"): "union_bbox",
    ("near", "OR", "near"): "union_bbox",
    ("near", "OR", "within"): "union_bbox",
    # THEN = sequential (non-commutative)
    ("river_direction", "THEN", "within"): "sequential",
    ("river_direction", "THEN", "near"): "sequential",
    ("within", "THEN", "river_direction"): "sequential",
    ("border", "THEN", "within"): "sequential",
}

# Default composition when no explicit rule exists
_DEFAULT_AND = "intersect_bbox"
_DEFAULT_OR = "union_bbox"
_DEFAULT_THEN = "sequential"


def compose(op1: str, connector: str, op2: str) -> str:
    """Determine the composition strategy for two operations.

    Args:
        op1: First operation type (e.g. "within", "near", "river_direction")
        connector: Composition connector ("AND", "OR", "THEN")
        op2: Second operation type

    Returns:
        Strategy name: "intersect_bbox", "union_bbox", "sequential"
    """
    key = (op1, connector, op2)
    if key in _COMPOSITION_RULES:
        return _COMPOSITION_RULES[key]

    # Fallback by connector
    if connector == "AND":
        return _DEFAULT_AND
    elif connector == "OR":
        return _DEFAULT_OR
    else:
        return _DEFAULT_THEN


def detect_composition(query: str) -> str:
    """Detect the composition connector from a natural language query.

    "and" → AND (intersection)
    "or" → OR (union)
    "then" / "after that" / "subsequently" → THEN (sequential)
    """
    q = query.lower()
    if " then " in q or "after that" in q or "subsequently" in q:
        return "THEN"
    if " or " in q:
        return "OR"
    return "AND"


def composition_matrix() -> dict[str, Any]:
    """Return the full composition matrix for inspection/API."""
    return {
        "rules": [
            {"op1": k[0], "connector": k[1], "op2": k[2], "strategy": v}
            for k, v in sorted(_COMPOSITION_RULES.items())
        ],
        "defaults": {
            "AND": _DEFAULT_AND,
            "OR": _DEFAULT_OR,
            "THEN": _DEFAULT_THEN,
        },
        "note": "Composition is non-commutative for THEN connector.",
    }
