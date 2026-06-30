"""Tests for tts_bridge — Piper TTS (no model required).

Tests config resolution, fallback WAV generation, and API routes
without loading the actual Piper TTS model.
"""

import os
import unittest
import wave
import io

# Ensure config sees TTS as enabled
os.environ["WORLDBASE_TTS_BRIDGE"] = "1"

import tts_bridge


class TTSConfigTest(unittest.TestCase):
    def test_enabled_flag(self):
        self.assertTrue(tts_bridge._enabled())

    def test_default_model(self):
        self.assertEqual(tts_bridge._MODEL_NAME, "en_US-lessac-medium")

    def test_sample_rate(self):
        self.assertEqual(tts_bridge._SAMPLE_RATE, 22050)

    def test_length_scale(self):
        self.assertIsInstance(tts_bridge._LENGTH_SCALE, float)


class TTSFallbackWavTest(unittest.TestCase):
    def test_fallback_wav_valid(self):
        """Fallback WAV should be a valid WAV file."""
        wav_bytes = tts_bridge._fallback_wav("test text")
        self.assertIsInstance(wav_bytes, bytes)
        self.assertGreater(len(wav_bytes), 44)  # WAV header is 44 bytes

        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getsampwidth(), 2)
            self.assertEqual(wf.getframerate(), tts_bridge._SAMPLE_RATE)
            frames = wf.getnframes()
            self.assertGreater(frames, 0)

    def test_fallback_wav_duration_scales_with_text(self):
        """Longer text should produce longer audio."""
        short = tts_bridge._fallback_wav("hi")
        long_text = tts_bridge._fallback_wav("a" * 200)
        self.assertLess(len(short), len(long_text))

    def test_fallback_wav_max_duration(self):
        """Very long text should be capped at 10 seconds."""
        huge = tts_bridge._fallback_wav("x" * 10000)
        buf = io.BytesIO(huge)
        with wave.open(buf, "rb") as wf:
            duration = wf.getnframes() / wf.getframerate()
            self.assertLessEqual(duration, 10.5)


class TTSSpeakRequestTest(unittest.TestCase):
    def test_speak_request_model(self):

        req = tts_bridge.SpeakRequest(text="hello world")
        self.assertEqual(req.text, "hello world")
        self.assertTrue(req.fallback)

        req2 = tts_bridge.SpeakRequest(text="test", fallback=False)
        self.assertFalse(req2.fallback)


class TTSAPITest(unittest.TestCase):
    """Test FastAPI route handlers."""

    def test_status_route(self):
        import asyncio

        result = asyncio.run(tts_bridge.tts_status())
        self.assertIn("enabled", result)
        self.assertIn("model", result)
        self.assertIn("sample_rate", result)
        self.assertIn("voice_loaded", result)

    def test_voices_route(self):
        import asyncio

        result = asyncio.run(tts_bridge.tts_voices())
        self.assertIn("voices", result)
        self.assertIn("count", result)
        self.assertIsInstance(result["voices"], list)

    def test_speak_fallback(self):
        """Speak with fallback should return audio/wav even if Piper missing."""
        import asyncio

        req = tts_bridge.SpeakRequest(text="test fallback", fallback=True)
        result = asyncio.run(tts_bridge.tts_speak(req))
        # Should return a Response object with audio/wav
        from fastapi.responses import Response

        self.assertIsInstance(result, Response)
        self.assertEqual(result.media_type, "audio/wav")
        self.assertGreater(len(result.body), 44)

    def test_speak_no_fallback_returns_error(self):
        """Speak without fallback should return error dict when Piper missing."""
        import asyncio

        req = tts_bridge.SpeakRequest(text="test no fallback", fallback=False)
        result = asyncio.run(tts_bridge.tts_speak(req))
        # Should return a dict with error (not a Response)
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)

    def test_speak_empty_text(self):
        """Empty text should return error."""
        import asyncio

        req = tts_bridge.SpeakRequest(text="", fallback=True)
        result = asyncio.run(tts_bridge.tts_speak(req))
        self.assertIsInstance(result, dict)
        self.assertIn("error", result)


class TTSSynthesizeTest(unittest.TestCase):
    def test_synthesize_raises_without_piper(self):
        """_synthesize_to_wav should raise when Piper is not installed."""
        import asyncio

        # Reset the voice singleton
        tts_bridge._piper_voice = None
        with self.assertRaises(Exception):
            asyncio.run(tts_bridge.get_voice())


if __name__ == "__main__":
    unittest.main()
