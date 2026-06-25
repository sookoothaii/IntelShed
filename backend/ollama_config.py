"""Shared Ollama VRAM / load settings (read from backend/.env after _load_env)."""
import logging
import os

logger = logging.getLogger(__name__)


def keep_alive() -> str:
    """Ollama keep_alive per request. Use '0' to free VRAM immediately."""
    return os.getenv("OLLAMA_KEEP_ALIVE", "1m")


def chat_timeout() -> float:
    """httpx timeout for Ollama chat/tool rounds (local LLM can be slow)."""
    return float(os.getenv("OLLAMA_CHAT_TIMEOUT", "600"))


def briefing_autopilot_on() -> bool:
    return os.getenv("WORLDBASE_BRIEFING_AUTOPILOT", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def rag_autopilot_on() -> bool:
    return os.getenv("WORLDBASE_RAG_AUTOPILOT", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def context_length() -> int | None:
    """Ollama num_ctx override. Returns None if not set (Ollama default 2048 applies)."""
    raw = os.getenv("OLLAMA_CONTEXT_LENGTH", "").strip()
    if not raw:
        return None
    try:
        val = int(raw)
        if val > 0:
            return val
    except ValueError:
        pass
    return None


def context_length_for(model: str) -> int | None:
    """Per-model context length. Logs a warning if prompt may exceed."""
    ctx = context_length()
    if ctx is None:
        return None
    logger.info("Ollama num_ctx=%d for model=%s", ctx, model)
    return ctx
