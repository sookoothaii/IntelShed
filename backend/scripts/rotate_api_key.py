#!/usr/bin/env python3
"""CLI helper — generate a new WORLDBASE_API_KEY and remind operator to update.

Usage (from backend/ with venv activated)::

    python scripts/rotate_api_key.py
    python scripts/rotate_api_key.py --length 48
    python scripts/rotate_api_key.py --update-env   # auto-update backend/.env

This is a **manual** tool. Automatic rotation is not implemented by design —
the operator decides when to rotate. For automated rotation, schedule this
script via Windows Task Scheduler or cron.

The generated key is a URL-safe base64 string (``secrets.token_urlsafe``).
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path


def generate_key(length: int = 32) -> str:
    """Generate a cryptographically secure API key."""
    return secrets.token_urlsafe(length)


def update_env_file(new_key: str) -> bool:
    """Best-effort: update WORLDBASE_API_KEY in backend/.env.

    Returns True if updated, False if file not found or key not present.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return False
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
        updated = False
        for i, line in enumerate(lines):
            if line.strip().startswith("WORLDBASE_API_KEY="):
                lines[i] = f"WORLDBASE_API_KEY={new_key}"
                updated = True
                break
        if updated:
            env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return updated
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a new WORLDBASE_API_KEY")
    parser.add_argument(
        "--length",
        type=int,
        default=32,
        help="Token length in bytes (default 32 → ~43 char URL-safe string)",
    )
    parser.add_argument(
        "--update-env",
        action="store_true",
        help="Auto-update backend/.env with the new key",
    )
    args = parser.parse_args()

    new_key = generate_key(args.length)

    print("=" * 60)
    print("WorldBase API Key Rotation")
    print("=" * 60)
    print()
    print("New API key:")
    print(f"  {new_key}")
    print()

    if args.update_env:
        if update_env_file(new_key):
            print("[OK] backend/.env updated with new key.")
        else:
            print("[WARN] Could not update backend/.env — update manually.")
    else:
        print("To activate this key:")
        print(f"  1. Update backend/.env:  WORLDBASE_API_KEY={new_key}")
        print(f"  2. Update frontend/.env: VITE_WORLDBASE_API_KEY={new_key}")
        print("  3. Restart the backend (start.ps1)")
        print("  4. Update Pi node tokens if using LAN sync")
        print()
        print("  Or re-run with --update-env to auto-update backend/.env")

    print()
    print("Note: The old key remains valid for 24h grace period if you use")
    print("POST /api/auth/rotate instead of this script (requires RBAC enabled).")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
