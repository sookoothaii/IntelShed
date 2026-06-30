"""Market overview bridge — crypto + equities/commodities, free sources, no key.

Purpose is *situational awareness*, not investment advice: WorldBase aims to
let every datapoint be cross-referenced so that broad market tendencies (risk-on
/ risk-off, drawdowns, crashes) become visible next to physical-world signals.

Two read-only, fail-soft endpoints, each with sparkline series + an aggregated
risk/sentiment roll-up so the UI can render a compact "what is the market doing"
overview:

* ``GET /api/markets/crypto`` — top coins (CoinGecko ``/coins/markets``),
  7-day sparkline, global market cap + BTC dominance, crypto Fear & Greed
  (alternative.me), and a derived ``risk`` block.
* ``GET /api/markets/stocks`` — indices, commodities and rate/vol gauges
  (Yahoo Finance chart endpoint), 1-month daily sparkline, breadth + VIX based
  ``risk`` block.

Everything is cached and degrades to stale cache / partial data on upstream
errors — never an HTTP 500.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/markets", tags=["markets"])

_UA = {"User-Agent": "WorldBase/1.0 (market situational awareness)"}

# Simple in-process cache: {key: (ts, payload)}
_CACHE: dict[str, tuple[float, dict]] = {}


def _cache_get(key: str, ttl: float) -> dict | None:
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def _cache_stale(key: str) -> dict | None:
    hit = _CACHE.get(key)
    return hit[1] if hit else None


def _cache_set(key: str, payload: dict) -> None:
    _CACHE[key] = (time.time(), payload)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pct_band(value: float | None, bands: list[tuple[float, str]], default: str) -> str:
    if value is None:
        return default
    for threshold, label in bands:
        if value <= threshold:
            return label
    return default


# ---------------------------------------------------------------------------
# Cross-feed market-stress summary — consumed by the 24h briefing so that a
# market regime (risk-off / drawdown) can be correlated with physical-world
# signals (outages, GDELT escalation, quakes). Pure functions, no I/O.
# ---------------------------------------------------------------------------

_LEVEL_ORDER = {"CALM": 0, "NORMAL": 1, "ELEVATED": 2, "HIGH": 3, "EXTREME": 4}


def summarize_market_stress(crypto: dict | None, stocks: dict | None) -> dict:
    """Fold the crypto + stocks ``risk`` blocks into one compact stress summary.

    Accepts the raw payloads returned by ``/api/markets/crypto`` and
    ``/api/markets/stocks``. Returns ``{}`` if neither carries a risk block.
    """
    cr = (crypto or {}).get("risk") or {}
    sr = (stocks or {}).get("risk") or {}
    c_level = cr.get("level")
    s_level = sr.get("level")
    levels = [lvl for lvl in (c_level, s_level) if lvl]
    if not levels:
        return {}
    overall = max(levels, key=lambda lvl: _LEVEL_ORDER.get(lvl, 0))
    return {
        "overall_level": overall,
        "crypto_level": c_level,
        "crypto_score": cr.get("score"),
        "fear_greed": cr.get("fear_greed"),
        "fear_greed_label": cr.get("fear_greed_label"),
        "stocks_level": s_level,
        "stocks_score": sr.get("score"),
        "vix": sr.get("vix"),
    }


def market_stress_severity(level: str | None) -> str:
    """Map a market-stress level to the briefing alert severity scale."""
    return {
        "CALM": "low",
        "NORMAL": "low",
        "ELEVATED": "medium",
        "HIGH": "high",
        "EXTREME": "high",
    }.get(level or "", "low")


def format_market_stress_line(summary: dict, lang: str = "en") -> str | None:
    """One-line, LLM-friendly market-stress description (or None if no data)."""
    if not summary:
        return None
    overall = summary.get("overall_level") or "—"
    fng = summary.get("fear_greed")
    vix = summary.get("vix")
    crypto = summary.get("crypto_level") or "—"
    equities = summary.get("stocks_level") or "—"
    fng_txt = f"Fear&Greed {fng}" if fng is not None else "Fear&Greed n/a"
    vix_txt = f"VIX {vix:.1f}" if isinstance(vix, (int, float)) else "VIX n/a"
    if lang.startswith("de"):
        return (
            f"Marktstress {overall}: Krypto {crypto} ({fng_txt}), "
            f"Aktien {equities} ({vix_txt})"
        )
    return (
        f"Market stress {overall}: crypto {crypto} ({fng_txt}), "
        f"equities {equities} ({vix_txt})"
    )


# ---------------------------------------------------------------------------
# Yahoo Finance chart helper (no key). Returns latest + change + sparkline.
# ---------------------------------------------------------------------------

_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"


async def _yahoo_series(
    client: httpx.AsyncClient, label: str, symbol: str, category: str
) -> dict | None:
    """One Yahoo symbol -> normalized quote with a 1-month daily sparkline."""
    try:
        r = await client.get(
            f"{_YAHOO_CHART}{symbol}",
            params={"interval": "1d", "range": "1mo"},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None

    result = (data.get("chart") or {}).get("result") or []
    if not result:
        return None
    res = result[0]
    meta = res.get("meta") or {}
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quote.get("close") or []
    spark = [round(float(c), 4) for c in closes if c is not None]
    if not spark:
        last = meta.get("regularMarketPrice")
        if last is None:
            return None
        spark = [float(last)]

    price = float(meta.get("regularMarketPrice") or spark[-1])
    prev = float(
        meta.get("chartPreviousClose")
        or meta.get("previousClose")
        or (spark[-2] if len(spark) > 1 else price)
    )
    change = price - prev
    change_pct = (change / prev * 100.0) if prev else 0.0
    # Trend over the whole sparkline window (≈1 month)
    base = spark[0] if spark else price
    trend_pct = ((spark[-1] - base) / base * 100.0) if base else 0.0

    return {
        "label": label,
        "symbol": symbol,
        "category": category,
        "name": meta.get("shortName") or meta.get("longName") or symbol,
        "currency": meta.get("currency"),
        "price": round(price, 4),
        "change": round(change, 4),
        "change_pct": round(change_pct, 2),
        "trend_pct": round(trend_pct, 2),
        "spark": spark[-30:],
    }


# Watchlists — chosen for broad-market situational coverage, not trading.
_INDICES = {
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "DOW": "^DJI",
    "DAX": "^GDAXI",
    "FTSE 100": "^FTSE",
    "EURO STOXX 50": "^STOXX50E",
    "NIKKEI 225": "^N225",
    "HANG SENG": "^HSI",
}
_COMMODITIES = {
    "GOLD": "GC=F",
    "SILVER": "SI=F",
    "WTI CRUDE": "CL=F",
    "BRENT": "BZ=F",
    "NAT GAS": "NG=F",
    "COPPER": "HG=F",
}
_RATES_FX = {
    "VIX": "^VIX",
    "US 10Y": "^TNX",
    "EUR/USD": "EURUSD=X",
    "USD/JPY": "JPY=X",
}


def _stocks_risk(indices: list[dict], rates_fx: list[dict]) -> dict:
    """Derive a market-stress roll-up from breadth + the VIX fear gauge."""
    board = indices
    advancers = sum(1 for q in board if (q.get("change_pct") or 0) > 0)
    decliners = sum(1 for q in board if (q.get("change_pct") or 0) < 0)
    changes = [q.get("change_pct") for q in board if q.get("change_pct") is not None]
    avg_change = round(sum(changes) / len(changes), 2) if changes else None

    vix = next((q for q in rates_fx if q.get("label") == "VIX"), None)
    vix_val = vix.get("price") if vix else None

    # Stress score 0-100 driven mostly by VIX, nudged by breadth.
    if vix_val is not None:
        score = max(0.0, min(100.0, (vix_val - 10.0) / 40.0 * 100.0))
    else:
        score = 50.0
    if avg_change is not None and avg_change < 0:
        score = min(100.0, score + min(20.0, abs(avg_change) * 4.0))
    score = round(score)

    level = _pct_band(
        score, [(25, "CALM"), (45, "NORMAL"), (65, "ELEVATED"), (82, "HIGH")], "EXTREME"
    )
    notes: list[str] = []
    if vix_val is not None:
        notes.append(f"VIX {vix_val:.1f}")
    if avg_change is not None:
        notes.append(
            f"index avg {'+' if avg_change >= 0 else ''}{avg_change:.2f}% (24h)"
        )
    notes.append(f"breadth {advancers}↑ / {decliners}↓")
    return {
        "level": level,
        "score": score,
        "advancers": advancers,
        "decliners": decliners,
        "avg_change": avg_change,
        "vix": vix_val,
        "notes": notes,
    }


@router.get("/stocks")
async def markets_stocks():
    """Indices, commodities and rate/vol gauges with sparklines + risk roll-up."""
    key = "markets:stocks"
    cached = _cache_get(key, ttl=120.0)
    if cached is not None:
        return cached

    jobs: list[tuple[str, str, str]] = []
    jobs += [(lbl, sym, "index") for lbl, sym in _INDICES.items()]
    jobs += [(lbl, sym, "commodity") for lbl, sym in _COMMODITIES.items()]
    jobs += [(lbl, sym, "rate_fx") for lbl, sym in _RATES_FX.items()]

    try:
        async with httpx.AsyncClient(
            timeout=20.0, headers=_UA, follow_redirects=True
        ) as client:
            results = await asyncio.gather(
                *[_yahoo_series(client, lbl, sym, cat) for lbl, sym, cat in jobs]
            )
    except Exception as e:
        stale = _cache_stale(key)
        if stale:
            return stale
        return {
            "error": str(e),
            "indices": [],
            "commodities": [],
            "rates_fx": [],
            "updated": _now_iso(),
        }

    quotes = [q for q in results if q]
    indices = [q for q in quotes if q["category"] == "index"]
    commodities = [q for q in quotes if q["category"] == "commodity"]
    rates_fx = [q for q in quotes if q["category"] == "rate_fx"]

    out = {
        "updated": _now_iso(),
        "source": "yahoo-finance",
        "count": len(quotes),
        "indices": indices,
        "commodities": commodities,
        "rates_fx": rates_fx,
        "risk": _stocks_risk(indices, rates_fx),
    }
    if not quotes:
        stale = _cache_stale(key)
        if stale:
            return stale
    _cache_set(key, out)
    return out


# ---------------------------------------------------------------------------
# Crypto — CoinGecko markets + global + alternative.me Fear & Greed.
# ---------------------------------------------------------------------------

_CG_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
_CG_GLOBAL = "https://api.coingecko.com/api/v3/global"
_FNG_URL = "https://api.alternative.me/fng/"

# Curated overview set (market leaders + privacy coin Monero for the
# security/anonymity angle). Sorted client-side by market cap.
_CRYPTO_IDS = (
    "bitcoin,ethereum,tether,binancecoin,solana,ripple,usd-coin,cardano,"
    "dogecoin,tron,avalanche-2,chainlink,polkadot,monero,litecoin,matic-network"
)


async def _fetch_fng(client: httpx.AsyncClient) -> dict | None:
    try:
        r = await client.get(_FNG_URL, params={"limit": "1"})
        r.raise_for_status()
        row = (r.json().get("data") or [])[0]
        return {
            "value": int(row.get("value")),
            "label": row.get("value_classification"),
            "updated": row.get("timestamp"),
        }
    except Exception:
        return None


async def _fetch_global(client: httpx.AsyncClient) -> dict | None:
    try:
        r = await client.get(_CG_GLOBAL)
        r.raise_for_status()
        d = (r.json() or {}).get("data") or {}
        return {
            "total_market_cap_usd": (d.get("total_market_cap") or {}).get("usd"),
            "total_volume_usd": (d.get("total_volume") or {}).get("usd"),
            "btc_dominance": (d.get("market_cap_percentage") or {}).get("btc"),
            "eth_dominance": (d.get("market_cap_percentage") or {}).get("eth"),
            "market_cap_change_24h": d.get("market_cap_change_percentage_24h_usd"),
            "active_cryptocurrencies": d.get("active_cryptocurrencies"),
        }
    except Exception:
        return None


async def _fetch_coins(client: httpx.AsyncClient) -> list[dict]:
    try:
        r = await client.get(
            _CG_MARKETS,
            params={
                "vs_currency": "usd",
                "ids": _CRYPTO_IDS,
                "order": "market_cap_desc",
                "sparkline": "true",
                "price_change_percentage": "1h,24h,7d",
            },
        )
        r.raise_for_status()
        rows = r.json() or []
    except Exception:
        return []
    coins: list[dict] = []
    for c in rows:
        spark = ((c.get("sparkline_in_7d") or {}).get("price")) or []
        # Down-sample 168 hourly points to ~48 for a light payload.
        if len(spark) > 48:
            step = len(spark) / 48.0
            spark = [round(float(spark[int(i * step)]), 4) for i in range(48)]
        else:
            spark = [round(float(x), 4) for x in spark]
        coins.append(
            {
                "id": c.get("id"),
                "symbol": (c.get("symbol") or "").upper(),
                "name": c.get("name"),
                "price": c.get("current_price"),
                "change_1h": c.get("price_change_percentage_1h_in_currency"),
                "change_24h": c.get("price_change_percentage_24h_in_currency"),
                "change_7d": c.get("price_change_percentage_7d_in_currency"),
                "market_cap": c.get("market_cap"),
                "market_cap_rank": c.get("market_cap_rank"),
                "volume": c.get("total_volume"),
                "high_24h": c.get("high_24h"),
                "low_24h": c.get("low_24h"),
                "ath": c.get("ath"),
                "ath_change_pct": c.get("ath_change_percentage"),
                "spark": spark,
            }
        )
    coins.sort(key=lambda x: x.get("market_cap") or 0, reverse=True)
    return coins


def _crypto_risk(coins: list[dict], glob: dict | None, fng: dict | None) -> dict:
    changes = [c.get("change_24h") for c in coins if c.get("change_24h") is not None]
    advancers = sum(1 for v in changes if v > 0)
    decliners = sum(1 for v in changes if v < 0)
    avg_change = round(sum(changes) / len(changes), 2) if changes else None
    mcap_change = (glob or {}).get("market_cap_change_24h")
    fng_val = (fng or {}).get("value")

    # Stress 0-100: fearful sentiment + negative cap move => higher stress.
    if fng_val is not None:
        score = (100 - fng_val) * 0.7
    else:
        score = 50.0
    if mcap_change is not None and mcap_change < 0:
        score = min(100.0, score + min(30.0, abs(mcap_change) * 3.0))
    score = round(score)

    level = _pct_band(
        score, [(25, "CALM"), (45, "NORMAL"), (65, "ELEVATED"), (82, "HIGH")], "EXTREME"
    )
    notes: list[str] = []
    if fng_val is not None:
        notes.append(f"Fear & Greed {fng_val} ({(fng or {}).get('label')})")
    if mcap_change is not None:
        notes.append(
            f"total cap {'+' if mcap_change >= 0 else ''}{mcap_change:.2f}% (24h)"
        )
    notes.append(f"breadth {advancers}↑ / {decliners}↓")
    return {
        "level": level,
        "score": score,
        "advancers": advancers,
        "decliners": decliners,
        "avg_change": avg_change,
        "fear_greed": fng_val,
        "fear_greed_label": (fng or {}).get("label"),
        "notes": notes,
    }


@router.get("/crypto")
async def markets_crypto():
    """Top coins with 7d sparklines, global cap/dominance, Fear & Greed + risk."""
    key = "markets:crypto"
    cached = _cache_get(key, ttl=90.0)
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(
            timeout=20.0, headers=_UA, follow_redirects=True
        ) as client:
            coins, glob, fng = await asyncio.gather(
                _fetch_coins(client),
                _fetch_global(client),
                _fetch_fng(client),
            )
    except Exception as e:
        stale = _cache_stale(key)
        if stale:
            return stale
        return {
            "error": str(e),
            "coins": [],
            "global": None,
            "fear_greed": None,
            "updated": _now_iso(),
        }

    out = {
        "updated": _now_iso(),
        "source": "coingecko + alternative.me",
        "count": len(coins),
        "coins": coins,
        "global": glob,
        "fear_greed": fng,
        "risk": _crypto_risk(coins, glob, fng),
    }
    if not coins:
        stale = _cache_stale(key)
        if stale:
            return stale
    _cache_set(key, out)
    return out
