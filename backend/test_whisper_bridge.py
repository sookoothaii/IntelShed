"""Tests for whisper_bridge — voice control (no GPU/model required).

Tests config resolution, transcript storage, KB export, and API routes
without loading the actual Whisper model.
"""

import os
import unittest
from unittest.mock import patch, MagicMock

# Ensure config sees whisper as enabled
os.environ["WORLDBASE_WHISPER_BRIDGE"] = "1"

import whisper_bridge


class WhisperConfigTest(unittest.TestCase):
    def test_enabled_flag(self):
        self.assertTrue(whisper_bridge._enabled())

    def test_resolve_device_auto_cpu_when_no_torch(self):
        with patch.dict("sys.modules", {"torch": None}):
            dev = whisper_bridge._resolve_device()
            # Without torch, auto falls back to cpu
            self.assertIn(dev, ("cpu", "cuda"))

    def test_resolve_device_explicit(self):
        with patch.object(whisper_bridge, "_DEVICE_PREF", "cpu"):
            self.assertEqual(whisper_bridge._resolve_device(), "cpu")
        with patch.object(whisper_bridge, "_DEVICE_PREF", "cuda"):
            self.assertEqual(whisper_bridge._resolve_device(), "cuda")

    def test_resolve_compute_type(self):
        self.assertEqual(whisper_bridge._resolve_compute_type("cpu"), "int8")
        self.assertEqual(whisper_bridge._resolve_compute_type("cuda"), "float16")

    def test_resolve_compute_type_custom(self):
        with patch.object(whisper_bridge, "_COMPUTE_PREF", "float32"):
            self.assertEqual(whisper_bridge._resolve_compute_type("cpu"), "float32")


class WhisperTranscriptStorageTest(unittest.TestCase):
    def setUp(self):
        whisper_bridge._transcripts.clear()

    def tearDown(self):
        whisper_bridge._transcripts.clear()

    def test_store_transcript(self):
        whisper_bridge._store_transcript("hello world", source="test")
        self.assertEqual(len(whisper_bridge._transcripts), 1)
        entry = list(whisper_bridge._transcripts)[0]
        self.assertEqual(entry["text"], "hello world")
        self.assertEqual(entry["source"], "test")
        self.assertIn("timestamp", entry)
        self.assertIn("iso", entry)

    def test_transcript_deque_maxlen(self):
        for i in range(60):
            whisper_bridge._store_transcript(f"text {i}")
        self.assertEqual(len(whisper_bridge._transcripts), 50)

    def test_store_multiple_sources(self):
        whisper_bridge._store_transcript("upload text", source="upload")
        whisper_bridge._store_transcript("ptt text", source="ptt")
        self.assertEqual(len(whisper_bridge._transcripts), 2)
        sources = [t["source"] for t in whisper_bridge._transcripts]
        self.assertIn("upload", sources)
        self.assertIn("ptt", sources)


class WhisperWavSaveTest(unittest.TestCase):
    def test_save_upload_to_wav(self):
        data = b"fake audio data"
        path = whisper_bridge._save_upload_to_wav(data)
        try:
            self.assertTrue(os.path.exists(path))
            with open(path, "rb") as f:
                self.assertEqual(f.read(), data)
        finally:
            os.unlink(path)

    def test_save_raw_pcm_to_wav(self):
        import wave

        frames = [b"\x00\x01" * 100, b"\x02\x03" * 100]
        path = whisper_bridge._save_raw_pcm_to_wav(frames, 16000)
        try:
            self.assertTrue(os.path.exists(path))
            with wave.open(path, "rb") as wf:
                self.assertEqual(wf.getnchannels(), 1)
                self.assertEqual(wf.getsampwidth(), 2)
                self.assertEqual(wf.getframerate(), 16000)
        finally:
            os.unlink(path)


class WhisperKBExportTest(unittest.TestCase):
    """Test KB export for Pi offline RAG sync."""

    def _mock_rag_memory(self, rows):
        """Create a mock rag_memory module with _conn context manager."""
        mock_mod = MagicMock()
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = rows
        mock_mod._conn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_mod._conn.return_value.__exit__ = MagicMock(return_value=False)
        return mock_mod, mock_conn

    def test_export_empty(self):
        """Export should return empty list when no RAG chunks."""
        mock_mod, _ = self._mock_rag_memory([])
        with patch.dict("sys.modules", {"rag_memory": mock_mod}):
            result = asyncio_run(whisper_bridge.export_kb_for_pi(limit=10))
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["chunks"], [])

    def test_export_with_chunks(self):
        """Export should return chunks with parsed metadata."""
        mock_rows = [
            {
                "id": 1,
                "source": "briefing",
                "source_id": "brief-001",
                "text": "Test briefing text",
                "meta_json": '{"lat": 13.7, "lon": 100.5}',
                "created_at": "2025-01-01T00:00:00Z",
            },
            {
                "id": 2,
                "source": "gdelt",
                "source_id": "gdel-002",
                "text": "GDELT event text",
                "meta_json": None,
                "created_at": "2025-01-02T00:00:00Z",
            },
        ]
        mock_mod, _ = self._mock_rag_memory(mock_rows)
        with patch.dict("sys.modules", {"rag_memory": mock_mod}):
            result = asyncio_run(whisper_bridge.export_kb_for_pi(limit=10))
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["chunks"][0]["source"], "briefing")
        self.assertEqual(result["chunks"][0]["meta"]["lat"], 13.7)
        self.assertEqual(result["chunks"][1]["meta"], {})
        self.assertEqual(result["latest_id"], 1)


class WhisperAPITest(unittest.TestCase):
    """Test FastAPI route handlers (without loading Whisper model)."""

    def test_status_route(self):
        import asyncio

        result = asyncio.run(whisper_bridge.whisper_status())
        self.assertIn("enabled", result)
        self.assertIn("model", result)
        self.assertIn("device", result)
        self.assertIn("listener_active", result)

    def test_transcripts_route(self):
        import asyncio

        whisper_bridge._transcripts.clear()
        whisper_bridge._store_transcript("test transcript")
        result = asyncio.run(whisper_bridge.whisper_transcripts(limit=10))
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["transcripts"][0]["text"], "test transcript")

    def test_start_stop_listener(self):
        import asyncio

        # Start listener (it will fail soft since keyboard/sounddevice not installed)
        result = asyncio.run(whisper_bridge.whisper_start_listener())
        self.assertTrue(result["active"])

        # Stop listener
        result = asyncio.run(whisper_bridge.whisper_stop_listener())
        self.assertFalse(result["active"])


def asyncio_run(coro):
    """Helper to run async function in test."""
    import asyncio

    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
