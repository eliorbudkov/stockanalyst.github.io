"""Dynamic universe fetcher for large-cap indices and liquid Russell 2000 names.

S&P 500 and Nasdaq-100 constituents come from Wikipedia. Russell 2000 exposure
comes from official BlackRock IWM holdings and is capped by daily liquidity.
The deduplicated result is cached to disk for 24 hours.

If a refresh fails, a stale dynamic cache is used. No hardcoded constituent
list is used.
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf
from curl_cffi import requests as curl_requests

log = logging.getLogger(__name__)

CACHE_FILE = Path(__file__).parent / "data" / "universe.json"
MOMENTUM_CACHE_FILE = Path(__file__).parent / "data" / "momentum_universe.json"
CACHE_FILE.parent.mkdir(exist_ok=True)
YFINANCE_CACHE_DIR = CACHE_FILE.parent / ".yfinance-cache"
YFINANCE_CACHE_DIR.mkdir(exist_ok=True)
yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))
CACHE_TTL_SECONDS = 24 * 60 * 60
MOMENTUM_CACHE_TTL_SECONDS = 15 * 60
MOMENTUM_SCREEN_SIZE = 50
RUSSELL_LIQUID_LIMIT = 500
RUSSELL_VOLUME_BATCH_SIZE = 50

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NASDAQ100_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"
IWM_HOLDINGS_URL = (
    "https://www.ishares.com/us/products/239710/"
    "ishares-russell-2000-etf/1467271812596.ajax"
    "?fileType=csv&fileName=IWM_holdings&dataType=fund"
)
BLACKROCK_PRODUCT_DATA_URL = (
    "https://www.blackrock.com/varnish-api/blk-one01-product-data/"
    "product-data/api/v2/get-product-data"
)

# Map Wikipedia GICS sector names → the canonical names used in heatmap.py
SECTOR_NORMALIZATION: dict[str, str] = {
    "Information Technology": "Technology",
    "Communication Services": "Communication",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Financials": "Financials",
    "Financial Services": "Financials",
    "Health Care": "Healthcare",
    "Healthcare": "Healthcare",
    "Industrials": "Industrials",
    "Real Estate": "Real Estate",
    "Energy": "Energy",
    "Utilities": "Utilities",
    "Materials": "Materials",
}


def _normalise_symbol(sym: str) -> str:
    # yfinance uses BRK-B, not BRK.B
    return sym.strip().upper().replace(".", "-")


def _is_supported_equity_symbol(symbol: str) -> bool:
    return bool(re.fullmatch(r"[A-Z][A-Z0-9-]{0,9}", symbol))


def _fetch_sp500() -> list[dict[str, Any]]:
    tables = _read_tables(SP500_URL)
    df = tables[0]
    cols = {str(c).strip(): c for c in df.columns}

    # Column names on Wikipedia have shifted over time; tolerate variants.
    sym_col = next((cols[c] for c in cols if c in ("Symbol", "Ticker symbol", "Ticker")), None)
    name_col = next((cols[c] for c in cols if c in ("Security", "Company", "Name")), None)
    sector_col = next((cols[c] for c in cols if c in ("GICS Sector", "Sector")), None)
    if not (sym_col and name_col):
        raise ValueError("S&P 500 table missing expected columns")

    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        sym = _normalise_symbol(str(row[sym_col]))
        if not sym or len(sym) > 6:
            continue
        name = str(row[name_col]).strip()
        sec_raw = str(row[sector_col]).strip() if sector_col else ""
        sector = SECTOR_NORMALIZATION.get(sec_raw, sec_raw or "Unknown")
        out.append({"symbol": sym, "name": name, "sector": sector, "source": "sp500"})
    return out


def _fetch_nasdaq100() -> list[dict[str, Any]]:
    tables = _read_tables(NASDAQ100_URL)
    # The constituent table is whichever has a Ticker/Symbol column
    target_df = None
    for df in tables:
        col_names = [str(c).strip() for c in df.columns]
        if any(c in ("Ticker", "Symbol") for c in col_names):
            target_df = df
            break
    if target_df is None:
        raise ValueError("Nasdaq-100 constituent table not found")

    cols = {str(c).strip(): c for c in target_df.columns}
    sym_col = next((cols[c] for c in cols if c in ("Ticker", "Symbol")), None)
    name_col = next((cols[c] for c in cols if c in ("Company", "Security", "Name")), None)
    sector_col = next(
        (cols[c] for c in cols if c in ("GICS Sector", "Sector", "GICS Sub-Industry")),
        None,
    )

    out: list[dict[str, Any]] = []
    for _, row in target_df.iterrows():
        if not sym_col:
            continue
        sym = _normalise_symbol(str(row[sym_col]))
        if not sym or len(sym) > 6:
            continue
        name = str(row[name_col]).strip() if name_col else ""
        sec_raw = str(row[sector_col]).strip() if sector_col else ""
        sector = SECTOR_NORMALIZATION.get(sec_raw, sec_raw or "Technology")
        out.append({"symbol": sym, "name": name, "sector": sector, "source": "nasdaq100"})
    return out


def _parse_iwm_holdings_csv(text: str) -> list[dict[str, Any]]:
    """Parse the metadata-prefixed official IWM holdings CSV."""
    lines = text.splitlines()
    header_index = next(
        (
            index
            for index, line in enumerate(lines)
            if line.lstrip("\ufeff").startswith("Ticker,Name,")
        ),
        None,
    )
    if header_index is None:
        raise ValueError("IWM holdings CSV header not found")

    df = pd.read_csv(StringIO("\n".join(lines[header_index:])))
    if "Ticker" not in df.columns:
        raise ValueError("IWM holdings CSV missing Ticker column")

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for _, row in df.iterrows():
        if "Asset Class" in df.columns and str(row.get("Asset Class", "")).strip() != "Equity":
            continue
        symbol = _normalise_symbol(str(row.get("Ticker") or ""))
        if symbol in seen or not _is_supported_equity_symbol(symbol):
            continue
        seen.add(symbol)
        sector_raw = str(row.get("Sector") or "").strip()
        out.append({
            "symbol": symbol,
            "name": str(row.get("Name") or symbol).strip(),
            "sector": SECTOR_NORMALIZATION.get(sector_raw, sector_raw or "Unknown"),
            "source": "russell2000",
        })
    if not out:
        raise ValueError("IWM holdings CSV contained no supported equities")
    return out


def _parse_iwm_holdings_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse the current BlackRock product-data response for IWM holdings."""
    try:
        data_points = (
            payload["componentsByNameMap"]["holdings"]
            ["containersByNameMap"]["all"]["dataPointsByNameMap"]
        )
        tickers = data_points["ticker"]["value"]
        names = data_points["issueName"]["value"]
        sectors = data_points["sectorName"]["value"]
        asset_classes = data_points["assetClass"]["value"]
    except (KeyError, TypeError) as exc:
        raise ValueError("BlackRock IWM holdings payload is incomplete") from exc

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ticker, name, sector_raw, asset_class in zip(
        tickers,
        names,
        sectors,
        asset_classes,
    ):
        if str(asset_class).strip() != "Equity":
            continue
        symbol = _normalise_symbol(str(ticker or ""))
        if symbol in seen or not _is_supported_equity_symbol(symbol):
            continue
        seen.add(symbol)
        sector_text = str(sector_raw or "").strip()
        out.append({
            "symbol": symbol,
            "name": str(name or symbol).strip(),
            "sector": SECTOR_NORMALIZATION.get(
                sector_text,
                sector_text or "Unknown",
            ),
            "source": "russell2000",
        })
    if not out:
        raise ValueError("BlackRock IWM payload contained no supported equities")
    return out


def _fetch_iwm_holdings() -> list[dict[str, Any]]:
    params = {
        "appSubType": "ISHARES",
        "appType": "PRODUCT_PAGE",
        "component": "holdings.all",
        "locale": "en_US",
        "portfolioId": "239710",
        "targetSite": "us-ishares",
        "userType": "individual",
        "excludeContent": "true",
        "asOfDate": "",
        "includeConfig": "true",
    }
    try:
        response = curl_requests.get(
            BLACKROCK_PRODUCT_DATA_URL,
            params=params,
            impersonate="chrome",
            headers={"Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        return _parse_iwm_holdings_payload(response.json())
    except Exception as api_exc:
        log.warning("BlackRock IWM JSON fetch failed; trying legacy CSV: %s", api_exc)

    response = curl_requests.get(
        IWM_HOLDINGS_URL,
        impersonate="chrome",
        headers={"Accept": "text/csv,*/*"},
        timeout=30,
    )
    response.raise_for_status()
    return _parse_iwm_holdings_csv(response.text)


def _latest_daily_volumes(
    symbols: list[str],
    batch_size: int = RUSSELL_VOLUME_BATCH_SIZE,
) -> dict[str, float]:
    """Fetch latest positive daily volume sequentially in bounded batches."""
    bounded_batch_size = max(1, min(int(batch_size), RUSSELL_VOLUME_BATCH_SIZE))
    volumes: dict[str, float] = {}

    for start in range(0, len(symbols), bounded_batch_size):
        chunk = symbols[start:start + bounded_batch_size]
        try:
            raw = yf.download(
                chunk,
                period="5d",
                interval="1d",
                auto_adjust=True,
                progress=False,
                group_by="ticker",
                threads=True,
            )
        except Exception as exc:
            log.warning("Russell volume batch failed (%s symbols): %s", len(chunk), exc)
            continue

        for symbol in chunk:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    if symbol in raw.columns.get_level_values(0):
                        series = raw[symbol]["Volume"]
                    else:
                        series = raw["Volume"][symbol]
                elif len(chunk) == 1:
                    series = raw["Volume"]
                else:
                    continue
                positive = pd.to_numeric(series, errors="coerce")
                positive = positive[positive > 0].dropna()
                if not positive.empty:
                    volumes[symbol] = float(positive.iloc[-1])
            except (KeyError, TypeError, ValueError):
                continue
    return volumes


def _select_liquid_russell(
    holdings: list[dict[str, Any]],
    excluded_symbols: set[str],
    limit: int = RUSSELL_LIQUID_LIMIT,
) -> list[dict[str, Any]]:
    """Remove overlaps, rank by latest volume, and retain the requested names."""
    unique: dict[str, dict[str, Any]] = {}
    for entry in holdings:
        symbol = str(entry.get("symbol") or "")
        if symbol and symbol not in excluded_symbols:
            unique.setdefault(symbol, entry)

    volumes = _latest_daily_volumes(sorted(unique))
    ranked = sorted(
        (
            {**unique[symbol], "daily_volume": volume}
            for symbol, volume in volumes.items()
            if volume > 0
        ),
        key=lambda entry: (-float(entry["daily_volume"]), entry["symbol"]),
    )
    bounded_limit = max(1, min(int(limit), RUSSELL_LIQUID_LIMIT))
    return ranked[:bounded_limit]


def _fetch_russell2000(excluded_symbols: set[str]) -> list[dict[str, Any]]:
    return _select_liquid_russell(_fetch_iwm_holdings(), excluded_symbols)


def _read_tables(url: str) -> list[pd.DataFrame]:
    """Fetch Wikipedia with a browser user-agent, then parse its HTML tables."""
    response = curl_requests.get(
        url,
        impersonate="chrome",
        headers={"Accept": "text/html,application/xhtml+xml"},
        timeout=20,
    )
    response.raise_for_status()
    return pd.read_html(StringIO(response.text))


def _fetch_momentum_screen(screen_name: str) -> list[dict[str, Any]]:
    payload = yf.screen(screen_name, count=MOMENTUM_SCREEN_SIZE)
    quotes = payload.get("quotes") or []
    results: list[dict[str, Any]] = []
    for quote in quotes:
        if quote.get("quoteType") != "EQUITY":
            continue
        if quote.get("market") not in (None, "us_market"):
            continue
        symbol = _normalise_symbol(str(quote.get("symbol") or ""))
        if not _is_supported_equity_symbol(symbol):
            continue
        results.append({
            "symbol": symbol,
            "name": str(
                quote.get("longName")
                or quote.get("shortName")
                or quote.get("displayName")
                or symbol
            ),
            "sector": "Unknown",
            "source": screen_name,
            "momentum_sources": [screen_name],
            "screener_change_pct": quote.get("regularMarketChangePercent"),
            "screener_volume": quote.get("regularMarketVolume"),
            "screener_avg_volume": quote.get("averageDailyVolume3Month"),
        })
    return results


def get_momentum_universe(force: bool = False) -> list[dict[str, Any]]:
    """Return deduplicated daily Top Gainers + Most Active US equities."""
    now = time.time()
    stale_cache: list[dict[str, Any]] | None = None
    if MOMENTUM_CACHE_FILE.exists():
        try:
            cached = json.loads(MOMENTUM_CACHE_FILE.read_text(encoding="utf-8"))
            stale_cache = cached.get("universe")
            if not force and now - float(cached.get("ts", 0)) < MOMENTUM_CACHE_TTL_SECONDS:
                return stale_cache or []
        except Exception:
            pass

    fetched: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {
            name: pool.submit(_fetch_momentum_screen, name)
            for name in ("day_gainers", "most_actives")
        }
        for name, future in futures.items():
            try:
                fetched.extend(future.result())
            except Exception as exc:
                log.warning("%s screener fetch failed: %s", name, exc)

    by_symbol: dict[str, dict[str, Any]] = {}
    for entry in fetched:
        symbol = entry["symbol"]
        existing = by_symbol.get(symbol)
        if existing is None:
            by_symbol[symbol] = entry
            continue
        sources = set(existing.get("momentum_sources") or [])
        sources.update(entry.get("momentum_sources") or [])
        existing["momentum_sources"] = sorted(sources)

    universe = sorted(by_symbol.values(), key=lambda item: item["symbol"])
    if not universe and stale_cache:
        log.warning("Momentum screeners unavailable; using stale momentum cache")
        return stale_cache

    try:
        MOMENTUM_CACHE_FILE.write_text(
            json.dumps({"ts": now, "universe": universe}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        log.warning("momentum universe cache write failed: %s", exc)
    return universe


def get_universe(force: bool = False) -> list[dict[str, Any]]:
    """Returns deduplicated S&P 500 ∪ Nasdaq-100 with disk-backed 24h cache."""
    now = time.time()
    stale_cache: list[dict[str, Any]] | None = None
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            stale_cache = cached.get("universe")
            if not force and now - float(cached.get("ts", 0)) < CACHE_TTL_SECONDS:
                return cached["universe"]
        except Exception:
            pass

    sp: list[dict[str, Any]] = []
    ndx: list[dict[str, Any]] = []
    try:
        sp = _fetch_sp500()
    except Exception as e:
        log.warning("S&P 500 fetch failed: %s", e)
    try:
        ndx = _fetch_nasdaq100()
    except Exception as e:
        log.warning("Nasdaq-100 fetch failed: %s", e)

    # Dedupe by symbol; S&P 500 records win on conflict (richer sector data).
    by_symbol: dict[str, dict[str, Any]] = {}
    for entry in ndx:
        by_symbol[entry["symbol"]] = entry
    for entry in sp:
        by_symbol[entry["symbol"]] = entry

    try:
        russell = _fetch_russell2000(set(by_symbol))
        for entry in russell:
            by_symbol.setdefault(entry["symbol"], entry)
    except Exception as e:
        log.warning("Russell 2000 liquid universe fetch failed: %s", e)

    universe = sorted(by_symbol.values(), key=lambda x: x["symbol"])
    if not universe:
        log.warning("Both Wikipedia fetches failed — using hardcoded fallback list")
        if stale_cache:
            return stale_cache
        raise RuntimeError("Dynamic US equity universe unavailable and cache is empty")

    try:
        CACHE_FILE.write_text(
            json.dumps({"ts": now, "universe": universe}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("universe cache write failed: %s", e)

    return universe
