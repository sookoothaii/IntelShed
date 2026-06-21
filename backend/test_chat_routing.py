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


if __name__ == "__main__":
    unittest.main()
