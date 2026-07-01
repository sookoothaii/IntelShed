"""Runtime credential store — persists operator-set API keys to a JSON file.

Keys are stored at ``backend/data/credentials.json`` and loaded into
``os.environ`` at startup so all existing env-based provider checks work
unchanged.  Secret values are never returned by the API — only masked
indicators.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_STORE_PATH = Path(os.getenv("WORLDBASE_DATA_DIR", "data")) / "credentials.json"

_MASK = "********"


def _store_path() -> Path:
    """Return the credential store path (re-reads env each call for testability)."""
    return Path(os.getenv("WORLDBASE_DATA_DIR", "data")) / "credentials.json"


def _load() -> dict[str, str]:
    p = _store_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, str]) -> None:
    p = _store_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, sort_keys=True), "utf-8")


def apply_credentials_to_env() -> int:
    """Load stored credentials into os.environ at startup.

    Returns the number of keys applied.
    """
    data = _load()
    for key, val in data.items():
        if val and not os.getenv(key):
            os.environ[key] = val
    return len(data)


def set_credential(env_var: str, value: str) -> dict[str, Any]:
    """Persist a credential and apply it to the current process env."""
    data = _load()
    data[env_var] = value
    _save(data)
    os.environ[env_var] = value
    return {"env_var": env_var, "set": True}


def delete_credential(env_var: str) -> dict[str, Any]:
    """Remove a credential from the store and unset it in the current env."""
    data = _load()
    existed = env_var in data
    if existed:
        del data[env_var]
        _save(data)
    os.environ.pop(env_var, None)
    return {"env_var": env_var, "deleted": existed}


def list_credentials() -> list[dict[str, Any]]:
    """Return all stored credentials with masked values."""
    data = _load()
    return [
        {"env_var": k, "masked": _MASK, "has_value": bool(v)}
        for k, v in sorted(data.items())
    ]
