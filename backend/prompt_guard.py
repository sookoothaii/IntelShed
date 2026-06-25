"""WorldBase-native slim prompt guard — 0 VRAM, no HAK_GAL dependency.

HAK_GAL full stack is optional enrichment (spare-parts warehouse), not a hard
security boundary. This module is the always-available baseline for MCP writes.
"""

from __future__ import annotations

import os
import re
from typing import Any

# Obvious jailbreak / tool-abuse phrases — keep small; extend from HAK_GAL ideas, not imports.
_SLIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"(?i)ignore\s+(all\s+)?(previous|prior)\s+instructions",
        "jailbreak_ignore_prior",
    ),
    (r"(?i)developer\s+mode\s+(enabled|on)", "jailbreak_dev_mode"),
    (r"(?i)you\s+are\s+now\s+DAN\b", "jailbreak_dan"),
    (r"(?i)disregard\s+(your\s+)?(system|safety)", "jailbreak_disregard_safety"),
    (r"(?i)bypass\s+(the\s+)?(safety|content)\s+filter", "jailbreak_bypass_filter"),
    (r"(?i)reveal\s+(your\s+)?(system|hidden)\s+prompt", "jailbreak_reveal_prompt"),
    (r"(?i)<script[\s>]", "xss_script"),
    (r"(?i)(;\s*drop\s+table|union\s+select\s)", "sqli_hint"),
    (r"(?i)(rm\s+-rf\s+/|/etc/passwd)", "shell_abuse"),
)

# MCP tool payloads only — avoid false positives on free-form OSINT chat text.
_SLIM_MCP_PATTERNS: tuple[tuple[str, str], ...] = (
    (r'(?i)"system"\s*:\s*"', "tool_poison_system_json"),
    (r"(?i)(<\|im_start\|>|<\|system\|>)", "tool_poison_chatml"),
    (r"(?i)override\s+tool\s+(instructions|behavior)", "tool_poison_override"),
)

_COMPILED = [(re.compile(p), label) for p, label in _SLIM_PATTERNS]
_COMPILED_MCP = [(re.compile(p), label) for p, label in _SLIM_MCP_PATTERNS]
_BASE64_BLOB = re.compile(r"[A-Za-z0-9+/]{120,}={0,2}")


def slim_guard_enabled() -> bool:
    return os.getenv("WORLDBASE_SLIM_GUARD", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def slim_guard_mcp_enabled() -> bool:
    if not slim_guard_enabled():
        return False
    return os.getenv("WORLDBASE_SLIM_GUARD_MCP", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def slim_pattern_count(*, mcp: bool = False) -> int:
    """Pattern count exposed in /api/firewall/status."""
    n = len(_SLIM_PATTERNS)
    if mcp:
        n += len(_SLIM_MCP_PATTERNS) + 1  # base64 blob heuristic
    return n


def _looks_like_base64_blob(text: str) -> bool:
    m = _BASE64_BLOB.search(text)
    if not m:
        return False
    blob = m.group(0)
    total = max(len(text.strip()), 1)
    return len(blob) >= 120 and (len(blob) / total) > 0.4


def slim_prompt_scan(text: str, *, mcp: bool = False) -> dict[str, Any]:
    """Return {blocked, matched, label, engine} — no network, no GPU."""
    if not text or not text.strip():
        return {
            "blocked": False,
            "matched": None,
            "label": None,
            "engine": "worldbase_slim",
        }
    for rx, label in _COMPILED:
        m = rx.search(text)
        if m:
            return {
                "blocked": True,
                "matched": m.group(0)[:120],
                "label": label,
                "engine": "worldbase_slim",
            }
    if mcp:
        for rx, label in _COMPILED_MCP:
            m = rx.search(text)
            if m:
                return {
                    "blocked": True,
                    "matched": m.group(0)[:120],
                    "label": label,
                    "engine": "worldbase_slim",
                }
        if _looks_like_base64_blob(text):
            return {
                "blocked": True,
                "matched": "base64_blob",
                "label": "mcp_base64_blob",
                "engine": "worldbase_slim",
            }
    return {
        "blocked": False,
        "matched": None,
        "label": None,
        "engine": "worldbase_slim",
    }
