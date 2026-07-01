"""CSP Single Source of Truth — generates all 3 CSP output formats from one definition.

Usage:
    from csp_policy import CSPPolicy
    header_value = CSPPolicy.to_header()        # for SecurityHeadersMiddleware
    meta_tag     = CSPPolicy.to_meta_tag()       # for index.html <meta> tag
    caddy_directive = CSPPolicy.to_caddyfile()   # for Caddyfile header block

CLI (used by Vite csp-sync plugin):
    python -c "from csp_policy import CSPPolicy; print(CSPPolicy.to_meta_tag())"
    python -c "from csp_policy import CSPPolicy; print(CSPPolicy.to_caddyfile())"
"""

from __future__ import annotations


class CSPPolicy:
    """Single source of truth for Content-Security-Policy directives.

    All three CSP surfaces (FastAPI middleware, index.html meta tag, Caddyfile
    header) are generated from these class attributes, eliminating manual sync.
    """

    # --- Directive definitions (edit here, all 3 outputs update automatically) ---

    DEFAULT_SRC = "'self'"
    SCRIPT_SRC = "'self' 'unsafe-inline' 'unsafe-eval' blob: https://unpkg.com"
    STYLE_SRC = "'self' 'unsafe-inline' https://fonts.googleapis.com"
    FONT_SRC = "'self' https://fonts.gstatic.com data:"
    IMG_SRC = "'self' data: blob: https:"
    CONNECT_SRC = (
        "'self' "
        "https://api.cesium.com "
        "https://*.cesium.com "
        "https://*.virtualearth.net "
        "https://server.arcgisonline.com "
        "https://*.arcgisonline.com "
        "https://protomaps.github.io "
        "https://api.windy.com "
        "wss: ws:"
    )
    WORKER_SRC = "'self' blob:"
    OBJECT_SRC = "'none'"
    FRAME_SRC = "'self' http://localhost:5173 http://127.0.0.1:5173"
    FRAME_ANCESTORS = "'self'"
    BASE_URI = "'self'"
    FORM_ACTION = "'self'"

    # --- Directive order (matches CSP spec convention) ---

    _DIRECTIVE_ORDER = [
        ("default-src", "DEFAULT_SRC"),
        ("script-src", "SCRIPT_SRC"),
        ("style-src", "STYLE_SRC"),
        ("font-src", "FONT_SRC"),
        ("img-src", "IMG_SRC"),
        ("connect-src", "CONNECT_SRC"),
        ("worker-src", "WORKER_SRC"),
        ("object-src", "OBJECT_SRC"),
        ("frame-src", "FRAME_SRC"),
        ("frame-ancestors", "FRAME_ANCESTORS"),
        ("base-uri", "BASE_URI"),
        ("form-action", "FORM_ACTION"),
    ]

    @classmethod
    def _build_policy_string(cls) -> str:
        """Build the raw CSP policy string from directives."""
        parts = []
        for directive, attr_name in cls._DIRECTIVE_ORDER:
            value = getattr(cls, attr_name)
            if value:
                parts.append(f"{directive} {value}")
        return "; ".join(parts) + ";"

    @classmethod
    def to_header(cls) -> str:
        """CSP header value for HTTP response (SecurityHeadersMiddleware)."""
        return cls._build_policy_string()

    # Directives not supported in <meta> tags per CSP spec — stripped from
    # meta tag output to avoid console warnings (delivered via HTTP header instead).
    _META_IGNORED = {"frame-ancestors", "report-uri", "sandbox"}

    @classmethod
    def to_meta_tag(cls) -> str:
        """CSP value for <meta http-equiv='Content-Security-Policy' content='...'>.

        Excludes directives not supported in meta tags (frame-ancestors, etc.)
        to avoid browser console warnings. These are still delivered via the
        Caddy HTTP header.
        """
        parts = []
        for directive, attr_name in cls._DIRECTIVE_ORDER:
            if directive in cls._META_IGNORED:
                continue
            value = getattr(cls, attr_name)
            if value:
                parts.append(f"{directive} {value}")
        return "; ".join(parts) + ";"

    @classmethod
    def to_caddyfile(cls) -> str:
        """CSP directive for Caddyfile header block.

        Returns the Content-Security-Policy header line (without quotes,
        caller wraps in Caddy header syntax).
        """
        return cls._build_policy_string()

    @classmethod
    def to_caddyfile_line(cls) -> str:
        """Full Caddyfile header line with proper quoting."""
        return f'Content-Security-Policy "{cls._build_policy_string()}"'

    @classmethod
    def to_meta_html(cls) -> str:
        """Full <meta> tag HTML for index.html."""
        return (
            f"    <meta\n"
            f'      http-equiv="Content-Security-Policy"\n'
            f'      content="{cls.to_meta_tag()}"\n'
            f"    />"
        )


if __name__ == "__main__":
    import sys

    fmt = sys.argv[1] if len(sys.argv) > 1 else "header"
    if fmt == "meta":
        print(CSPPolicy.to_meta_tag())
    elif fmt == "caddy":
        print(CSPPolicy.to_caddyfile_line())
    elif fmt == "meta-html":
        print(CSPPolicy.to_meta_html())
    else:
        print(CSPPolicy.to_header())
