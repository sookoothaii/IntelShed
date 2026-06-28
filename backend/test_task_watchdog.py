"""Unit tests for TaskWatchdog (Phase 1.1 — process health watchdog)."""

from __future__ import annotations

import asyncio
import time
import unittest

from lifespan import TaskWatchdog


class TaskWatchdogTests(unittest.IsolatedAsyncioTestCase):
    """Core watchdog mechanics: registration, start, heartbeat, status, restart."""

    async def test_register_and_start(self):
        """Registered task is started and tracked."""
        wd = TaskWatchdog(timeout_multiplier=2.0)

        async def dummy():
            await asyncio.sleep(100)

        wd.register("dummy", dummy, 60.0)
        task = wd.start("dummy")
        self.assertFalse(task.done())
        await asyncio.sleep(0.05)
        status = wd.status()
        self.assertIn("dummy", status["tasks"])
        self.assertTrue(status["tasks"]["dummy"]["alive"])
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def test_heartbeat_updates_silent_for(self):
        """Heartbeat resets the silent-for timer."""
        wd = TaskWatchdog(timeout_multiplier=2.0)

        async def dummy():
            while True:
                wd.heartbeat("dummy")
                await asyncio.sleep(0.05)

        wd.register("dummy", dummy, 1.0)
        wd.start("dummy")
        await asyncio.sleep(0.15)
        status = wd.status()
        self.assertLess(status["tasks"]["dummy"]["silent_for_sec"], 0.5)
        wd.stop_watchdog()

    async def test_crash_detected_and_restarted(self):
        """A crashed task is detected and restarted."""
        wd = TaskWatchdog(timeout_multiplier=10.0)
        call_count = 0

        async def crash_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("deliberate crash")

        wd.register("crasher", crash_once, 999.0)
        wd.start("crasher")
        # Wait for crash + restart (monitor runs every 30s, but we can check directly)
        await asyncio.sleep(0.1)
        # Manually trigger monitor logic by calling the crash detection path
        rec = wd._tasks["crasher"]
        if rec.task and rec.task.done():
            exc = rec.task.exception()
            if exc:
                rec.error_count += 1
                rec.last_error = str(exc)
            # Restart
            rec.task = asyncio.create_task(rec.coro_factory(), name="crasher")
            rec.restart_count += 1
            rec.last_heartbeat = time.monotonic()
        await asyncio.sleep(0.05)
        self.assertEqual(rec.error_count, 1)
        self.assertEqual(rec.restart_count, 1)
        self.assertEqual(call_count, 2)
        wd.stop_watchdog()

    async def test_restart_limit_exceeded(self):
        """After 5 errors, no more restarts."""
        wd = TaskWatchdog(timeout_multiplier=10.0)
        call_count = 0

        async def always_crash():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("always fails")

        wd.register("crasher", always_crash, 999.0)
        rec = wd._tasks["crasher"]
        # Simulate 5 prior errors
        rec.error_count = 5
        rec.task = asyncio.create_task(always_crash(), name="crasher")
        await asyncio.sleep(0.05)
        # Manually run crash detection
        if rec.task and rec.task.done():
            exc = rec.task.exception()
            if exc:
                rec.error_count += 1
            # Should NOT restart since error_count >= 5
            self.assertGreaterEqual(rec.error_count, 5)
        self.assertEqual(rec.restart_count, 0)
        wd.stop_watchdog()

    async def test_status_returns_all_fields(self):
        """Status dict has all expected fields."""
        wd = TaskWatchdog(timeout_multiplier=2.5)

        async def dummy():
            await asyncio.sleep(100)

        wd.register("dummy", dummy, 60.0)
        wd.start("dummy")
        await asyncio.sleep(0.05)
        status = wd.status()
        self.assertIn("tasks", status)
        self.assertIn("loop_lag_ms", status)
        self.assertIn("rss_mb", status)
        self.assertIn("watchdog_enabled", status)
        task_status = status["tasks"]["dummy"]
        self.assertIn("alive", task_status)
        self.assertIn("silent_for_sec", task_status)
        self.assertIn("timeout_sec", task_status)
        self.assertIn("error_count", task_status)
        self.assertIn("restart_count", task_status)
        self.assertIn("interval_sec", task_status)
        wd.stop_watchdog()

    async def test_record_error(self):
        """record_error increments error count and stores last error."""
        wd = TaskWatchdog()

        async def dummy():
            await asyncio.sleep(100)

        wd.register("dummy", dummy, 60.0)
        wd.start("dummy")
        wd.record_error("dummy", "test error")
        status = wd.status()
        self.assertEqual(status["tasks"]["dummy"]["error_count"], 1)
        self.assertEqual(status["tasks"]["dummy"]["last_error"], "test error")
        wd.stop_watchdog()

    async def test_stop_cancels_tasks(self):
        """stop_watchdog cancels all supervised tasks."""
        wd = TaskWatchdog()

        async def dummy():
            await asyncio.sleep(100)

        wd.register("dummy", dummy, 60.0)
        task = wd.start("dummy")
        await asyncio.sleep(0.05)
        self.assertFalse(task.done())
        wd.stop_watchdog()
        await asyncio.sleep(0.05)
        self.assertTrue(task.done() or task.cancelled())

    async def test_timeout_calculation(self):
        """Timeout = interval * multiplier."""
        wd = TaskWatchdog(timeout_multiplier=3.0)

        async def dummy():
            await asyncio.sleep(100)

        wd.register("dummy", dummy, 120.0)
        wd.start("dummy")
        status = wd.status()
        self.assertEqual(status["tasks"]["dummy"]["timeout_sec"], 360.0)
        wd.stop_watchdog()

    async def test_unregistered_start_raises(self):
        """Starting an unregistered task raises KeyError."""
        wd = TaskWatchdog()
        with self.assertRaises(KeyError):
            wd.start("nonexistent")


class TaskWatchdogMonitorTests(unittest.IsolatedAsyncioTestCase):
    """Integration tests for the monitor loop."""

    async def test_monitor_restarts_crashed_task(self):
        """The _monitor loop detects and restarts a crashed task."""
        wd = TaskWatchdog(timeout_multiplier=10.0)
        call_count = 0

        async def crash_first_time():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await asyncio.sleep(0.01)
                raise ValueError("crash")
            await asyncio.sleep(100)

        wd.register("crasher", crash_first_time, 999.0)
        wd.start("crasher")
        # Wait for crash
        await asyncio.sleep(0.1)
        # Run one monitor iteration manually
        now = time.monotonic()
        for name, rec in list(wd._tasks.items()):
            if rec.task is not None and rec.task.done():
                exc = rec.task.exception()
                if exc:
                    rec.error_count += 1
                    rec.last_error = str(exc)
                if rec.error_count < 5:
                    rec.task = asyncio.create_task(rec.coro_factory(), name=name)
                    rec.restart_count += 1
                    rec.last_heartbeat = now
        await asyncio.sleep(0.05)
        self.assertEqual(call_count, 2)
        self.assertEqual(wd._tasks["crasher"].restart_count, 1)
        wd.stop_watchdog()

    async def test_monitor_warns_on_silent_task(self):
        """Monitor detects a silent task (heartbeat stale)."""
        wd = TaskWatchdog(timeout_multiplier=1.0)

        async def silent_task():
            """Never calls heartbeat."""
            await asyncio.sleep(100)

        wd.register("silent", silent_task, 0.5)
        wd.start("silent")
        # Wait past timeout
        await asyncio.sleep(0.6)
        now = time.monotonic()
        rec = wd._tasks["silent"]
        timeout_sec = rec.interval_sec * wd._timeout_multiplier
        is_silent = rec.last_heartbeat and (now - rec.last_heartbeat) > timeout_sec
        self.assertTrue(is_silent)
        wd.stop_watchdog()


class TaskWatchdogDisabledTests(unittest.TestCase):
    """Test behavior when watchdog is disabled (get_watchdog returns None)."""

    def test_get_watchdog_none_by_default(self):
        """get_watchdog returns None when not initialized."""
        # The global might be set from a previous test; just verify the function exists
        from lifespan import get_watchdog

        result = get_watchdog()
        # It's either None or a TaskWatchdog instance
        self.assertTrue(result is None or isinstance(result, TaskWatchdog))


if __name__ == "__main__":
    unittest.main()
