"""Tests for Country Instability Index (CII) engine.

Covers:
  - Country code normalization (ISO2, ISO3, name → ISO2)
  - Signal family classification (keyword + theme based)
  - Score calculation (family scores, weighted CII, risk bands)
  - Trend indicator (rising/falling/stable/insufficient_data)
  - Snapshot persistence (save + load previous + load trend)
  - Digest gathering (cache-based, fail-soft)
  - API endpoint integration (country, rankings)
  - 20+ country fixtures for normalization
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

import pytest

# Set temp DB before importing
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["WORLDBASE_DB_PATH"] = _tmp.name

import cii_engine  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear in-memory cache between tests."""
    cii_engine._mem_cache.clear()
    yield
    cii_engine._mem_cache.clear()


@pytest.fixture(autouse=True)
def _reset_db():
    """Ensure clean DB table for each test."""
    try:
        with cii_engine._conn() as c:
            c.execute("DROP TABLE IF EXISTS cii_snapshots")
            c.commit()
    except Exception:
        pass
    yield
    try:
        with cii_engine._conn() as c:
            c.execute("DROP TABLE IF EXISTS cii_snapshots")
            c.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Country code normalization
# ---------------------------------------------------------------------------


class TestCountryCodeNormalization:
    """20+ country fixtures for normalization."""

    @pytest.mark.parametrize(
        "iso2,iso3,name",
        [
            ("TH", "THA", "Thailand"),
            ("MM", "MMR", "Myanmar"),
            ("LA", "LAO", "Laos"),
            ("KH", "KHM", "Cambodia"),
            ("VN", "VNM", "Vietnam"),
            ("PH", "PHL", "Philippines"),
            ("MY", "MYS", "Malaysia"),
            ("SG", "SGP", "Singapore"),
            ("BN", "BRN", "Brunei"),
            ("ID", "IDN", "Indonesia"),
            ("CN", "CHN", "China"),
            ("JP", "JPN", "Japan"),
            ("KR", "KOR", "South Korea"),
            ("IN", "IND", "India"),
            ("PK", "PAK", "Pakistan"),
            ("AF", "AFG", "Afghanistan"),
            ("IR", "IRN", "Iran"),
            ("IQ", "IRQ", "Iraq"),
            ("SY", "SYR", "Syria"),
            ("YE", "YEM", "Yemen"),
            ("SA", "SAU", "Saudi Arabia"),
            ("IL", "ISR", "Israel"),
            ("TR", "TUR", "Turkey"),
            ("RU", "RUS", "Russia"),
            ("UA", "UKR", "Ukraine"),
            ("US", "USA", "United States"),
            ("GB", "GBR", "United Kingdom"),
            ("DE", "DEU", "Germany"),
            ("FR", "FRA", "France"),
            ("BR", "BRA", "Brazil"),
        ],
    )
    def test_iso2_to_iso3(self, iso2, iso3, name):
        assert cii_engine.iso2_to_iso3(iso2) == iso3

    @pytest.mark.parametrize(
        "iso2,iso3,name",
        [
            ("TH", "THA", "Thailand"),
            ("MM", "MMR", "Myanmar"),
            ("VN", "VNM", "Vietnam"),
            ("ID", "IDN", "Indonesia"),
            ("IR", "IRN", "Iran"),
            ("RU", "RUS", "Russia"),
            ("UA", "UKR", "Ukraine"),
            ("US", "USA", "United States"),
        ],
    )
    def test_iso2_to_name(self, iso2, iso3, name):
        assert cii_engine.iso2_to_name(iso2) == name

    @pytest.mark.parametrize(
        "iso2,iso3,name",
        [
            ("TH", "THA", "Thailand"),
            ("MM", "MMR", "Myanmar"),
            ("VN", "VNM", "Vietnam"),
            ("ID", "IDN", "Indonesia"),
            ("IR", "IRN", "Iran"),
            ("RU", "RUS", "Russia"),
            ("UA", "UKR", "Ukraine"),
            ("US", "USA", "United States"),
        ],
    )
    def test_normalize_iso2(self, iso2, iso3, name):
        assert cii_engine.normalize_country_code(iso2) == iso2

    @pytest.mark.parametrize(
        "iso2,iso3,name",
        [
            ("TH", "THA", "Thailand"),
            ("MM", "MMR", "Myanmar"),
            ("VN", "VNM", "Vietnam"),
            ("ID", "IDN", "Indonesia"),
            ("IR", "IRN", "Iran"),
            ("RU", "RUS", "Russia"),
            ("UA", "UKR", "Ukraine"),
            ("US", "USA", "United States"),
        ],
    )
    def test_normalize_iso3(self, iso2, iso3, name):
        assert cii_engine.normalize_country_code(iso3) == iso2

    @pytest.mark.parametrize(
        "iso2,iso3,name",
        [
            ("TH", "THA", "Thailand"),
            ("MM", "MMR", "Myanmar"),
            ("VN", "VNM", "Vietnam"),
            ("ID", "IDN", "Indonesia"),
            ("IR", "IRN", "Iran"),
            ("RU", "RUS", "Russia"),
            ("UA", "UKR", "Ukraine"),
            ("US", "USA", "United States"),
        ],
    )
    def test_normalize_name(self, iso2, iso3, name):
        assert cii_engine.normalize_country_code(name) == iso2
        assert cii_engine.normalize_country_code(name.upper()) == iso2

    def test_normalize_lowercase(self):
        assert cii_engine.normalize_country_code("th") == "TH"
        assert cii_engine.normalize_country_code("tha") == "TH"
        assert cii_engine.normalize_country_code("thailand") == "TH"

    def test_normalize_unknown(self):
        # Unknown 2-letter code returns as-is
        assert cii_engine.normalize_country_code("ZZ") == "ZZ"
        # Unknown 3-letter code returns first 2 chars
        assert cii_engine.normalize_country_code("ZZZ") == "ZZ"


# ---------------------------------------------------------------------------
# Signal classification
# ---------------------------------------------------------------------------


class TestSignalClassification:
    def test_conflict_keywords(self):
        families = cii_engine._classify_article(
            "Armed clash kills 10 in border skirmish"
        )
        assert "conflict" in families

    def test_economy_keywords(self):
        families = cii_engine._classify_article(
            "Inflation hits record high as currency crisis deepens"
        )
        assert "economy" in families

    def test_climate_keywords(self):
        families = cii_engine._classify_article(
            "Flood disaster displaces thousands after typhoon"
        )
        assert "climate" in families

    def test_governance_keywords(self):
        families = cii_engine._classify_article(
            "Mass protest over corruption scandal in capital"
        )
        assert "governance" in families

    def test_multiple_families(self):
        families = cii_engine._classify_article(
            "Armed conflict escalates as economic crisis and protests mount"
        )
        assert "conflict" in families
        assert "economy" in families
        assert "governance" in families

    def test_no_match(self):
        families = cii_engine._classify_article("Local sports team wins championship")
        assert families == []

    def test_theme_conflict(self):
        families = cii_engine._classify_article(
            "Something happened", themes=["ARMEDCONFLICT"]
        )
        assert "conflict" in families

    def test_theme_economy(self):
        families = cii_engine._classify_article(
            "Report released", themes=["ECON", "TRADE"]
        )
        assert "economy" in families

    def test_theme_climate(self):
        families = cii_engine._classify_article("Update", themes=["DISASTER", "FLOOD"])
        assert "climate" in families

    def test_theme_governance(self):
        families = cii_engine._classify_article(
            "Announcement", themes=["PROTEST", "ELECTION"]
        )
        assert "governance" in families

    def test_theme_and_keyword_combined(self):
        families = cii_engine._classify_article(
            "Protest march turns violent with casualties", themes=["PROTEST"]
        )
        assert "governance" in families
        assert "conflict" in families


# ---------------------------------------------------------------------------
# Score calculation
# ---------------------------------------------------------------------------


class TestScoreCalculation:
    def test_zero_count(self):
        assert cii_engine._family_score(0) == 0.0

    def test_single_article(self):
        score = cii_engine._family_score(1)
        assert 10 < score < 30

    def test_ten_articles(self):
        score = cii_engine._family_score(10)
        assert 40 < score < 70

    def test_fifty_articles(self):
        score = cii_engine._family_score(50)
        assert score >= 95.0

    def test_cii_all_zero(self):
        score = cii_engine._compute_cii(
            {"conflict": 0, "economy": 0, "climate": 0, "governance": 0}
        )
        assert score == 0.0

    def test_cii_conflict_only(self):
        score = cii_engine._compute_cii(
            {"conflict": 20, "economy": 0, "climate": 0, "governance": 0}
        )
        # Conflict is 40% weight
        conflict_sub = cii_engine._family_score(20)
        expected = round(conflict_sub * 0.40, 1)
        assert score == expected

    def test_cii_all_equal(self):
        signals = {"conflict": 10, "economy": 10, "climate": 10, "governance": 10}
        score = cii_engine._compute_cii(signals)
        sub = cii_engine._family_score(10)
        expected = round(sub * 0.40 + sub * 0.20 + sub * 0.20 + sub * 0.20, 1)
        assert score == expected

    def test_risk_band_stable(self):
        assert cii_engine._risk_band(0) == "stable"
        assert cii_engine._risk_band(10) == "stable"

    def test_risk_band_low(self):
        assert cii_engine._risk_band(15) == "low"
        assert cii_engine._risk_band(29) == "low"

    def test_risk_band_moderate(self):
        assert cii_engine._risk_band(30) == "moderate"
        assert cii_engine._risk_band(49) == "moderate"

    def test_risk_band_high(self):
        assert cii_engine._risk_band(50) == "high"
        assert cii_engine._risk_band(69) == "high"

    def test_risk_band_critical(self):
        assert cii_engine._risk_band(70) == "critical"
        assert cii_engine._risk_band(100) == "critical"


# ---------------------------------------------------------------------------
# Trend indicator
# ---------------------------------------------------------------------------


class TestTrendIndicator:
    def test_insufficient_data(self):
        assert cii_engine._trend_indicator([]) == "insufficient_data"
        assert cii_engine._trend_indicator([{"score": 50}]) == "insufficient_data"

    def test_stable(self):
        trend = [
            {"score": 40, "date": "2026-01-01"},
            {"score": 42, "date": "2026-01-02"},
            {"score": 41, "date": "2026-01-03"},
            {"score": 43, "date": "2026-01-04"},
        ]
        assert cii_engine._trend_indicator(trend) == "stable"

    def test_rising(self):
        trend = [
            {"score": 20, "date": "2026-01-01"},
            {"score": 22, "date": "2026-01-02"},
            {"score": 40, "date": "2026-01-03"},
            {"score": 45, "date": "2026-01-04"},
        ]
        assert cii_engine._trend_indicator(trend) == "rising"

    def test_falling(self):
        trend = [
            {"score": 60, "date": "2026-01-01"},
            {"score": 55, "date": "2026-01-02"},
            {"score": 30, "date": "2026-01-03"},
            {"score": 25, "date": "2026-01-04"},
        ]
        assert cii_engine._trend_indicator(trend) == "falling"


# ---------------------------------------------------------------------------
# Snapshot persistence
# ---------------------------------------------------------------------------


class TestSnapshotPersistence:
    def test_save_and_load(self):
        scores = {
            "TH": {
                "score": 35.0,
                "conflict": 20.0,
                "economy": 10.0,
                "climate": 5.0,
                "governance": 15.0,
                "article_count": 10,
                "event_count": 2,
            },
            "MM": {
                "score": 65.0,
                "conflict": 50.0,
                "economy": 20.0,
                "climate": 10.0,
                "governance": 30.0,
                "article_count": 25,
                "event_count": 5,
            },
        }
        cii_engine._save_snapshot(scores)
        prev = cii_engine._load_previous_snapshot("TH", hours_ago=0)
        assert prev is not None
        assert prev["score"] == 35.0

    def test_load_nonexistent(self):
        assert cii_engine._load_previous_snapshot("ZZ") is None

    def test_trend_load(self):
        scores = {
            "TH": {
                "score": 30.0,
                "conflict": 15.0,
                "economy": 10.0,
                "climate": 5.0,
                "governance": 10.0,
                "article_count": 5,
                "event_count": 0,
            },
        }
        # Save multiple snapshots
        for i in range(3):
            scores["TH"]["score"] = 30.0 + i * 5
            cii_engine._save_snapshot(scores)

        trend = cii_engine._load_trend("TH", days=7)
        assert len(trend) >= 3
        assert all("score" in t for t in trend)

    def test_save_empty(self):
        cii_engine._save_snapshot({})
        # Should not crash
        assert True


# ---------------------------------------------------------------------------
# Country extraction from articles
# ---------------------------------------------------------------------------


class TestCountryExtraction:
    def test_newsdata_country_code(self):
        art = {"country_code": "TH", "title": "Event", "description": ""}
        assert cii_engine._extract_country_from_article(art) == "TH"

    def test_gdelt_country_name(self):
        art = {"country": "Thailand", "title": "Event", "description": ""}
        assert cii_engine._extract_country_from_article(art) == "TH"

    def test_name_in_title(self):
        art = {"title": "Unrest in Myanmar escalates", "description": ""}
        assert cii_engine._extract_country_from_article(art) == "MM"

    def test_no_match(self):
        art = {"title": "Weather update", "description": ""}
        assert cii_engine._extract_country_from_article(art) is None

    def test_iso3_country_code(self):
        art = {"country_code": "THA", "title": "", "description": ""}
        assert cii_engine._extract_country_from_article(art) == "TH"


# ---------------------------------------------------------------------------
# Digest gathering
# ---------------------------------------------------------------------------


class TestDigestGathering:
    def test_digest_empty_cache(self):
        digest = cii_engine.gather_cii_digest()
        # With no feed data, should return enabled but empty or disabled
        assert isinstance(digest, dict)
        assert "enabled" in digest
        assert "count" in digest
        assert "lines" in digest

    def test_digest_with_mock_data(self):
        # Mock compute_all_cii to return test data
        mock_scores = {
            "TH": {
                "country_code": "TH",
                "country_name": "Thailand",
                "iso3": "THA",
                "score": 45.0,
                "risk_band": "moderate",
                "conflict": 30.0,
                "economy": 20.0,
                "climate": 10.0,
                "governance": 15.0,
                "article_count": 10,
                "event_count": 2,
                "computed_at": "2026-01-01T00:00:00Z",
            },
            "MM": {
                "country_code": "MM",
                "country_name": "Myanmar",
                "iso3": "MMR",
                "score": 72.0,
                "risk_band": "critical",
                "conflict": 60.0,
                "economy": 25.0,
                "climate": 15.0,
                "governance": 35.0,
                "article_count": 30,
                "event_count": 8,
                "computed_at": "2026-01-01T00:00:00Z",
            },
        }
        with patch("cii_engine.compute_all_cii", return_value=mock_scores):
            with patch("cii_engine._save_snapshot"):
                with patch("cii_engine._load_previous_snapshot", return_value=None):
                    with patch("cii_engine._load_trend", return_value=[]):
                        digest = cii_engine.gather_cii_digest()
        assert digest["enabled"] is True
        assert digest["count"] >= 1
        # Myanmar should be in top lines (score 72 > 15 threshold)
        texts = [line.get("text", "") for line in digest["lines"]]
        assert any("Myanmar" in t for t in texts)

    def test_digest_fail_soft(self):
        with patch("cii_engine.get_cii_rankings", side_effect=Exception("DB error")):
            digest = cii_engine.gather_cii_digest()
        assert digest["enabled"] is False
        assert digest["count"] == 0


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------


class TestAPIEndpoints:
    def test_country_endpoint_no_data(self):
        result = cii_engine.get_cii_country("TH")
        assert result["country_code"] == "TH"
        assert result["country_name"] == "Thailand"
        assert result["iso3"] == "THA"
        assert result["score"] == 0.0
        assert result["risk_band"] == "stable"

    def test_country_endpoint_name_input(self):
        result = cii_engine.get_cii_country("Thailand")
        assert result["country_code"] == "TH"

    def test_country_endpoint_iso3_input(self):
        result = cii_engine.get_cii_country("THA")
        assert result["country_code"] == "TH"

    def test_rankings_empty(self):
        result = cii_engine.get_cii_rankings()
        assert result["count"] >= 0
        assert "countries" in result
        assert "updated" in result

    def test_rankings_sorted_desc(self):
        mock_scores = {
            "TH": {
                "country_code": "TH",
                "country_name": "Thailand",
                "iso3": "THA",
                "score": 30.0,
                "risk_band": "moderate",
                "conflict": 20.0,
                "economy": 10.0,
                "climate": 5.0,
                "governance": 10.0,
                "article_count": 5,
                "event_count": 0,
                "computed_at": "2026-01-01T00:00:00Z",
            },
            "MM": {
                "country_code": "MM",
                "country_name": "Myanmar",
                "iso3": "MMR",
                "score": 70.0,
                "risk_band": "critical",
                "conflict": 50.0,
                "economy": 20.0,
                "climate": 10.0,
                "governance": 30.0,
                "article_count": 20,
                "event_count": 5,
                "computed_at": "2026-01-01T00:00:00Z",
            },
        }
        with patch("cii_engine.compute_all_cii", return_value=mock_scores):
            with patch("cii_engine._save_snapshot"):
                with patch("cii_engine._load_previous_snapshot", return_value=None):
                    with patch("cii_engine._load_trend", return_value=[]):
                        result = cii_engine.get_cii_rankings(refresh=True)
        assert result["count"] == 2
        assert result["countries"][0]["score"] >= result["countries"][1]["score"]
        assert result["countries"][0]["country_code"] == "MM"

    def test_rankings_cache(self):
        # First call populates cache
        with patch("cii_engine.compute_all_cii", return_value={}) as mock_compute:
            with patch("cii_engine._save_snapshot"):
                cii_engine.get_cii_rankings(refresh=True)
            # Second call should use cache (no refresh)
            cii_engine.get_cii_rankings(refresh=False)
            # compute_all_cii should only be called once (for refresh=True)
            assert mock_compute.call_count == 1


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    def test_enabled_default(self):
        # Default is "1" (on)
        old = os.environ.get("WORLDBASE_CII")
        os.environ["WORLDBASE_CII"] = "1"
        assert cii_engine._enabled() is True
        if old is None:
            del os.environ["WORLDBASE_CII"]
        else:
            os.environ["WORLDBASE_CII"] = old

    def test_disabled(self):
        old = os.environ.get("WORLDBASE_CII")
        os.environ["WORLDBASE_CII"] = "0"
        assert cii_engine._enabled() is False
        if old is None:
            del os.environ["WORLDBASE_CII"]
        else:
            os.environ["WORLDBASE_CII"] = old
