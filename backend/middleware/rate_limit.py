"""
Rate limiting middleware for WorldBase backend.

Two layers:
1. **slowapi** per-endpoint decorators (fixed-window, Redis or in-memory).
   Applied via ``@rate_limit_node_ingest()`` etc. on specific routes.
2. **SlidingWindowLimiter** — global middleware that applies a per-IP sliding
   window to *all* requests.  API-key requests and ``/api/health/*`` are exempt.
   Controlled by ``WORLDBASE_RATE_LIMIT=1`` (default on) and
   ``WORLDBASE_RATE_LIMIT_RPM=60`` (default).
"""

import logging
import os
import time
from collections import defaultdict
from typing import Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

_log = logging.getLogger("worldbase.rate_limit")


# =============================================================================
# Configuration via Environment Variables
# =============================================================================

REDIS_URL = os.getenv("RATE_LIMIT_REDIS_URL", None)
RATE_LIMIT_STORAGE = os.getenv("RATE_LIMIT_STORAGE", "memory")  # "memory" or "redis"
# Consistent key namespace (worldbase:ratelimit:…) — avoids collisions if Redis is shared.
RATE_LIMIT_KEY_PREFIX = os.getenv("RATE_LIMIT_KEY_PREFIX", "worldbase:ratelimit")
RATE_LIMIT_REDIS_CONNECT_TIMEOUT = float(
    os.getenv("RATE_LIMIT_REDIS_CONNECT_TIMEOUT", "2")
)
RATE_LIMIT_REDIS_SOCKET_TIMEOUT = float(
    os.getenv("RATE_LIMIT_REDIS_SOCKET_TIMEOUT", "2")
)
RATE_LIMIT_REDIS_MAX_CONNECTIONS = int(
    os.getenv("RATE_LIMIT_REDIS_MAX_CONNECTIONS", "10")
)

# Rate limit strings (format: "count/per unit")
RATE_LIMIT_NODE_INGEST = os.getenv("RATE_LIMIT_NODE_INGEST", "100/minute")
RATE_LIMIT_NODE_PULL = os.getenv("RATE_LIMIT_NODE_PULL", "20/minute")
RATE_LIMIT_NODE_COMMAND = os.getenv("RATE_LIMIT_NODE_COMMAND", "10/minute")
RATE_LIMIT_GENERAL = os.getenv("RATE_LIMIT_GENERAL", "1000/hour")


# =============================================================================
# Custom Key Functions
# =============================================================================


def get_node_id_from_payload(request: Request) -> str:
    """
    Extract node_id from request payload for ingest endpoints.
    Falls back to remote IP if node_id cannot be extracted.
    """
    try:
        # Try to get node_id from request state (set by auth middleware)
        node_id = getattr(request.state, "node_id", None)
        if node_id:
            return str(node_id)

        # Try to extract from query parameters
        node_id = request.query_params.get("node_id")
        if node_id:
            return str(node_id)

        # Try to extract from path parameters
        node_id = request.path_params.get("node_id")
        if node_id:
            return str(node_id)

    except Exception:
        pass

    # Fallback to IP-based identification
    return get_remote_address(request)


def get_ip_with_forwarding(request: Request) -> str:
    """
    Get client IP considering X-Forwarded-For header.
    Uses X-Forwarded-For first, falls back to remote address.
    """
    # Check X-Forwarded-For header (common for proxies/load balancers)
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs, use the first (client)
        client_ip = forwarded_for.split(",")[0].strip()
        return client_ip

    # Check X-Real-IP header (alternative proxy header)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fallback to direct remote address
    return get_remote_address(request)


def get_admin_key(request: Request) -> str:
    """
    Generate rate limit key for admin endpoints.
    Combines admin token hash with IP for granular limiting.
    """
    ip = get_ip_with_forwarding(request)

    # Get admin token from header
    admin_token = request.headers.get("X-Admin-Token", "")

    # If no token, rate limit by IP only
    if not admin_token:
        return f"admin:no_token:{ip}"

    # Use a hash of the token (first 16 chars) combined with IP
    # This prevents exact token exposure in rate limit keys
    token_hash = hash(admin_token) & 0xFFFFFFFF
    return f"admin:{token_hash}:{ip}"


def get_combined_key(request: Request) -> str:
    """
    Combined key function that checks for node_id, admin token, or falls back to IP.
    Useful for endpoints that can be accessed by different client types.
    """
    # Check if it's a node request
    node_id = getattr(request.state, "node_id", None)
    if node_id:
        return f"node:{node_id}"

    # Check if it's an admin request
    admin_token = request.headers.get("X-Admin-Token")
    if admin_token:
        token_hash = hash(admin_token) & 0xFFFFFFFF
        return f"admin:{token_hash}"

    # Default to IP-based
    return f"ip:{get_ip_with_forwarding(request)}"


# =============================================================================
# Limiter Setup
# =============================================================================


def _redis_storage_options() -> dict:
    """Redis client options: short timeouts + pooled connections (fail fast, no blocking)."""
    return {
        "socket_connect_timeout": RATE_LIMIT_REDIS_CONNECT_TIMEOUT,
        "socket_timeout": RATE_LIMIT_REDIS_SOCKET_TIMEOUT,
        "max_connections": RATE_LIMIT_REDIS_MAX_CONNECTIONS,
    }


def _limiter_common_kwargs() -> dict:
    """Shared limiter settings for memory and Redis backends."""
    prefix = RATE_LIMIT_KEY_PREFIX.rstrip(":")
    return {
        "key_func": get_ip_with_forwarding,
        "default_limits": [RATE_LIMIT_GENERAL],
        "strategy": "fixed-window",
        "key_prefix": f"{prefix}:",
        # Keep Pi/chat limits active when Redis blips (in-memory fallback inherits limits).
        "in_memory_fallback": [RATE_LIMIT_GENERAL],
        "in_memory_fallback_enabled": True,
    }


def create_limiter() -> Limiter:
    """
    Create and configure the slowapi limiter instance.

    Uses Redis if RATE_LIMIT_STORAGE=redis and REDIS_URL is set,
    otherwise falls back to in-memory storage.
    """
    if RATE_LIMIT_STORAGE == "redis" and REDIS_URL:
        try:
            return Limiter(
                **_limiter_common_kwargs(),
                storage_uri=REDIS_URL,
                storage_options=_redis_storage_options(),
            )
        except Exception as exc:
            print(
                f"[RATE_LIMIT] Redis backend unavailable ({exc!s:.200}) — using in-memory fallback.",
                flush=True,
            )
    return Limiter(**_limiter_common_kwargs())


# Global limiter instance
limiter = create_limiter()


# =============================================================================
# Custom Exception Handler
# =============================================================================


def custom_rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors.

    Returns a 429 status with JSON error body and Retry-After header.
    """
    # Get retry after from the exception
    retry_after = getattr(exc, "retry_after", 60)

    # Create detailed error response
    error_response = {
        "error": {
            "code": "RATE_LIMIT_EXCEEDED",
            "message": "Rate limit exceeded. Please slow down your requests.",
            "details": {
                "retry_after_seconds": retry_after,
                "retry_after": f"{retry_after}s",
                "limit": exc.limit if hasattr(exc, "limit") else "unknown",
            },
            "suggestion": "Reduce request frequency or contact support for higher limits.",
        }
    }

    response = JSONResponse(
        status_code=429,
        content=error_response,
    )

    # Add standard Retry-After header
    response.headers["Retry-After"] = str(retry_after)

    # Add rate limit info headers
    response.headers["X-RateLimit-Limit"] = str(getattr(exc, "limit", "unknown"))
    response.headers["X-RateLimit-Remaining"] = "0"

    return response


# =============================================================================
# Rate Limit Decorators
# =============================================================================


def rate_limit_node_ingest() -> Callable:
    """
    Rate limit decorator for node ingest endpoints.

    Limit: 100 requests per minute per node
    Key: Extracted from node_id in payload/query/path

    Example usage:
        @app.post("/api/node/ingest")
        @rate_limit_node_ingest()
        async def ingest_data(request: Request):
            pass
    """
    return limiter.limit(RATE_LIMIT_NODE_INGEST, key_func=get_node_id_from_payload)


def rate_limit_node_pull() -> Callable:
    """
    Rate limit decorator for node pull endpoints.

    Limit: 20 requests per minute per node
    Key: Extracted from node_id in payload/query/path

    Example usage:
        @app.get("/api/node/pull")
        @rate_limit_node_pull()
        async def pull_data(request: Request):
            pass
    """
    return limiter.limit(RATE_LIMIT_NODE_PULL, key_func=get_node_id_from_payload)


def rate_limit_node_command() -> Callable:
    """
    Rate limit decorator for node command endpoints (admin only).

    Limit: 10 requests per minute per admin token/IP combo
    Key: Combined admin token hash + IP

    Example usage:
        @app.post("/api/node/command")
        @rate_limit_node_command()
        async def send_command(request: Request):
            pass
    """
    return limiter.limit(RATE_LIMIT_NODE_COMMAND, key_func=get_admin_key)


def rate_limit_general() -> Callable:
    """
    General rate limit decorator for API endpoints.

    Limit: 1000 requests per hour per IP
    Key: IP address (respects X-Forwarded-For)

    Example usage:
        @app.get("/api/general/endpoint")
        @rate_limit_general()
        async def general_endpoint(request: Request):
            pass
    """
    return limiter.limit(RATE_LIMIT_GENERAL, key_func=get_ip_with_forwarding)


def rate_limit_custom(
    limit_string: str, key_func: Optional[Callable] = None
) -> Callable:
    """
    Create a custom rate limit decorator with specified parameters.

    Args:
        limit_string: Rate limit in format "count/per unit" (e.g., "100/minute")
        key_func: Optional custom key function. Defaults to IP-based.

    Example usage:
        @app.post("/api/custom")
        @rate_limit_custom("50/minute", key_func=get_node_id_from_payload)
        async def custom_endpoint(request: Request):
            pass
    """
    key = key_func or get_ip_with_forwarding
    return limiter.limit(limit_string, key_func=key)


# =============================================================================
# Integration Helper for main.py
# =============================================================================


def setup_rate_limiting(app) -> None:
    """
    Setup rate limiting for a FastAPI application.

    This function integrates slowapi with the FastAPI app and configures
    the custom exception handler for rate limit exceeded errors.

    Args:
        app: FastAPI application instance

    Example in main.py:
        from fastapi import FastAPI
        from middleware.rate_limit import setup_rate_limiting, limiter

        app = FastAPI()

        # Setup rate limiting
        setup_rate_limiting(app)

        # Add the limiter instance to app state for access in routes
        app.state.limiter = limiter
    """
    # Add limiter to app state for access in routes if needed
    app.state.limiter = limiter

    # Add custom exception handler for RateLimitExceeded
    app.add_exception_handler(RateLimitExceeded, custom_rate_limit_exceeded_handler)

    # Install global sliding-window middleware (WORLDBASE_RATE_LIMIT=1, default on)
    setup_sliding_window_middleware(app)

    # Add default rate limit headers to all responses (optional)
    @app.middleware("http")
    async def add_rate_limit_headers(request: Request, call_next):
        response = await call_next(request)

        # Add rate limit info to headers if available in request state
        if hasattr(request.state, "view_rate_limit"):
            limit_info = request.state.view_rate_limit
            if isinstance(limit_info, dict):
                response.headers["X-RateLimit-Limit"] = str(limit_info.get("limit", ""))
                response.headers["X-RateLimit-Remaining"] = str(
                    limit_info.get("remaining", "")
                )
                response.headers["X-RateLimit-Reset"] = str(limit_info.get("reset", ""))

        return response


# =============================================================================
# Additional Utility Functions
# =============================================================================


def get_limiter_instance() -> Limiter:
    """
    Get the global limiter instance.

    Returns:
        The configured Limiter instance
    """
    return limiter


def get_rate_limit_backend_status() -> dict:
    """
    Report active rate-limit storage backend (memory vs Redis) for health/trust probes.
    """
    backend = "redis" if RATE_LIMIT_STORAGE == "redis" and REDIS_URL else "memory"
    status = {
        "backend": backend,
        "key_prefix": f"{RATE_LIMIT_KEY_PREFIX.rstrip(':')}:",
        "redis_configured": bool(REDIS_URL),
        "redis_reachable": None,
    }
    if backend != "redis" or not REDIS_URL:
        return status
    try:
        from limits.storage import storage_from_string

        storage = storage_from_string(REDIS_URL, **_redis_storage_options())
        storage.storage.ping()
        status["redis_reachable"] = True
    except Exception as exc:
        status["redis_reachable"] = False
        status["redis_error"] = str(exc)[:200]
    return status


def reset_rate_limit(key: str) -> bool:
    """
    Reset rate limit for a specific key.

    Note: This only works with certain storage backends and should be
    used with caution, primarily for administrative purposes.

    Args:
        key: The rate limit key to reset

    Returns:
        True if successful, False otherwise
    """
    try:
        if hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
            limiter._storage.reset(key)
            return True
        return False
    except Exception:
        return False


def check_rate_limit_status(
    request: Request, limit: str, key_func: Optional[Callable] = None
) -> dict:
    """
    Check current rate limit status for a request without consuming a limit.

    Args:
        request: FastAPI request object
        limit: Rate limit string (e.g., "100/minute")
        key_func: Optional key function

    Returns:
        Dictionary with limit status information
    """
    key_func = key_func or get_ip_with_forwarding
    key = key_func(request)

    # This is a placeholder - actual implementation depends on storage backend
    return {
        "key": key,
        "limit": limit,
        "status": "active",
    }


# =============================================================================
# Sliding Window Rate Limiter (global middleware)
# =============================================================================


class SlidingWindowLimiter:
    """Sliding-window rate limiter with Redis ZSET or in-memory deque fallback.

    Uses a sliding window of *window_seconds* seconds.  Each request appends
    a timestamp to a sorted set (Redis) or deque (memory).  Before adding,
    entries older than the window are pruned.  If the remaining count >= limit,
    the request is rejected with 429.

    Per-endpoint overrides can be configured via the *endpoint_overrides* dict
    mapping path prefixes to (rpm, window_seconds) tuples.
    """

    def __init__(
        self,
        rpm: int = 60,
        window_seconds: float = 60.0,
        endpoint_overrides: dict[str, tuple[int, float]] | None = None,
    ) -> None:
        self.rpm = rpm
        self.window_seconds = window_seconds
        self.endpoint_overrides = endpoint_overrides or {}
        self._redis = None
        self._memory: dict[str, list[float]] = defaultdict(list)
        self._init_redis()

    def _init_redis(self) -> None:
        """Try to connect to Redis for distributed sliding window."""
        if RATE_LIMIT_STORAGE == "redis" and REDIS_URL:
            try:
                import redis

                self._redis = redis.from_url(
                    REDIS_URL,
                    socket_connect_timeout=RATE_LIMIT_REDIS_CONNECT_TIMEOUT,
                    socket_timeout=RATE_LIMIT_REDIS_SOCKET_TIMEOUT,
                    max_connections=RATE_LIMIT_REDIS_MAX_CONNECTIONS,
                    decode_responses=True,
                )
                self._redis.ping()
                _log.info("sliding_window_redis_connected url=%s", REDIS_URL)
            except Exception as exc:
                _log.warning(
                    "sliding_window_redis_unavailable falling back to memory: %s",
                    exc,
                )
                self._redis = None

    def _get_limit_for_path(self, path: str) -> tuple[int, float]:
        """Return (rpm, window_seconds) for a given path, checking overrides."""
        for prefix, (rpm, window) in self.endpoint_overrides.items():
            if path.startswith(prefix):
                return rpm, window
        return self.rpm, self.window_seconds

    def _is_exempt(self, request: Request) -> bool:
        """Check if request is exempt from sliding-window limiting."""
        # Health endpoints
        path = request.url.path
        if path.startswith("/api/health"):
            return True
        # API-key authenticated requests
        api_key = request.headers.get("X-API-Key", "")
        if api_key and api_key == os.getenv("WORLDBASE_API_KEY", ""):
            return True
        # Node token authenticated requests (Pi sync)
        node_token = request.headers.get("X-Node-Token", "")
        if node_token and node_token == os.getenv("NODE_INGEST_TOKEN", ""):
            return True
        return False

    def _check_redis(
        self, key: str, rpm: int, window: float, now: float
    ) -> tuple[bool, int]:
        """Redis ZSET sliding window. Returns (allowed, remaining)."""
        redis_key = f"{RATE_LIMIT_KEY_PREFIX}:sw:{key}"
        member = f"{now}"
        pipe = self._redis.pipeline()
        pipe.zremrangebyscore(redis_key, 0, now - window)
        pipe.zcard(redis_key)
        pipe.zadd(redis_key, {member: now})
        pipe.expire(redis_key, int(window) + 1)
        results = pipe.execute()
        count = results[1]
        if count >= rpm:
            # Revert the zadd we just did
            self._redis.zrem(redis_key, member)
            return False, 0
        return True, rpm - count - 1

    def _check_memory(
        self, key: str, rpm: int, window: float, now: float
    ) -> tuple[bool, int]:
        """In-memory deque sliding window. Returns (allowed, remaining)."""
        entries = self._memory[key]
        cutoff = now - window
        # Prune old entries
        while entries and entries[0] < cutoff:
            entries.pop(0)
        if len(entries) >= rpm:
            return False, 0
        entries.append(now)
        return True, rpm - len(entries)

    def check(self, request: Request) -> tuple[bool, int, int, int]:
        """Check if request is allowed.

        Returns:
            (allowed, remaining, limit, retry_after_seconds)
        """
        if self._is_exempt(request):
            return True, -1, -1, 0

        path = request.url.path
        rpm, window = self._get_limit_for_path(path)
        ip = get_ip_with_forwarding(request)
        key = ip
        now = time.monotonic()

        if self._redis:
            try:
                allowed, remaining = self._check_redis(key, rpm, window, now)
            except Exception as exc:
                _log.warning("sliding_window_redis_error falling back: %s", exc)
                self._redis = None
                allowed, remaining = self._check_memory(key, rpm, window, now)
        else:
            allowed, remaining = self._check_memory(key, rpm, window, now)

        retry_after = int(window) if not allowed else 0
        return allowed, remaining, rpm, retry_after


# =============================================================================
# Global Sliding Window Middleware
# =============================================================================


def _truthy_env(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


# Configurable via env vars
SLIDING_WINDOW_ENABLED = _truthy_env("WORLDBASE_RATE_LIMIT", "1")
SLIDING_WINDOW_RPM = int(os.getenv("WORLDBASE_RATE_LIMIT_RPM", "60"))
SLIDING_WINDOW_WINDOW_SEC = float(os.getenv("WORLDBASE_RATE_LIMIT_WINDOW_SEC", "60"))


def _parse_endpoint_overrides() -> dict[str, tuple[int, float]]:
    """Parse WORLDBASE_RATE_LIMIT_OVERRIDES env var.

    Format: "prefix:rpm,prefix2:rpm2" e.g. "/api/chat:30,/api/briefing:10"
    Window is always SLIDING_WINDOW_WINDOW_SEC.
    """
    raw = os.getenv("WORLDBASE_RATE_LIMIT_OVERRIDES", "")
    if not raw:
        return {}
    overrides: dict[str, tuple[int, float]] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if ":" not in entry:
            continue
        prefix, rpm_str = entry.rsplit(":", 1)
        try:
            rpm = int(rpm_str)
            overrides[prefix.strip()] = (rpm, SLIDING_WINDOW_WINDOW_SEC)
        except ValueError:
            continue
    return overrides


# Global instance (created lazily)
_sliding_window_limiter: SlidingWindowLimiter | None = None


def get_sliding_window_limiter() -> SlidingWindowLimiter | None:
    """Get or create the global sliding window limiter instance."""
    global _sliding_window_limiter
    if not SLIDING_WINDOW_ENABLED:
        return None
    if _sliding_window_limiter is None:
        _sliding_window_limiter = SlidingWindowLimiter(
            rpm=SLIDING_WINDOW_RPM,
            window_seconds=SLIDING_WINDOW_WINDOW_SEC,
            endpoint_overrides=_parse_endpoint_overrides(),
        )
    return _sliding_window_limiter


def setup_sliding_window_middleware(app) -> None:
    """Install the global sliding-window rate-limit middleware on a FastAPI app.

    This is called automatically by ``setup_rate_limiting`` when
    ``WORLDBASE_RATE_LIMIT=1`` (default on).
    """
    limiter_instance = get_sliding_window_limiter()
    if limiter_instance is None:
        return

    @app.middleware("http")
    async def sliding_window_rate_limit(request: Request, call_next):
        allowed, remaining, limit, retry_after = limiter_instance.check(request)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Sliding window rate limit exceeded.",
                        "details": {
                            "retry_after_seconds": retry_after,
                            "limit": f"{limit}/minute",
                        },
                    }
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                },
            )
        response = await call_next(request)
        if remaining >= 0:
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


# =============================================================================
# Example Usage Comments (for reference when implementing)
# =============================================================================

"""
EXAMPLE INTEGRATION IN main.py:

```python
from fastapi import FastAPI, Request
from middleware.rate_limit import (
    setup_rate_limiting,
    limiter,
    rate_limit_node_ingest,
    rate_limit_node_pull,
    rate_limit_node_command,
    rate_limit_general,
)

app = FastAPI()

# Setup rate limiting
setup_rate_limiting(app)

# Example routes with different rate limits:

# 1. Node ingest endpoint - 100 req/min per node
@app.post("/api/node/ingest")
@rate_limit_node_ingest()
async def node_ingest(request: Request, data: dict):
    # Extract node_id from payload and set in request state
    request.state.node_id = data.get("node_id")
    # ... process ingest
    return {"status": "success"}


# 2. Node pull endpoint - 20 req/min per node
@app.get("/api/node/pull/{node_id}")
@rate_limit_node_pull()
async def node_pull(node_id: str, request: Request):
    request.state.node_id = node_id
    # ... process pull
    return {"data": []}


# 3. Admin command endpoint - 10 req/min per admin
@app.post("/api/node/command")
@rate_limit_node_command()
async def node_command(request: Request, command: dict):
    # Requires X-Admin-Token header
    # ... process command
    return {"status": "executed"}


# 4. General API endpoint - 1000 req/hour per IP
@app.get("/api/status")
@rate_limit_general()
async def get_status(request: Request):
    return {"status": "ok"}
```

EXAMPLE ENVIRONMENT CONFIGURATION:

```bash
# .env file
RATE_LIMIT_STORAGE=memory              # or "redis"
RATE_LIMIT_REDIS_URL=redis://localhost:6379/0
RATE_LIMIT_NODE_INGEST=100/minute
RATE_LIMIT_NODE_PULL=20/minute
RATE_LIMIT_NODE_COMMAND=10/minute
RATE_LIMIT_GENERAL=1000/hour
```

EXAMPLE ERROR RESPONSE (429 Too Many Requests):

```json
{
  "error": {
    "code": "RATE_LIMIT_EXCEEDED",
    "message": "Rate limit exceeded. Please slow down your requests.",
    "details": {
      "retry_after_seconds": 45,
      "retry_after": "45s",
      "limit": "100/minute"
    },
    "suggestion": "Reduce request frequency or contact support for higher limits."
  }
}
```

With headers:
- `Retry-After: 45`
- `X-RateLimit-Limit: 100`
- `X-RateLimit-Remaining: 0`
"""
