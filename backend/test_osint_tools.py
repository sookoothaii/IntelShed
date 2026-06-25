"""Unit tests for OSINT tool helpers (no network)."""

import unittest

import osint_tools as ot


class OsintToolsTests(unittest.TestCase):
    def test_parse_crt_sh_names_dedupes(self):
        rows = [
            {"name_value": "api.example.com\nwww.example.com"},
            {"common_name": "*.example.com"},
            {"name_value": "other.org"},
        ]
        names = ot._parse_crt_sh_names(rows, "example.com")
        self.assertIn("api.example.com", names)
        self.assertIn("www.example.com", names)
        self.assertTrue(all("example.com" in n for n in names))
        self.assertNotIn("other.org", names)

    def test_parse_crt_sh_names_limit(self):
        rows = [{"name_value": f"h{i}.example.com"} for i in range(100)]
        names = ot._parse_crt_sh_names(rows, "example.com", limit=10)
        self.assertEqual(len(names), 10)


if __name__ == "__main__":
    unittest.main()
