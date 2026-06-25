"""Tests for J1 — Prompt Versioning & A/B Testing."""

from __future__ import annotations

import os
import unittest


class TestPromptRegistry(unittest.TestCase):
    """Prompt registry SQLite operations."""

    def test_registry_disabled_by_default(self):
        from prompt_registry import prompt_registry_enabled

        os.environ.pop("WORLDBASE_PROMPT_REGISTRY", None)
        self.assertFalse(prompt_registry_enabled())

    def test_registry_enabled_when_configured(self):
        from prompt_registry import prompt_registry_enabled

        os.environ["WORLDBASE_PROMPT_REGISTRY"] = "1"
        self.assertTrue(prompt_registry_enabled())
        os.environ.pop("WORLDBASE_PROMPT_REGISTRY", None)

    def test_get_active_returns_none_when_disabled(self):
        from prompt_registry import get_active

        os.environ.pop("WORLDBASE_PROMPT_REGISTRY", None)
        self.assertIsNone(get_active("test_prompt"))

    def test_save_and_list_prompt(self):
        from prompt_registry import save_prompt, list_prompts, init_prompt_db

        init_prompt_db()
        prompt_id = save_prompt("test_j1", "Hello {name}", set_default=True)
        self.assertIsInstance(prompt_id, int)
        prompts = list_prompts("test_j1")
        self.assertTrue(any(p["id"] == prompt_id for p in prompts))

    def test_activate_prompt(self):
        from prompt_registry import save_prompt, activate_prompt, list_prompts, init_prompt_db

        init_prompt_db()
        id1 = save_prompt("test_activate", "v1", set_default=True)
        id2 = save_prompt("test_activate", "v2")
        ok = activate_prompt(id2)
        self.assertTrue(ok)
        prompts = list_prompts("test_activate")
        active = [p for p in prompts if p["is_default"]]
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], id2)

    def test_activate_nonexistent_returns_false(self):
        from prompt_registry import activate_prompt

        self.assertFalse(activate_prompt(999999))

    def test_create_and_get_experiment(self):
        from prompt_registry import (
            save_prompt, create_experiment, get_experiment, init_prompt_db,
        )

        init_prompt_db()
        id_a = save_prompt("test_exp", "variant a")
        id_b = save_prompt("test_exp", "variant b")
        exp_id = create_experiment("test_exp_1", id_a, id_b, 0.5)
        self.assertIsInstance(exp_id, int)
        exp = get_experiment("test_exp_1")
        self.assertIsNotNone(exp)
        self.assertEqual(exp["variant_a_id"], id_a)
        self.assertEqual(exp["variant_b_id"], id_b)

    def test_record_and_get_results(self):
        from prompt_registry import record_result, get_results, init_prompt_db
        import uuid

        init_prompt_db()
        exp_name = f"test_results_{uuid.uuid4().hex[:8]}"
        record_result(exp_name, "a", 0.8, "briefing-1")
        record_result(exp_name, "a", 0.9, "briefing-2")
        record_result(exp_name, "b", 0.7, "briefing-3")
        results = get_results(exp_name)
        self.assertEqual(len(results["a"]), 2)
        self.assertEqual(len(results["b"]), 1)


class TestPromptEval(unittest.TestCase):
    """A/B evaluation logic."""

    def test_evaluate_no_experiment(self):
        from prompt_eval import evaluate_experiment

        result = evaluate_experiment("nonexistent_exp")
        self.assertIn("error", result)
        self.assertFalse(result["significant"])

    def test_evaluate_insufficient_samples(self):
        from prompt_registry import (
            save_prompt, create_experiment, record_result, init_prompt_db,
        )
        from prompt_eval import evaluate_experiment

        init_prompt_db()
        id_a = save_prompt("test_eval", "a")
        id_b = save_prompt("test_eval", "b")
        create_experiment("test_eval_1", id_a, id_b)
        record_result("test_eval_1", "a", 0.8)
        record_result("test_eval_1", "b", 0.7)
        result = evaluate_experiment("test_eval_1")
        self.assertFalse(result["significant"])
        self.assertIn("message", result)

    def test_fallback_ttest(self):
        from prompt_eval import _fallback_ttest

        # Identical distributions → high p-value
        p = _fallback_ttest([0.5, 0.5, 0.5, 0.5, 0.5], [0.5, 0.5, 0.5, 0.5, 0.5])
        self.assertGreater(p, 0.1)

        # Very different distributions → low p-value
        p = _fallback_ttest([0.9, 0.9, 0.9, 0.9, 0.9], [0.1, 0.1, 0.1, 0.1, 0.1])
        self.assertLess(p, 0.05)


class TestAdminRoutes(unittest.TestCase):
    """Admin API route presence."""

    def test_admin_router_has_prompt_routes(self):
        from routes.admin import router

        paths = [r.path for r in router.routes]
        self.assertIn("/api/admin/prompts", paths)
        self.assertIn("/api/admin/prompts/{prompt_id}/activate", paths)
        self.assertIn("/api/admin/prompts/experiments", paths)
        self.assertIn("/api/admin/prompts/experiments/{name}/evaluate", paths)
        self.assertIn("/api/admin/prompts/experiments/{name}/results", paths)


class TestConfigPromptRegistry(unittest.TestCase):
    """Config integration."""

    def test_config_prompt_registry_default_off(self):
        os.environ.pop("WORLDBASE_PROMPT_REGISTRY", None)
        from config import WorldBaseConfig

        cfg = WorldBaseConfig.from_env()
        self.assertFalse(cfg.prompt_registry_enabled)

    def test_config_prompt_registry_enabled(self):
        os.environ["WORLDBASE_PROMPT_REGISTRY"] = "1"
        try:
            from config import WorldBaseConfig

            cfg = WorldBaseConfig.from_env()
            self.assertTrue(cfg.prompt_registry_enabled)
        finally:
            os.environ.pop("WORLDBASE_PROMPT_REGISTRY", None)


if __name__ == "__main__":
    unittest.main()
