"""Daily market scanner.

Uses a dynamic S&P 500, Nasdaq-100, and liquid Russell 2000 universe. Tier 1
performs a cheap batch OHLCV pass with separate Swing and Long-Term funnels.
Tier 2 runs expensive fundamentals for at most 30 merged candidates. ETFs run
independently through their dedicated matrix.

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
DEFAULT_THRESHOLD = 7.0
SWING_THRESHOLD = 7.0
SWING_OVERALL_THRESHOLD = 7.0
LONG_TERM_OVERALL_THRESHOLD = 7.0
MIN_FINAL_SCORE = 7.0
ETF_THRESHOLD = MIN_FINAL_SCORE
SWING_MIN_RVOL = 1.20
ETF_SWING_MIN_RVOL = 1.10
SWING_MIN_RISK_REWARD = 1.50
SWING_MIN_SUCCESS_RATE = 60.0
SWING_MAX_BREAKOUT_DISTANCE_PCT = 5.0
SWING_MAX_ATR_PCT = 8.0
ETF_SWING_MAX_ATR_PCT = 5.0
SWING_MIN_DOLLAR_VOLUME = 10_000_000.0
ETF_SWING_MIN_DOLLAR_VOLUME = 20_000_000.0
DEFAULT_TOP_N = 5
TIER1_MAX_CANDIDATES = 30
SWING_TIER1_MAX_CANDIDATES = 15
LONG_TERM_TIER1_MAX_CANDIDATES = 15
TIER1_PRIMARY_RVOL = 1.50
TIER1_FLOOR_RVOL = 1.15
STOCK_BATCH_CHUNK_SIZE = 50
STOCK_BATCH_WORKERS = 3


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
    setup = result.get("swing_setup")
    return bool(isinstance(setup, dict) and setup.get("qualified"))


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
    setup = result.get("swing_setup")
    return bool(isinstance(setup, dict) and setup.get("qualified"))


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
    # Use the current policy even when a committed seed stores an older gate.
    score_threshold = DEFAULT_THRESHOLD

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
    current_policy = {
        "threshold": DEFAULT_THRESHOLD,
        "swing_threshold": SWING_THRESHOLD,
        "swing_overall_threshold": SWING_OVERALL_THRESHOLD,
        "swing_min_rvol": SWING_MIN_RVOL,
        "etf_swing_min_rvol": ETF_SWING_MIN_RVOL,
        "swing_min_risk_reward": SWING_MIN_RISK_REWARD,
        "swing_min_success_rate": SWING_MIN_SUCCESS_RATE,
        "long_term_overall_threshold": LONG_TERM_OVERALL_THRESHOLD,
        "minimum_final_score": MIN_FINAL_SCORE,
        "etf_threshold": ETF_THRESHOLD,
        "etf_short_term_threshold": SWING_THRESHOLD,
        "etf_short_term_overall_threshold": SWING_OVERALL_THRESHOLD,
        "etf_long_term_threshold": DEFAULT_THRESHOLD,
        "etf_long_term_overall_threshold": LONG_TERM_OVERALL_THRESHOLD,
    }
    changed = any(data.get(key) != value for key, value in current_policy.items())
    sanitized.update(current_policy)
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


def _has_rising_price_structure(sub: pd.DataFrame) -> bool:
    """Require recent pivot highs and pivot lows to rise together."""
    if sub is None or len(sub) < 35:
        return False
    recent = sub.tail(90).reset_index(drop=True)

    def pivots(values: list[float], mode: str, k: int = 3) -> list[float]:
        found: list[float] = []
        for index in range(k, len(values) - k):
            window = values[index - k:index + k + 1]
            if mode == "high" and values[index] == max(window):
                found.append(float(values[index]))
            elif mode == "low" and values[index] == min(window):
                found.append(float(values[index]))
        return found

    highs = pivots(recent["high"].astype(float).tolist(), "high")
    lows = pivots(recent["low"].astype(float).tolist(), "low")
    if len(highs) < 2 or len(lows) < 2:
        return False
    high_sample = highs[-3:]
    low_sample = lows[-3:]
    return (
        all(right > left for left, right in zip(high_sample, high_sample[1:]))
        and all(right > left for left, right in zip(low_sample, low_sample[1:]))
    )


def _build_prebreakout_swing_setup(
    *,
    current_price: float,
    rvol: float | None,
    cup_pattern: dict[str, Any] | None,
    rising_structure: bool,
) -> dict[str, Any]:
    """Evaluate the score-free pre-breakout Swing gate."""
    pattern = cup_pattern or {}
    geometry = pattern.get("geometry") or {}
    breakout = _safe_float(pattern.get("level"))
    target = _safe_float(pattern.get("target"))
    stop = _safe_float(pattern.get("stop"))
    success_rate = _safe_float(pattern.get("confidence")) or 0.0
    handle_stage = bool(
        pattern.get("detected")
        and pattern.get("direction") == "bullish"
        and geometry.get("handle_low")
        and not geometry.get("broke_out")
        and breakout is not None
        and current_price < breakout
    )
    elevated_rvol = bool(rvol is not None and rvol >= SWING_MIN_RVOL)

    risk_reward = None
    if (
        breakout is not None
        and target is not None
        and stop is not None
        and stop < breakout < target
    ):
        risk = breakout - stop
        if risk > 0:
            risk_reward = round((target - breakout) / risk, 2)

    checks = {
        "cup_handle_stage": handle_stage,
        "rising_structure": rising_structure,
        "elevated_rvol": elevated_rvol,
        "risk_reward": bool(
            risk_reward is not None and risk_reward >= SWING_MIN_RISK_REWARD
        ),
        "success_rate": success_rate >= SWING_MIN_SUCCESS_RATE,
    }
    qualified = all(checks.values())
    reasons = [
        "Cup and Handle is in the handle stage before breakout",
        "Recent pivot highs and lows are rising",
        f"RVOL {float(rvol or 0.0):.2f}x",
        f"R:R 1:{float(risk_reward or 0.0):.2f}",
        f"Estimated success {success_rate:.0f}%",
    ]
    return {
        "qualified": qualified,
        "checks": checks,
        "breakout_price": breakout,
        "stop_price": stop,
        "target_price": target,
        "risk_reward": risk_reward,
        "success_rate": round(success_rate, 1),
        "rvol": rvol,
        "reasons": reasons,
    }


def _compute_prebreakout_swing_setup(
    sub: pd.DataFrame,
    *,
    rvol: float | None = None,
    is_etf: bool = False,
) -> dict[str, Any]:
    close = sub["close"]
    current_price = float(close.iloc[-1])
    atr_series = atr(sub["high"], sub["low"], close, 14)
    atr_value = _safe_float(atr_series.iloc[-1])
    effective_rvol = (
        rvol
        if rvol is not None
        else compute_session_adjusted_rvol(sub["volume"], sub.index[-1])
    )
    patterns = detect_patterns(sub, current_price, atr_value)
    ma20_value = _safe_float(sma(close, 20).iloc[-1])
    ma50_value = _safe_float(sma(close, 50).iloc[-1])
    rsi_value = _safe_float(rsi(close, 14).iloc[-1])
    vwap_series = vwap(
        sub["high"],
        sub["low"],
        close,
        sub["volume"],
        20,
    )
    macd_line, macd_signal, macd_histogram = macd(close)
    vwap_value = _safe_float(vwap_series.iloc[-1])
    prior_vwap = _safe_float(vwap_series.iloc[-2]) if len(vwap_series) > 1 else None
    prior_close = _safe_float(close.iloc[-2]) if len(close) > 1 else None
    macd_value = _safe_float(macd_line.iloc[-1])
    macd_signal_value = _safe_float(macd_signal.iloc[-1])
    macd_histogram_value = _safe_float(macd_histogram.iloc[-1])
    prior_macd_histogram = (
        _safe_float(macd_histogram.iloc[-2])
        if len(macd_histogram) > 1
        else None
    )

    resistance_window = sub["high"].tail(21).iloc[:-1]
    resistance = (
        _safe_float(resistance_window.max())
        if not resistance_window.empty
        else None
    )
    distance_to_breakout_pct = (
        (resistance - current_price) / resistance * 100.0
        if resistance and resistance > 0
        else None
    )
    rising_structure = _has_rising_price_structure(sub)
    trend_ok = bool(
        ma20_value is not None
        and ma50_value is not None
        and current_price >= ma20_value
        and current_price >= ma50_value
    )
    healthy_rsi = bool(rsi_value is not None and 45.0 <= rsi_value <= 72.0)
    vwap_reclaim = bool(
        vwap_value is not None
        and prior_vwap is not None
        and prior_close is not None
        and prior_close <= prior_vwap
        and current_price > vwap_value
    )
    macd_cross = bool(
        macd_value is not None
        and macd_signal_value is not None
        and macd_histogram_value is not None
        and prior_macd_histogram is not None
        and macd_value > macd_signal_value
        and macd_histogram_value > 0
        and prior_macd_histogram <= 0
    )

    bullish_patterns: list[dict[str, Any]] = []
    for key in ("cup_and_handle", "flag", "double_bottom", "triangle"):
        pattern = patterns.get(key) or {}
        if pattern.get("detected") and pattern.get("direction") == "bullish":
            bullish_patterns.append(pattern)
    bullish_patterns.sort(
        key=lambda pattern: -float(pattern.get("confidence") or 0.0)
    )
    selected_pattern = bullish_patterns[0] if bullish_patterns else None
    pattern_name = str(selected_pattern.get("name")) if selected_pattern else None
    pattern_level = _safe_float(selected_pattern.get("level")) if selected_pattern else None
    pattern_target = _safe_float(selected_pattern.get("target")) if selected_pattern else None
    pattern_stop = _safe_float(selected_pattern.get("stop")) if selected_pattern else None
    pattern_confidence = (
        _safe_float(selected_pattern.get("confidence")) or 0.0
        if selected_pattern
        else 0.0
    )

    breakout_price = pattern_level or resistance or current_price
    pattern_broke_out = bool(
        pattern_level is not None and current_price >= pattern_level
    )
    near_pattern_breakout = bool(
        pattern_level is not None
        and current_price < pattern_level
        and (pattern_level - current_price) / pattern_level * 100.0
        <= SWING_MAX_BREAKOUT_DISTANCE_PCT
    )
    near_resistance = bool(
        distance_to_breakout_pct is not None
        and 0.0 <= distance_to_breakout_pct <= SWING_MAX_BREAKOUT_DISTANCE_PCT
    )

    entry_price = (
        breakout_price
        if breakout_price and breakout_price >= current_price
        else current_price
    )
    recent_support = _safe_float(sub["low"].tail(20).min())
    atr_stop = (
        entry_price - atr_value * 1.25
        if atr_value is not None
        else entry_price * 0.96
    )
    valid_pattern_stop = (
        pattern_stop
        if pattern_stop is not None and 0 < pattern_stop < entry_price
        else None
    )
    stop_price = valid_pattern_stop or max(
        0.01,
        min(atr_stop, recent_support or atr_stop),
    )
    risk = entry_price - stop_price
    target_price = (
        pattern_target
        if pattern_target is not None and pattern_target > entry_price
        else entry_price + risk * 2.0
    )
    risk_reward = (
        round((target_price - entry_price) / risk, 2)
        if risk > 0 and target_price > entry_price
        else None
    )

    median_dollar_volume = float(
        (close * sub["volume"]).tail(20).median()
    )
    min_rvol = ETF_SWING_MIN_RVOL if is_etf else SWING_MIN_RVOL
    min_dollar_volume = (
        ETF_SWING_MIN_DOLLAR_VOLUME
        if is_etf
        else SWING_MIN_DOLLAR_VOLUME
    )
    max_atr_pct = ETF_SWING_MAX_ATR_PCT if is_etf else SWING_MAX_ATR_PCT
    atr_pct = (
        atr_value / current_price * 100.0
        if atr_value is not None and current_price > 0
        else None
    )
    volume_ok = bool(effective_rvol is not None and effective_rvol >= min_rvol)
    liquidity_ok = median_dollar_volume >= min_dollar_volume
    volatility_ok = bool(atr_pct is not None and atr_pct <= max_atr_pct)
    trigger_names: list[str] = []
    if pattern_name:
        trigger_names.append(pattern_name)
    if vwap_reclaim:
        trigger_names.append("VWAP Reclaim")
    if macd_cross:
        trigger_names.append("MACD Crossover")
    if near_resistance and not pattern_name:
        trigger_names.append("Resistance Proximity")

    ready_trigger = bool(pattern_broke_out or vwap_reclaim or macd_cross)
    near_trigger = bool(
        near_pattern_breakout
        or near_resistance
        or (selected_pattern is not None and not pattern_broke_out)
    )
    quality_ok = trend_ok and liquidity_ok and volatility_ok
    rr_ok = bool(
        risk_reward is not None and risk_reward >= SWING_MIN_RISK_REWARD
    )
    if quality_ok and volume_ok and rr_ok and ready_trigger:
        status = "ready"
    elif quality_ok and volume_ok and rr_ok and near_trigger:
        status = "near_trigger"
    else:
        status = "watchlist"

    trend_points = 10.0 if trend_ok and rising_structure else 8.0 if trend_ok else 3.0
    momentum_points = 10.0 if healthy_rsi and (macd_value or 0) > (macd_signal_value or 0) else 7.0 if healthy_rsi else 4.0
    volume_points = min(10.0, 5.0 + max(0.0, float(effective_rvol or 0.0) - min_rvol) * 3.0)
    liquidity_points = 10.0 if liquidity_ok else 3.0
    trigger_points = 10.0 if ready_trigger else 8.0 if near_trigger else 2.0
    proximity_points = (
        max(0.0, 10.0 - float(distance_to_breakout_pct or 0.0) * 2.0)
        if near_resistance
        else 5.0
    )
    rr_points = min(10.0, float(risk_reward or 0.0) / 2.0 * 10.0)
    setup_score = round(
        ((trend_points + momentum_points) / 2.0) * 0.40
        + ((volume_points + liquidity_points) / 2.0) * 0.25
        + ((trigger_points + proximity_points) / 2.0) * 0.20
        + rr_points * 0.15,
        2,
    )
    success_rate = round(
        min(
            92.0,
            max(
                45.0,
                pattern_confidence
                if pattern_confidence
                else 50.0 + setup_score * 4.0,
            ),
        ),
        1,
    )
    qualified = status in ("ready", "near_trigger")
    checks = {
        "trend": trend_ok,
        "liquidity": liquidity_ok,
        "volatility": volatility_ok,
        "elevated_rvol": volume_ok,
        "bullish_trigger": bool(ready_trigger or near_trigger),
        "risk_reward": rr_ok,
    }
    reasons = [
        f"Status: {status.replace('_', ' ').title()}",
        f"Triggers: {', '.join(trigger_names) if trigger_names else 'None'}",
        f"RVOL {float(effective_rvol or 0.0):.2f}x; median dollar volume ${median_dollar_volume / 1_000_000:.1f}M",
        f"R:R 1:{float(risk_reward or 0.0):.2f}; breakout distance {float(distance_to_breakout_pct or 0.0):.1f}%",
        f"Setup score {setup_score:.1f}/10",
    ]
    return {
        "qualified": qualified,
        "status": status,
        "setup_score": setup_score,
        "trigger_names": trigger_names,
        "pattern_name": pattern_name,
        "checks": checks,
        "breakout_price": round(float(breakout_price), 4),
        "stop_price": round(float(stop_price), 4),
        "target_price": round(float(target_price), 4),
        "risk_reward": risk_reward,
        "success_rate": success_rate,
        "distance_to_breakout_pct": (
            round(float(distance_to_breakout_pct), 2)
            if distance_to_breakout_pct is not None
            else None
        ),
        "median_dollar_volume": round(median_dollar_volume, 2),
        "rvol": effective_rvol,
        "reasons": reasons,
    }


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
    swing_setup = _compute_prebreakout_swing_setup(
        sub,
        rvol=rvol_v,
        is_etf=is_etf,
    )

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
        "swing_setup": swing_setup,
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


def _normalize_batch_columns(raw: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    """Ensure every batch can be concatenated and sliced by ticker."""
    if raw is None or raw.empty or isinstance(raw.columns, pd.MultiIndex):
        return raw
    if len(symbols) != 1:
        return raw
    normalized = raw.copy()
    normalized.columns = pd.MultiIndex.from_product([symbols, normalized.columns])
    return normalized


def _download_stock_batch(symbols: list[str]) -> tuple[pd.DataFrame, int]:
    """Download the large stock universe in bounded parallel chunks."""
    if not symbols:
        return pd.DataFrame(), 0
    chunks = [
        symbols[index:index + STOCK_BATCH_CHUNK_SIZE]
        for index in range(0, len(symbols), STOCK_BATCH_CHUNK_SIZE)
    ]
    if len(chunks) == 1:
        return _normalize_batch_columns(_download_batch(chunks[0]), chunks[0]), 1

    with ThreadPoolExecutor(max_workers=min(STOCK_BATCH_WORKERS, len(chunks))) as pool:
        frames = list(pool.map(_download_batch, chunks))
    normalized = [
        _normalize_batch_columns(frame, chunk)
        for frame, chunk in zip(frames, chunks)
        if frame is not None and not frame.empty
    ]
    if not normalized:
        return pd.DataFrame(), len(chunks)
    return pd.concat(normalized, axis=1), len(chunks)


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


def _build_tier1_rows(
    universe: list[dict[str, Any]],
    raw: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Build the shared OHLCV dataset used by both strategy funnels."""
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
    return rows


def _select_swing_tier1(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select liquid multi-trigger short-term setups before fundamentals."""
    selected: list[dict[str, Any]] = []
    for row in rows:
        if float(row.get("rvol") or 0.0) < SWING_MIN_RVOL:
            continue
        setup = _compute_prebreakout_swing_setup(
            row["sub"],
            rvol=float(row["rvol"]),
        )
        row["swing_setup"] = setup
        if setup["qualified"]:
            selected.append({**row, "swing_setup": setup})
    selected.sort(
        key=lambda row: (
            0 if row["swing_setup"].get("status") == "ready" else 1,
            -float(row["swing_setup"].get("setup_score") or 0.0),
            -float(row["swing_setup"]["success_rate"]),
            -float(row["swing_setup"]["risk_reward"] or 0.0),
            -float(row["rvol"]),
        )
    )
    return selected[:SWING_TIER1_MAX_CANDIDATES]


def _long_term_prefilter_score(sub: pd.DataFrame) -> float:
    """Rank long-term candidates cheaply without making RVOL a requirement."""
    if sub is None or len(sub) < 150:
        return -1.0
    close = sub["close"].astype(float)
    price = float(close.iloc[-1])
    ma50 = float(close.tail(50).mean())
    ma150 = float(close.tail(150).mean())
    ma200 = float(close.tail(200).mean()) if len(close) >= 200 else ma150
    returns = close.pct_change().dropna()
    annual_vol = (
        float(returns.tail(126).std() * math.sqrt(252))
        if len(returns) >= 20
        else 1.0
    )
    six_month_return = (
        price / float(close.iloc[-126]) - 1.0
        if len(close) >= 126 and float(close.iloc[-126]) > 0
        else 0.0
    )
    distance_ma200 = price / ma200 - 1.0 if ma200 > 0 else 0.0

    score = 0.0
    score += 2.0 if price >= ma200 else 0.0
    score += 1.5 if ma150 >= ma200 else 0.0
    score += 1.0 if price >= ma50 else 0.0
    score += 0.5 if six_month_return >= 0 else 0.0
    if annual_vol <= 0.25:
        score += 3.0
    elif annual_vol <= 0.35:
        score += 2.0
    elif annual_vol <= 0.50:
        score += 1.0
    if -0.10 <= distance_ma200 <= 0.20:
        score += 2.0
    elif -0.20 <= distance_ma200 <= 0.35:
        score += 1.0
    return round(score, 3)


def _select_long_term_tier1(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Select stable long-term candidates independently of current volume."""
    ranked: list[dict[str, Any]] = []
    for row in rows:
        long_term_rank = _long_term_prefilter_score(row["sub"])
        if long_term_rank < 0:
            continue
        ranked.append({**row, "long_term_prefilter_score": long_term_rank})
    ranked.sort(
        key=lambda row: (
            -float(row["long_term_prefilter_score"]),
            row["symbol"],
        )
    )
    return ranked[:LONG_TERM_TIER1_MAX_CANDIDATES]


def _merge_tier2_candidates(
    swing_candidates: list[dict[str, Any]],
    long_term_candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge both funnels while retaining strategy eligibility."""
    merged: dict[str, dict[str, Any]] = {}
    for path, candidates in (
        ("swing", swing_candidates),
        ("long_term", long_term_candidates),
    ):
        for candidate in candidates:
            symbol = candidate["symbol"]
            existing = merged.setdefault(symbol, {**candidate, "scan_paths": []})
            if path not in existing["scan_paths"]:
                existing["scan_paths"].append(path)
            if "long_term_prefilter_score" in candidate:
                existing["long_term_prefilter_score"] = candidate[
                    "long_term_prefilter_score"
                ]
    return list(merged.values())[:TIER1_MAX_CANDIDATES]


def _tier1_candidates(
    universe: list[dict[str, Any]],
    raw: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Backward-compatible combined Tier 1 interface."""
    rows = _build_tier1_rows(universe, raw)
    selected = _merge_tier2_candidates(
        _select_swing_tier1(rows),
        _select_long_term_tier1(rows),
    )

    return selected, rows


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

    def timed_stock_download(
        symbols: list[str],
    ) -> tuple[pd.DataFrame, float, int]:
        download_started = time.time()
        raw, chunk_count = _download_stock_batch(symbols)
        return raw, round(time.time() - download_started, 2), chunk_count

    stage_started = time.time()
    with ThreadPoolExecutor(max_workers=2) as pool:
        stock_download = pool.submit(timed_stock_download, stock_symbols)
        etf_download = pool.submit(timed_download, etf_symbols)
        stock_raw, stock_download_seconds, stock_batch_chunks = stock_download.result()
        etf_raw, etf_download_seconds = etf_download.result()
    timings["batch_download_seconds"] = round(time.time() - stage_started, 2)
    timings["stock_batch_download_seconds"] = stock_download_seconds
    timings["etf_batch_download_seconds"] = etf_download_seconds
    timings["stock_batch_chunks"] = stock_batch_chunks

    stage_started = time.time()
    tier1_rows = _build_tier1_rows(stock_universe, stock_raw)
    swing_tier1_candidates = _select_swing_tier1(tier1_rows)
    long_term_tier1_candidates = _select_long_term_tier1(tier1_rows)
    tier2_candidates = _merge_tier2_candidates(
        swing_tier1_candidates,
        long_term_tier1_candidates,
    )
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
            evaluation["source"] = row.get("source")
            evaluation["scan_paths"] = row.get("scan_paths") or []
            evaluation["scan_rvol"] = round(float(row.get("rvol") or 0.0), 2)
            evaluation["long_term_prefilter_score"] = row.get(
                "long_term_prefilter_score"
            )
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
        (
            r for r in stocks_results
            if "swing" in (r.get("scan_paths") or []) and _is_swing_qualified(r)
        ),
        key=lambda r: (
            0 if (r.get("swing_setup") or {}).get("status") == "ready" else 1,
            -float((r.get("swing_setup") or {}).get("setup_score") or 0.0),
            -float((r.get("swing_setup") or {}).get("success_rate") or 0.0),
            -float((r.get("swing_setup") or {}).get("risk_reward") or 0.0),
        ),
    )
    invest_stocks = sorted(
        (
            r for r in stocks_results
            if (
                "long_term" in (r.get("scan_paths") or [])
                and _is_long_term_qualified(r, score_threshold)
            )
        ),
        key=lambda r: -r["long_term_score"],
    )
    short_term_etfs = sorted(
        (r for r in etfs_results if _is_etf_short_qualified(r)),
        key=lambda r: (
            0 if (r.get("swing_setup") or {}).get("status") == "ready" else 1,
            -float((r.get("swing_setup") or {}).get("setup_score") or 0.0),
            -float((r.get("swing_setup") or {}).get("success_rate") or 0.0),
            -float((r.get("swing_setup") or {}).get("risk_reward") or 0.0),
        ),
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
        setup = r.get("swing_setup") or {}
        out = dict(r)
        out.pop("display_score", None)
        out["display_rationale"] = setup.get("reasons", [])
        out["strategy"] = "swing"
        out["strategy_label"] = (
            "Ready"
            if setup.get("status") == "ready"
            else "Near Trigger"
        )
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
        setup = r.get("swing_setup") or {}
        out = dict(r)
        out.pop("display_score", None)
        out["display_rationale"] = setup.get("reasons", [])
        out["strategy"] = "etf_swing"
        out["strategy_label"] = (
            "ETF Ready"
            if setup.get("status") == "ready"
            else "ETF Near Trigger"
        )
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

    qualified_swing = sum(
        1 for r in stocks_results
        if "swing" in (r.get("scan_paths") or []) and _is_swing_qualified(r)
    )
    qualified_invest = sum(
        1 for r in stocks_results
        if (
            "long_term" in (r.get("scan_paths") or [])
            and _is_long_term_qualified(r, score_threshold)
        )
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
        if (
            "swing" in (r.get("scan_paths") or []) and _is_swing_qualified(r)
        ) or (
            "long_term" in (r.get("scan_paths") or [])
            and _is_long_term_qualified(r, score_threshold)
        )
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
                (
                    "swing" in (r.get("scan_paths") or [])
                    and _is_swing_qualified(r)
                )
                or (
                    "long_term" in (r.get("scan_paths") or [])
                    and _is_long_term_qualified(r, score_threshold)
                )
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
        "russell_tier1_valid_count": sum(
            1 for row in tier1_rows
            if row.get("source") == "russell2000"
        ),
        "swing_tier1_candidate_count": len(swing_tier1_candidates),
        "russell_swing_tier1_candidate_count": sum(
            1 for row in swing_tier1_candidates
            if row.get("source") == "russell2000"
        ),
        "long_term_tier1_candidate_count": len(long_term_tier1_candidates),
        "russell_long_term_tier1_candidate_count": sum(
            1 for row in long_term_tier1_candidates
            if row.get("source") == "russell2000"
        ),
        "tier2_overlap_count": (
            len(swing_tier1_candidates)
            + len(long_term_tier1_candidates)
            - len(tier2_candidates)
        ),
        "tier2_candidate_count": len(tier2_candidates),
        "russell_tier2_candidate_count": sum(
            1 for row in tier2_candidates
            if row.get("source") == "russell2000"
        ),
        "tier2_info_calls": len(tier2_symbols),
        "russell_evaluated_count": sum(
            1 for result in stocks_results
            if result.get("source") == "russell2000"
        ),
        "tier1_primary_rvol": TIER1_PRIMARY_RVOL,
        "tier1_floor_rvol": TIER1_FLOOR_RVOL,
        "scan_duration_seconds": round(time.time() - started_at, 2),
        "scan_timings": timings,
        "universe_sources": {
            "sp500": sum(1 for entry in index_universe if entry.get("source") == "sp500"),
            "nasdaq100_only": sum(1 for entry in index_universe if entry.get("source") == "nasdaq100"),
            "russell2000": sum(
                1 for entry in index_universe
                if entry.get("source") == "russell2000"
            ),
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
        "swing_min_rvol": SWING_MIN_RVOL,
        "etf_swing_min_rvol": ETF_SWING_MIN_RVOL,
        "swing_min_risk_reward": SWING_MIN_RISK_REWARD,
        "swing_min_success_rate": SWING_MIN_SUCCESS_RATE,
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
        "stock_diagnostics": [
            {
                "symbol": r["symbol"],
                "scan_paths": r.get("scan_paths") or [],
                "rvol": r.get("scan_rvol"),
                "long_term_prefilter_score": r.get("long_term_prefilter_score"),
                "short_term_score": r.get("short_term_score"),
                "long_term_score": r.get("long_term_score"),
                "overall_score": r.get("overall_score"),
                "swing_setup": r.get("swing_setup"),
                "swing_qualified": (
                    "swing" in (r.get("scan_paths") or [])
                    and _is_swing_qualified(r)
                ),
                "long_term_qualified": (
                    "long_term" in (r.get("scan_paths") or [])
                    and _is_long_term_qualified(r, score_threshold)
                ),
            }
            for r in sorted(
                stocks_results,
                key=lambda item: -max(
                    float(item.get("short_term_score") or 0.0),
                    float(item.get("long_term_score") or 0.0),
                ),
            )
        ],
        "swing_tier1_diagnostics": [
            {
                "symbol": row["symbol"],
                "rvol": round(float(row.get("rvol") or 0.0), 2),
                "qualified": bool((row.get("swing_setup") or {}).get("qualified")),
                "checks": (row.get("swing_setup") or {}).get("checks", {}),
                "risk_reward": (row.get("swing_setup") or {}).get("risk_reward"),
                "success_rate": (row.get("swing_setup") or {}).get("success_rate"),
                "breakout_price": (row.get("swing_setup") or {}).get(
                    "breakout_price"
                ),
            }
            for row in sorted(
                (
                    row for row in tier1_rows
                    if row.get("swing_setup") is not None
                ),
                key=lambda item: (
                    -sum(
                        bool(value)
                        for value in (
                            (item.get("swing_setup") or {}).get("checks") or {}
                        ).values()
                    ),
                    -float(item.get("rvol") or 0.0),
                ),
            )[:30]
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
