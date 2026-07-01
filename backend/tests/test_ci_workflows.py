"""Tests for CI workflow YAML structure validation.

Validates that the GitHub Actions workflow files exist and contain the expected
jobs and triggers. Does not execute the workflows — only checks structure.
"""

from __future__ import annotations

import os
import unittest
import yaml


_WORKFLOWS_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", ".github", "workflows"
)


def _load_yaml(filename: str) -> dict:
    path = os.path.join(_WORKFLOWS_DIR, filename)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _get_triggers(data: dict) -> dict:
    """Extract the 'on' section from a workflow, handling YAML's True key."""
    on = data.get("on", data.get(True, {}))
    if isinstance(on, str):
        return {on: {}}
    return on or {}


class TestCIWorkflowStructure(unittest.TestCase):
    """Validate that all expected CI workflows exist with correct structure."""

    def test_ci_yml_exists(self):
        data = _load_yaml("ci.yml")
        self.assertTrue(data, "ci.yml must exist and be valid YAML")
        self.assertIn("jobs", data)

    def test_ci_yml_has_expected_jobs(self):
        data = _load_yaml("ci.yml")
        jobs = data.get("jobs", {})
        expected = {"frontend", "backend", "backend-tests", "pre-commit"}
        for name in expected:
            self.assertIn(name, jobs, f"ci.yml must have job '{name}'")

    def test_security_audit_yml_exists(self):
        data = _load_yaml("security-audit.yml")
        self.assertTrue(data, "security-audit.yml must exist")
        self.assertIn("jobs", data)

    def test_security_audit_has_pip_audit(self):
        data = _load_yaml("security-audit.yml")
        jobs = data.get("jobs", {})
        self.assertIn("pip-audit", jobs)

    def test_security_audit_has_npm_audit(self):
        data = _load_yaml("security-audit.yml")
        jobs = data.get("jobs", {})
        self.assertIn("npm-audit", jobs)

    def test_security_audit_has_schedule_trigger(self):
        data = _load_yaml("security-audit.yml")
        triggers = _get_triggers(data)
        self.assertIn("schedule", triggers)

    def test_feed_validation_yml_exists(self):
        data = _load_yaml("feed-validation.yml")
        self.assertTrue(data, "feed-validation.yml must exist")
        self.assertIn("jobs", data)

    def test_feed_validation_has_feed_smoke_job(self):
        data = _load_yaml("feed-validation.yml")
        jobs = data.get("jobs", {})
        self.assertIn("feed-smoke", jobs)

    def test_feed_validation_has_path_filter(self):
        data = _load_yaml("feed-validation.yml")
        triggers = _get_triggers(data)
        pr_config = triggers.get("pull_request", {})
        paths = pr_config.get("paths", [])
        self.assertTrue(
            any("bridge" in p for p in paths),
            "feed-validation.yml should trigger on bridge file changes",
        )

    def test_typecheck_yml_exists(self):
        data = _load_yaml("typecheck.yml")
        self.assertTrue(data, "typecheck.yml must exist")
        self.assertIn("jobs", data)

    def test_typecheck_has_mypy_job(self):
        data = _load_yaml("typecheck.yml")
        jobs = data.get("jobs", {})
        self.assertIn("mypy", jobs)

    def test_typecheck_has_tsc_job(self):
        data = _load_yaml("typecheck.yml")
        jobs = data.get("jobs", {})
        self.assertIn("tsc", jobs)

    def test_deploy_gate_yml_exists(self):
        data = _load_yaml("deploy-gate.yml")
        self.assertTrue(data, "deploy-gate.yml must exist")
        self.assertIn("jobs", data)

    def test_deploy_gate_has_aggregate_job(self):
        data = _load_yaml("deploy-gate.yml")
        jobs = data.get("jobs", {})
        self.assertIn("deploy-gate", jobs)

    def test_deploy_gate_needs_dependencies(self):
        data = _load_yaml("deploy-gate.yml")
        gate_job = data.get("jobs", {}).get("deploy-gate", {})
        needs = gate_job.get("needs", [])
        # Should depend on multiple jobs
        self.assertGreaterEqual(
            len(needs), 5, "deploy-gate should aggregate multiple jobs"
        )

    def test_all_workflows_are_valid_yaml(self):
        """All .yml files in workflows dir should be parseable."""
        if not os.path.isdir(_WORKFLOWS_DIR):
            self.skipTest("No .github/workflows directory")
        for filename in os.listdir(_WORKFLOWS_DIR):
            if not filename.endswith((".yml", ".yaml")):
                continue
            path = os.path.join(_WORKFLOWS_DIR, filename)
            with open(path, encoding="utf-8") as f:
                try:
                    yaml.safe_load(f)
                except yaml.YAMLError as exc:
                    self.fail(f"{filename} is not valid YAML: {exc}")


if __name__ == "__main__":
    unittest.main()
