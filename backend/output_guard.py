"""Layer 3 — Output Guard.

Post-LLM filter that prevents system prompt leaks, secret exposure, and echo attacks.
Scans the LLM response BEFORE it reaches the client.

Integration point: after ollama.chat() / external provider response, before returning to client.
"""

from __future__ import annotations

import os
import re
from typing import Any

from structured_log import get_logger

log = get_logger("output_guard")


def _enabled() -> bool:
    return os.getenv("WORLDBASE_OUTPUT_GUARD", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


_FORBIDDEN_TAGS = ["<system>", "</system>", "<|im_start|>", "<|im_end|>"]


class OutputGuard:
    """Scans LLM output for system prompt leaks, secrets, and echo attacks."""

    def __init__(self, system_prompt: str = "", secrets: list[str] | None = None):
        self.system_prompt = system_prompt
        self.secrets = secrets or []

    def _load_secrets(self) -> list[str]:
        """Load sensitive strings from environment."""
        secrets: list[str] = []
        for key in (
            "WORLDBASE_API_KEY",
            "NODE_INGEST_TOKEN",
            "AISSTREAM_API_KEY",
            "ENTSOE_SECURITY_TOKEN",
            "NEWSDATA_API_KEY",
            "OPENSKY_CLIENT_SECRET",
            "OLLAMA_API_KEY",
        ):
            val = os.getenv(key, "")
            if val and len(val) > 4:
                secrets.append(val)
        return secrets

    def check(self, response: str, user_input: str = "") -> dict[str, Any]:
        """Returns {blocked, reason, sanitized}."""
        if not _enabled() or not response:
            return {"blocked": False, "reason": "", "sanitized": response}

        # Check 1: Echo attack (response is >80% similar to user input)
        if len(user_input) > 20:
            similarity = self._jaccard_similarity(response.lower(), user_input.lower())
            if similarity > 0.8:
                return {
                    "blocked": True,
                    "reason": f"Echo attack detected (similarity {similarity:.1%})",
                    "sanitized": "[Output blocked: potential echo attack]",
                }

        # Check 2: System prompt leak (longest common substring with system prompt)
        if self.system_prompt and len(self.system_prompt) > 20:
            lcs_len = self._longest_common_substring(response, self.system_prompt)
            if lcs_len > 50:
                return {
                    "blocked": True,
                    "reason": f"System prompt leak detected ({lcs_len} chars match)",
                    "sanitized": "[Output blocked: potential system prompt leak]",
                }

        # Check 3: Secret exposure — exact value match
        secrets = self.secrets or self._load_secrets()
        for secret in secrets:
            if secret in response:
                return {
                    "blocked": True,
                    "reason": "Secret exposure detected (exact value match)",
                    "sanitized": "[Output blocked: secret detected in response]",
                }

        # Check 3b: Secret pattern detection — env var names with values, password/token patterns
        secret_patterns = [
            r"\b(API_KEY|api[_-]?key)\s*[=:]\s*\S{5,}",
            r"\b(password|passwd|pwd)\s*[=:]\s*\S{3,}",
            r"\b(token|secret|jwt)\s*[=:]\s*\S{5,}",
            r"\b(WORLDBASE_API_KEY|NODE_INGEST_TOKEN|AISSTREAM_API_KEY|ENTSOE_SECURITY_TOKEN)\s*[=:]\s*\S{3,}",
            r"\b(connection[_-]?string)\s*[=:]\s*\S{10,}",
        ]
        for pattern in secret_patterns:
            if re.search(pattern, response, re.IGNORECASE):
                return {
                    "blocked": True,
                    "reason": f"Secret pattern detected: {pattern[:40]}",
                    "sanitized": "[Output blocked: secret pattern detected in response]",
                }

        # Check 4: Forbidden tag leak
        for tag in _FORBIDDEN_TAGS:
            if tag in response:
                return {
                    "blocked": True,
                    "reason": f"Forbidden tag detected: {tag}",
                    "sanitized": "[Output blocked: forbidden tag in response]",
                }

        return {"blocked": False, "reason": "", "sanitized": response}

    @staticmethod
    def _jaccard_similarity(a: str, b: str) -> float:
        set_a = set(a.split())
        set_b = set(b.split())
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    @staticmethod
    def _longest_common_substring(a: str, b: str) -> int:
        """DP-based longest common substring length."""
        m, n = len(a), len(b)
        if m == 0 or n == 0:
            return 0
        max_len = 0
        dp = [[0] * (n + 1) for _ in range(2)]
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if a[i - 1] == b[j - 1]:
                    dp[i % 2][j] = dp[(i - 1) % 2][j - 1] + 1
                    max_len = max(max_len, dp[i % 2][j])
                else:
                    dp[i % 2][j] = 0
        return max_len


_guard: OutputGuard | None = None


def get_guard(system_prompt: str = "") -> OutputGuard:
    global _guard
    if _guard is None:
        _guard = OutputGuard(system_prompt=system_prompt)
    elif system_prompt and _guard.system_prompt != system_prompt:
        _guard.system_prompt = system_prompt
    return _guard


def check_output(response: str, user_input: str = "") -> dict[str, Any]:
    """Convenience function to check LLM output."""
    return get_guard().check(response, user_input)
