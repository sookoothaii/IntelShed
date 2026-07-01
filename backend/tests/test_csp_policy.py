"""E-09 — CSP Single Source of Truth tests.

Validates that csp_policy.py generates identical policy strings across
all 3 output formats (header, meta tag, Caddyfile) and that the
middleware imports from the single source.
"""

from __future__ import annotations

import pathlib
import re
import unittest

from csp_policy import CSPPolicy


class TestCSPPolicyFormats(unittest.TestCase):
    """Verify all 3 output formats produce identical CSP strings."""

    def test_to_header_returns_string(self) -> None:
        csp = CSPPolicy.to_header()
        self.assertIsInstance(csp, str)
        self.assertGreater(len(csp), 50)

    def test_to_meta_tag_returns_string(self) -> None:
        csp = CSPPolicy.to_meta_tag()
        self.assertIsInstance(csp, str)
        self.assertGreater(len(csp), 50)

    def test_to_caddyfile_returns_string(self) -> None:
        csp = CSPPolicy.to_caddyfile()
        self.assertIsInstance(csp, str)
        self.assertGreater(len(csp), 50)

    def test_header_equals_caddyfile(self) -> None:
        """Header and Caddyfile produce identical policy strings."""
        header = CSPPolicy.to_header()
        caddy = CSPPolicy.to_caddyfile()
        self.assertEqual(header, caddy, "header != caddyfile")

    def test_meta_tag_strips_frame_ancestors(self) -> None:
        """Meta tag excludes frame-ancestors (not supported in meta tags per CSP spec)."""
        meta = CSPPolicy.to_meta_tag()
        header = CSPPolicy.to_header()
        self.assertNotIn("frame-ancestors", meta)
        self.assertIn("frame-ancestors", header)

    def test_meta_tag_has_all_other_directives(self) -> None:
        """Meta tag still contains all non-ignored directives."""
        meta = CSPPolicy.to_meta_tag()
        for directive in [
            "default-src",
            "script-src",
            "style-src",
            "font-src",
            "img-src",
            "connect-src",
            "worker-src",
            "object-src",
            "base-uri",
            "form-action",
        ]:
            self.assertIn(directive, meta, f"Missing in meta tag: {directive}")

    def test_caddyfile_line_has_quotes(self) -> None:
        line = CSPPolicy.to_caddyfile_line()
        self.assertIn('Content-Security-Policy "', line)
        self.assertTrue(line.endswith('"'))

    def test_meta_html_has_correct_tag(self) -> None:
        html = CSPPolicy.to_meta_html()
        self.assertIn('http-equiv="Content-Security-Policy"', html)
        self.assertIn('content="', html)


class TestCSPPolicyDirectives(unittest.TestCase):
    """Verify all required CSP directives are present."""

    def _policy(self) -> str:
        return CSPPolicy.to_header()

    def test_default_src_self(self) -> None:
        self.assertIn("default-src 'self'", self._policy())

    def test_script_src(self) -> None:
        p = self._policy()
        self.assertIn("script-src", p)
        self.assertIn("'unsafe-inline'", p)
        self.assertIn("'unsafe-eval'", p)
        self.assertIn("blob:", p)
        self.assertIn("https://unpkg.com", p)

    def test_style_src(self) -> None:
        p = self._policy()
        self.assertIn("style-src", p)
        self.assertIn("https://fonts.googleapis.com", p)

    def test_font_src(self) -> None:
        p = self._policy()
        self.assertIn("font-src", p)
        self.assertIn("https://fonts.gstatic.com", p)

    def test_img_src(self) -> None:
        p = self._policy()
        self.assertIn("img-src", p)
        self.assertIn("blob:", p)
        self.assertIn("https:", p)

    def test_connect_src(self) -> None:
        p = self._policy()
        self.assertIn("connect-src", p)
        self.assertIn("https://api.cesium.com", p)
        self.assertIn("https://*.cesium.com", p)
        self.assertIn("https://*.virtualearth.net", p)
        self.assertIn("https://server.arcgisonline.com", p)
        self.assertIn("https://*.arcgisonline.com", p)
        self.assertIn("https://protomaps.github.io", p)
        self.assertIn("https://api.windy.com", p)
        self.assertIn("wss:", p)
        self.assertIn("ws:", p)

    def test_worker_src(self) -> None:
        p = self._policy()
        self.assertIn("worker-src", p)
        self.assertIn("blob:", p)

    def test_object_src_none(self) -> None:
        self.assertIn("object-src 'none'", self._policy())

    def test_frame_ancestors_self(self) -> None:
        self.assertIn("frame-ancestors 'self'", self._policy())

    def test_base_uri_self(self) -> None:
        self.assertIn("base-uri 'self'", self._policy())

    def test_form_action_self(self) -> None:
        self.assertIn("form-action 'self'", self._policy())

    def test_directive_order(self) -> None:
        """default-src must come first, form-action last."""
        p = self._policy()
        self.assertTrue(p.startswith("default-src"))
        self.assertIn("form-action", p.rsplit(";", 1)[0])


class TestCSPMiddlewareIntegration(unittest.TestCase):
    """Verify SecurityHeadersMiddleware uses CSPPolicy."""

    def test_middleware_imports_csp_policy(self) -> None:
        from middleware.security_headers import SecurityHeadersMiddleware

        csp = SecurityHeadersMiddleware._HEADERS["Content-Security-Policy"]
        self.assertEqual(csp, CSPPolicy.to_header())

    def test_middleware_csp_has_all_directives(self) -> None:
        from middleware.security_headers import SecurityHeadersMiddleware

        csp = SecurityHeadersMiddleware._HEADERS["Content-Security-Policy"]
        for directive in [
            "default-src",
            "script-src",
            "style-src",
            "font-src",
            "img-src",
            "connect-src",
            "worker-src",
            "object-src",
            "frame-ancestors",
            "base-uri",
            "form-action",
        ]:
            self.assertIn(directive, csp, f"Missing directive: {directive}")


class TestCSPCrossSourceSync(unittest.TestCase):
    """Verify CSP is synchronized across index.html, Caddyfile, and middleware."""

    def _extract_index_html_csp(self) -> str | None:
        root = pathlib.Path(__file__).parent.parent.parent
        index = root / "frontend" / "index.html"
        if not index.exists():
            return None
        html = index.read_text(encoding="utf-8")
        # Match specifically the CSP meta tag (http-equiv="Content-Security-Policy")
        match = re.search(
            r'<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]*)"',
            html,
        )
        return match.group(1) if match else None

    def _extract_caddyfile_csp(self) -> str | None:
        root = pathlib.Path(__file__).parent.parent.parent
        caddy = root / "Caddyfile"
        if not caddy.exists():
            return None
        text = caddy.read_text(encoding="utf-8")
        match = re.search(r'Content-Security-Policy "([^"]*)"', text)
        return match.group(1) if match else None

    def test_index_html_matches_meta_tag(self) -> None:
        """index.html meta tag must match CSPPolicy.to_meta_tag() (no frame-ancestors)."""
        html_csp = self._extract_index_html_csp()
        if html_csp is None:
            self.skipTest("index.html not found")
        self.assertEqual(html_csp, CSPPolicy.to_meta_tag())

    def test_caddyfile_matches_header(self) -> None:
        """Caddyfile must match CSPPolicy.to_caddyfile() (includes frame-ancestors)."""
        caddy_csp = self._extract_caddyfile_csp()
        if caddy_csp is None:
            self.skipTest("Caddyfile not found")
        self.assertEqual(caddy_csp, CSPPolicy.to_caddyfile())

    def test_header_and_caddyfile_identical(self) -> None:
        """Header and Caddyfile must be byte-identical (both include frame-ancestors)."""
        middleware_csp = CSPPolicy.to_header()
        caddy_csp = self._extract_caddyfile_csp()
        if caddy_csp:
            self.assertEqual(middleware_csp, caddy_csp, "middleware != Caddyfile")

    def test_meta_tag_subset_of_header(self) -> None:
        """Meta tag must be a subset of header (only difference: no frame-ancestors)."""
        html_csp = self._extract_index_html_csp()
        if html_csp is None:
            self.skipTest("index.html not found")
        header = CSPPolicy.to_header()
        # Meta tag = header with frame-ancestors directive removed
        header_without_fa = header.replace("frame-ancestors 'self'; ", "")
        self.assertEqual(html_csp, header_without_fa)


if __name__ == "__main__":
    unittest.main()
