"""Daily market scanner.

Uses a dynamic S&P 500 + Nasdaq-100 universe. Tier 1 performs a cheap batch
OHLCV/RVOL pass; Tier 2 runs expensive fundamentals for only 15-30 abnormal
volume candidates. ETFs run independently through their dedicated matrix.

Tier 1 uses one batched OHLCV download. Tier 2 fetches complete `.info`
fundamentals in parallel only for selected candidates. Optional per-symbol
sentiment providers remain excluded because they require extra HTTP calls.
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, time as dt_time
from pathlib import Path
from threading import Lock, Thread
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from behavior_sentiment import get_behavior_sentiment
from etf_metrics import (
    compute_net_inflows,
    compute_weighted_debt_equity,
    set_universe_debt_equity,
)
from entries import compute_long_term_entry
from fear_greed import get_fear_greed
from global_liquidity import get_global_liquidity, snapshot_to_dict
from trump_holdings import is_trump_held
from heatmap import SP500_MARKET_CAP_B, get_sector_status_for_symbol
from indicators import atr, bollinger_bands, macd, rsi, sma, vwap
from matrices import (
    compute_etf_score,
    compute_gap_pct,
    compute_long_term_score,
    compute_rvol,
    compute_short_term_score,
)
from patterns import detect_patterns
from scoring import compute_score
from universe import get_momentum_universe, get_universe

# How long a *freshly computed* scan is served before a background refresh is
# triggered. Kept short so an actively-used dyno reflects current prices instead
# of freezing on one result for a whole day; the refresh runs off the request
# path so it never blocks. (The committed cold-start seed is handled separately —
# it is always treated as stale, see `from_seed` below.)
CACHE_TTL_SECONDS = 30 * 60
DEFAULT_THRESHOLD = 8.0
SWING_THRESHOLD = 8.0
SWING_OVERALL_THRESHOLD = 7.0
LONG_TERM_OVERALL_THRESHOLD = 7.5
MIN_FINAL_SCORE = 7.0
ETF_THRESHOLD = MIN_FINAL_SCORE
DEFAULT_TOP_N = 5
TIER1_MIN_CANDIDATES = 15
TIER1_MAX_CANDIDATES = 30
TIER1_PRIMARY_RVOL = 1.50
TIER1_FLOOR_RVOL = 1.15


# Curated ETF universe — broad market + sector + factor.
ETFS: list[tuple[str, str, str]] = [
    ("SPY",  "Broad Market",         "SPDR S&P 500 ETF"),
    ("QQQ",  "Broad Market",         "Invesco QQQ Trust"),
    ("IWM",  "Broad Market",         "iShares Russell 2000"),
    ("DIA",  "Broad Market",         "SPDR Dow Jones"),
    ("XLK",  "Technology",           "Technology Select Sector"),
    ("XLF",  "Financials",           "Financial Select Sector"),
    ("XLV",  "Healthcare",           "Healthcare Select Sector"),
    ("XLY",  "Consumer Discretionary","Consumer Discretionary Select"),
    ("XLE",  "Energy",               "Energy Select Sector"),
    ("XLI",  "Industrials",          "Industrials Select Sector"),
    ("ARKK", "Technology",           "ARK Innovation ETF"),
    ("SOXX", "Technology",           "iShares Semiconductor ETF"),
    ("VTI",  "Broad Market",         "Vanguard Total Stock Market"),
]


_cache: dict[str, Any] = {"data": None, "ts": 0.0, "running": False, "from_seed": False}
_scan_lock = Lock()

# ── Disk-backed scan cache (cold-start survival) ─────────────────────────────
# The in-memory cache above evaporates whenever the process restarts — which on
# a free hosting tier (e.g. Render) happens after every idle spin-down. Running
# the full ~516-symbol scan inside the request then takes 60-120s and times out.
#
# So we mirror the result to disk and reload it on import. A *committed* seed
# (backend/data/scan.json, tracked in git) ships inside the deploy image, so even
# a brand-new dyno serves the last result instantly. Render's runtime disk is
# ephemeral — the committed seed is what survives spin-downs; the runtime write
# additionally helps hosts with a persistent disk and is harmless otherwise.
log = logging.getLogger(__name__)
SCAN_CACHE_FILE = Path(__file__).parent / "data" / "scan.json"
SCAN_CACHE_FILE.parent.mkdir(exist_ok=True)

# Whether to run the heavy scan *in this process*. OFF by default: on a 512MB
# free tier (Render) computing run_scan in-request spikes RSS past the limit
# (OOM) and starves /api/analyze, so we serve the committed seed — which CI
# regenerates daily — instead of ever scanning here. Local dev or a resourced
# host can opt in with ENABLE_LIVE_SCAN=1.
LIVE_SCAN_ENABLED = os.getenv("ENABLE_LIVE_SCAN", "").strip().lower() in ("1", "true", "yes", "on")

_refresh_lock = Lock()
_refreshing = False


class ScanSeedUnavailable(RuntimeError):
    """Raised when live scanning is disabled and no committed seed is available."""


def _load_disk_cache() -> None:
    """Populate the in-memory cache from disk once, at import time."""
    if _cache["data"] is not None:
        return
    try:
        if SCAN_CACHE_FILE.exists():
            cached = json.loads(SCAN_CACHE_FILE.read_text(encoding="utf-8"))
            data = cached.get("data")
            if data:
                _cache["data"] = data
                _cache["ts"] = float(cached.get("ts", 0.0))
                # Mark this as the cold-start seed. On Render the runtime disk is
                # ephemeral, so every boot reloads the *committed* seed — whose
                # timestamp may be only minutes old and would otherwise look
                # "fresh", freezing the scan on identical results for a full TTL.
                # Flagging it stale forces the first request to refresh live.
                _cache["from_seed"] = True
    except Exception as e:
        log.warning("scan cache load failed: %s", e)


def _persist_disk_cache(data: dict[str, Any], ts: float) -> None:
    try:
        SCAN_CACHE_FILE.write_text(
            json.dumps({"ts": ts, "data": data}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        log.warning("scan cache write failed: %s", e)


def _kick_background_refresh() -> None:
    """Recompute the scan off the request path (stale-while-revalidate).

    Lets a cold start return stale-but-instant data while fresh numbers are
    computed in a daemon thread, so the user never waits on the heavy scan and
    the single free-tier worker isn't blocked for other endpoints.
    """
    global _refreshing
    with _refresh_lock:
        if _refreshing:
            return
        _refreshing = True

    def _worker() -> None:
        global _refreshing
        try:
            data = run_scan(refresh_momentum=False)
            _cache["data"] = data
            _cache["ts"] = time.time()
            _cache["from_seed"] = False
            _persist_disk_cache(data, _cache["ts"])
        except Exception as e:
            log.warning("background scan refresh failed: %s", e)
        finally:
            with _refresh_lock:
                _refreshing = False

    Thread(target=_worker, name="scan-refresh", daemon=True).start()


_load_disk_cache()


def _is_long_term_qualified(
    result: dict[str, Any],
    score_threshold: float = DEFAULT_THRESHOLD,
) -> bool:
    return (
        _passes_final_gate(result.get("long_term_score"), score_threshold)
        and _passes_final_gate(result.get("overall_score"), LONG_TERM_OVERALL_THRESHOLD)
    )


def _is_swing_qualified(result: dict[str, Any]) -> bool:
    return (
        _passes_final_gate(result.get("short_term_score"), SWING_THRESHOLD)
        and _passes_final_gate(result.get("overall_score"), SWING_OVERALL_THRESHOLD)
    )


def _passes_final_gate(score: Any, threshold: float = MIN_FINAL_SCORE) -> bool:
    """Apply the universal gate to the final rounded score only."""
    final_rounded = round(float(score or 0.0), 2)
    required = max(MIN_FINAL_SCORE, threshold)
    return final_rounded >= required


def _etf_entry_score(result: dict[str, Any]) -> Any:
    """Use the same overall entry score shown by the full asset analysis."""
    overall_score = result.get("overall_score")
    return overall_score if overall_score is not None else result.get("etf_score")


def _is_etf_short_qualified(result: dict[str, Any]) -> bool:
    return (
        _passes_final_gate(result.get("short_term_score"), SWING_THRESHOLD)
        and _passes_final_gate(_etf_entry_score(result), SWING_OVERALL_THRESHOLD)
    )


def _is_etf_long_qualified(result: dict[str, Any]) -> bool:
    return (
        _passes_final_gate(result.get("long_term_score"), DEFAULT_THRESHOLD)
        and _passes_final_gate(_etf_entry_score(result), LONG_TERM_OVERALL_THRESHOLD)
    )


def _is_etf_qualified(result: dict[str, Any]) -> bool:
    """Backward-compatible union of the two ETF strategy gates."""
    return _is_etf_short_qualified(result) or _is_etf_long_qualified(result)


def _passes_universal_asset_gate(result: dict[str, Any]) -> bool:
    """Prevent sub-7 assets from leaking through auxiliary response lists."""
    if result.get("kind") == "etf":
        return _passes_final_gate(_etf_entry_score(result))
    return (
        _passes_final_gate(result.get("overall_score"))
        and (
            _passes_final_gate(result.get("short_term_score"))
            or _passes_final_gate(result.get("long_term_score"))
        )
    )


def _sanitize_scan_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Reapply current gates to cached/committed scan payloads.

    A seed can be generated by an older deployment whose response lists used
    different thresholds. Never trust membership in a stored top list: filter
    it again with the current final-score rules immediately before serving it.
    """
    score_threshold = float(data.get("threshold") or DEFAULT_THRESHOLD)

    def swing_ok(item: dict[str, Any]) -> bool:
        return item.get("kind") != "etf" and _is_swing_qualified(item)

    def invest_ok(item: dict[str, Any]) -> bool:
        return item.get("kind") != "etf" and _is_long_term_qualified(
            item, score_threshold,
        )

    def etf_short_ok(item: dict[str, Any]) -> bool:
        return item.get("kind") == "etf" and _is_etf_short_qualified(item)

    def etf_long_ok(item: dict[str, Any]) -> bool:
        return item.get("kind") == "etf" and _is_etf_long_qualified(item)

    def etf_ok(item: dict[str, Any]) -> bool:
        return etf_short_ok(item) or etf_long_ok(item)

    predicates = {
        "top_swing_stocks": swing_ok,
        "top_invest_stocks": invest_ok,
        "top_stocks": swing_ok,
        "top_etfs": etf_ok,
        "top_short_term_etfs": etf_short_ok,
        "top_long_term_etfs": etf_long_ok,
        "top": lambda item: etf_ok(item) or swing_ok(item) or invest_ok(item),
    }

    sanitized = dict(data)
    changed = False
    for key, predicate in predicates.items():
        items = data.get(key)
        if items is None and key in {"top_short_term_etfs", "top_long_term_etfs"}:
            items = data.get("top_etfs")
            if isinstance(items, list):
                changed = True
        if not isinstance(items, list):
            continue
        filtered = [item for item in items if isinstance(item, dict) and predicate(item)]
        if len(filtered) != len(items):
            changed = True
        sanitized[key] = filtered

    return sanitized if changed else data


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


def compute_session_adjusted_rvol(
    volume_series: pd.Series,
    latest_timestamp: Any = None,
    now: datetime | None = None,
) -> float | None:
    """Project an incomplete US session volume before calculating RVOL."""
    raw = compute_rvol(volume_series)
    if raw is None or len(volume_series) < 21:
        return raw

    market_now = now or datetime.now(ZoneInfo("America/New_York"))
    if market_now.tzinfo is None:
        market_now = market_now.replace(tzinfo=ZoneInfo("America/New_York"))
    else:
        market_now = market_now.astimezone(ZoneInfo("America/New_York"))

    if market_now.weekday() >= 5:
        return raw

    session_open = datetime.combine(
        market_now.date(),
        dt_time(9, 30),
        tzinfo=market_now.tzinfo,
    )
    session_close = datetime.combine(
        market_now.date(),
        dt_time(16, 0),
        tzinfo=market_now.tzinfo,
    )
    if not session_open < market_now < session_close:
        return raw

    try:
        latest_date = pd.Timestamp(
            latest_timestamp if latest_timestamp is not None else volume_series.index[-1],
        ).date()
    except Exception:
        return raw
    if latest_date != market_now.date():
        return raw

    elapsed_minutes = (market_now - session_open).total_seconds() / 60.0
    # Yahoo daily bars can lag by roughly 15 minutes. A small floor also avoids
    # unstable projections immediately after the opening bell.
    session_fraction = max(0.10, min(1.0, (elapsed_minutes - 15.0) / 390.0))
    base = float(volume_series.iloc[-21:-1].mean())
    if base <= 0:
        return raw
    projected_volume = float(volume_series.iloc[-1]) / session_fraction
    return round(projected_volume / base, 2)


def _fetch_info(symbol: str) -> dict[str, Any]:
    """Fundamentals fetch for a single symbol. Used inside ThreadPoolExecutor.

    yfinance .info is a slow per-symbol HTTP round trip — fetching 76 in series
    is ~60-120s. We parallelise with limited concurrency to bring this under 30s
    without tripping Yahoo's rate limiter.
    """
    try:
        return yf.Ticker(symbol).info or {}
    except Exception:
        return {}


def _evaluate(
    symbol: str,
    name: str,
    sector: str,
    sub: pd.DataFrame,
    fg_data: dict[str, Any] | None,
    info: dict[str, Any] | None = None,
    gli_data: dict[str, Any] | None = None,
    behavior_data: dict[str, Any] | None = None,
    *,
    is_etf: bool = False,
) -> dict[str, Any] | None:
    """Score a single symbol given its OHLCV slice. Returns None if too thin.

    Every asset gets the overall/short/long score family used by the analysis
    page. ETFs also keep their dedicated matrix as a secondary diagnostic.
    """
    if sub is None or len(sub) < 30:
        return None

    close = sub["close"]
    vol = sub["volume"]

    ma20_s = sma(close, 20)
    ma50_s = sma(close, 50)
    ma150_s = sma(close, 150)
    ma200_s = sma(close, 200)
    rsi_s = rsi(close, 14)
    atr_s = atr(sub["high"], sub["low"], close, 14)
    vwap_s = vwap(sub["high"], sub["low"], close, vol, 20)
    _, _, macd_histogram_s = macd(close)
    bb_upper_s, _, bb_lower_s, _ = bollinger_bands(close)

    last_price = float(close.iloc[-1])
    if last_price <= 0:
        return None

    last_ma20 = _safe_float(ma20_s.iloc[-1])
    last_ma50 = _safe_float(ma50_s.iloc[-1])
    last_ma150 = _safe_float(ma150_s.iloc[-1])
    last_ma200 = _safe_float(ma200_s.iloc[-1])
    last_rsi = _safe_float(rsi_s.iloc[-1])
    last_atr = _safe_float(atr_s.iloc[-1])
    last_vwap = _safe_float(vwap_s.iloc[-1])
    last_macd_histogram = _safe_float(macd_histogram_s.iloc[-1])
    last_bb_upper = _safe_float(bb_upper_s.iloc[-1])
    last_bb_lower = _safe_float(bb_lower_s.iloc[-1])
    atr_pct = (last_atr / last_price * 100.0) if last_atr and last_price else None

    rvol_v = compute_session_adjusted_rvol(vol, sub.index[-1])
    gap_v = compute_gap_pct(sub)
    sector_status = get_sector_status_for_symbol(symbol, sector)
    patterns_data = detect_patterns(sub, last_price, last_atr)

    # Fundamentals — fetched in parallel by run_scan() and passed in via `info`.
    # Falls back to the hardcoded market cap dict if `.info` failed.
    info = info or {}
    pe = _safe_float(info.get("trailingPE"))
    pb = _safe_float(info.get("priceToBook"))
    beta = _safe_float(info.get("beta"))
    debt_to_equity = _safe_float(info.get("debtToEquity"))
    free_cashflow = _safe_float(info.get("freeCashflow"))
    shares_outstanding = _safe_float(info.get("sharesOutstanding"))
    operating_cashflow = _safe_float(info.get("operatingCashflow"))
    total_cash = _safe_float(info.get("totalCash"))
    total_debt = _safe_float(info.get("totalDebt"))
    current_ratio = _safe_float(info.get("currentRatio"))
    quick_ratio = _safe_float(info.get("quickRatio"))
    profit_margin = _safe_float(info.get("profitMargins"))
    operating_margin = _safe_float(info.get("operatingMargins"))
    return_on_equity = _safe_float(info.get("returnOnEquity"))
    revenue_growth = _safe_float(info.get("revenueGrowth"))
    earnings_growth = _safe_float(info.get("earningsGrowth"))
    eps = _safe_float(info.get("trailingEps"))
    market_cap_dollars = _safe_float(info.get("marketCap"))
    if market_cap_dollars is None:
        mc_b = SP500_MARKET_CAP_B.get(symbol)
        if mc_b:
            market_cap_dollars = mc_b * 1_000_000_000

    change_pct = None
    if len(close) >= 2:
        prev = float(close.iloc[-2])
        if prev > 0:
            change_pct = round((last_price - prev) / prev * 100.0, 2)

    # ETFs retain their dedicated matrix as a secondary diagnostic metric.
    etf_matrix = None
    inflows = None
    weighted_de = None
    if is_etf:
        inflows = compute_net_inflows(symbol)
        weighted_de = compute_weighted_debt_equity(symbol, sector_status)
        etf_matrix = compute_etf_score(
            price=last_price,
            ma20=last_ma20,
            ma50=last_ma50,
            ma150=last_ma150,
            ma200=last_ma200,
            rsi14=last_rsi,
            vwap=last_vwap,
            sector_status=sector_status,
            net_inflows=inflows,
            weighted_debt_equity=weighted_de,
            global_liquidity=gli_data,
        )

    # All assets use the same score family as the full analysis endpoint.
    trump_flag = False if is_etf else is_trump_held(symbol)
    st = compute_short_term_score(
        price=last_price,
        ma20=last_ma20,
        ma50=last_ma50,
        rsi14=last_rsi,
        vwap=last_vwap,
        rvol=rvol_v,
        gap_pct=gap_v,
        atr_pct=atr_pct,
        patterns=patterns_data,
        behavior=behavior_data,
        sector_status=sector_status,
        global_liquidity=gli_data,
        trump_held=trump_flag,
    )

    overall = compute_score(
        price=last_price,
        ma20=last_ma20,
        ma50=last_ma50,
        ma150=last_ma150,
        ma200=last_ma200,
        rsi14=last_rsi,
        atr_pct=atr_pct,
        volume_series=vol,
        pe=pe,
        pb=pb,
        beta=beta,
        macd_histogram=last_macd_histogram,
        bb_lower=last_bb_lower,
        bb_upper=last_bb_upper,
        vwap=last_vwap,
        patterns=patterns_data,
        fear_greed=fg_data,
        behavior_sentiment=behavior_data,
        sector_status=sector_status,
        global_liquidity=gli_data,
    )

    long_entry = compute_long_term_entry(
        price=last_price,
        ma150=last_ma150,
        ma200=last_ma200,
        pe=pe,
        eps=eps,
    )

    lt = compute_long_term_score(
        price=last_price,
        ma50=last_ma50,
        ma150=last_ma150,
        ma200=last_ma200,
        pe=pe,
        pb=pb,
        beta=beta,
        debt_to_equity=debt_to_equity,
        free_cashflow=free_cashflow,
        market_cap=market_cap_dollars,
        shares_outstanding=shares_outstanding,
        operating_cashflow=operating_cashflow,
        total_cash=total_cash,
        total_debt=total_debt,
        current_ratio=current_ratio,
        quick_ratio=quick_ratio,
        profit_margin=profit_margin,
        operating_margin=operating_margin,
        return_on_equity=return_on_equity,
        revenue_growth=revenue_growth,
        earnings_growth=earnings_growth,
        fear_greed=fg_data,
        behavior=behavior_data,
        sector_status=sector_status,
        global_liquidity=gli_data,
        rvol=rvol_v,
        patterns=patterns_data,
        overvaluation_gate=getattr(long_entry, "blocked", False) if long_entry else False,
        trump_held=trump_flag,
    )

    # NO COMBINED SCORE — strategies are mutually exclusive (swing vs. invest).
    # Each is exposed independently; the scan groups by strategy separately.
    result = {
        "kind": "etf" if is_etf else "stock",
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "sector_status": sector_status,
        "price": round(last_price, 2),
        "change_pct": change_pct,
        "rvol": rvol_v,
        "gap_pct": gap_v,
        "short_term_score": st.score,
        "short_term_blocker": st.blocker_applied,
        "short_term_raw": st.raw_score,
        "short_term_bonus": st.bonus,
        "short_term_bonus_reasons": st.bonus_reasons,
        "short_term_rationale": st.rationale[:3],
        "long_term_score": lt.score,
        "overall_score": round(overall.score, 2),
        "overall_score_breakdown": overall.breakdown,
        "long_term_raw": lt.raw_score,
        "long_term_bonus": lt.bonus,
        "long_term_bonus_reasons": lt.bonus_reasons,
        "long_term_entry": None if long_entry is None else {
            "price": long_entry.price,
            "method": long_entry.method,
            "reason": long_entry.reason,
            "blocked": getattr(long_entry, "blocked", False),
            "fair_value": getattr(long_entry, "fair_value", None),
        },
        "long_term_rationale": lt.rationale[:3],
        "final_score": round(overall.score, 2) if is_etf else st.score,
        "top_reasons": overall.rationale[:3] if is_etf else st.rationale[:3],
    }
    if is_etf and etf_matrix is not None:
        result.update({
            # Keep the legacy field aligned with the canonical entry score.
            "etf_score": round(overall.score, 2),
            "etf_matrix_score": etf_matrix.score,
            "etf_blocker": etf_matrix.blocker_applied,
            "etf_matrix_rationale": etf_matrix.rationale[:3],
            "net_inflows": inflows,
            "weighted_debt_equity": weighted_de,
        })
    return result


def _download_batch(symbols: list[str]) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()
    return yf.download(
        symbols,
        period="1y",
        interval="1d",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )


def _slice_symbol(raw: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
    if raw is None or raw.empty:
        return None
    try:
        if isinstance(raw.columns, pd.MultiIndex):
            sub_raw = raw[symbol]
        else:
            sub_raw = raw
        sub = sub_raw.rename(columns=str.lower)
        return sub[["open", "high", "low", "close", "volume"]].dropna()
    except Exception:
        return None


def _tier1_candidates(
    universe: list[dict[str, Any]],
    raw: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Cheap OHLCV-only gate. Returns selected candidates and all valid rows."""
    rows: list[dict[str, Any]] = []
    for entry in universe:
        symbol = entry["symbol"]
        sub = _slice_symbol(raw, symbol)
        if sub is None or len(sub) < 50:
            continue
        rvol_v = compute_session_adjusted_rvol(sub["volume"], sub.index[-1])
        if rvol_v is None:
            continue
        rows.append({**entry, "rvol": float(rvol_v), "sub": sub})

    rows.sort(key=lambda row: row["rvol"], reverse=True)
    primary = [row for row in rows if row["rvol"] >= TIER1_PRIMARY_RVOL]
    selected = primary[:TIER1_MAX_CANDIDATES]

    # Keep the expensive stage useful on quieter days, but never admit normal
    # volume: fillers still need at least 1.15x relative volume.
    if len(selected) < TIER1_MIN_CANDIDATES:
        selected_symbols = {row["symbol"] for row in selected}
        fillers = [
            row for row in rows
            if row["symbol"] not in selected_symbols and row["rvol"] >= TIER1_FLOOR_RVOL
        ]
        selected.extend(fillers[: TIER1_MIN_CANDIDATES - len(selected)])

    return selected[:TIER1_MAX_CANDIDATES], rows


def _merge_stock_universes(
    index_universe: list[dict[str, Any]],
    momentum_universe: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge index members with daily momentum names, deduplicated by symbol."""
    merged = {entry["symbol"]: dict(entry) for entry in index_universe}
    for momentum in momentum_universe:
        symbol = momentum["symbol"]
        existing = merged.get(symbol)
        if existing is None:
            merged[symbol] = dict(momentum)
            continue
        sources = set(existing.get("momentum_sources") or [])
        sources.update(momentum.get("momentum_sources") or [])
        existing["momentum_sources"] = sorted(sources)
        existing["screener_change_pct"] = momentum.get("screener_change_pct")
        existing["screener_volume"] = momentum.get("screener_volume")
        existing["screener_avg_volume"] = momentum.get("screener_avg_volume")
    return sorted(merged.values(), key=lambda entry: entry["symbol"])


def run_scan(
    top_n: int = DEFAULT_TOP_N,
    score_threshold: float = DEFAULT_THRESHOLD,
    refresh_momentum: bool = False,
) -> dict[str, Any]:
    started_at = time.time()
    stage_started = started_at
    timings: dict[str, float] = {}
    index_universe = get_universe(force=False)
    momentum_universe = get_momentum_universe(force=refresh_momentum)
    stock_universe = _merge_stock_universes(index_universe, momentum_universe)
    stock_symbols = [entry["symbol"] for entry in stock_universe]
    etf_symbols = [entry[0] for entry in ETFS]
    timings["universe_seconds"] = round(time.time() - stage_started, 2)

    # Single batched HTTP request — much faster than per-symbol calls.
    def timed_download(symbols: list[str]) -> tuple[pd.DataFrame, float]:
        download_started = time.time()
        return _download_batch(symbols), round(time.time() - download_started, 2)

    stage_started = time.time()
    with ThreadPoolExecutor(max_workers=2) as pool:
        stock_download = pool.submit(timed_download, stock_symbols)
        etf_download = pool.submit(timed_download, etf_symbols)
        stock_raw, stock_download_seconds = stock_download.result()
        etf_raw, etf_download_seconds = etf_download.result()
    timings["batch_download_seconds"] = round(time.time() - stage_started, 2)
    timings["stock_batch_download_seconds"] = stock_download_seconds
    timings["etf_batch_download_seconds"] = etf_download_seconds

    stage_started = time.time()
    tier2_candidates, tier1_rows = _tier1_candidates(stock_universe, stock_raw)
    timings["tier1_filter_seconds"] = round(time.time() - stage_started, 2)

    try:
        fg = get_fear_greed(force=False)
        fg_data = {
            "score": fg.score,
            "rating": fg.rating,
            "label": fg.label,
        }
    except Exception:
        fg_data = None

    try:
        gli_data = snapshot_to_dict(get_global_liquidity(force=False))
    except Exception:
        gli_data = None

    # Parallel fundamentals fetch — drops total scan time from ~120s to ~25s.
    # Concurrency capped at 6 to stay below Yahoo's rate limit.
    tier2_symbols = [row["symbol"] for row in tier2_candidates]
    stage_started = time.time()
    with ThreadPoolExecutor(max_workers=6) as pool:
        infos = dict(zip(tier2_symbols, pool.map(_fetch_info, tier2_symbols)))
    timings["tier2_fundamentals_seconds"] = round(time.time() - stage_started, 2)

    # Feed universe D/E to the ETF matrix so weighted-leverage can be computed.
    set_universe_debt_equity(infos, tier2_candidates)

    stocks_results: list[dict[str, Any]] = []
    etfs_results: list[dict[str, Any]] = []

    for row in tier2_candidates:
        symbol = row["symbol"]
        try:
            info = infos.get(symbol) or {}
            evaluation = _evaluate(
                symbol,
                info.get("longName") or info.get("shortName") or row.get("name") or symbol,
                info.get("sector") or row.get("sector") or "Unknown",
                row["sub"],
                fg_data,
                info,
                gli_data,
                is_etf=False,
            )
            if not evaluation:
                continue
            evaluation["momentum_sources"] = row.get("momentum_sources") or []
            # This loop only evaluates the stock universe. Normalize the type
            # explicitly so malformed provider metadata cannot discard a stock.
            evaluation["kind"] = "stock"
            stocks_results.append(evaluation)
        except Exception:
            # Quietly skip symbols that errored — the rest still score.
            continue

    # NO COMBINED SCORE. Strategies are mutually exclusive — a stock can be
    # a swing candidate OR an investment candidate, possibly both, but the
    # decision criteria don't average. So we maintain two independent top-N
    # lists for stocks, ranked by the strategy-specific score only.
    def evaluate_etf(entry: tuple[str, str, str]) -> dict[str, Any] | None:
        symbol, sector, name = entry
        sub = _slice_symbol(etf_raw, symbol)
        if sub is None:
            return None
        try:
            info = _fetch_info(symbol)
            try:
                behavior_data = get_behavior_sentiment(symbol, force=False)
            except Exception:
                behavior_data = None
            return _evaluate(
                symbol,
                info.get("longName") or info.get("shortName") or name,
                info.get("sector") or sector,
                sub,
                fg_data,
                info,
                gli_data,
                behavior_data,
                is_etf=True,
            )
        except Exception:
            return None

    # ETFs use their own matrix and execute independently of stock Tier 2.
    stage_started = time.time()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for evaluation in pool.map(evaluate_etf, ETFS):
            if evaluation:
                etfs_results.append(evaluation)
    timings["etf_evaluation_seconds"] = round(time.time() - stage_started, 2)

    swing_stocks = sorted(
        (r for r in stocks_results if _is_swing_qualified(r)),
        key=lambda r: -r["short_term_score"],
    )
    invest_stocks = sorted(
        (
            r for r in stocks_results
            if _is_long_term_qualified(r, score_threshold)
        ),
        key=lambda r: -r["long_term_score"],
    )
    short_term_etfs = sorted(
        (r for r in etfs_results if _is_etf_short_qualified(r)),
        key=lambda r: -float(r.get("short_term_score") or 0.0),
    )
    long_term_etfs = sorted(
        (r for r in etfs_results if _is_etf_long_qualified(r)),
        key=lambda r: -float(r.get("long_term_score") or 0.0),
    )

    def _tag_swing(r: dict[str, Any]) -> dict[str, Any]:
        # Card displays the strategy-specific score, not a combined metric.
        # Swing uses its OWN, slightly lower threshold — patterns + RVOL
        # confirmation tend to top out below the strict 8.0 of the value
        # strategy.
        out = dict(r)
        out["display_score"] = r["short_term_score"]
        out["display_rationale"] = r.get("short_term_rationale", [])
        out["strategy"] = "swing"
        out["strategy_label"] = "Swing Setup"
        out["is_qualified"] = _is_swing_qualified(r)
        return out

    def _tag_invest(r: dict[str, Any]) -> dict[str, Any]:
        out = dict(r)
        out["display_score"] = r["long_term_score"]
        out["display_rationale"] = r.get("long_term_rationale", [])
        out["strategy"] = "investment"
        out["strategy_label"] = "Long-Term Investment"
        out["is_qualified"] = _is_long_term_qualified(r, score_threshold)
        return out

    def _tag_short_term_etf(r: dict[str, Any]) -> dict[str, Any]:
        out = dict(r)
        out["display_score"] = r["short_term_score"]
        out["display_rationale"] = r.get("short_term_rationale", [])
        out["strategy"] = "etf_swing"
        out["strategy_label"] = "Short-Term ETF"
        out["is_qualified"] = _is_etf_short_qualified(r)
        return out

    def _tag_long_term_etf(r: dict[str, Any]) -> dict[str, Any]:
        out = dict(r)
        out["display_score"] = r["long_term_score"]
        out["display_rationale"] = r.get("long_term_rationale", [])
        out["strategy"] = "etf_investment"
        out["strategy_label"] = "Long-Term ETF"
        out["is_qualified"] = _is_etf_long_qualified(r)
        return out

    top_swing_stocks = [_tag_swing(r) for r in swing_stocks[:top_n]]
    top_invest_stocks = [_tag_invest(r) for r in invest_stocks[:top_n]]
    top_short_term_etfs = [
        _tag_short_term_etf(r) for r in short_term_etfs[:top_n]
    ]
    top_long_term_etfs = [
        _tag_long_term_etf(r) for r in long_term_etfs[:top_n]
    ]
    # Legacy union retained for older clients.
    top_etfs_final = top_short_term_etfs + [
        item for item in top_long_term_etfs
        if item["symbol"] not in {short["symbol"] for short in top_short_term_etfs}
    ]

    # Legacy `top_stocks` field kept for backward compatibility — points at
    # the swing list (most common usage from the previous algorithm).
    top_stocks_final = top_swing_stocks

    qualified_swing = sum(1 for r in stocks_results if _is_swing_qualified(r))
    qualified_invest = sum(
        1 for r in stocks_results
        if _is_long_term_qualified(r, score_threshold)
    )
    qualified_short_term_etfs = sum(
        1 for r in etfs_results if _is_etf_short_qualified(r)
    )
    qualified_long_term_etfs = sum(
        1 for r in etfs_results if _is_etf_long_qualified(r)
    )
    qualified_etfs = sum(1 for r in etfs_results if _is_etf_qualified(r))
    qualified_stocks = [
        r for r in stocks_results
        if _is_swing_qualified(r) or _is_long_term_qualified(r, score_threshold)
    ]
    all_results = stocks_results + etfs_results

    # Bucket distribution uses the BEST per-strategy score for each stock,
    # since "qualified" now means "qualified in at least one strategy".
    def _best(r: dict[str, Any]) -> float:
        if r.get("kind") == "etf":
            return float(_etf_entry_score(r) or 0.0)
        return max(r["short_term_score"], r["long_term_score"])

    buckets = {
        "ge_9": sum(1 for r in all_results if _best(r) >= 9.0),
        "ge_8": sum(1 for r in all_results if _best(r) >= 8.0),
        "ge_7": sum(1 for r in all_results if _best(r) >= 7.0),
        "ge_6": sum(1 for r in all_results if _best(r) >= 6.0),
        "ge_5": sum(1 for r in all_results if _best(r) >= 5.0),
    }

    # `top` keeps backward compatibility while honoring every strategy gate.
    combined = sorted(all_results, key=_best, reverse=True)
    qualified_combined = [
        r for r in combined
        if (
            r.get("kind") == "etf"
            and _is_etf_qualified(r)
        )
        or (
            r.get("kind") == "stock"
            and (
                _is_swing_qualified(r)
                or _is_long_term_qualified(r, score_threshold)
            )
        )
    ]

    return {
        "top": qualified_combined[:top_n],
        # Three independent top-N lists — no cross-strategy averaging.
        "top_swing_stocks": top_swing_stocks,
        "top_invest_stocks": top_invest_stocks,
        "top_stocks": top_stocks_final,  # legacy alias for swing list
        "top_etfs": top_etfs_final,
        "top_short_term_etfs": top_short_term_etfs,
        "top_long_term_etfs": top_long_term_etfs,
        "qualified_count": len(qualified_stocks) + qualified_etfs,
        "qualified_swing_count": qualified_swing,
        "qualified_invest_count": qualified_invest,
        "qualified_stocks_count": len(qualified_stocks),
        "qualified_etfs_count": qualified_etfs,
        "qualified_short_term_etfs_count": qualified_short_term_etfs,
        "qualified_long_term_etfs_count": qualified_long_term_etfs,
        "evaluated_count": len(all_results),
        "stocks_evaluated": len(stocks_results),
        "etfs_evaluated": len(etfs_results),
        "universe_size": len(stock_universe) + len(ETFS),
        "stock_universe_size": len(stock_universe),
        "index_universe_size": len(index_universe),
        "momentum_universe_size": len(momentum_universe),
        "momentum_added_count": len(stock_universe) - len(index_universe),
        "momentum_overlap_count": len(
            {entry["symbol"] for entry in index_universe}
            & {entry["symbol"] for entry in momentum_universe}
        ),
        "etf_universe_size": len(ETFS),
        "tier1_valid_count": len(tier1_rows),
        "tier2_candidate_count": len(tier2_candidates),
        "tier2_info_calls": len(tier2_symbols),
        "tier1_primary_rvol": TIER1_PRIMARY_RVOL,
        "tier1_floor_rvol": TIER1_FLOOR_RVOL,
        "scan_duration_seconds": round(time.time() - started_at, 2),
        "scan_timings": timings,
        "universe_sources": {
            "sp500": sum(1 for entry in index_universe if entry.get("source") == "sp500"),
            "nasdaq100_only": sum(1 for entry in index_universe if entry.get("source") == "nasdaq100"),
            "day_gainers": sum(
                1 for entry in momentum_universe
                if "day_gainers" in (entry.get("momentum_sources") or [])
            ),
            "most_actives": sum(
                1 for entry in momentum_universe
                if "most_actives" in (entry.get("momentum_sources") or [])
            ),
        },
        "threshold": score_threshold,
        "swing_threshold": SWING_THRESHOLD,
        "swing_overall_threshold": SWING_OVERALL_THRESHOLD,
        "long_term_overall_threshold": LONG_TERM_OVERALL_THRESHOLD,
        "minimum_final_score": MIN_FINAL_SCORE,
        "etf_threshold": ETF_THRESHOLD,
        "etf_short_term_threshold": SWING_THRESHOLD,
        "etf_short_term_overall_threshold": SWING_OVERALL_THRESHOLD,
        "etf_long_term_threshold": DEFAULT_THRESHOLD,
        "etf_long_term_overall_threshold": LONG_TERM_OVERALL_THRESHOLD,
        "etf_diagnostics": [
            {
                "symbol": r["symbol"],
                "score": _etf_entry_score(r),
                "matrix_score": r.get("etf_matrix_score"),
                "qualified": _is_etf_qualified(r),
                "blocker_applied": r.get("etf_blocker", False),
                "net_inflows_available": r.get("net_inflows") is not None,
                "weighted_de_available": r.get("weighted_debt_equity") is not None,
                "top_reasons": r.get("top_reasons", []),
            }
            for r in sorted(
                etfs_results,
                key=lambda item: -float(_etf_entry_score(item) or 0.0),
            )
        ],
        "buckets": buckets,
        "near_miss": [
            {
                "symbol": r["symbol"],
                "name": r["name"],
                "kind": r["kind"],
                "short_term_score": r.get("short_term_score"),
                "long_term_score": r.get("long_term_score"),
                "overall_score": r.get("overall_score"),
                "etf_score": r.get("etf_score"),
                "short_term_blocker": r.get("short_term_blocker", False),
            }
            for r in combined[:10]
            if _passes_universal_asset_gate(r) and _best(r) < score_threshold
        ],
        "fetched_at": time.time(),
    }


def get_scan(force: bool = False) -> dict[str, Any]:
    now = time.time()
    have_cache = _cache["data"] is not None

    # On a constrained host the heavy scan never runs in-process: serve the
    # committed seed (CI refreshes it on demand) and skip ALL computation — including
    # the manual force rescan, which would otherwise OOM the 512MB dyno.
    if not LIVE_SCAN_ENABLED:
        if have_cache:
            return _sanitize_scan_payload(_cache["data"])
        raise ScanSeedUnavailable(
            "Scan seed unavailable and live scanning is disabled. "
            "Run the refresh-seed GitHub workflow to regenerate backend/data/scan.json."
        )

    # The committed seed is never "fresh" — serving it must always kick a live
    # refresh, otherwise a recently-generated seed freezes the scan for a TTL.
    fresh = (
        have_cache
        and not _cache["from_seed"]
        and now - _cache["ts"] < CACHE_TTL_SECONDS
    )

    if not force:
        if fresh:
            return _sanitize_scan_payload(_cache["data"])
        if have_cache:
            # Stale but present (cold start served the seed, or TTL lapsed) →
            # return instantly and refresh off the request path. The frontend
            # polls a couple of times to pick up the fresh result.
            _kick_background_refresh()
            return _sanitize_scan_payload(_cache["data"])

    # force=True, or no cache at all → compute synchronously (the slow path).
    with _scan_lock:
        now = time.time()
        if (
            not force
            and _cache["data"] is not None
            and not _cache["from_seed"]
            and now - _cache["ts"] < CACHE_TTL_SECONDS
        ):
            return _cache["data"]
        _cache["running"] = True
        try:
            data = run_scan(refresh_momentum=force)
            _cache["data"] = data
            _cache["ts"] = time.time()
            _cache["from_seed"] = False
            _persist_disk_cache(data, _cache["ts"])
            return _sanitize_scan_payload(data)
        finally:
            _cache["running"] = False
