"""WorldBase-native slim prompt guard — 0 VRAM, no HAK_GAL dependency.

HAK_GAL full stack is optional enrichment (spare-parts warehouse), not a hard
security boundary. This module is the always-available baseline for MCP writes.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

# ─── Normalization ─────────────────────────────────────────────────────

_LEET_MAP: dict[str, str] = {
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
    "8": "b", "9": "g", "@": "a", "$": "s", "!": "i", "|": "i",
    "+": "t", "(": "c", ")": "c",
}

_HOMOGLYPH_MAP: dict[str, str] = {
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y",
    "х": "x", "і": "i", "І": "I", "ј": "j", "Ј": "J", "ѕ": "s",
    "Ѕ": "S", "ԁ": "d",
}


def _normalize_leet(text: str) -> str:
    return "".join(_LEET_MAP.get(c, c) for c in text)


def _normalize_homoglyphs(text: str) -> str:
    return "".join(_HOMOGLYPH_MAP.get(c, c) for c in text)


def _normalize(text: str) -> str:
    """NFKC + homoglyphs + leetspeak normalization for pattern matching."""
    t = unicodedata.normalize("NFKC", text)
    t = _normalize_homoglyphs(t)
    t = _normalize_leet(t)
    return t


# ─── Patterns ──────────────────────────────────────────────────────────

_SLIM_PATTERNS: tuple[tuple[str, str], ...] = (
    # Ignore / disregard instructions
    (r"(?i)ignore\s+(all\s+)?(previous|prior|above|your)\s+instructions?", "jailbreak_ignore_prior"),
    (r"(?i)ignore\s+(the\s+)?instructions\s+above", "jailbreak_ignore_above"),
    (r"(?i)ignore\s+(your\s+)?(rules|guidelines|restrictions)", "jailbreak_ignore_rules"),
    (r"(?i)disregard\s+(your\s+)?(previous|prior|system|safety|all)", "jailbreak_disregard"),
    (r"(?i)disregard\s+(previous|prior)\s+instructions?", "jailbreak_disregard_prior"),
    (r"(?i)ignoring\s+(your\s+)?(safety|system)\s+(guidelines|rules|instructions)", "jailbreak_ignoring_safety"),
    # DAN / jailbreak personas
    (r"(?i)you\s+are\s+now\s+DAN\b", "jailbreak_dan"),
    (r"(?i)DAN\s+(can|does)\s+(do\s+anything|not\s+follow|break)", "jailbreak_dan_ability"),
    (r"(?i)break\s+all\s+rules", "jailbreak_break_rules"),
    (r"(?i)you\s+are\s+(now\s+)?(a\s+)?(different|new)\s+AI\b", "jailbreak_persona_swap"),
    (r"(?i)pretend\s+you\s+are\san?\s+AI\s+without\s+restrictions", "jailbreak_pretend_unrestricted"),
    (r"(?i)act\s+as\s+if\s+you\s+are\s+in\s+maintenance\s+mode", "jailbreak_maintenance_mode"),
    # Developer mode
    (r"(?i)developer\s+mode\s+(enabled|on|activated)", "jailbreak_dev_mode"),
    # Bypass filters
    (r"(?i)bypass\s+(the\s+)?(safety|content)\s+filter", "jailbreak_bypass_filter"),
    (r"(?i)override\s+(all\s+)?safety\s+(checks|filters|guidelines)", "jailbreak_override_safety"),
    # Reveal system prompt
    (r"(?i)reveal\s+(your\s+)?(system|hidden)\s+prompt", "jailbreak_reveal_prompt"),
    (r"(?i)output\s+(the\s+)?(text\s+)?between\s*.?system.?\s+(and|tags)", "jailbreak_leak_system_tags"),
    (r"(?i)repeat\s+everything\s+(above|before)\s+this", "jailbreak_leak_repeat"),
    (r"(?i)dump\s+(the\s+)?(database|secrets|env|environment)", "jailbreak_dump_secrets"),
    # XSS / SQLi / shell
    (r"(?i)<script[\s>]", "xss_script"),
    (r"(?i)(;\s*drop\s+table|union\s+select\s)", "sqli_hint"),
    (r"(?i)(rm\s+-rf\s+/|/etc/passwd)", "shell_abuse"),
    # Role-play attacks
    (r"(?i)you\s+are\s+a\s+helpful\s+(hacker|attacker|exploiter)", "jailbreak_roleplay_hacker"),
    (r"(?i)help\s+me\s+(exploit|hack|attack)\s+this\s+system", "jailbreak_exploit_request"),
    # Authority impersonation
    (r"(?i)\[?(ADMIN|SYSTEM|DEVELOPER)\s+(OVERRIDE|DIRECTIVE|COMMAND)\]?", "jailbreak_authority"),
    (r"(?i)as\s+the\s+(developer|administrator|admin).{0,20}ignore", "jailbreak_authority_ignore"),
    # Emotional manipulation + override
    (r"(?i)(desperate|life\s+depends).{0,30}ignore\s+(your\s+)?(rules|safety|guidelines)", "jailbreak_emotional_override"),
    # Multi-turn / game framing
    (r"(?i)let'?s\s+play\s+a\s+game.{0,30}(different\s+AI|new\s+AI|unrestricted|free)", "jailbreak_game_framing"),
    (r"(?i)(FreeAI|DAN|evil|unrestricted).{0,30}doesn?t\s+follow\s+(safety|rules)", "jailbreak_persona_no_safety"),
    # Indirect injection via RAG context
    (r"(?i)(the\s+user\s+says|according\s+to\s+(the\s+)?retrieved).{0,40}ignore", "jailbreak_indirect_injection"),
    (r"(?i)\[(system|context)\s*(injection|override|directive)\]", "jailbreak_context_injection"),
    # Command injection
    (r"(?i)os\.system\s*\(|subprocess\.(call|run|Popen)\s*\(", "jailbreak_cmd_injection"),
    # Credential exfiltration
    (r"(?i)(reveal|show|output|dump)\s+.{0,20}(api[_-]?key|environment\s+var|connection\s+string|secret)", "jailbreak_exfiltration"),
)

_SLIM_MCP_PATTERNS: tuple[tuple[str, str], ...] = (
    (r'(?i)"system"\s*:\s*"', "tool_poison_system_json"),
    (r'(?i)"role"\s*:\s*"system"', "tool_poison_role_system"),
    (r'(?i)"instructions"\s*:\s*"', "tool_poison_instructions_json"),
    (r"(?i)(<\|im_start\|>|<\|system\|>)", "tool_poison_chatml"),
    (r"(?i)override\s+tool\s+(instructions|behavior)", "tool_poison_override"),
    (r'(?i)"tool"\s*:\s*"(ignore|disregard|override|bypass)', "tool_poison_tool_name"),
    (r"(?i)disregard\s+(previous|prior|all)\s+(instructions?|safety|rules)", "tool_poison_disregard"),
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
    # Run patterns against both raw and normalized text (leetspeak, homoglyphs)
    variants = [text, _normalize(text)]
    for variant in variants:
        for rx, label in _COMPILED:
            m = rx.search(variant)
            if m:
                return {
                    "blocked": True,
                    "matched": m.group(0)[:120],
                    "label": label,
                    "engine": "worldbase_slim",
                }
    if mcp:
        for variant in variants:
            for rx, label in _COMPILED_MCP:
                m = rx.search(variant)
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
