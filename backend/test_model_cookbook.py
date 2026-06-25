"""Unit tests for model_cookbook (no network, no GPU required)."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import model_cookbook as mc


class TestDecayWeight(unittest.TestCase):
    def test_vram_estimation_scales_with_ctx(self):
        base = mc._estimate_vram_for_ctx(5.0, 4096)
        high = mc._estimate_vram_for_ctx(5.0, 16384)
        self.assertGreater(high, base)

    def test_fits_in_vram(self):
        model = {"file_size_gb": 5.0}
        self.assertTrue(mc._fits_in_vram(model, 4096, 10.0))
        self.assertFalse(mc._fits_in_vram(model, 16384, 5.0))

    def test_best_ctx_for_model(self):
        model = {"file_size_gb": 5.0}
        ctx = mc._best_ctx_for_model(model, 10.0)
        self.assertGreaterEqual(ctx, 4096)
        ctx_tight = mc._best_ctx_for_model(model, 6.0)
        self.assertLessEqual(ctx_tight, 8192)

    def test_recommend_no_gpu(self):
        with patch.object(mc, "_run_nvidia_smi", return_value=None):
            with patch.object(mc, "_query_ollama_models", return_value=[]):
                with patch.dict(os.environ, {"OLLAMA_MODEL": "qwen3:8b"}):
                    rec = mc.recommend()
        self.assertIsNone(rec["gpu"])
        self.assertEqual(rec["recommended_model"], "qwen3:8b")
        self.assertEqual(rec["recommended_ctx"], 4096)
        self.assertIn("No NVIDIA GPU", rec["reasoning"])

    def test_recommend_with_gpu_16gb(self):
        gpu = {
            "gpu_name": "RTX 3080 Ti",
            "vram_total_mb": 12288,
            "vram_used_mb": 2048,
            "vram_free_mb": 10240,
            "vram_total_gb": 12.0,
            "vram_free_gb": 10.0,
        }
        models = [
            {"name": "qwen3:8b"},
            {"name": "qwen3:14b"},
            {"name": "nomic-embed-text"},
        ]
        with patch.object(mc, "_run_nvidia_smi", return_value=gpu):
            with patch.object(mc, "_query_ollama_models", return_value=models):
                with patch.dict(os.environ, {"OLLAMA_MODEL": "qwen3:8b"}):
                    rec = mc.recommend()
        self.assertIsNotNone(rec["gpu"])
        self.assertEqual(rec["gpu"]["gpu_name"], "RTX 3080 Ti")
        self.assertIn(rec["recommended_model"], ["qwen3:14b", "qwen3:8b"])
        self.assertGreaterEqual(rec["recommended_ctx"], 4096)
        self.assertIn("available_models", rec)
        self.assertIn("qwen3:8b", rec["available_models"])

    def test_recommend_with_gpu_24gb(self):
        gpu = {
            "gpu_name": "RTX 4090",
            "vram_total_mb": 24576,
            "vram_used_mb": 1024,
            "vram_free_mb": 23552,
            "vram_total_gb": 24.0,
            "vram_free_gb": 23.0,
        }
        models = [
            {"name": "qwen3:8b"},
            {"name": "qwen3:14b"},
            {"name": "qwen3:32b"},
        ]
        with patch.object(mc, "_run_nvidia_smi", return_value=gpu):
            with patch.object(mc, "_query_ollama_models", return_value=models):
                with patch.dict(os.environ, {"OLLAMA_MODEL": "qwen3:8b"}):
                    rec = mc.recommend()
        self.assertEqual(rec["recommended_model"], "qwen3:32b")
        self.assertGreaterEqual(rec["recommended_ctx"], 4096)

    def test_recommend_very_tight_vram(self):
        gpu = {
            "gpu_name": "GTX 1060",
            "vram_total_mb": 6144,
            "vram_used_mb": 4096,
            "vram_free_mb": 2048,
            "vram_total_gb": 6.0,
            "vram_free_gb": 2.0,
        }
        models = [{"name": "qwen3:8b"}, {"name": "qwen3:1.7b"}]
        with patch.object(mc, "_run_nvidia_smi", return_value=gpu):
            with patch.object(mc, "_query_ollama_models", return_value=models):
                with patch.dict(os.environ, {"OLLAMA_MODEL": "qwen3:8b"}):
                    rec = mc.recommend()
        self.assertEqual(rec["recommended_model"], "qwen3:1.7b")
        self.assertEqual(rec["recommended_ctx"], 2048)
        self.assertIn("VRAM very tight", rec["reasoning"])

    def test_recommend_no_installed_models(self):
        gpu = {
            "gpu_name": "RTX 3080 Ti",
            "vram_total_mb": 12288,
            "vram_used_mb": 2048,
            "vram_free_mb": 10240,
            "vram_total_gb": 12.0,
            "vram_free_gb": 10.0,
        }
        with patch.object(mc, "_run_nvidia_smi", return_value=gpu):
            with patch.object(mc, "_query_ollama_models", return_value=[]):
                with patch.dict(os.environ, {"OLLAMA_MODEL": "qwen3:8b"}):
                    rec = mc.recommend()
        # Falls back to registry
        self.assertIsNotNone(rec["recommended_model"])
        self.assertGreaterEqual(rec["recommended_ctx"], 4096)


if __name__ == "__main__":
    unittest.main()
