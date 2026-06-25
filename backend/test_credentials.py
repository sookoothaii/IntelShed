"""Unit tests for credential registry."""

import os
import unittest
from unittest.mock import patch

from credentials.registry import (
    PROVIDERS,
    get_env,
    is_configured,
    provider_for_feed,
    provider_status,
    providers_status,
)


class TestCredentialRegistry(unittest.TestCase):
    def test_catalog_has_core_providers(self):
        for pid in (
            "windy_point",
            "windy_webcam",
            "data_gov_sg",
            "opentrafficcammap",
            "ollama",
        ):
            self.assertIn(pid, PROVIDERS)

    def test_free_provider_always_configured(self):
        self.assertTrue(is_configured("data_gov_sg"))
        self.assertTrue(is_configured("ollama"))

    def test_status_never_includes_secret_values(self):
        with patch.dict(os.environ, {"WINDY_POINT_API_KEY": "super-secret-key-12345"}, clear=False):
            st = provider_status("windy_point")
        self.assertIsNotNone(st)
        assert st is not None
        self.assertTrue(st["configured"])
        blob = str(st)
        self.assertNotIn("super-secret-key", blob)

    def test_placeholder_not_configured(self):
        with patch.dict(os.environ, {"WINDY_POINT_API_KEY": "your-point-forecast-key"}, clear=False):
            self.assertFalse(is_configured("windy_point"))

    def test_providers_status_shape(self):
        body = providers_status()
        self.assertIn("providers", body)
        self.assertIn("configured", body)
        self.assertEqual(body["usage_policy_default"], "private_research")
        self.assertGreater(body["count"], 5)

    def test_feed_provider_map(self):
        self.assertEqual(provider_for_feed("webcams"), "windy_webcam")
        self.assertEqual(provider_for_feed("traffic_cams_regional"), "data_gov_sg")

    def test_get_env_single_var(self):
        with patch.dict(os.environ, {"WINDY_MAP_API_KEY": "abc"}, clear=False):
            self.assertEqual(get_env("windy_map"), "abc")

    def test_opensky_requires_both_vars(self):
        with patch.dict(
            os.environ,
            {"OPENSKY_CLIENT_ID": "id", "OPENSKY_CLIENT_SECRET": ""},
            clear=False,
        ):
            self.assertFalse(is_configured("opensky"))

    def test_ais_maritime_any_one_key(self):
        with patch.dict(
            os.environ,
            {
                "AISHUB_API_KEY": "",
                "AISSTREAM_API_KEY": "live-aisstream-token",
                "MYSHIPTRACKING_API_KEY": "",
            },
            clear=False,
        ):
            self.assertTrue(is_configured("ais_maritime"))
        with patch.dict(
            os.environ,
            {"AISHUB_API_KEY": "", "AISSTREAM_API_KEY": "", "MYSHIPTRACKING_API_KEY": ""},
            clear=False,
        ):
            self.assertFalse(is_configured("ais_maritime"))


if __name__ == "__main__":
    unittest.main()
