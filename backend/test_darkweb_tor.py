"""Tests for darkweb_tor (Phase 3.2) — Tor exit-node rotation, no live Tor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import darkweb_tor


def _cfg(**over):
    cfg = MagicMock()
    cfg.darkweb_tor_rotate_identity = over.get("rotate", True)
    cfg.darkweb_tor_control_host = over.get("host", "127.0.0.1:9051")
    cfg.darkweb_tor_control_password = over.get("password", "")
    cfg.darkweb_exit_blocklist = over.get("blocklist", "CN,RU,IR")
    return cfg


class TorConfigHelperTests(unittest.TestCase):
    def test_rotation_disabled_by_default_config(self):
        with patch.object(darkweb_tor, "get_config", return_value=_cfg(rotate=False)):
            self.assertFalse(darkweb_tor.rotation_enabled())

    def test_rotation_enabled(self):
        with patch.object(darkweb_tor, "get_config", return_value=_cfg(rotate=True)):
            self.assertTrue(darkweb_tor.rotation_enabled())

    def test_control_endpoint_parsing(self):
        with patch.object(
            darkweb_tor, "get_config", return_value=_cfg(host="10.0.0.5:9999")
        ):
            self.assertEqual(darkweb_tor._control_endpoint(), ("10.0.0.5", 9999))

    def test_control_endpoint_defaults_on_garbage(self):
        with patch.object(
            darkweb_tor, "get_config", return_value=_cfg(host="badport:abc")
        ):
            self.assertEqual(darkweb_tor._control_endpoint(), ("badport", 9051))

    def test_control_endpoint_default_when_empty(self):
        with patch.object(darkweb_tor, "get_config", return_value=_cfg(host="")):
            self.assertEqual(darkweb_tor._control_endpoint(), ("127.0.0.1", 9051))

    def test_control_password_none_when_blank(self):
        with patch.object(darkweb_tor, "get_config", return_value=_cfg(password="  ")):
            self.assertIsNone(darkweb_tor._control_password())

    def test_control_password_returned(self):
        with patch.object(
            darkweb_tor, "get_config", return_value=_cfg(password="secret")
        ):
            self.assertEqual(darkweb_tor._control_password(), "secret")

    def test_exit_blocklist_parsing(self):
        with patch.object(
            darkweb_tor, "get_config", return_value=_cfg(blocklist="cn, ru ,ir")
        ):
            self.assertEqual(darkweb_tor.exit_blocklist(), {"CN", "RU", "IR"})

    def test_exit_blocklist_empty(self):
        with patch.object(darkweb_tor, "get_config", return_value=_cfg(blocklist="")):
            self.assertEqual(darkweb_tor.exit_blocklist(), set())


class TorRotateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        darkweb_tor.reset_rate_limit()

    async def test_disabled_is_noop(self):
        with patch.object(darkweb_tor, "get_config", return_value=_cfg(rotate=False)):
            out = await darkweb_tor.rotate_identity(reason="x")
        self.assertFalse(out["rotated"])
        self.assertEqual(out["error"], "disabled")

    async def test_stem_missing_fail_soft(self):
        with patch.object(darkweb_tor, "get_config", return_value=_cfg()):
            with patch.object(darkweb_tor, "_import_stem", return_value=None):
                out = await darkweb_tor.rotate_identity()
        self.assertFalse(out["rotated"])
        self.assertEqual(out["error"], "stem not installed")

    async def test_successful_rotation_signals_newnym(self):
        rotator = darkweb_tor.TorRotator()
        with patch.object(darkweb_tor, "get_config", return_value=_cfg()):
            with patch.object(darkweb_tor, "_import_stem", return_value=MagicMock()):
                with patch.object(
                    rotator, "_signal_and_inspect", return_value="US"
                ) as sig:
                    out = await rotator.rotate(check_exit=True)
        self.assertTrue(out["rotated"])
        self.assertEqual(out["attempts"], 1)
        self.assertEqual(out["exit_country"], "US")
        self.assertFalse(out["blocklisted"])
        sig.assert_called_once()

    async def test_blocklisted_exit_triggers_re_rotation(self):
        rotator = darkweb_tor.TorRotator()
        # First exit is blocked (RU), second is clean (NL).
        countries = ["RU", "NL"]
        with patch.object(darkweb_tor, "get_config", return_value=_cfg()):
            with patch.object(darkweb_tor, "_import_stem", return_value=MagicMock()):
                with patch.object(darkweb_tor, "NEWNYM_MIN_INTERVAL_SEC", 0.0):
                    with patch.object(
                        rotator,
                        "_signal_and_inspect",
                        side_effect=lambda *a: countries.pop(0),
                    ) as sig:
                        out = await rotator.rotate(check_exit=True, max_attempts=3)
        self.assertTrue(out["rotated"])
        self.assertEqual(out["attempts"], 2)
        self.assertEqual(out["exit_country"], "NL")
        self.assertFalse(out["blocklisted"])
        self.assertEqual(sig.call_count, 2)

    async def test_blocklisted_exhausts_attempts(self):
        rotator = darkweb_tor.TorRotator()
        with patch.object(darkweb_tor, "get_config", return_value=_cfg()):
            with patch.object(darkweb_tor, "_import_stem", return_value=MagicMock()):
                with patch.object(darkweb_tor, "NEWNYM_MIN_INTERVAL_SEC", 0.0):
                    with patch.object(
                        rotator, "_signal_and_inspect", return_value="CN"
                    ) as sig:
                        out = await rotator.rotate(check_exit=True, max_attempts=2)
        self.assertTrue(out["rotated"])
        self.assertEqual(out["attempts"], 2)
        self.assertTrue(out["blocklisted"])
        self.assertEqual(sig.call_count, 2)

    async def test_rate_limit_skip_when_no_wait(self):
        rotator = darkweb_tor.TorRotator()
        with patch.object(darkweb_tor, "get_config", return_value=_cfg()):
            with patch.object(darkweb_tor, "_import_stem", return_value=MagicMock()):
                with patch.object(rotator, "_signal_and_inspect", return_value="US"):
                    first = await rotator.rotate(check_exit=False)
                    second = await rotator.rotate(check_exit=False, wait=False)
        self.assertTrue(first["rotated"])
        self.assertFalse(second["rotated"])
        self.assertEqual(second["error"], "rate_limited")

    async def test_rate_limit_waits_when_wait_true(self):
        rotator = darkweb_tor.TorRotator()
        sleeps: list[float] = []

        async def fake_sleep(d):
            sleeps.append(d)

        with patch.object(darkweb_tor, "get_config", return_value=_cfg()):
            with patch.object(darkweb_tor, "_import_stem", return_value=MagicMock()):
                with patch.object(rotator, "_signal_and_inspect", return_value="US"):
                    with patch.object(darkweb_tor.asyncio, "sleep", fake_sleep):
                        await rotator.rotate(check_exit=False)
                        await rotator.rotate(check_exit=False, wait=True)
        # Second rotation must have waited out the remaining window.
        self.assertTrue(sleeps)
        self.assertGreater(sleeps[0], 0)

    async def test_signal_inspect_exception_fail_soft(self):
        rotator = darkweb_tor.TorRotator()
        with patch.object(darkweb_tor, "get_config", return_value=_cfg()):
            with patch.object(darkweb_tor, "_import_stem", return_value=MagicMock()):
                with patch.object(
                    rotator, "_signal_and_inspect", side_effect=RuntimeError("boom")
                ):
                    out = await rotator.rotate(check_exit=True)
        self.assertFalse(out["rotated"])
        self.assertEqual(out["error"], "boom")


class ExitCountryTests(unittest.TestCase):
    def test_exit_country_reads_built_circuit(self):
        controller = MagicMock()
        circ = MagicMock()
        circ.status = "BUILT"
        circ.path = [("AAA", "g"), ("BBB", "m"), ("CCC", "exit")]
        controller.get_circuits.return_value = [circ]
        desc = MagicMock()
        desc.address = "1.2.3.4"
        controller.get_network_status.return_value = desc
        controller.get_info.return_value = "nl"
        out = darkweb_tor.TorRotator._exit_country(controller)
        self.assertEqual(out, "NL")
        controller.get_info.assert_called_once_with("ip-to-country/1.2.3.4")

    def test_exit_country_skips_unbuilt(self):
        controller = MagicMock()
        circ = MagicMock()
        circ.status = "EXTENDING"
        circ.path = [("AAA", "g")]
        controller.get_circuits.return_value = [circ]
        out = darkweb_tor.TorRotator._exit_country(controller)
        self.assertIsNone(out)

    def test_exit_country_unknown_country(self):
        controller = MagicMock()
        circ = MagicMock()
        circ.status = "BUILT"
        circ.path = [("AAA", "g"), ("CCC", "exit")]
        controller.get_circuits.return_value = [circ]
        desc = MagicMock()
        desc.address = "1.2.3.4"
        controller.get_network_status.return_value = desc
        controller.get_info.return_value = "??"
        self.assertIsNone(darkweb_tor.TorRotator._exit_country(controller))

    def test_exit_country_fail_soft(self):
        controller = MagicMock()
        controller.get_circuits.side_effect = RuntimeError("no control")
        self.assertIsNone(darkweb_tor.TorRotator._exit_country(controller))


class StatusTests(unittest.TestCase):
    def test_status_fields(self):
        with patch.object(darkweb_tor, "get_config", return_value=_cfg(password="x")):
            st = darkweb_tor.status()
        self.assertIn("enabled", st)
        self.assertIn("stem_available", st)
        self.assertEqual(st["control_host"], "127.0.0.1:9051")
        self.assertTrue(st["control_password_set"])
        self.assertEqual(st["exit_blocklist"], ["CN", "IR", "RU"])
        self.assertEqual(st["newnym_min_interval_sec"], 10.0)


if __name__ == "__main__":
    unittest.main()
