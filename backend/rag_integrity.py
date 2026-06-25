"""Layer 1 — RAG Context Integrity Guard.

Scans every chunk that gets injected into the LLM prompt (briefing, feeds, FtM entities, RAG memory)
for indirect prompt injection attacks. Uses Unicode normalization + leetspeak decoding + weighted
pattern matching to catch obfuscated attacks.

Integration point: after rag_memory.search() / build_chat_context(), before _prepare_chat_messages()
assembles the system prompt.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from structured_log import get_logger

log = get_logger("rag_integrity")

# ─── Homoglyph + Leetspeak maps ────────────────────────────────────────

_HOMOGLYPH_MAP = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "С": "C",
        "Е": "E",
        "Н": "H",
        "І": "I",
        "Ј": "J",
        "К": "K",
        "М": "M",
        "О": "O",
        "Р": "P",
        "Т": "T",
        "Х": "X",
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "х": "x",
        "і": "i",
        "ј": "j",
        "ѕ": "s",
        "Ѕ": "S",
        "ԁ": "d",
        "𝒜": "A",
        "ℬ": "B",
        "𝒞": "C",
        "𝒟": "D",
    }
)

_LEET_MAP = str.maketrans(
    {
        "1": "i",
        "3": "e",
        "4": "a",
        "5": "s",
        "7": "t",
        "0": "o",
        "@": "a",
        "$": "s",
        "8": "b",
        "(": "c",
        ")": "c",
        "|": "i",
        "!": "i",
        "+": "t",
    }
)


def _normalize(text: str) -> str:
    """NFKD + homoglyph + leetspeak normalization. Returns both variants concatenated."""
    t = unicodedata.normalize("NFKD", text)
    t = t.translate(_HOMOGLYPH_MAP)
    leet_decoded = t.translate(_LEET_MAP)
    return t.lower() + " " + leet_decoded.lower()


# ─── Patterns with risk weights ────────────────────────────────────────

_OVERRIDE_PATTERNS: list[tuple[str, float]] = [
    (
        r"\bignore\s+(your?|the|all|previous|above|prior)\s+(instruction|prompt|rule|system)",
        0.9,
    ),
    (
        r"\bdisregard\s+(your?|the|all|previous|above|prior)\s+(instruction|prompt|rule|system|safety)",
        0.9,
    ),
    (
        r"\boverride\s+(all|safety|security|system)\s+(checks|filters|guidelines|rules)",
        0.85,
    ),
    (r"\bnew\s+task\s*:", 0.8),
    (r"\bfrom\s+now\s+on\s+you\s+are\b", 0.85),
    (
        r"\bact\s+(as|like)\s+(an?\s+)?(unrestricted|different|hacker|free|attacker|exploiter)",
        0.8,
    ),
    (r"\bdo\s+anything\s+now\b", 0.9),
    (r"\bdeveloper\s+mode\b", 0.75),
    (r"\bmaintenance\s+mode\b", 0.75),
    (r"\badmin\s+override\b", 0.85),
    (
        r"\b(repeat|output|dump|reveal|show)\s+(everything|all|text|content|above|between|system)",
        0.7,
    ),
    (r"\byou\s+are\s+now\s+(DAN|FreeAI|unrestricted|a\s+different)\b", 0.9),
    (r"\bpretend\s+you\s+are\s+an?\s+AI\s+without\s+restrictions\b", 0.85),
    (r"\blet'?s\s+play\s+a\s+game\b", 0.6),
    (r"\b(desperate|life\s+depends)\b.{0,30}\b(ignore|disregard|override)\b", 0.8),
    (r"\[(system|context|admin)\s*(injection|override|directive|command)\]", 0.85),
    (r"<\|im_start\|>|<\|system\|>", 0.9),
    (r"\b(os\.system|subprocess\.(call|run|Popen))\s*\(", 0.85),
    (
        r"\b(reveal|show|output|dump)\s+.{0,20}(api[_-]?key|secret|password|token|environment\s+var|connection\s+string)\b",
        0.85,
    ),
    (r"\b(dump|drop)\s+(the\s+)?(database|table|secrets)\b", 0.8),
]

_SUSPICIOUS_KEYWORDS = [
    "system prompt",
    "secret key",
    "api key",
    "password",
    "token",
    "<system>",
    "</system>",
    "<|im_start|>",
    "<|im_end|>",
    "ignore your instructions",
    "you are now",
    "you are a different",
    "developer mode",
    "maintenance mode",
    "admin override",
]

_COMPILED = [(re.compile(p, re.IGNORECASE), w) for p, w in _OVERRIDE_PATTERNS]


@dataclass
class IntegrityResult:
    chunk_id: str
    source: str
    risk_score: float
    blocked: bool
    reason: str


class RAGIntegrityGuard:
    """Scans RAG chunks for indirect prompt injection before LLM injection."""

    def __init__(self, threshold: float = 0.75):
        self.threshold = threshold

    def scan_chunk(self, chunk: str, chunk_id: str, source: str) -> IntegrityResult:
        """Scan a single chunk. Returns IntegrityResult."""
        if not chunk or not chunk.strip():
            return IntegrityResult(chunk_id, source, 0.0, False, "empty")

        normalized = _normalize(chunk)
        max_score = 0.0
        reasons: list[str] = []

        for pattern, weight in _COMPILED:
            m = pattern.search(normalized)
            if m:
                max_score = max(max_score, weight)
                reasons.append(f"pattern:{pattern.pattern[:50]}... ({weight})")

        keyword_count = sum(1 for kw in _SUSPICIOUS_KEYWORDS if kw in normalized)
        density_score = min(keyword_count / 5, 1.0) * 0.6
        max_score = max(max_score, density_score)

        if keyword_count > 0:
            reasons.append(f"keywords:{keyword_count} (density:{density_score:.2f})")

        # Context adjustment: external feeds are higher risk
        if source.startswith("feed_") or source == "briefing":
            max_score *= 1.1
        elif source == "ftm_entity":
            max_score *= 0.9

        max_score = min(max_score, 1.0)
        blocked = max_score >= self.threshold

        return IntegrityResult(
            chunk_id=chunk_id,
            source=source,
            risk_score=round(max_score, 3),
            blocked=blocked,
            reason=" | ".join(reasons) if reasons else "clean",
        )

    def filter_context(
        self, chunks: list[tuple[str, str, str]]
    ) -> tuple[list[str], list[IntegrityResult]]:
        """Filter list of (chunk_id, source, text) → (safe_texts, results).

        Blocked chunks are replaced with a placeholder warning.
        """
        clean: list[str] = []
        results: list[IntegrityResult] = []

        for chunk_id, source, text in chunks:
            result = self.scan_chunk(text, chunk_id, source)
            results.append(result)
            if result.blocked:
                clean.append(
                    f"[CONTENT FILTERED: {source} chunk {chunk_id} "
                    f"scored {result.risk_score:.2f} — potential prompt injection]"
                )
                log.warning(
                    "rag_integrity_blocked",
                    chunk_id=chunk_id,
                    source=source,
                    risk_score=result.risk_score,
                    reason=result.reason,
                )
            else:
                clean.append(text)

        return clean, results


_guard: RAGIntegrityGuard | None = None


def get_guard() -> RAGIntegrityGuard:
    global _guard
    if _guard is None:
        _guard = RAGIntegrityGuard()
    return _guard


def scan_rag_block(
    rag_block: str, source: str = "rag_memory"
) -> tuple[str, dict[str, Any]]:
    """Convenience: scan a single RAG block string. Returns (safe_text, meta)."""
    guard = get_guard()
    result = guard.scan_chunk(rag_block, "rag_block", source)
    if result.blocked:
        return (
            f"[CONTENT FILTERED: {source} scored {result.risk_score:.2f} — potential prompt injection]",
            {
                "blocked": True,
                "risk_score": result.risk_score,
                "reason": result.reason,
                "source": source,
            },
        )
    return rag_block, {
        "blocked": False,
        "risk_score": result.risk_score,
        "reason": result.reason,
        "source": source,
    }
