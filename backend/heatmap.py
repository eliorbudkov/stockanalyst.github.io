"""S&P 500 mini-heatmap.

Fetches a curated list of ~60 major S&P 500 components grouped by GICS sector,
computes today's percent change, and caches for 5 minutes. Used by the home
dashboard as a market-temperature widget.
"""
from __future__ import annotations

import math
import time
from typing import Any

import pandas as pd
import yfinance as yf

CACHE_TTL_SECONDS = 300  # 5 minutes


# Approximate market caps in $B — used as fixed weights for treemap sizing so
# we don't pay 60 yfinance .info calls per request. Refresh occasionally.
SP500_MARKET_CAP_B: dict[str, float] = {
    "AAPL": 3500, "MSFT": 3200, "NVDA": 3400, "AVGO": 1100, "ORCL": 700,
    "ADBE": 280, "CRM": 280, "AMD": 250, "INTC": 150, "CSCO": 250,
    "IBM": 200, "QCOM": 200,
    "GOOGL": 2400, "META": 1700, "NFLX": 300, "DIS": 200, "TMUS": 270, "VZ": 180,
    "AMZN": 2200, "TSLA": 1200, "HD": 400, "MCD": 220, "NKE": 130, "SBUX": 100,
    "BKNG": 150,
    "WMT": 800, "COST": 430, "PG": 400, "KO": 290, "PEP": 220,
    "JPM": 700, "BAC": 360, "WFC": 250, "GS": 200, "MS": 180,
    "V": 600, "MA": 500, "AXP": 220, "BLK": 170,
    "PNC": 80, "SCHW": 130, "USB": 70, "COF": 65, "BX": 170,
    "UNH": 450, "JNJ": 420, "LLY": 800, "ABBV": 370,
    "PFE": 160, "MRK": 280, "ABT": 230, "TMO": 200,
    "XOM": 480, "CVX": 280, "COP": 130, "EOG": 75,
    "CAT": 200, "BA": 130, "HON": 140, "UPS": 110, "RTX": 170, "GE": 220,
    "AMT": 100, "PLD": 110,
    "NEE": 150, "DUK": 90,
    "LIN": 220, "APD": 70,
}


# 11 GICS sectors with representative large-caps. Order matters for display.
SP500_STOCKS: list[tuple[str, str, str]] = [
    # (symbol, sector, name)
    # ── Technology ──
    ("AAPL",  "Technology",            "Apple"),
    ("MSFT",  "Technology",            "Microsoft"),
    ("NVDA",  "Technology",            "Nvidia"),
    ("AVGO",  "Technology",            "Broadcom"),
    ("ORCL",  "Technology",            "Oracle"),
    ("ADBE",  "Technology",            "Adobe"),
    ("CRM",   "Technology",            "Salesforce"),
    ("AMD",   "Technology",            "AMD"),
    ("INTC",  "Technology",            "Intel"),
    ("CSCO",  "Technology",            "Cisco"),
    ("IBM",   "Technology",            "IBM"),
    ("QCOM",  "Technology",            "Qualcomm"),

    # ── Communication ──
    ("GOOGL", "Communication",         "Alphabet"),
    ("META",  "Communication",         "Meta"),
    ("NFLX",  "Communication",         "Netflix"),
    ("DIS",   "Communication",         "Disney"),
    ("TMUS",  "Communication",         "T-Mobile"),
    ("VZ",    "Communication",         "Verizon"),

    # ── Consumer Discretionary ──
    ("AMZN",  "Consumer Discretionary","Amazon"),
    ("TSLA",  "Consumer Discretionary","Tesla"),
    ("HD",    "Consumer Discretionary","Home Depot"),
    ("MCD",   "Consumer Discretionary","McDonald's"),
    ("NKE",   "Consumer Discretionary","Nike"),
    ("SBUX",  "Consumer Discretionary","Starbucks"),
    ("BKNG",  "Consumer Discretionary","Booking"),

    # ── Consumer Staples ──
    ("WMT",   "Consumer Staples",      "Walmart"),
    ("COST",  "Consumer Staples",      "Costco"),
    ("PG",    "Consumer Staples",      "Procter & Gamble"),
    ("KO",    "Consumer Staples",      "Coca-Cola"),
    ("PEP",   "Consumer Staples",      "PepsiCo"),

    # ── Financials ──
    ("JPM",   "Financials",            "JPMorgan"),
    ("BAC",   "Financials",            "Bank of America"),
    ("WFC",   "Financials",            "Wells Fargo"),
    ("GS",    "Financials",            "Goldman Sachs"),
    ("MS",    "Financials",            "Morgan Stanley"),
    ("V",     "Financials",            "Visa"),
    ("MA",    "Financials",            "Mastercard"),
    ("AXP",   "Financials",            "American Express"),
    ("BLK",   "Financials",            "BlackRock"),
    ("PNC",   "Financials",            "PNC Financial Services"),
    ("SCHW",  "Financials",            "Charles Schwab"),
    ("USB",   "Financials",            "U.S. Bancorp"),
    ("COF",   "Financials",            "Capital One"),
    ("BX",    "Financials",            "Blackstone"),

    # ── Healthcare ──
    ("UNH",   "Healthcare",            "UnitedHealth"),
    ("JNJ",   "Healthcare",            "Johnson & Johnson"),
    ("LLY",   "Healthcare",            "Eli Lilly"),
    ("ABBV",  "Healthcare",            "AbbVie"),
    ("PFE",   "Healthcare",            "Pfizer"),
    ("MRK",   "Healthcare",            "Merck"),
    ("ABT",   "Healthcare",            "Abbott"),
    ("TMO",   "Healthcare",            "Thermo Fisher"),

    # ── Energy ──
    ("XOM",   "Energy",                "ExxonMobil"),
    ("CVX",   "Energy",                "Chevron"),
    ("COP",   "Energy",                "ConocoPhillips"),
    ("EOG",   "Energy",                "EOG Resources"),

    # ── Industrials ──
    ("CAT",   "Industrials",           "Caterpillar"),
    ("BA",    "Industrials",           "Boeing"),
    ("HON",   "Industrials",           "Honeywell"),
    ("UPS",   "Industrials",           "UPS"),
    ("RTX",   "Industrials",           "RTX"),
    ("GE",    "Industrials",           "GE Aerospace"),

    # ── Real Estate ──
    ("AMT",   "Real Estate",           "American Tower"),
    ("PLD",   "Real Estate",           "Prologis"),

    # ── Utilities ──
    ("NEE",   "Utilities",             "NextEra Energy"),
    ("DUK",   "Utilities",             "Duke Energy"),

    # ── Materials ──
    ("LIN",   "Materials",             "Linde"),
    ("APD",   "Materials",             "Air Products"),
]

# Hebrew sector labels for display
SECTOR_HE = {
    "Technology":             "טכנולוגיה",
    "Communication":          "תקשורת",
    "Consumer Discretionary": "מוצרי צריכה - מותרות",
    "Consumer Staples":       "מוצרי צריכה - בסיסיים",
    "Financials":             "פיננסים",
    "Healthcare":             "בריאות",
    "Energy":                 "אנרגיה",
    "Industrials":            "תעשייה",
    "Real Estate":            "נדל\"ן",
    "Utilities":              "תשתיות",
    "Materials":              "חומרי גלם",
}


_cache: dict[str, Any] = {"data": None, "ts": 0.0}


def _safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _build_heatmap() -> dict[str, Any]:
    symbols = [s[0] for s in SP500_STOCKS]
    # Batch download in one HTTP request; yfinance returns a multi-index DataFrame.
    raw = yf.download(
        symbols,
        period="5d",
        interval="1d",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )

    stocks: list[dict[str, Any]] = []
    for symbol, sector, name in SP500_STOCKS:
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                sub = raw[symbol].dropna()
            else:
                sub = raw.dropna()
            if sub is None or len(sub) < 2:
                continue
            last_close = _safe_float(sub["Close"].iloc[-1])
            prev_close = _safe_float(sub["Close"].iloc[-2])
            if last_close is None or prev_close is None or prev_close == 0:
                continue
            change_pct = (last_close - prev_close) / prev_close * 100.0
            stocks.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "sector": sector,
                    "sector_label": SECTOR_HE.get(sector, sector),
                    "price": round(last_close, 2),
                    "prev_close": round(prev_close, 2),
                    "change_pct": round(change_pct, 2),
                    "market_cap_b": SP500_MARKET_CAP_B.get(symbol, 50.0),
                }
            )
        except Exception:
            # Quietly skip symbols that yfinance failed on; the rest still render.
            continue

    # Sort by market cap descending so the treemap renderer can apply the
    # squarified algorithm cleanly (largest first → most square tiles).
    stocks.sort(key=lambda s: -s["market_cap_b"])

    advancers = sum(1 for s in stocks if s["change_pct"] > 0)
    decliners = sum(1 for s in stocks if s["change_pct"] < 0)
    avg_change = (
        round(sum(s["change_pct"] for s in stocks) / len(stocks), 2)
        if stocks
        else None
    )

    return {
        "stocks": stocks,
        "summary": {
            "total": len(stocks),
            "advancers": advancers,
            "decliners": decliners,
            "unchanged": len(stocks) - advancers - decliners,
            "avg_change_pct": avg_change,
        },
        "fetched_at": time.time(),
    }


def get_sp500_heatmap(force: bool = False) -> dict[str, Any]:
    now = time.time()
    if not force and _cache["data"] is not None and now - _cache["ts"] < CACHE_TTL_SECONDS:
        return _cache["data"]
    data = _build_heatmap()
    _cache["data"] = data
    _cache["ts"] = now
    return data


# yfinance reports slightly different sector names than ours — bridge them
# so we can correctly classify a stock against the heatmap's sector buckets.
YFINANCE_SECTOR_MAP: dict[str, str] = {
    "Technology": "Technology",
    "Information Technology": "Technology",
    "Communication Services": "Communication",
    "Communication": "Communication",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Consumer Staples": "Consumer Staples",
    "Financial Services": "Financials",
    "Financial": "Financials",
    "Financials": "Financials",
    "Healthcare": "Healthcare",
    "Health Care": "Healthcare",
    "Industrials": "Industrials",
    "Real Estate": "Real Estate",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Basic Materials": "Materials",
    "Materials": "Materials",
}


def get_sector_status(yfinance_sector: str | None) -> dict[str, Any] | None:
    """Average daily change for a stock's sector, derived from the heatmap.

    Returns None if the sector can't be mapped or the heatmap can't be fetched.
    The Hebrew label is returned for direct UI use.
    """
    if not yfinance_sector:
        return None
    canonical = YFINANCE_SECTOR_MAP.get(yfinance_sector.strip())
    if canonical is None:
        return None
    return _status_for_canonical_sector(canonical)


def _status_for_canonical_sector(canonical: str) -> dict[str, Any] | None:
    try:
        hm = get_sp500_heatmap(force=False)
    except Exception:
        return None
    matches = [s for s in hm["stocks"] if s["sector"] == canonical]
    if not matches:
        return None
    avg = sum(s["change_pct"] for s in matches) / len(matches)
    advancers = sum(1 for s in matches if s["change_pct"] > 0)
    decliners = sum(1 for s in matches if s["change_pct"] < 0)
    return {
        "sector": canonical,
        "sector_label": SECTOR_HE.get(canonical, canonical),
        "avg_change_pct": round(avg, 2),
        "is_red": avg <= -1.0,
        "is_green": avg >= 1.0,
        "advancers": advancers,
        "decliners": decliners,
        "members": len(matches),
    }


# Sector ETF → canonical sector. yfinance returns `sector: null` for ETFs,
# which broke sector identification in /api/analyze (sector_status was None
# for XLV, XLK, etc.). This map restores the link so ETFs can:
#   • benefit from sector tailwind in the short-term matrix
#   • trigger the algorithmic blocker when their underlying sector is red
ETF_TO_SECTOR: dict[str, str] = {
    "XLK":  "Technology",
    "XLC":  "Communication",
    "SOXX": "Technology",
    "ARKK": "Technology",
    "XLY":  "Consumer Discretionary",
    "XLP":  "Consumer Staples",
    "XLF":  "Financials",
    "XLV":  "Healthcare",
    "XLE":  "Energy",
    "XLI":  "Industrials",
    "XLRE": "Real Estate",
    "XLU":  "Utilities",
    "XLB":  "Materials",
    # Broad-market ETFs (SPY, QQQ, IWM, DIA, VTI) intentionally omitted —
    # they are not a single sector.
}


def get_sector_status_for_symbol(
    symbol: str | None,
    yfinance_sector: str | None,
) -> dict[str, Any] | None:
    """Sector status that also handles sector ETFs (yfinance returns null
    for their `sector` field). Preferred over `get_sector_status` whenever
    the symbol is known.
    """
    # 1. Try yfinance's sector (works for ordinary stocks).
    primary = get_sector_status(yfinance_sector)
    if primary is not None:
        return primary

    # 2. Fall back to the ETF→sector map.
    if not symbol:
        return None
    canonical = ETF_TO_SECTOR.get(symbol.upper().strip())
    if canonical is None:
        return None
    return _status_for_canonical_sector(canonical)
