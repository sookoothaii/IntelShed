"""Tests for Smart Model Router (V4-01) — complexity classifier, fallback chain, fail-soft."""

from __future__ import annotations

import os
import unittest

# Ensure clean env for each test
os.environ.pop("WORLDBASE_SMART_ROUTER", None)
os.environ.pop("WORLDBASE_CLOUD_AI", None)
os.environ.pop("WORLDBASE_SMART_ROUTER_CHAIN", None)

import chat_model_router as smr


class TestComplexityClassifier(unittest.TestCase):
    def test_empty_query_is_simple(self):
        self.assertEqual(smr.classify_complexity(""), "simple")
        self.assertEqual(smr.classify_complexity("   "), "simple")

    def test_greeting_is_simple(self):
        self.assertEqual(smr.classify_complexity("hi"), "simple")
        self.assertEqual(smr.classify_complexity("hello there"), "simple")
        self.assertEqual(smr.classify_complexity("hey"), "simple")
        self.assertEqual(smr.classify_complexity("danke"), "simple")

    def test_factual_keywords(self):
        self.assertEqual(
            smr.classify_complexity("what is the capital of Thailand"), "factual"
        )
        self.assertEqual(
            smr.classify_complexity("who is the prime minister"), "factual"
        )
        self.assertEqual(
            smr.classify_complexity("how many ships in the strait"), "factual"
        )
        self.assertEqual(smr.classify_complexity("was ist das"), "factual")

    def test_analytical_keywords(self):
        self.assertEqual(
            smr.classify_complexity("analyze the security situation in the Gulf"),
            "analytical",
        )
        self.assertEqual(
            smr.classify_complexity("assess the implications of the earthquake"),
            "analytical",
        )
        self.assertEqual(
            smr.classify_complexity("compare the two scenarios"), "analytical"
        )
        self.assertEqual(
            smr.classify_complexity("forecast the next 24h events"), "analytical"
        )
        self.assertEqual(smr.classify_complexity("bewerte die lage"), "analytical")

    def test_long_multi_question_is_analytical(self):
        long_q = "What happened in Thailand? Who is involved? Why did this occur? Please provide a detailed analysis of the situation."
        self.assertEqual(smr.classify_complexity(long_q), "analytical")

    def test_short_non_keyword_is_simple(self):
        self.assertEqual(smr.classify_complexity("show ships"), "simple")
        # "list" is a factual keyword, so this is factual not simple
        self.assertEqual(smr.classify_complexity("list feeds"), "factual")

    def test_medium_default_is_factual(self):
        self.assertEqual(
            smr.classify_complexity(
                "Tell me about the current maritime situation near Hormuz"
            ),
            "factual",
        )

    def test_very_long_is_analytical(self):
        long_text = "x" * 250
        self.assertEqual(smr.classify_complexity(long_text), "analytical")


class TestFeatureFlags(unittest.TestCase):
    def test_smart_router_default_off(self):
        os.environ.pop("WORLDBASE_SMART_ROUTER", None)
        self.assertFalse(smr.smart_router_enabled())

    def test_smart_router_on(self):
        os.environ["WORLDBASE_SMART_ROUTER"] = "1"
        try:
            self.assertTrue(smr.smart_router_enabled())
        finally:
            os.environ.pop("WORLDBASE_SMART_ROUTER", None)

    def test_cloud_ai_default_off(self):
        os.environ.pop("WORLDBASE_CLOUD_AI", None)
        self.assertFalse(smr.cloud_ai_enabled())

    def test_cloud_ai_on(self):
        os.environ["WORLDBASE_CLOUD_AI"] = "true"
        try:
            self.assertTrue(smr.cloud_ai_enabled())
        finally:
            os.environ.pop("WORLDBASE_CLOUD_AI", None)


class TestFallbackChain(unittest.TestCase):
    def test_default_chain(self):
        os.environ.pop("WORLDBASE_SMART_ROUTER_CHAIN", None)
        chain = smr.get_fallback_chain()
        self.assertEqual(chain, ["nvidia", "groq", "openrouter", "ollama"])

    def test_custom_chain(self):
        os.environ["WORLDBASE_SMART_ROUTER_CHAIN"] = "groq,ollama"
        try:
            chain = smr.get_fallback_chain()
            self.assertEqual(chain, ["groq", "ollama"])
        finally:
            os.environ.pop("WORLDBASE_SMART_ROUTER_CHAIN", None)

    def test_empty_chain_falls_back_to_default(self):
        os.environ["WORLDBASE_SMART_ROUTER_CHAIN"] = "  ,  "
        try:
            chain = smr.get_fallback_chain()
            self.assertEqual(chain, ["nvidia", "groq", "openrouter", "ollama"])
        finally:
            os.environ.pop("WORLDBASE_SMART_ROUTER_CHAIN", None)


class TestSelectProvider(unittest.TestCase):
    def test_cloud_ai_off_returns_ollama(self):
        os.environ.pop("WORLDBASE_CLOUD_AI", None)
        provider, model, complexity = smr.select_provider("analyze the situation")
        self.assertEqual(provider, "ollama")
        self.assertEqual(complexity, "analytical")

    def test_cloud_ai_on_analytical_prefers_nvidia(self):
        os.environ["WORLDBASE_CLOUD_AI"] = "1"
        os.environ["NVIDIA_API_KEY"] = "test-key"
        try:
            provider, model, complexity = smr.select_provider(
                "analyze the security situation"
            )
            self.assertEqual(provider, "nvidia")
            self.assertEqual(complexity, "analytical")
            self.assertTrue(model)
        finally:
            os.environ.pop("WORLDBASE_CLOUD_AI", None)
            os.environ.pop("NVIDIA_API_KEY", None)

    def test_cloud_ai_on_simple_prefers_ollama(self):
        os.environ["WORLDBASE_CLOUD_AI"] = "1"
        os.environ["NVIDIA_API_KEY"] = "test-key"
        try:
            provider, model, complexity = smr.select_provider("hi")
            self.assertEqual(provider, "ollama")
            self.assertEqual(complexity, "simple")
        finally:
            os.environ.pop("WORLDBASE_CLOUD_AI", None)
            os.environ.pop("NVIDIA_API_KEY", None)

    def test_cloud_ai_on_factual_prefers_groq(self):
        os.environ["WORLDBASE_CLOUD_AI"] = "1"
        os.environ["GROQ_API_KEY"] = "test-key"
        os.environ.pop("NVIDIA_API_KEY", None)
        try:
            provider, model, complexity = smr.select_provider(
                "what is the capital of Thailand"
            )
            self.assertEqual(provider, "groq")
            self.assertEqual(complexity, "factual")
        finally:
            os.environ.pop("WORLDBASE_CLOUD_AI", None)
            os.environ.pop("GROQ_API_KEY", None)

    def test_explicit_provider_respected(self):
        os.environ["WORLDBASE_CLOUD_AI"] = "1"
        os.environ["NVIDIA_API_KEY"] = "test-key"
        try:
            provider, model, complexity = smr.select_provider(
                "analyze", explicit_provider="openai"
            )
            self.assertEqual(provider, "openai")
        finally:
            os.environ.pop("WORLDBASE_CLOUD_AI", None)
            os.environ.pop("NVIDIA_API_KEY", None)

    def test_no_keys_falls_back_to_ollama(self):
        os.environ["WORLDBASE_CLOUD_AI"] = "1"
        os.environ.pop("NVIDIA_API_KEY", None)
        os.environ.pop("GROQ_API_KEY", None)
        os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            provider, model, complexity = smr.select_provider("analyze the situation")
            self.assertEqual(provider, "ollama")
        finally:
            os.environ.pop("WORLDBASE_CLOUD_AI", None)

    def test_hud_keys_used(self):
        os.environ["WORLDBASE_CLOUD_AI"] = "1"
        os.environ.pop("NVIDIA_API_KEY", None)
        try:
            provider, model, complexity = smr.select_provider(
                "analyze the situation",
                api_keys={"nvidia": "hud-key"},
            )
            self.assertEqual(provider, "nvidia")
        finally:
            os.environ.pop("WORLDBASE_CLOUD_AI", None)


class TestShouldFallback(unittest.TestCase):
    def test_timeout_triggers_fallback(self):
        self.assertTrue(smr.should_fallback({"error": "Request timeout"}))
        self.assertTrue(smr.should_fallback("timed out"))

    def test_rate_limit_triggers_fallback(self):
        self.assertTrue(
            smr.should_fallback(
                {"error": "429 rate limit", "detail": "too many requests"}
            )
        )

    def test_503_triggers_fallback(self):
        self.assertTrue(
            smr.should_fallback(
                {"error": "nvidia HTTP 503", "detail": "service unavailable"}
            )
        )

    def test_model_not_found_no_fallback(self):
        self.assertFalse(
            smr.should_fallback({"error": "Model 'x' not found", "detail": ""})
        )

    def test_context_budget_no_fallback(self):
        self.assertFalse(
            smr.should_fallback({"error": "Context budget refused", "detail": ""})
        )

    def test_firewall_block_no_fallback(self):
        self.assertFalse(
            smr.should_fallback(
                {"error": "Session guard triggered", "detail": "blocked"}
            )
        )

    def test_400_no_fallback(self):
        self.assertFalse(
            smr.should_fallback({"error": "nvidia HTTP 400", "detail": "bad request"})
        )


class TestNextFallbackProvider(unittest.TestCase):
    def test_next_after_nvidia(self):
        os.environ["NVIDIA_API_KEY"] = "k1"
        os.environ["GROQ_API_KEY"] = "k2"
        os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            result = smr.next_fallback_provider("nvidia", ["nvidia"])
            self.assertEqual(result, "groq")
        finally:
            os.environ.pop("NVIDIA_API_KEY", None)
            os.environ.pop("GROQ_API_KEY", None)

    def test_next_after_groq_skips_to_ollama(self):
        os.environ["GROQ_API_KEY"] = "k2"
        os.environ.pop("NVIDIA_API_KEY", None)
        os.environ.pop("OPENROUTER_API_KEY", None)
        try:
            result = smr.next_fallback_provider("groq", ["groq"])
            self.assertEqual(result, "ollama")
        finally:
            os.environ.pop("GROQ_API_KEY", None)

    def test_no_more_providers_returns_none(self):
        result = smr.next_fallback_provider("ollama", ["ollama"])
        self.assertIsNone(result)

    def test_skips_attempted(self):
        os.environ["NVIDIA_API_KEY"] = "k1"
        os.environ["GROQ_API_KEY"] = "k2"
        os.environ["OPENROUTER_API_KEY"] = "k3"
        try:
            result = smr.next_fallback_provider("nvidia", ["nvidia", "groq"])
            self.assertEqual(result, "openrouter")
        finally:
            os.environ.pop("NVIDIA_API_KEY", None)
            os.environ.pop("GROQ_API_KEY", None)
            os.environ.pop("OPENROUTER_API_KEY", None)


class TestDefaultModelFor(unittest.TestCase):
    def test_nvidia_default(self):
        os.environ.pop("WORLDBASE_NVIDIA_MODEL", None)
        model = smr._default_model_for("nvidia")
        self.assertTrue(model)

    def test_env_override(self):
        os.environ["WORLDBASE_NVIDIA_MODEL"] = "custom/model"
        try:
            model = smr._default_model_for("nvidia")
            self.assertEqual(model, "custom/model")
        finally:
            os.environ.pop("WORLDBASE_NVIDIA_MODEL", None)

    def test_ollama_default(self):
        os.environ.pop("OLLAMA_MODEL", None)
        model = smr._default_model_for("ollama")
        self.assertEqual(model, "qwen3:8b")


if __name__ == "__main__":
    unittest.main()
