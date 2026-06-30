"""Tests for V4-58 engine-specific HTML parsers (darkweb_parsers.py)."""

from __future__ import annotations

import unittest

import darkweb_parsers


class Tor66ParserTests(unittest.TestCase):
    def test_parse_table_layout(self):
        html = """
        <table>
            <tr class="result">
                <td>
                    <a href="http://abc234abc234abcd.onion/page1">Test Title 1</a>
                    <br/>This is a snippet about the first result page.
                    <br/><span>abc234abc234abcd.onion/page1</span>
                </td>
            </tr>
            <tr class="result">
                <td>
                    <a href="http://xyz234xyz234xyz2.onion/post2">Second Result</a>
                    <br/>Another snippet with more details here.
                </td>
            </tr>
        </table>
        """
        results = darkweb_parsers.parse_tor66(html, 10)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["engine"], "tor66")
        self.assertEqual(results[0]["title"], "Test Title 1")
        self.assertEqual(results[0]["url"], "http://abc234abc234abcd.onion/page1")
        self.assertIn("snippet", results[0])
        self.assertTrue(len(results[0]["snippet"]) > 0)

    def test_parse_empty_html(self):
        results = darkweb_parsers.parse_tor66("<html><body></body></html>", 10)
        self.assertEqual(len(results), 0)

    def test_limit_respected(self):
        html = """
        <tr class="result"><td><a href="http://abc234abc234abcd.onion/1">A</a><br/>snippet text here.</td></tr>
        <tr class="result"><td><a href="http://abc234abc234abcd.onion/2">B</a><br/>snippet text here.</td></tr>
        <tr class="result"><td><a href="http://abc234abc234abcd.onion/3">C</a><br/>snippet text here.</td></tr>
        """
        results = darkweb_parsers.parse_tor66(html, 2)
        self.assertEqual(len(results), 2)

    def test_dedup_urls(self):
        html = """
        <tr class="result"><td><a href="http://abc234abc234abcd.onion/dup">A</a><br/>snippet.</td></tr>
        <tr class="result"><td><a href="http://abc234abc234abcd.onion/dup">B</a><br/>snippet.</td></tr>
        """
        results = darkweb_parsers.parse_tor66(html, 10)
        self.assertEqual(len(results), 1)

    def test_fallback_on_no_structured_results(self):
        """Should fall back to generic link extraction."""
        html = '<a href="http://abc234abc234abcd.onion/page">Some Link</a>'
        results = darkweb_parsers.parse_tor66(html, 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "http://abc234abc234abcd.onion/page")


class TorDexParserTests(unittest.TestCase):
    def test_parse_card_layout(self):
        html = """
        <div class="result">
            <h3><a href="http://def234def234def2.onion/page">TorDex Title</a></h3>
            <p class="description">A description of the result.</p>
        </div>
        <div class="search-result">
            <h3><a href="http://ghi234ghi234ghi2.onion/post">Second Hit</a></h3>
            <p class="snippet">Another snippet here.</p>
        </div>
        """
        results = darkweb_parsers.parse_tordex(html, 10)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["engine"], "tordex")
        self.assertEqual(results[0]["title"], "TorDex Title")
        self.assertEqual(results[0]["url"], "http://def234def234def2.onion/page")
        self.assertIn("description", results[0]["snippet"])

    def test_redirect_url_unwrapped(self):
        html = """
        <div class="result">
            <a href="/redirect?url=http://abc234abc234abcd.onion/real">Title</a>
            <p class="desc">Snippet.</p>
        </div>
        """
        results = darkweb_parsers.parse_tordex(html, 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "http://abc234abc234abcd.onion/real")

    def test_empty_html(self):
        results = darkweb_parsers.parse_tordex("<html></html>", 10)
        self.assertEqual(len(results), 0)


class HaystakParserTests(unittest.TestCase):
    def test_parse_standard_layout(self):
        html = """
        <div class="result">
            <h4><a href="http://abc234abc234abcd.onion/page">Haystak Result</a></h4>
            <p class="url">abc234abc234abcd.onion/page</p>
            <p class="summary">This is a summary of the page content.</p>
        </div>
        """
        results = darkweb_parsers.parse_haystak(html, 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["engine"], "haystak")
        self.assertEqual(results[0]["title"], "Haystak Result")
        self.assertEqual(results[0]["url"], "http://abc234abc234abcd.onion/page")
        self.assertIn("summary", results[0]["snippet"])

    def test_url_redirect_unwrapped(self):
        html = """
        <div class="result">
            <h4><a href="/url?u=http://xyz234xyz234xyz2.onion/real">Title</a></h4>
            <p class="summary">Snippet.</p>
        </div>
        """
        results = darkweb_parsers.parse_haystak(html, 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "http://xyz234xyz234xyz2.onion/real")

    def test_empty_html(self):
        results = darkweb_parsers.parse_haystak("<html></html>", 10)
        self.assertEqual(len(results), 0)


class NotEvilParserTests(unittest.TestCase):
    def test_parse_div_result(self):
        html = """
        <div class="result">
            <a href="http://abc234abc234abcd.onion/page">Not Evil Title</a>
            <div class="snippet">Some snippet text.</div>
        </div>
        <div class="g">
            <a href="http://xyz234xyz234xyz2.onion/other">Second</a>
            <cite>xyz234xyz234xyz2.onion/other</cite>
        </div>
        """
        results = darkweb_parsers.parse_notevil(html, 10)
        # div.result matches first, div.g is not tried (selector stops at first hit)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["engine"], "notevil")
        self.assertEqual(results[0]["title"], "Not Evil Title")
        self.assertEqual(results[0]["url"], "http://abc234abc234abcd.onion/page")

    def test_url_redirect_unwrapped(self):
        html = """
        <div class="result">
            <a href="/url?q=http://abc234abc234abcd.onion/real">Title</a>
        </div>
        """
        results = darkweb_parsers.parse_notevil(html, 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "http://abc234abc234abcd.onion/real")

    def test_cite_as_snippet_fallback(self):
        html = """
        <div class="result">
            <a href="http://abc234abc234abcd.onion/page">Title</a>
            <cite>abc234abc234abcd.onion/page</cite>
        </div>
        """
        results = darkweb_parsers.parse_notevil(html, 10)
        self.assertEqual(len(results), 1)
        self.assertIn("abc234", results[0]["snippet"])

    def test_empty_html(self):
        results = darkweb_parsers.parse_notevil("<html></html>", 10)
        self.assertEqual(len(results), 0)


class TorchParserTests(unittest.TestCase):
    def test_parse_div_result(self):
        html = """
        <div class="result">
            <h3><a href="http://abc234abc234abcd.onion/page">Torch Title</a></h3>
            <div class="url">abc234abc234abcd.onion/page</div>
            <div class="snippet">Torch snippet text.</div>
        </div>
        """
        results = darkweb_parsers.parse_torch(html, 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["engine"], "torch")
        self.assertEqual(results[0]["title"], "Torch Title")
        self.assertEqual(results[0]["url"], "http://abc234abc234abcd.onion/page")
        self.assertIn("Torch snippet", results[0]["snippet"])

    def test_relative_url_resolved(self):
        html = """
        <div class="result">
            <h3><a href="/search/result/123">Title</a></h3>
            <div class="snippet">Snippet.</div>
        </div>
        """
        results = darkweb_parsers.parse_torch(html, 10)
        # Relative URL gets resolved to full .onion URL by the parser,
        # so it DOES match _ONION_URL_RE and is included
        self.assertEqual(len(results), 1)
        self.assertIn(
            "xmh57jrknzkhv6y3ls3ubitzfqnkrwxhopf5aygthi7d6rplyvk3noyd",
            results[0]["url"],
        )

    def test_fallback_link_extraction(self):
        html = '<a href="http://abc234abc234abcd.onion/page">Direct Link</a>'
        results = darkweb_parsers.parse_torch(html, 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "http://abc234abc234abcd.onion/page")

    def test_empty_html(self):
        results = darkweb_parsers.parse_torch("<html></html>", 10)
        self.assertEqual(len(results), 0)


class RegistryTests(unittest.TestCase):
    def test_has_engine_parser(self):
        self.assertTrue(darkweb_parsers.has_engine_parser("torch"))
        self.assertTrue(darkweb_parsers.has_engine_parser("tor66"))
        self.assertTrue(darkweb_parsers.has_engine_parser("tordex"))
        self.assertTrue(darkweb_parsers.has_engine_parser("haystak"))
        self.assertTrue(darkweb_parsers.has_engine_parser("notevil"))
        self.assertFalse(darkweb_parsers.has_engine_parser("ahmia"))
        self.assertFalse(darkweb_parsers.has_engine_parser("unknown"))

    def test_parse_engine_html_dispatches(self):
        html = '<a href="http://abc234abc234abcd.onion/page">Test</a>'
        results = darkweb_parsers.parse_engine_html("torch", html, 10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["engine"], "torch")

    def test_parse_engine_html_unknown_engine(self):
        results = darkweb_parsers.parse_engine_html("unknown", "<html></html>", 10)
        self.assertEqual(len(results), 0)

    def test_parse_engine_html_exception_returns_empty(self):
        """Parser exception should be caught and return empty list."""
        # Pass non-string to trigger exception
        results = darkweb_parsers.parse_engine_html("torch", None, 10)  # type: ignore[arg-type]
        self.assertEqual(len(results), 0)

    def test_list_parser_engines(self):
        engines = darkweb_parsers.list_parser_engines()
        self.assertIn("torch", engines)
        self.assertIn("tor66", engines)
        self.assertIn("tordex", engines)
        self.assertIn("haystak", engines)
        self.assertIn("notevil", engines)
        self.assertEqual(len(engines), 5)


class IntegrationTests(unittest.TestCase):
    """Test that parsers return dicts in the format darkweb_bridge expects."""

    def test_result_format(self):
        html = """
        <div class="result">
            <h3><a href="http://abc234abc234abcd.onion/page">Title</a></h3>
            <div class="snippet">Snippet text.</div>
        </div>
        """
        results = darkweb_parsers.parse_torch(html, 10)
        self.assertEqual(len(results), 1)
        r = results[0]
        # Must have all required keys
        self.assertIn("title", r)
        self.assertIn("url", r)
        self.assertIn("snippet", r)
        self.assertIn("engine", r)
        self.assertIn("first_seen", r)
        # Types
        self.assertIsInstance(r["title"], str)
        self.assertIsInstance(r["url"], str)
        self.assertIsInstance(r["snippet"], str)
        self.assertIsInstance(r["engine"], str)
        self.assertIsInstance(r["first_seen"], str)

    def test_all_engines_produce_consistent_format(self):
        """Every parser should return the same dict structure."""
        engines_html = {
            "torch": '<div class="result"><h3><a href="http://abc234abc234abcd.onion/p">T</a></h3><div class="snippet">S</div></div>',
            "tor66": '<tr class="result"><td><a href="http://abc234abc234abcd.onion/p">T</a><br/>This is a snippet text.</td></tr>',
            "tordex": '<div class="result"><h3><a href="http://abc234abc234abcd.onion/p">T</a></h3><p class="desc">S</p></div>',
            "haystak": '<div class="result"><h4><a href="http://abc234abc234abcd.onion/p">T</a></h4><p class="summary">S</p></div>',
            "notevil": '<div class="result"><a href="http://abc234abc234abcd.onion/p">T</a><div class="snippet">S</div></div>',
        }
        for engine, html in engines_html.items():
            results = darkweb_parsers.parse_engine_html(engine, html, 10)
            self.assertEqual(len(results), 1, f"{engine} failed to parse")
            r = results[0]
            self.assertEqual(r["engine"], engine)
            self.assertEqual(r["url"], "http://abc234abc234abcd.onion/p")
            self.assertTrue(r["title"])
            self.assertTrue(r["snippet"])


if __name__ == "__main__":
    unittest.main()
