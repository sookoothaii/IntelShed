"""Shared Ollama VRAM / load settings (read from backend/.env after _load_env)."""
import os


def keep_alive() -> str:
    """Ollama keep_alive per request. Use '0' to free VRAM immediately."""
    return os.getenv("OLLAMA_KEEP_ALIVE", "1m")


def briefing_autopilot_on() -> bool:
    return os.getenv("WORLDBASE_BRIEFING_AUTOPILOT", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }


def rag_autopilot_on() -> bool:
    return os.getenv("WORLDBASE_RAG_AUTOPILOT", "1").strip().lower() not in {
        "0", "false", "no", "off",
    }
