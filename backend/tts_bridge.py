"""Piper TTS bridge — CPU-based text-to-speech for briefing narration.

Uses Piper TTS (piper-tts or piper-phonemize) for on-device CPU inference.
Falls back to a simple WAV generator if Piper is not installed.

Env:
  WORLDBASE_TTS_BRIDGE=1   (default off — opt-in)
  WORLDBASE_TTS_MODEL=en_US-lessac-medium  (Piper voice model name)
  WORLDBASE_TTS_MODEL_PATH=  (directory containing .onnx + .onnx.json)
  WORLDBASE_TTS_SAMPLE_RATE=22050
  WORLDBASE_TTS_LENGTH_SCALE=1.0  (speed: <1.0 faster, >1.0 slower)
  WORLDBASE_TTS_NOISE_SCALE=0.667
  WORLDBASE_TTS_NOISE_W=0.8

Endpoints:
  GET  /api/tts/status
  POST /api/tts/speak    (text → audio/wav response)
  POST /api/tts/narrate  (narrate latest briefing)
  GET  /api/tts/voices   (available voice models)
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import struct
import wave
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["tts"])

# --- Config ---

_MODEL_NAME = os.getenv("WORLDBASE_TTS_MODEL", "en_US-lessac-medium")
_MODEL_PATH = os.getenv("WORLDBASE_TTS_MODEL_PATH", "")
_SAMPLE_RATE = int(os.getenv("WORLDBASE_TTS_SAMPLE_RATE", "22050"))
_LENGTH_SCALE = float(os.getenv("WORLDBASE_TTS_LENGTH_SCALE", "1.0"))
_NOISE_SCALE = float(os.getenv("WORLDBASE_TTS_NOISE_SCALE", "0.667"))
_NOISE_W = float(os.getenv("WORLDBASE_TTS_NOISE_W", "0.8"))

# Lazy-loaded Piper voice singleton
_piper_voice: Any = None
_piper_lock = asyncio.Lock()


def _enabled() -> bool:
    return get_config().tts_bridge_enabled


async def get_voice():
    """Lazy-load the Piper TTS voice (thread-safe)."""
    global _piper_voice
    if _piper_voice is not None:
        return _piper_voice
    async with _piper_lock:
        if _piper_voice is not None:
            return _piper_voice
        try:
            from piper import PiperVoice

            model_dir = _MODEL_PATH or os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "models",
                "tts",
            )
            onnx_path = os.path.join(model_dir, f"{_MODEL_NAME}.onnx")
            config_path = os.path.join(model_dir, f"{_MODEL_NAME}.onnx.json")

            if not os.path.exists(onnx_path):
                # Try direct path
                onnx_path = _MODEL_NAME if _MODEL_NAME.endswith(".onnx") else onnx_path
                config_path = onnx_path + ".json"

            logger.info("tts_voice_loading model=%s onnx=%s", _MODEL_NAME, onnx_path)
            _piper_voice = PiperVoice.load(onnx_path, config_path=config_path)
            logger.info("tts_voice_loaded model=%s", _MODEL_NAME)
        except ImportError:
            logger.warning("tts_import_error — piper-tts not installed")
            raise RuntimeError("piper-tts not installed. Run: pip install piper-tts")
        except Exception as exc:
            logger.warning("tts_voice_load_error: %s", exc)
            raise
    return _piper_voice


def _synthesize_to_wav(text: str) -> bytes:
    """Synthesize text to WAV bytes using Piper (synchronous)."""
    voice = asyncio.run(get_voice())

    # Collect audio chunks
    audio_chunks: list[bytes] = []
    sample_rate = _SAMPLE_RATE

    try:
        for chunk in voice.synthesize(
            text,
            length_scale=_LENGTH_SCALE,
            noise_scale=_NOISE_SCALE,
            noise_w=_NOISE_W,
        ):
            if hasattr(chunk, "audio_int16_bytes"):
                audio_chunks.append(chunk.audio_int16_bytes)
            elif hasattr(chunk, "audio_bytes"):
                audio_chunks.append(chunk.audio_bytes)
            elif isinstance(chunk, (bytes, bytearray)):
                audio_chunks.append(bytes(chunk))
            # Try to get sample rate from chunk
            if hasattr(chunk, "sample_rate"):
                sample_rate = chunk.sample_rate
    except Exception as exc:
        logger.warning("tts_synthesize_error: %s", exc)
        raise

    if not audio_chunks:
        raise RuntimeError("TTS produced no audio output")

    # Concatenate raw audio and wrap in WAV
    raw_audio = b"".join(audio_chunks)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(raw_audio)
    return buf.getvalue()


def _fallback_wav(text: str) -> bytes:
    """Generate a simple beep-tone WAV as fallback when Piper is unavailable.

    This produces a short tone so the caller gets a valid audio response
    even without Piper installed.
    """
    import math

    duration = min(len(text) * 0.05, 10.0)  # ~50ms per char, max 10s
    num_samples = int(_SAMPLE_RATE * duration)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)

        for i in range(num_samples):
            # Simple sine wave at 440Hz with fade
            t = i / _SAMPLE_RATE
            fade = 1.0 - (i / num_samples) * 0.3
            sample = int(8000 * fade * math.sin(2 * math.pi * 440 * t))
            wf.writeframes(struct.pack("<h", sample))
    return buf.getvalue()


class SpeakRequest(BaseModel):
    text: str
    fallback: bool = True


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


@router.get("/status")
async def tts_status():
    return {
        "enabled": _enabled(),
        "model": _MODEL_NAME,
        "model_path": _MODEL_PATH or "(default)",
        "sample_rate": _SAMPLE_RATE,
        "length_scale": _LENGTH_SCALE,
        "voice_loaded": _piper_voice is not None,
    }


@router.post("/speak")
async def tts_speak(req: SpeakRequest):
    """Synthesize text to speech and return as audio/wav."""
    if not _enabled():
        return {"enabled": False, "error": "TTS bridge disabled"}
    if not req.text.strip():
        return {"error": "Empty text"}

    try:
        wav_bytes = await asyncio.to_thread(_synthesize_to_wav, req.text)
        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": "inline; filename=tts.wav"},
        )
    except Exception as exc:
        if req.fallback:
            logger.info("tts_fallback_used error=%s", str(exc)[:100])
            wav_bytes = _fallback_wav(req.text)
            return Response(
                content=wav_bytes,
                media_type="audio/wav",
                headers={
                    "Content-Disposition": "inline; filename=tts_fallback.wav",
                    "X-TTS-Fallback": "true",
                },
            )
        return {"error": str(exc)[:500]}


@router.post("/narrate")
async def tts_narrate(fallback: bool = True):
    """Narrate the latest briefing via TTS."""
    if not _enabled():
        return {"enabled": False, "error": "TTS bridge disabled"}

    try:
        import node_briefing

        brief = await node_briefing.latest_briefing()
        text = brief.get("text") or brief.get("summary") or ""
        if not text:
            return {"error": "No briefing available to narrate"}

        # Limit text length for TTS (avoid very long synthesis)
        max_chars = 2000
        if len(text) > max_chars:
            text = text[:max_chars] + "..."

        wav_bytes = await asyncio.to_thread(_synthesize_to_wav, text)
        return Response(
            content=wav_bytes,
            media_type="audio/wav",
            headers={"Content-Disposition": "inline; filename=briefing_tts.wav"},
        )
    except Exception as exc:
        if fallback:
            wav_bytes = _fallback_wav("Briefing narration fallback.")
            return Response(
                content=wav_bytes,
                media_type="audio/wav",
                headers={"X-TTS-Fallback": "true"},
            )
        return {"error": str(exc)[:500]}


@router.get("/voices")
async def tts_voices():
    """List available Piper voice models in the model directory."""
    model_dir = _MODEL_PATH or os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "models",
        "tts",
    )
    voices: list[dict[str, str]] = []
    if os.path.isdir(model_dir):
        for fname in sorted(os.listdir(model_dir)):
            if fname.endswith(".onnx"):
                name = fname.replace(".onnx", "")
                config_file = fname + ".json"
                voices.append(
                    {
                        "name": name,
                        "onnx": fname,
                        "config": config_file,
                        "config_exists": os.path.exists(
                            os.path.join(model_dir, config_file)
                        ),
                    }
                )
    return {"voices": voices, "model_dir": model_dir, "count": len(voices)}
