"""Stock & index prices via Yahoo Finance (unofficial but stable JSON endpoints).
No API key required. Rate-limit friendly polling.
"""

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["stocks"])

# Yahoo Finance unofficial quote endpoint
_YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"

# Default watchlist
_WATCHLIST = {
    "DAX": "^GDAXI",
    "S&P500": "^GSPC",
    "NASDAQ": "^IXIC",
    "NIKKEI": "^N225",
    "EUR-USD": "EURUSD=X",
    "GOLD": "GC=F",
    "OIL": "CL=F",
    "BTC-USD": "BTC-USD",
    "ETH-USD": "ETH-USD",
}

_stock_cache = {}
_STOCK_TTL = 120  # 2 minutes


async def _fetch_yahoo(symbol: str):
    """Fetch latest quote for a Yahoo Finance symbol."""
    url = f"{_YAHOO_QUOTE_URL}{symbol}"
    params = {"interval": "1d", "range": "2d"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(
                url, params=params, headers={"User-Agent": "Mozilla/5.0"}
            )
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return {"error": str(e)}

    chart = data.get("chart", {})
    result = chart.get("result", [])
    if not result:
        return {"error": "no data"}

    res = result[0]
    meta = res.get("meta", {})
    timestamps = res.get("timestamp", [])
    closes = res.get("indicators", {}).get("quote", [{}])[0].get("close", [])

    if not timestamps or not closes:
        return {"error": "incomplete data"}

    # Filter out None values
    valid = [(ts, c) for ts, c in zip(timestamps, closes) if c is not None]
    if len(valid) < 1:
        return {"error": "no valid close prices"}

    latest_ts, latest_close = valid[-1]
    prev_close = valid[-2][1] if len(valid) > 1 else latest_close
    change = latest_close - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0

    return {
        "symbol": symbol,
        "name": meta.get("shortName") or meta.get("longName") or meta.get("symbol"),
        "currency": meta.get("currency"),
        "price": round(latest_close, 2),
        "previous_close": round(prev_close, 2),
        "change": round(change, 2),
        "change_pct": round(change_pct, 2),
        "timestamp": datetime.fromtimestamp(latest_ts, timezone.utc).isoformat(),
    }


@router.get("/stocks")
async def get_stocks():
    """Stock and index quotes from Yahoo Finance. Cached 2 minutes. No key.
    Covers: DAX, S&P500, NASDAQ, NIKKEI, EUR-USD, Gold, Oil, BTC, ETH.
    """
    now = datetime.now(timezone.utc).timestamp()
    cached = _stock_cache.get("watchlist")
    if cached and (now - cached["ts"]) < _STOCK_TTL:
        return cached["data"]

    items = []
    errors = []
    for label, symbol in _WATCHLIST.items():
        try:
            quote = await _fetch_yahoo(symbol)
            if "error" in quote:
                errors.append({label: quote["error"]})
            else:
                quote["label"] = label
                items.append(quote)
        except Exception as e:
            errors.append({label: str(e)})

    result = {
        "count": len(items),
        "updated": datetime.now(timezone.utc).isoformat(),
        "quotes": items,
        "errors": errors if errors else None,
    }

    _stock_cache["watchlist"] = {"ts": now, "data": result}
    return result
