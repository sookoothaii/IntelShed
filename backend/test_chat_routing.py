"""Phase 0 — chat routing characterization (no network, no main import)."""

from __future__ import annotations

import unittest

import chat_routing as cr


class ChatRoutingTests(unittest.TestCase):
    def test_default_provider_ollama(self):
        opts = cr.resolve_chat_options({}, default_model="qwen3:8b")
        self.assertEqual(opts["provider"], "ollama")
        self.assertEqual(opts["model"], "qwen3:8b")
        self.assertTrue(opts["use_tools"])

    def test_force_fast_disables_tools(self):
        opts = cr.resolve_chat_options(
            {"provider": "ollama", "force_fast": True},
            default_model="qwen3:8b",
        )
        self.assertFalse(opts["use_tools"])
        self.assertTrue(opts["force_fast"])

    def test_entity_context_disables_tools(self):
        opts = cr.resolve_chat_options(
            {"provider": "ollama", "entity_context": {"id": "x"}},
            default_model="qwen3:8b",
        )
        self.assertFalse(opts["use_tools"])

    def test_non_ollama_default_no_tools(self):
        opts = cr.resolve_chat_options(
            {"provider": "openai", "model": "gpt-4o"},
            default_model="qwen3:8b",
        )
        self.assertEqual(opts["provider"], "openai")
        self.assertFalse(opts["use_tools"])

    def test_explicit_use_tools_false(self):
        opts = cr.resolve_chat_options(
            {"provider": "ollama", "use_tools": False},
            default_model="qwen3:8b",
        )
        self.assertFalse(opts["use_tools"])

    def test_provider_requires_api_key(self):
        self.assertFalse(cr.provider_requires_api_key("ollama"))
        self.assertTrue(cr.provider_requires_api_key("anthropic"))

    def test_ollama_body_qwen3_think_false(self):
        body = cr.build_ollama_chat_body(
            "qwen3:8b",
            [{"role": "user", "content": "hi"}],
            stream=False,
            force_fast=False,
            keep_alive="5m",
        )
        self.assertFalse(body["think"])
        self.assertEqual(body["keep_alive"], "5m")

    def test_ollama_body_force_fast_options(self):
        body = cr.build_ollama_chat_body(
            "llama3",
            [],
            stream=True,
            force_fast=True,
            keep_alive=0,
        )
        self.assertNotIn("think", body)
        self.assertEqual(body["options"]["num_predict"], 260)

    def test_supported_providers_set(self):
        self.assertIn("ollama", cr.SUPPORTED_PROVIDERS)
        self.assertIn("openrouter", cr.SUPPORTED_PROVIDERS)

    def test_provider_supports_tools(self):
        self.assertTrue(cr.provider_supports_tools("ollama"))
        self.assertTrue(cr.provider_supports_tools("openai"))
        self.assertTrue(cr.provider_supports_tools("groq"))
        self.assertTrue(cr.provider_supports_tools("openrouter"))
        self.assertFalse(cr.provider_supports_tools("anthropic"))

    def test_select_api_key_prefers_request(self):
        key = cr.select_api_key("openai", {"openai": "sk-ui"}, "sk-env")
        self.assertEqual(key, "sk-ui")

    def test_select_api_key_falls_back_to_env(self):
        self.assertEqual(cr.select_api_key("openai", {}, "sk-env"), "sk-env")
        self.assertEqual(cr.select_api_key("openai", None, "sk-env"), "sk-env")
        self.assertEqual(cr.select_api_key("openai", {"openai": "   "}, "sk-env"), "sk-env")

    def test_select_api_key_no_cross_provider_leak(self):
        # An OpenAI key in the map must not be used for anthropic.
        self.assertEqual(cr.select_api_key("anthropic", {"openai": "sk-ui"}, None), None)

    def test_select_api_key_strips_whitespace(self):
        self.assertEqual(cr.select_api_key("groq", {"groq": "  gk-1 "}, None), "gk-1")

    def test_select_base_url_prefers_request(self):
        url = cr.select_base_url(
            "openai",
            {"openai": "http://127.0.0.1:8080/v1"},
            "https://api.openai.com/v1",
            cr.DEFAULT_BASE_URLS["openai"],
        )
        self.assertEqual(url, "http://127.0.0.1:8080/v1")

    def test_select_base_url_falls_back_to_env_then_default(self):
        self.assertEqual(
            cr.select_base_url("openai", {}, "https://proxy.local/v1", cr.DEFAULT_BASE_URLS["openai"]),
            "https://proxy.local/v1",
        )
        self.assertEqual(
            cr.select_base_url("openai", {}, None, cr.DEFAULT_BASE_URLS["openai"]),
            cr.DEFAULT_BASE_URLS["openai"],
        )

    def test_openai_chat_completions_url_from_base(self):
        self.assertEqual(
            cr.openai_chat_completions_url("https://api.openai.com/v1"),
            "https://api.openai.com/v1/chat/completions",
        )

    def test_openai_chat_completions_url_full_passthrough(self):
        full = "https://proxy.local/v1/chat/completions"
        self.assertEqual(cr.openai_chat_completions_url(full), full)

    def test_anthropic_messages_url_from_base(self):
        self.assertEqual(
            cr.anthropic_messages_url("https://api.anthropic.com/v1"),
            "https://api.anthropic.com/v1/messages",
        )


if __name__ == "__main__":
    unittest.main()
