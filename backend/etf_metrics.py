"""ETF-specific metrics: net inflows (proxy via shares outstanding) and
weighted-average debt/equity for the underlying holdings.

These feed the ETF-only matrix in `matrices.compute_etf_score` — DCF, P/E and
insider data don't apply to passive index products, so we replace them with
proxies that actually move with ETF performance: AUM flow direction and the
financial leverage of the basket.
"""
from __future__ import annotations

import math
import time
from typing import Any

import pandas as pd
import yfinance as yf


_inflows_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}
INFLOWS_TTL_SECONDS = 12 * 60 * 60


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


def compute_net_inflows(symbol: str) -> dict[str, Any] | None:
    """Estimate 30-day net inflows via change in shares outstanding.

    ETFs grow/shrink share count via creation/redemption units, so Δshares
    is a reliable proxy for net inflows (no need for paid flow-data vendors).
    Cached for 12h since it doesn't move intraday.
    """
    now = time.time()
    cached = _inflows_cache.get(symbol)
    if cached is not None and now - cached[0] < INFLOWS_TTL_SECONDS:
        return cached[1]

    try:
        ticker = yf.Ticker(symbol)
        # 90 days of shares-outstanding readings — enough for a 30-day delta.
        start = pd.Timestamp.utcnow() - pd.Timedelta(days=90)
        shares = ticker.get_shares_full(start=start)
        if shares is None or len(shares) < 2:
            _inflows_cache[symbol] = (now, None)
            return None

        recent = shares.tail(30)
        first = _safe_float(recent.iloc[0])
        last = _safe_float(recent.iloc[-1])
        if first is None or last is None or first <= 0:
            _inflows_cache[symbol] = (now, None)
            return None

        change_pct = (last - first) / first * 100.0
        if change_pct >= 5:
            score, label = 9.5, f"זרימה חזקה (+{change_pct:.1f}% במניות)"
        elif change_pct >= 2:
            score, label = 8.0, f"זרימה חיובית (+{change_pct:.1f}%)"
        elif change_pct >= 0:
            score, label = 6.5, f"יציב (+{change_pct:.1f}%)"
        elif change_pct >= -2:
            score, label = 4.5, f"יציאה קלה ({change_pct:.1f}%)"
        else:
            score, label = 3.0, f"יציאת הון ({change_pct:.1f}%) — אזהרה"

        result = {
            "shares_change_pct_30d": round(change_pct, 2),
            "score": round(score, 2),
            "label": label,
        }
        _inflows_cache[symbol] = (now, result)
        return result
    except Exception:
        _inflows_cache[symbol] = (now, None)
        return None


# Sector → canonical name → weighted D/E lookup.
# We populate it from the scanner's universe-info pass (one call per
# universe, cached for 24h) so we don't pay extra yfinance round-trips here.
_universe_de: dict[str, float] = {}
_universe_sector: dict[str, str] = {}
_universe_market_cap: dict[str, float] = {}
_universe_de_ts: float = 0.0


def set_universe_debt_equity(
    infos: dict[str, dict[str, Any]],
    universe: list[dict[str, Any]] | None = None,
) -> None:
    """Called once per scan with the already-fetched info objects."""
    global _universe_de, _universe_sector, _universe_market_cap, _universe_de_ts
    out: dict[str, float] = {}
    sectors = {
        str(entry.get("symbol")): str(entry.get("sector") or "Unknown")
        for entry in (universe or [])
    }
    caps: dict[str, float] = {}
    for sym, info in infos.items():
        if not info:
            continue
        de = info.get("debtToEquity")
        if de is None:
            continue
        try:
            de_val = float(de)
        except (TypeError, ValueError):
            continue
        # yfinance sometimes returns D/E as percent (e.g. 6.5 = 6.5%) and
        # sometimes as ratio. Heuristic: > 5 → treat as percent.
        de_ratio = de_val / 100.0 if de_val > 5 else de_val
        if de_ratio >= 0:
            out[sym] = de_ratio
        market_cap = _safe_float(info.get("marketCap"))
        if market_cap is not None and market_cap > 0:
            caps[sym] = market_cap
    _universe_de = out
    _universe_sector = sectors
    _universe_market_cap = caps
    _universe_de_ts = time.time()


def compute_weighted_debt_equity(
    symbol: str,
    sector_status: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Approximate the basket's market-cap-weighted D/E.

    For sector ETFs we use constituents from the same sector in our S&P 500
    universe — XLV ≈ Healthcare members, XLF ≈ Financials, etc. For broad
    ETFs (SPY/QQQ/IWM/DIA/VTI) sector_status is None, so we return None
    rather than fabricate a number.
    """
    if not sector_status or not _universe_de:
        return None
    canonical_sector = sector_status.get("sector")
    if not canonical_sector:
        return None

    # Import here to dodge the circular import (heatmap → etf_metrics).
    in_sector = [
        symbol for symbol, sector in _universe_sector.items()
        if sector == canonical_sector and symbol in _universe_de
    ]
    if not in_sector:
        return None

    total_cap = sum(_universe_market_cap.get(s, 1.0) for s in in_sector)
    if total_cap <= 0:
        return None
    weighted = sum(
        _universe_de[s] * _universe_market_cap.get(s, 1.0)
        for s in in_sector
    ) / total_cap

    if weighted <= 0.5:
        score, label = 9.0, f"D/E נמוך ({weighted:.2f}) — מאזן חזק"
    elif weighted <= 1.0:
        score, label = 7.0, f"D/E סביר ({weighted:.2f})"
    elif weighted <= 2.0:
        score, label = 5.0, f"D/E בינוני ({weighted:.2f})"
    else:
        score, label = 3.0, f"D/E גבוה ({weighted:.2f}) — מנוף מערכתי"

    return {
        "weighted_de": round(weighted, 3),
        "constituents": len(in_sector),
        "score": round(score, 2),
        "label": label,
    }
