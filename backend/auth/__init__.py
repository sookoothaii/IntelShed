"""WorldBase Authentication Module — Enhanced HMAC security with replay protection.

This module provides hardened authentication primitives:
- Constant-time HMAC comparison (timing attack resistant)
- Replay attack prevention via nonce/timestamp cache
- Token expiration with configurable TTL
- Request signing helpers for Pi client integration

Example Usage:
    Server-side (verify request):
        >>> from auth.security import verify_request_auth
        >>> payload = verify_request_auth(request, secret="my-secret")

    Client-side (sign request):
        >>> from auth.security import create_signed_request
        >>> signed = create_signed_request(data, secret="my-secret")
        >>> requests.post(url, json=signed["payload"], headers=signed["headers"])

    Admin authorization:
        >>> from auth.security import require_admin_token
        >>> require_admin_token(request)  # Raises 403 if invalid
"""

from .security import (
    check_replay_attack,
    clear_nonce_cache,
    create_signed_request,
    generate_hmac_signature,
    generate_secure_nonce,
    get_auth_config,
    require_admin_token,
    verify_hmac_signature,
    verify_legacy_hmac,
    verify_legacy_hmac_bytes,
    verify_request_auth,
    verify_token_expiration,
)

__all__ = [
    "check_replay_attack",
    "clear_nonce_cache",
    "create_signed_request",
    "generate_hmac_signature",
    "generate_secure_nonce",
    "get_auth_config",
    "require_admin_token",
    "verify_hmac_signature",
    "verify_legacy_hmac",
    "verify_legacy_hmac_bytes",
    "verify_request_auth",
    "verify_token_expiration",
]
