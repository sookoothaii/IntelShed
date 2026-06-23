"""Shared Ollama VRAM / load settings (read from backend/.env after _load_env)."""
import os


def keep_alive() -> str:
    """Ollama keep_alive for interactive /api/chat (operator-tunable warm cache)."""
    return os.getenv("OLLAMA_KEEP_ALIVE", "1m")


def background_keep_alive() -> str:
    """Ollama keep_alive for autopilot paths (RAG embed, briefing, insight narration).

  Default ``0`` so models unload between background batches and the dGPU can
  deep-idle when the HUD globe is the only GPU consumer.
    """
    return os.getenv("OLLAMA_BACKGROUND_KEEP_ALIVE", "0")


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
