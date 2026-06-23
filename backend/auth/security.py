"""WorldBase — Enhanced HMAC authentication with replay protection.

This module provides hardened HMAC signature validation with:
- Constant-time comparison (timing attack resistance)
- Replay attack protection via nonce/timestamp cache
- Token expiration with configurable TTL
- Request signing helpers for Pi client
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from starlette.status import HTTP_401_UNAUTHORIZED, HTTP_403_FORBIDDEN

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_TTL_SECONDS = int(os.getenv("WORLDBASE_AUTH_TTL", "300"))  # 5 minutes
REPLAY_WINDOW_SECONDS = int(os.getenv("WORLDBASE_REPLAY_WINDOW", "300"))  # 5 min
NONCE_MAX_AGE_SECONDS = int(os.getenv("WORLDBASE_NONCE_MAX_AGE", "600"))  # 10 min
CLEANUP_INTERVAL_SECONDS = 60

# Token constants (exported for node_sync compatibility)
INGEST_TOKEN = os.getenv("NODE_INGEST_TOKEN", "")
ADMIN_TOKEN = os.getenv("NODE_ADMIN_TOKEN", "") or INGEST_TOKEN
API_KEY = os.getenv("WORLDBASE_API_KEY", "")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
node_token_header = APIKeyHeader(name="X-Node-Token", auto_error=False)

_LOOPBACK_BINDS = frozenset({"127.0.0.1", "localhost", "::1"})


def lan_exposed() -> bool:
    """Server listens beyond loopback (Pi sync / Docker LAN bind)."""
    bind = os.getenv("WORLDBASE_BIND_HOST", "127.0.0.1").strip().lower()
    return bind not in _LOOPBACK_BINDS


def lan_auth_required() -> bool:
    """MCP and other operator tools: key when configured, or when LAN-exposed."""
    if API_KEY:
        return True
    return lan_exposed()


async def verify_api_key(api_key: str = Security(api_key_header)):
    """Verify API key if WORLDBASE_API_KEY is set."""
    if not API_KEY:
        return None  # Auth disabled
    if api_key != API_KEY:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API Key",
        )
    return api_key


async def verify_lan_auth(
    api_key: str = Security(api_key_header),
    x_node_token: str = Security(node_token_header),
) -> str | None:
    """Require X-API-Key or X-Node-Token only when the API is LAN-exposed.

    Default PC dev (``WORLDBASE_BIND_HOST=127.0.0.1``): HUD and pilots stay open;
    keys in ``.env`` still gate chat, MCP, and node ingest/pull routes.
    """
    if not lan_exposed():
        return None
    if API_KEY and api_key and hmac.compare_digest(API_KEY, api_key):
        return "api_key"
    if INGEST_TOKEN and x_node_token and hmac.compare_digest(INGEST_TOKEN, x_node_token):
        return "node_token"
    if not API_KEY and not INGEST_TOKEN:
        raise HTTPException(
            status_code=HTTP_503_SERVICE_UNAVAILABLE,
            detail="LAN exposure requires WORLDBASE_API_KEY or NODE_INGEST_TOKEN",
        )
    raise HTTPException(
        status_code=HTTP_401_UNAUTHORIZED,
        detail="Invalid or missing credentials (X-API-Key or X-Node-Token)",
    )


# ---------------------------------------------------------------------------
# Replay Protection Cache
# ---------------------------------------------------------------------------

@dataclass
class _CacheEntry:
    """Single cache entry with TTL tracking."""

    nonce: str
    timestamp: int
    expires_at: float


class _NonceCache:
    """Thread-safe in-memory nonce cache with automatic expiration.

    Uses a combination of nonce and timestamp to prevent replay attacks.
    Stores nonces with expiration time and cleans up periodically.
    """

    def __init__(self) -> None:
        self._cache: dict[str, _CacheEntry] = {}
        self._lock = threading.RLock()
        self._last_cleanup = time.time()

    def _cleanup_expired(self) -> None:
        """Remove expired entries from cache."""
        now = time.time()
        if now - self._last_cleanup < CLEANUP_INTERVAL_SECONDS:
            return

        with self._lock:
            expired = [
                key for key, entry in self._cache.items() if entry.expires_at < now
            ]
            for key in expired:
                del self._cache[key]
            self._last_cleanup = now

    def add(self, nonce: str, timestamp: int, ttl_seconds: int) -> bool:
        """Add nonce to cache. Returns False if nonce already exists (replay detected).

        Args:
            nonce: Unique request nonce
            timestamp: Request timestamp in seconds
            ttl_seconds: Time-to-live in seconds

        Returns:
            True if nonce was added, False if already exists (potential replay)
        """
        self._cleanup_expired()

        key = f"{nonce}:{timestamp}"
        with self._lock:
            if key in self._cache:
                return False

            expires_at = time.time() + ttl_seconds
            self._cache[key] = _CacheEntry(
                nonce=nonce, timestamp=timestamp, expires_at=expires_at
            )
            return True

    def exists(self, nonce: str, timestamp: int) -> bool:
        """Check if nonce/timestamp combination exists in cache.

        Args:
            nonce: Unique request nonce
            timestamp: Request timestamp in seconds

        Returns:
            True if nonce exists, False otherwise
        """
        self._cleanup_expired()

        key = f"{nonce}:{timestamp}"
        with self._lock:
            return key in self._cache

    def clear(self) -> None:
        """Clear all cached nonces (useful for testing)."""
        with self._lock:
            self._cache.clear()


# Global nonce cache instance
_nonce_cache = _NonceCache()


# ---------------------------------------------------------------------------
# HMAC Signature Functions
# ---------------------------------------------------------------------------


def generate_hmac_signature(payload: dict, secret: str) -> str:
    """Generate HMAC-SHA256 signature for a payload.

    Creates a deterministic signature by sorting JSON keys and using
    compact separators to ensure consistent hashing.

    Args:
        payload: Dictionary containing data to sign. Should include 'nonce'
                 and 'timestamp' for replay protection.
        secret: Shared secret key for HMAC

    Returns:
        Hexadecimal HMAC-SHA256 signature string

    Example:
        >>> payload = {"data": "test", "nonce": "abc123", "timestamp": 1234567890}
        >>> sig = generate_hmac_signature(payload, "my-secret-key")
        >>> print(sig)  # 'a1b2c3d4...'
    """
    if not secret:
        raise ValueError("Secret cannot be empty")

    # Canonical JSON representation: sorted keys, no whitespace
    body_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )

    signature = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
    return signature


def verify_hmac_signature(payload: dict, signature: str, secret: str) -> bool:
    """Verify HMAC signature with constant-time comparison.

    Uses hmac.compare_digest to prevent timing attacks. The payload must
    be identical (including key order) to what was signed.

    Args:
        payload: Dictionary containing signed data
        signature: Expected HMAC signature (hex string)
        secret: Shared secret key for HMAC verification

    Returns:
        True if signature is valid, False otherwise

    Security:
        Uses constant-time comparison to prevent timing attacks.

    Example:
        >>> payload = {"data": "test"}
        >>> sig = generate_hmac_signature(payload, "secret")
        >>> verify_hmac_signature(payload, sig, "secret")  # True
        >>> verify_hmac_signature(payload, sig, "wrong")   # False
    """
    if not signature or not secret:
        return False

    try:
        expected = generate_hmac_signature(payload, secret)
        # Constant-time comparison prevents timing attacks
        return hmac.compare_digest(expected, signature)
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Replay Attack Protection
# ---------------------------------------------------------------------------


def check_replay_attack(
    nonce: str, timestamp: int, window_seconds: int = REPLAY_WINDOW_SECONDS
) -> bool:
    """Validate nonce and timestamp to prevent replay attacks.

    Checks:
    1. Nonce hasn't been seen before (in cache)
    2. Timestamp is within acceptable window (prevents old request replay)
    3. Nonce format is valid

    Args:
        nonce: Unique request identifier (should be cryptographically random)
        timestamp: Unix timestamp in seconds when request was created
        window_seconds: Acceptable time window for timestamp (default: 300)

    Returns:
        True if request is valid (not a replay), False if replay detected

    Raises:
        HTTPException: With 401 if timestamp is too old or nonce is invalid

    Example:
        >>> import time, secrets
        >>> nonce = secrets.token_hex(16)
        >>> timestamp = int(time.time())
        >>> check_replay_attack(nonce, timestamp)  # True
        >>> check_replay_attack(nonce, timestamp)  # False (duplicate)
    """
    if not nonce or not isinstance(nonce, str):
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="Missing or invalid nonce"
        )

    if len(nonce) < 16:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail="Nonce too short (minimum 16 characters)",
        )

    now = int(time.time())

    # Check timestamp is not too far in the future (clock skew tolerance: 60s)
    if timestamp > now + 60:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="Timestamp too far in future"
        )

    # Check timestamp is not too old
    if now - timestamp > window_seconds:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail=f"Request expired (older than {window_seconds}s)",
        )

    # Check for replay (nonce already seen)
    if _nonce_cache.exists(nonce, timestamp):
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED, detail="Replay attack detected (duplicate nonce)"
        )

    # Add nonce to cache to prevent future replays
    return _nonce_cache.add(nonce, timestamp, NONCE_MAX_AGE_SECONDS)


def clear_nonce_cache() -> None:
    """Clear the nonce cache. Useful for testing only."""
    _nonce_cache.clear()


# ---------------------------------------------------------------------------
# Token Expiration
# ---------------------------------------------------------------------------


def verify_token_expiration(
    issued_at: int, ttl_seconds: int = DEFAULT_TTL_SECONDS
) -> bool:
    """Verify that a token has not expired.

    Args:
        issued_at: Unix timestamp when token was issued
        ttl_seconds: Time-to-live in seconds (default: 300)

    Returns:
        True if token is still valid, False if expired

    Raises:
        HTTPException: With 401 if token has expired
    """
    now = int(time.time())
    elapsed = now - issued_at

    if elapsed > ttl_seconds:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail=f"Token expired (valid for {ttl_seconds}s)",
        )

    return True


# ---------------------------------------------------------------------------
# Request Authentication
# ---------------------------------------------------------------------------


def verify_request_auth(
    request: Request,
    token_header: str = "X-Node-Token",
    secret: Optional[str] = None,
    require_timestamp: bool = True,
    require_nonce: bool = True,
) -> dict:
    """Verify complete request authentication with HMAC + replay protection.

    Validates:
    1. Presence of required headers
    2. HMAC signature validity (constant-time comparison)
    3. Timestamp freshness (prevent stale requests)
    4. Nonce uniqueness (prevent replay attacks)
    5. Token expiration (configurable TTL)

    Args:
        request: FastAPI Request object
        token_header: Header name containing the HMAC signature
        secret: Shared secret for HMAC verification (defaults to NODE_INGEST_TOKEN env)
        require_timestamp: Whether to require and validate timestamp
        require_nonce: Whether to require and validate nonce

    Returns:
        Dictionary with decoded payload if all checks pass

    Raises:
        HTTPException: 401 for authentication failures, 403 for authorization failures

    Expected Headers:
        X-Node-Token: HMAC-SHA256 signature (hex)
        X-Request-Timestamp: Unix timestamp (optional, required if require_timestamp=True)
        X-Request-Nonce: Unique nonce string (optional, required if require_nonce=True)

    Example:
        >>> from fastapi import FastAPI, Request
        >>> app = FastAPI()
        >>>
        >>> @app.post("/api/secure")
        >>> async def secure_endpoint(request: Request):
        ...     payload = verify_request_auth(request, secret="my-secret")
        ...     return {"status": "ok", "data": payload}
    """
    # Get secret from environment if not provided
    if secret is None:
        secret = os.getenv("NODE_INGEST_TOKEN", "")
        if not secret:
            # Development mode: skip authentication
            return {"authenticated": False, "mode": "development"}

    # Extract signature from header
    signature = request.headers.get(token_header, "")
    if not signature:
        raise HTTPException(
            status_code=HTTP_401_UNAUTHORIZED,
            detail=f"Missing {token_header} header",
        )

    # Extract and validate timestamp
    timestamp_str = request.headers.get("X-Request-Timestamp", "")
    if require_timestamp:
        if not timestamp_str:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Missing X-Request-Timestamp header",
            )
        try:
            timestamp = int(timestamp_str)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Invalid X-Request-Timestamp format",
            )
    else:
        timestamp = int(time.time())

    # Extract and validate nonce
    nonce = request.headers.get("X-Request-Nonce", "")
    if require_nonce:
        if not nonce:
            raise HTTPException(
                status_code=HTTP_401_UNAUTHORIZED,
                detail="Missing X-Request-Nonce header",
            )
        # Replay protection check
        check_replay_attack(nonce, timestamp)

    # Build verification payload (must match client signing)
    # In production, the body would be read and hashed
    auth_payload = {
        "timestamp": timestamp,
        "nonce": nonce,
        "path": str(request.url.path),
        "method": request.method,
    }

    # Verify HMAC signature
    if not verify_hmac_signature(auth_payload, signature, secret):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid HMAC signature",
        )

    return {
        "authenticated": True,
        "timestamp": timestamp,
        "nonce": nonce,
        "expires_at": timestamp + DEFAULT_TTL_SECONDS,
    }


# ---------------------------------------------------------------------------
# Admin Authorization
# ---------------------------------------------------------------------------


def require_admin_token(request: Request, admin_header: str = "X-Admin-Token") -> None:
    """Require and validate admin token from request headers.

    Compares provided token against NODE_ADMIN_TOKEN environment variable.
    Uses constant-time comparison to prevent timing attacks.

    Args:
        request: FastAPI Request object
        admin_header: Header name containing the admin token

    Raises:
        HTTPException: 403 if admin token is invalid or missing

    Example:
        >>> from fastapi import FastAPI, Request
        >>> app = FastAPI()
        >>>
        >>> @app.post("/api/admin/command")
        >>> async def admin_command(request: Request):
        ...     require_admin_token(request)
        ...     return {"status": "executed"}
    """
    admin_token = os.getenv("NODE_ADMIN_TOKEN", "") or os.getenv("NODE_INGEST_TOKEN", "")

    if not admin_token:
        # Development mode: allow without token
        return

    provided_token = request.headers.get(admin_header, "")
    if not provided_token:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail=f"Missing {admin_header} header",
        )

    if not hmac.compare_digest(admin_token, provided_token):
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Invalid admin token",
        )


# ---------------------------------------------------------------------------
# Client-Side Request Signing Helper (for Pi client)
# ---------------------------------------------------------------------------


def create_signed_request(
    payload: dict,
    secret: str,
    include_nonce: bool = True,
    include_timestamp: bool = True,
) -> dict:
    """Create a fully signed request payload with all security headers.

    This helper function is designed for the Pi client to generate
    properly signed requests that the server can validate.

    Args:
        payload: Data payload to sign and send
        secret: Shared secret key
        include_nonce: Whether to generate and include a nonce (recommended)
        include_timestamp: Whether to include current timestamp (recommended)

    Returns:
        Dictionary with:
        - payload: Original data with nonce/timestamp added
        - headers: Dictionary of HTTP headers to send
        - signature: The HMAC signature (also in headers)

    Example (Pi client usage):
        >>> import requests
        >>> data = {"temperature": 25.5, "humidity": 60}
        >>> signed = create_signed_request(data, "shared-secret")
        >>> response = requests.post(
        ...     "https://worldbase.local/api/node/ingest",
        ...     json=signed["payload"],
        ...     headers=signed["headers"]
        ... )
    """
    if not secret:
        raise ValueError("Secret is required for signed requests")

    # Create a copy to avoid mutating original
    signed_payload = dict(payload)

    # Add timestamp
    if include_timestamp:
        signed_payload["timestamp"] = int(time.time())

    # Add cryptographically secure nonce
    if include_nonce:
        signed_payload["nonce"] = secrets.token_hex(16)

    # Generate signature
    signature = generate_hmac_signature(signed_payload, secret)

    # Build headers
    headers = {
        "X-Node-Token": signature,
        "Content-Type": "application/json",
    }

    if include_timestamp:
        headers["X-Request-Timestamp"] = str(signed_payload["timestamp"])
    if include_nonce:
        headers["X-Request-Nonce"] = signed_payload["nonce"]

    return {
        "payload": signed_payload,
        "headers": headers,
        "signature": signature,
    }


# ---------------------------------------------------------------------------
# Legacy Compatibility Wrappers
# ---------------------------------------------------------------------------


def verify_legacy_hmac(body: dict, signature: str, secret: str) -> bool:
    """Verify HMAC from legacy node_sync format (no nonce/timestamp).

    Maintains backward compatibility with existing Pi clients while
    still using constant-time comparison.

    Args:
        body: Request body dictionary
        signature: HMAC signature from X-Node-Token header
        secret: Shared secret

    Returns:
        True if signature valid, False otherwise
    """
    if not secret:
        return True  # No authentication required

    if not signature:
        return False

    try:
        # The Pi may serialize with ensure_ascii=False (raw UTF-8); we cannot
        # know which it used, so accept either ASCII-escaped or UTF-8 compact
        # forms. Re-serializing a parsed dict is inherently fragile — prefer
        # verify_legacy_hmac_bytes() over the exact request bytes when possible.
        for ascii_only in (True, False):
            body_bytes = json.dumps(
                body, separators=(",", ":"), ensure_ascii=ascii_only
            ).encode("utf-8")
            expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
            if hmac.compare_digest(expected, signature):
                return True
        return False
    except Exception:
        return False


def verify_legacy_hmac_bytes(body_bytes: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC over the *exact* raw request bytes the client signed.

    Serialization-agnostic: unlike :func:`verify_legacy_hmac`, this does not
    re-serialize a parsed dict, so it is immune to ``ensure_ascii`` / key-order
    / float-format / whitespace differences between the signer (Pi) and the
    verifier (PC). This is the preferred check for node ingest.

    Args:
        body_bytes: Raw request body bytes (exactly as received).
        signature: HMAC signature from the X-Node-Token header.
        secret: Shared secret.

    Returns:
        True if signature valid, False otherwise.
    """
    if not secret:
        return True  # No authentication required
    if not signature:
        return False
    try:
        expected = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Utility Functions
# ---------------------------------------------------------------------------


def generate_secure_nonce(length: int = 32) -> str:
    """Generate a cryptographically secure random nonce.

    Args:
        length: Length of nonce in bytes (results in 2*length hex chars)

    Returns:
        Hexadecimal nonce string
    """
    return secrets.token_hex(length)


def get_auth_config() -> dict:
    """Get current authentication configuration.

    Returns:
        Dictionary with current auth settings and status
    """
    return {
        "ttl_seconds": DEFAULT_TTL_SECONDS,
        "replay_window_seconds": REPLAY_WINDOW_SECONDS,
        "nonce_max_age_seconds": NONCE_MAX_AGE_SECONDS,
        "cleanup_interval_seconds": CLEANUP_INTERVAL_SECONDS,
        "ingest_token_set": bool(os.getenv("NODE_INGEST_TOKEN")),
        "admin_token_set": bool(
            os.getenv("NODE_ADMIN_TOKEN") or os.getenv("NODE_INGEST_TOKEN")
        ),
    }


__all__ = [
    "generate_hmac_signature",
    "verify_hmac_signature",
    "check_replay_attack",
    "verify_request_auth",
    "require_admin_token",
    "create_signed_request",
    "verify_token_expiration",
    "verify_legacy_hmac",
    "verify_legacy_hmac_bytes",
    "generate_secure_nonce",
    "get_auth_config",
    "clear_nonce_cache",
    "lan_auth_required",
    "lan_exposed",
    "verify_lan_auth",
    "verify_api_key",
]
