"""Whisper voice control bridge — faster-whisper CUDA/CPU + hotkey handler.

Provides hands-free speech-to-text for the WorldBase operator workstation.
Uses faster-whisper for inference (CUDA if available, CPU fallback) and a
configurable push-to-talk hotkey listener.

Env:
  WORLDBASE_WHISPER_BRIDGE=1   (default off — opt-in, GPU/CPU load)
  WORLDBASE_WHISPER_MODEL=small   (tiny/base/small/medium/large-v3)
  WORLDBASE_WHISPER_DEVICE=auto   (auto/cuda/cpu)
  WORLDBASE_WHISPER_COMPUTE=int8  (int8/float16/float32)
  WORLDBASE_WHISPER_HOTKEY=ctrl+space  (push-to-talk hotkey)
  WORLDBASE_WHISPER_LANGUAGE=en   (language code or None for auto-detect)
  WORLDBASE_WHISPER_SAMPLE_RATE=16000

Endpoints:
  GET  /api/whisper/status
  POST /api/whisper/transcribe   (upload audio file)
  POST /api/whisper/start-listener  (start hotkey push-to-talk)
  POST /api/whisper/stop-listener
  GET  /api/whisper/transcripts  (recent transcripts)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import wave
import tempfile
from collections import deque
from typing import Any

from fastapi import APIRouter, File, UploadFile
from pydantic import BaseModel

from config import get_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whisper", tags=["whisper-voice"])

# --- Config helpers ---

_MODEL_NAME = os.getenv("WORLDBASE_WHISPER_MODEL", "small")
_DEVICE_PREF = os.getenv("WORLDBASE_WHISPER_DEVICE", "auto")
_COMPUTE_PREF = os.getenv("WORLDBASE_WHISPER_COMPUTE", "int8")
_HOTKEY = os.getenv("WORLDBASE_WHISPER_HOTKEY", "ctrl+space")
_LANGUAGE = os.getenv("WORLDBASE_WHISPER_LANGUAGE", "en")
_SAMPLE_RATE = int(os.getenv("WORLDBASE_WHISPER_SAMPLE_RATE", "16000"))

# Lazy-loaded model singleton
_model: Any = None
_model_lock = asyncio.Lock()

# Listener state
_listener_active = False
_listener_task: asyncio.Task | None = None
_transcripts: deque[dict[str, Any]] = deque(maxlen=50)

# Audio recording state (push-to-talk)
_recording = False
_audio_frames: list[bytes] = []


def _enabled() -> bool:
    return get_config().whisper_bridge_enabled


def _resolve_device() -> str:
    """Resolve device: auto → cuda if available, else cpu."""
    if _DEVICE_PREF != "auto":
        return _DEVICE_PREF
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


def _resolve_compute_type(device: str) -> str:
    """Pick a sensible compute type for the device."""
    if _COMPUTE_PREF != "int8":
        return _COMPUTE_PREF
    return "float16" if device == "cuda" else "int8"


async def get_model():
    """Lazy-load the faster-whisper model (thread-safe)."""
    global _model
    if _model is not None:
        return _model
    async with _model_lock:
        if _model is not None:
            return _model
        try:
            from faster_whisper import WhisperModel

            device = _resolve_device()
            compute = _resolve_compute_type(device)
            logger.info(
                "whisper_model_loading model=%s device=%s compute=%s",
                _MODEL_NAME,
                device,
                compute,
            )
            _model = WhisperModel(
                _MODEL_NAME,
                device=device,
                compute_type=compute,
            )
            logger.info("whisper_model_loaded model=%s", _MODEL_NAME)
        except ImportError:
            logger.warning("whisper_import_error — faster-whisper not installed")
            raise RuntimeError(
                "faster-whisper not installed. Run: pip install faster-whisper"
            )
        except Exception as exc:
            logger.warning("whisper_model_load_error: %s", exc)
            raise
    return _model


def transcribe_audio_file(
    audio_path: str,
    language: str | None = None,
) -> dict[str, Any]:
    """Transcribe an audio file synchronously (for thread executor)."""
    model = asyncio.run(get_model())
    lang = language or (_LANGUAGE if _LANGUAGE != "auto" else None)
    segments, info = model.transcribe(
        audio_path,
        language=lang,
        beam_size=5,
        vad_filter=True,
    )
    text_parts: list[str] = []
    segments_meta: list[dict[str, Any]] = []
    for seg in segments:
        text_parts.append(seg.text.strip())
        segments_meta.append(
            {
                "start": round(seg.start, 2),
                "end": round(seg.end, 2),
                "text": seg.text.strip(),
                "confidence": round(float(getattr(seg, "avg_logprob", 0)), 4),
            }
        )
    full_text = " ".join(text_parts).strip()
    return {
        "text": full_text,
        "language": info.language if hasattr(info, "language") else lang,
        "language_probability": (
            round(float(info.language_probability), 4)
            if hasattr(info, "language_probability")
            else None
        ),
        "duration": (
            round(float(info.duration), 2) if hasattr(info, "duration") else None
        ),
        "segments": segments_meta,
    }


def _save_upload_to_wav(upload_bytes: bytes, suffix: str = ".wav") -> str:
    """Save uploaded audio bytes to a temp WAV file."""
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp.write(upload_bytes)
    tmp.close()
    return tmp.name


def _save_raw_pcm_to_wav(
    pcm_frames: list[bytes], sample_rate: int, channels: int = 1, sampwidth: int = 2
) -> str:
    """Convert raw PCM frames to a WAV file."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    with wave.open(tmp.name, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        for frame in pcm_frames:
            wf.writeframes(frame)
    return tmp.name


def _store_transcript(text: str, source: str = "upload") -> None:
    """Store a transcript in the recent deque."""
    _transcripts.append(
        {
            "text": text,
            "source": source,
            "timestamp": time.time(),
            "iso": _now_iso(),
        }
    )


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Hotkey listener (push-to-talk)
# ---------------------------------------------------------------------------


class HotkeyConfig(BaseModel):
    hotkey: str = _HOTKEY
    language: str | None = _LANGUAGE


async def _run_listener(hotkey: str) -> None:
    """Background task: listen for hotkey, record audio, transcribe.

    Uses keyboard library for hotkey detection and sounddevice for audio.
    Both are optional dependencies — the listener fails soft if missing.
    """
    global _recording, _audio_frames, _listener_active

    try:
        import keyboard
        import sounddevice as sd
    except ImportError:
        logger.warning(
            "whisper_listener_deps_missing — pip install keyboard sounddevice"
        )
        return

    loop = asyncio.get_event_loop()

    def on_press():
        global _recording
        if not _recording:
            _recording = True
            _audio_frames.clear()
            logger.info("whisper_ptt_start")

    def on_release():
        global _recording
        if _recording:
            _recording = False
            logger.info("whisper_ptt_stop frames=%d", len(_audio_frames))
            if _audio_frames:
                frames = list(_audio_frames)
                _audio_frames.clear()
                # Transcribe in a thread to avoid blocking the event loop
                asyncio.run_coroutine_threadsafe(_transcribe_ptt(frames), loop)

    async def _transcribe_ptt(frames: list[bytes]):
        try:
            wav_path = _save_raw_pcm_to_wav(frames, _SAMPLE_RATE)
            result = await asyncio.to_thread(transcribe_audio_file, wav_path)
            text = result.get("text", "")
            if text:
                _store_transcript(text, source="ptt")
                logger.info("whisper_ptt_transcribed text=%s", text[:100])
            try:
                os.unlink(wav_path)
            except OSError:
                pass
        except Exception as exc:
            logger.warning("whisper_ptt_transcribe_error: %s", exc)

    # Record callback
    def audio_callback(indata, _frames, _time, status):
        if _recording:
            _audio_frames.append(bytes(indata))

    # Start audio stream
    try:
        with sd.RawInputStream(
            samplerate=_SAMPLE_RATE,
            dtype="int16",
            channels=1,
            blocksize=1024,
            callback=audio_callback,
        ):
            # Register hotkey (press=start, release=stop)
            keyboard.add_hotkey(hotkey, on_press, suppress=False)
            keyboard.add_hotkey(
                hotkey, on_release, suppress=False, trigger_on_release=True
            )
            logger.info("whisper_listener_active hotkey=%s", hotkey)
            while _listener_active:
                await asyncio.sleep(0.5)
    except Exception as exc:
        logger.warning("whisper_listener_error: %s", exc)
    finally:
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        _listener_active = False
        logger.info("whisper_listener_stopped")


# ---------------------------------------------------------------------------
# FastAPI routes
# ---------------------------------------------------------------------------


@router.get("/status")
async def whisper_status():
    device = _resolve_device()
    return {
        "enabled": _enabled(),
        "model": _MODEL_NAME,
        "device": device,
        "compute_type": _resolve_compute_type(device),
        "hotkey": _HOTKEY,
        "language": _LANGUAGE,
        "sample_rate": _SAMPLE_RATE,
        "listener_active": _listener_active,
        "transcript_count": len(_transcripts),
    }


@router.post("/transcribe")
async def whisper_transcribe(
    file: UploadFile = File(...),
    language: str | None = None,
):
    """Transcribe an uploaded audio file."""
    if not _enabled():
        return {"enabled": False, "error": "Whisper bridge disabled"}
    audio_bytes = await file.read()
    if not audio_bytes:
        return {"error": "Empty audio file"}
    wav_path = _save_upload_to_wav(audio_bytes, suffix=".wav")
    try:
        result = await asyncio.to_thread(transcribe_audio_file, wav_path, language)
        text = result.get("text", "")
        if text:
            _store_transcript(text, source="upload")
        return result
    except Exception as exc:
        return {"error": str(exc)[:500]}
    finally:
        try:
            os.unlink(wav_path)
        except OSError:
            pass


@router.post("/start-listener")
async def whisper_start_listener():
    """Start the push-to-talk hotkey listener."""
    global _listener_active, _listener_task
    if not _enabled():
        return {"enabled": False, "error": "Whisper bridge disabled"}
    if _listener_active:
        return {"active": True, "message": "Listener already running"}
    _listener_active = True
    _listener_task = asyncio.create_task(_run_listener(_HOTKEY))
    return {"active": True, "hotkey": _HOTKEY}


@router.post("/stop-listener")
async def whisper_stop_listener():
    """Stop the push-to-talk listener."""
    global _listener_active, _listener_task
    _listener_active = False
    if _listener_task and not _listener_task.done():
        _listener_task.cancel()
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass
    _listener_task = None
    return {"active": False}


@router.get("/transcripts")
async def whisper_transcripts(limit: int = 20):
    """Return recent transcripts."""
    items = list(_transcripts)[-limit:]
    items.reverse()
    return {"transcripts": items, "count": len(items)}


# ---------------------------------------------------------------------------
# KB export for Pi offline RAG sync
# ---------------------------------------------------------------------------


async def export_kb_for_pi(
    limit: int = 500,
    since: str | None = None,
) -> dict[str, Any]:
    """Export condensed RAG chunks for Pi offline sync.

    Returns chunks with text + metadata (no embeddings — Pi generates
    its own via a lightweight model or uses keyword search).
    """
    try:
        import rag_memory

        with rag_memory._conn() as conn:
            if since:
                rows = conn.execute(
                    """
                    SELECT id, source, source_id, text, meta_json, created_at
                    FROM rag_chunks
                    WHERE created_at > ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (since, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT id, source, source_id, text, meta_json, created_at
                    FROM rag_chunks
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()

        chunks = []
        for row in rows:
            meta = {}
            if row["meta_json"]:
                try:
                    meta = json.loads(row["meta_json"])
                except (json.JSONDecodeError, TypeError):
                    pass
            chunks.append(
                {
                    "id": row["id"],
                    "source": row["source"],
                    "source_id": row["source_id"],
                    "text": row["text"],
                    "meta": meta,
                    "created_at": row["created_at"],
                }
            )
        return {
            "chunks": chunks,
            "count": len(chunks),
            "exported_at": _now_iso(),
            "latest_id": chunks[0]["id"] if chunks else 0,
        }
    except Exception as exc:
        logger.warning("whisper_kb_export_error: %s", exc)
        return {"chunks": [], "count": 0, "error": str(exc)[:200]}


@router.get("/kb/export")
async def whisper_kb_export(
    limit: int = 500,
    since: str | None = None,
):
    """Export condensed KB chunks for Pi offline RAG sync."""
    return await export_kb_for_pi(limit=limit, since=since)
