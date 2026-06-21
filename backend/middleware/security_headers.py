"""Pure-ASGI security headers — streaming-safe (does not buffer SSE)."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders


class SecurityHeadersMiddleware:
    """Unlike BaseHTTPMiddleware, does not buffer StreamingResponse/SSE (chat)."""

    _HEADERS = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "SAMEORIGIN",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "X-Permitted-Cross-Domain-Policies": "none",
        "Permissions-Policy": "geolocation=(self), microphone=(), camera=()",
    }

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for key, value in self._HEADERS.items():
                    headers.setdefault(key, value)
            await send(message)

        await self.app(scope, receive, send_wrapper)
