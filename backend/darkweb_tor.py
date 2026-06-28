"""Tor control-port OPSEC helper (Phase 3.2) — exit-node rotation.

Isolates all Tor *control-port* logic from ``darkweb_bridge``. Sends
``SIGNAL NEWNYM`` to regenerate Tor circuits (new exit node) before a batch of
Tor-engine requests, respecting Tor's mandatory 10-second minimum between
NEWNYM signals. Optionally checks the resolved exit-node country against a
jurisdiction blocklist and rotates again if it is blocked.

All operations are **opt-in** and **fail-soft**: if the feature is disabled,
the ``stem`` library is missing, or the control port is unreachable, the helper
returns a status dict and never raises into the caller.

Env:
  WORLDBASE_DARKWEB_TOR_ROTATE_IDENTITY=0          (default off, opt-in)
  WORLDBASE_DARKWEB_TOR_CONTROL_HOST=127.0.0.1:9051
  WORLDBASE_DARKWEB_TOR_CONTROL_PASSWORD=          (optional control auth)
  WORLDBASE_DARKWEB_EXIT_BLOCKLIST=CN,RU,IR        (ISO country codes)

Dependency: ``stem`` (lazy-imported; rotation is a no-op when not installed).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from config import get_config

# Tor enforces a minimum interval between NEWNYM signals. Exposed as a module
# constant so tests can monkeypatch it without waiting in real time.
NEWNYM_MIN_INTERVAL_SEC: float = 10.0


def rotation_enabled() -> bool:
    return bool(get_config().darkweb_tor_rotate_identity)


def _control_endpoint() -> tuple[str, int]:
    """Parse ``host:port`` from config, defaulting to 127.0.0.1:9051."""
    raw = (get_config().darkweb_tor_control_host or "127.0.0.1:9051").strip()
    host, _, port = raw.partition(":")
    host = host or "127.0.0.1"
    try:
        port_num = int(port) if port else 9051
    except ValueError:
        port_num = 9051
    return host, port_num


def _control_password() -> str | None:
    pw = (get_config().darkweb_tor_control_password or "").strip()
    return pw or None


def exit_blocklist() -> set[str]:
    """Return the set of uppercased ISO country codes to avoid as exit nodes."""
    raw = get_config().darkweb_exit_blocklist or ""
    return {c.strip().upper() for c in raw.split(",") if c.strip()}


def _import_stem() -> Any | None:
    """Lazy-import stem.control. Returns the module or None if unavailable."""
    try:
        from stem import control  # type: ignore

        return control
    except Exception:
        return None


class TorRotator:
    """Stateful Tor control-port rotator with NEWNYM rate-limiting.

    A single instance is shared module-wide so the 10s rate-limit is enforced
    across all callers. All blocking ``stem`` calls run in a worker thread to
    avoid blocking the event loop.
    """

    def __init__(self) -> None:
        self._last_signal_ts: float = 0.0
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        """Reset the rate-limit clock (test helper)."""
        self._last_signal_ts = 0.0

    async def rotate(
        self,
        *,
        reason: str = "",
        check_exit: bool = True,
        max_attempts: int = 3,
        wait: bool = True,
    ) -> dict[str, Any]:
        """Send SIGNAL NEWNYM, respecting the 10s rate-limit.

        Args:
            reason: Free-text reason recorded in the result (for audit/logs).
            check_exit: Re-rotate if the exit-node country is blocklisted.
            max_attempts: Max NEWNYM signals when avoiding blocked exits.
            wait: When True, sleep out the remaining rate-limit window;
                  when False, skip rotation and report ``rate_limited``.

        Returns:
            A status dict; never raises.
        """
        result: dict[str, Any] = {
            "rotated": False,
            "reason": reason,
            "attempts": 0,
            "exit_country": None,
            "blocklisted": False,
            "error": None,
        }

        if not rotation_enabled():
            result["error"] = "disabled"
            return result

        control = _import_stem()
        if control is None:
            result["error"] = "stem not installed"
            return result

        async with self._lock:
            blocklist = exit_blocklist()
            attempts = max(1, int(max_attempts))
            try:
                for _ in range(attempts):
                    await self._respect_rate_limit(wait=wait, result=result)
                    if result["error"] == "rate_limited":
                        return result

                    country = await asyncio.to_thread(
                        self._signal_and_inspect, control, check_exit
                    )
                    self._last_signal_ts = time.monotonic()
                    result["rotated"] = True
                    result["attempts"] += 1
                    result["exit_country"] = country

                    if not (check_exit and country and country in blocklist):
                        result["blocklisted"] = False
                        return result
                    # Exit node is in a blocked jurisdiction — rotate again.
                    result["blocklisted"] = True
                return result
            except Exception as exc:  # fail-soft
                result["error"] = str(exc)
                return result

    async def _respect_rate_limit(self, *, wait: bool, result: dict[str, Any]) -> None:
        elapsed = time.monotonic() - self._last_signal_ts
        remaining = NEWNYM_MIN_INTERVAL_SEC - elapsed
        if self._last_signal_ts <= 0 or remaining <= 0:
            return
        if not wait:
            result["error"] = "rate_limited"
            return
        await asyncio.sleep(remaining)

    def _signal_and_inspect(self, control: Any, check_exit: bool) -> str | None:
        """Blocking: connect, authenticate, NEWNYM, optionally read exit country.

        Runs in a worker thread. Returns the exit-node ISO country code (upper)
        or None when it cannot be determined.
        """
        host, port = _control_endpoint()
        password = _control_password()
        with control.Controller.from_port(address=host, port=port) as controller:
            controller.authenticate(password=password)
            from stem import Signal  # type: ignore

            controller.signal(Signal.NEWNYM)
            if not check_exit:
                return None
            return self._exit_country(controller)

    @staticmethod
    def _exit_country(controller: Any) -> str | None:
        """Best-effort: resolve the current circuit's exit-node country.

        Uses Tor's GeoIP via ``GETINFO ip-to-country/<ip>``. Fail-soft: returns
        None on any error or when no built circuit is available.
        """
        try:
            for circ in controller.get_circuits():
                if getattr(circ, "status", None) != "BUILT" or not circ.path:
                    continue
                exit_fp = circ.path[-1][0]
                desc = controller.get_network_status(exit_fp)
                ip = getattr(desc, "address", None)
                if not ip:
                    continue
                country = controller.get_info(f"ip-to-country/{ip}")
                if country and country not in ("??", ""):
                    return country.strip().upper()
        except Exception:
            return None
        return None


_ROTATOR = TorRotator()


async def rotate_identity(
    *,
    reason: str = "",
    check_exit: bool = True,
    max_attempts: int = 3,
    wait: bool = True,
) -> dict[str, Any]:
    """Module-level convenience wrapper around the shared :class:`TorRotator`."""
    return await _ROTATOR.rotate(
        reason=reason,
        check_exit=check_exit,
        max_attempts=max_attempts,
        wait=wait,
    )


def reset_rate_limit() -> None:
    """Reset the shared rotator's rate-limit clock (test helper)."""
    _ROTATOR.reset()


def status() -> dict[str, Any]:
    """Return current rotation configuration (no secrets)."""
    host, port = _control_endpoint()
    return {
        "enabled": rotation_enabled(),
        "stem_available": _import_stem() is not None,
        "control_host": f"{host}:{port}",
        "control_password_set": _control_password() is not None,
        "exit_blocklist": sorted(exit_blocklist()),
        "newnym_min_interval_sec": NEWNYM_MIN_INTERVAL_SEC,
    }
