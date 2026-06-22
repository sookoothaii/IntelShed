"""Unit tests for NewsData bridge (no network)."""



from __future__ import annotations



import os

import unittest

from unittest.mock import AsyncMock, MagicMock, patch



import newsdata_bridge as nd





class NewsDataBridgeTests(unittest.IsolatedAsyncioTestCase):

    def tearDown(self):

        for key in (

            "NEWSDATA_API_KEY",

            "WORLDBASE_OPERATOR_REGION",

            "WORLDBASE_NEWSDATA_COUNTRIES",

            "WORLDBASE_NEWSDATA_DOMAINURL",

        ):

            if key in os.environ:

                del os.environ[key]



    async def test_missing_key_returns_unconfigured(self):

        os.environ.pop("NEWSDATA_API_KEY", None)

        out = await nd.fetch_newsdata_latest(limit=5)

        self.assertFalse(out["configured"])

        self.assertEqual(out["count"], 0)



    async def test_parse_success_payload(self):

        os.environ["NEWSDATA_API_KEY"] = "test-key"

        mock_resp = MagicMock()

        mock_resp.status_code = 200

        mock_resp.json.return_value = {

            "status": "success",

            "totalResults": 1,

            "results": [

                {

                    "title": "Flooding in central Thailand",

                    "link": "https://example.com/a",

                    "pubDate": "2026-06-22 10:00:00",

                    "country": ["thailand"],

                }

            ],

        }

        mock_resp.raise_for_status = lambda: None



        with patch("newsdata_bridge._request_newsdata", new_callable=AsyncMock) as req:

            req.return_value = (200, mock_resp.json.return_value, None)

            out = await nd.fetch_newsdata_latest(country="th", limit=5)



        self.assertTrue(out["configured"])

        self.assertEqual(out["count"], 1)

        self.assertEqual(out["articles"][0]["title"], "Flooding in central Thailand")

        self.assertEqual(out["filters"]["country"], "th")



    async def test_sources_parse_success(self):

        os.environ["NEWSDATA_API_KEY"] = "test-key"

        payload = {

            "status": "success",

            "totalResults": 1,

            "results": [

                {

                    "id": "nationthailand",

                    "name": "Nation Thailand",

                    "url": "https://www.nationthailand.com",

                    "country": ["thailand"],

                    "language": ["english"],

                }

            ],

        }

        with patch("newsdata_bridge._request_newsdata", new_callable=AsyncMock) as req:

            req.return_value = (200, payload, None)

            out = await nd.fetch_newsdata_sources(country="th", limit=10)



        self.assertTrue(out["configured"])

        self.assertEqual(out["count"], 1)

        self.assertEqual(out["sources"][0]["id"], "nationthailand")



    async def test_invalid_domainurl_surfaces_error(self):

        os.environ["NEWSDATA_API_KEY"] = "test-key"

        payload = {

            "status": "error",

            "results": [

                {

                    "invalid_domain": "ground.news",

                    "message": "The domain you provided does not exist in our database.",

                    "code": "UnsupportedFilter",

                }

            ],

        }

        with patch("newsdata_bridge._request_newsdata", new_callable=AsyncMock) as req:

            req.return_value = (422, payload, None)

            out = await nd.fetch_newsdata_sources(domainurl="ground.news", limit=5)



        self.assertTrue(out["configured"])

        self.assertEqual(out["count"], 0)

        self.assertIn("domain", (out.get("error") or "").lower())



    def test_default_filter_params_match_preview(self):

        os.environ.pop("WORLDBASE_NEWSDATA_DOMAINURL", None)

        params = nd._filter_params()

        self.assertEqual(params["country"], "al,de,us,ir,th")

        self.assertEqual(params["language"], "de,en")

        self.assertEqual(params["category"], "breaking,domestic,politics,technology,world")

        self.assertEqual(params["prioritydomain"], "low")
        self.assertEqual(params["excludedomain"], "reflector.com")
        self.assertNotIn("domainurl", params)



    def test_operator_country_thailand(self):

        os.environ["WORLDBASE_OPERATOR_REGION"] = "thailand"

        self.assertEqual(nd._operator_country(), "th")

    def test_is_briefing_article_filters_jail_and_paid_stub(self):
        self.assertFalse(
            nd._is_briefing_article(
                {
                    "title": "256979 ZAIQUAN ARNOLD",
                    "description": "ONLY AVAILABLE IN PAID PLANS",
                    "link": "https://www.reflector.com/jail_bookings/x.html",
                }
            )
        )
        self.assertTrue(
            nd._is_briefing_article(
                {
                    "title": "US-Iran Talks Go Into Day 2 After Trump Threats",
                    "description": "Iran-U.S. peace talks in Switzerland stretched into a second day.",
                    "link": "https://www.usnews.com/news/world/articles/x",
                }
            )
        )
        self.assertFalse(
            nd._is_briefing_article(
                {
                    "title": "Arsenal beat Chelsea 2-1 in Premier League clash",
                    "description": "Football highlights from London.",
                    "category": ["sports"],
                    "link": "https://example.com/sports/x",
                }
            )
        )
        self.assertTrue(nd.is_sports_content(title="NBA Finals Game 7 tips off tonight"))

    async def test_fetch_filters_junk_from_batch(self):
        os.environ["NEWSDATA_API_KEY"] = "test-key"
        payload = {
            "status": "success",
            "totalResults": 3,
            "results": [
                {
                    "title": "256979 ZAIQUAN ARNOLD",
                    "description": "ONLY AVAILABLE IN PAID PLANS",
                    "link": "https://www.reflector.com/jail_bookings/x.html",
                },
                {
                    "title": "US-Iran Talks Go Into Day 2 After Trump Threats",
                    "description": "Iran-U.S. peace talks in Switzerland stretched into a second day.",
                    "link": "https://www.usnews.com/news/world/articles/x",
                },
            ],
        }
        with patch("newsdata_bridge._request_newsdata", new_callable=AsyncMock) as req:
            req.return_value = (200, payload, None)
            out = await nd.fetch_newsdata_latest(limit=5)

        self.assertEqual(out["count"], 1)
        self.assertEqual(out["filtered_count"], 1)
        self.assertIn("US-Iran", out["articles"][0]["title"])





if __name__ == "__main__":

    unittest.main()

