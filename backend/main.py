"""FastAPI service: yfinance data + technical indicators + 1-10 entry score.

Run locally:
    cd backend
    python -m venv .venv
    .venv\\Scripts\\activate    (Windows) or  source .venv/bin/activate  (mac/linux)
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

# Load backend/.env (ANTHROPIC_API_KEY, etc.) before any module that reads env.
load_dotenv(Path(__file__).parent / ".env")

from behavior_sentiment import get_behavior_sentiment
from entries import compute_long_term_entry, compute_short_term_entry, entries_to_dict
from fear_greed import get_fear_greed
from global_liquidity import get_global_liquidity, snapshot_to_dict
from heatmap import get_sector_status_for_symbol, get_sp500_heatmap
from indicators import atr, bollinger_bands, macd, rsi, sma, to_nullable_list, vwap
from levels import find_support_resistance
from matrices import (
    compute_gap_pct,
    compute_long_term_score,
    compute_rvol,
    compute_short_term_score,
    matrix_to_dict,
)
from patterns import detect_patterns
from risk import build_long_term_plan, build_risk_plan
from scanner import get_scan
from scoring import compute_score
from translate import translate_to_hebrew
from trump_holdings import get_trump_holdings, is_trump_held

app = FastAPI(title="Stock Analyst API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Helpers ────────────────────────────────────────────────────────────────────
def _safe_float(v: Any) -> float | None:
    try:
        if v is None: return None
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _ticker(symbol: str) -> yf.Ticker:
    sym = symbol.strip().upper()
    if not sym or len(sym) > 10:
        raise HTTPException(status_code=400, detail="Invalid symbol")
    return yf.Ticker(sym)


def _history(symbol: str, period: str = "2y") -> pd.DataFrame:
    t = _ticker(symbol)
    df = t.history(period=period, interval="1d", auto_adjust=True)
    if df is None or df.empty:
        raise HTTPException(status_code=404, detail=f"No data for {symbol}")
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns=str.lower)
    df = df[["open", "high", "low", "close", "volume"]].dropna()
    return df


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/")
def root() -> dict[str, str]:
    return {"service": "stock-analyst-api", "status": "ok"}


@app.get("/api/fear-greed")
def fear_greed(force: bool = Query(False)) -> dict[str, Any]:
    try:
        fg = get_fear_greed(force=force)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"CNN fetch failed: {e}")
    return {
        "score": fg.score,
        "rating": fg.rating,
        "label": fg.label,
        "previous_close": fg.previous_close,
        "previous_week": fg.previous_week,
        "previous_month": fg.previous_month,
        "previous_year": fg.previous_year,
        "updated_at": fg.updated_at,
        "fetched_at": fg.fetched_at,
    }


@app.get("/api/heatmap")
def heatmap(force: bool = Query(False)) -> dict[str, Any]:
    try:
        return get_sp500_heatmap(force=force)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Heatmap fetch failed: {e}")


@app.get("/api/scan")
def scan(force: bool = Query(False)) -> dict[str, Any]:
    try:
        return get_scan(force=force)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Scan failed: {e}")


# ── On-demand scan trigger ───────────────────────────────────────────────────
# The heavy market scan never runs on this 512MB free-tier dyno — it OOMs (see
# scanner.LIVE_SCAN_ENABLED, default off). Instead the in-app "scan" button asks
# GitHub Actions to run it on a 7GB runner: this dispatches refresh-seed.yml,
# which regenerates backend/data/scan.json and pushes it, auto-deploying a fresh
# seed here (~5-10 min). The PAT lives ONLY in Render's env (GH_DISPATCH_TOKEN) —
# never in git. Without it the endpoint is a no-op 503.
GH_REPO = os.getenv("GH_REPO", "eliorbudkov/stockanalyst.github.io")
GH_WORKFLOW = os.getenv("GH_WORKFLOW", "refresh-seed.yml")
GH_REF = os.getenv("GH_REF", "main")
_SCAN_TRIGGER_COOLDOWN_S = 90  # block accidental double-clicks / spam dispatches
_last_scan_trigger = 0.0


@app.post("/api/scan/trigger")
def scan_trigger() -> dict[str, Any]:
    global _last_scan_trigger
    token = os.getenv("GH_DISPATCH_TOKEN", "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="הפעלת סריקה אינה מוגדרת בשרת (חסר GH_DISPATCH_TOKEN).",
        )

    now = time.time()
    since = now - _last_scan_trigger
    if since < _SCAN_TRIGGER_COOLDOWN_S:
        return {
            "status": "already_running",
            "retry_after_seconds": int(_SCAN_TRIGGER_COOLDOWN_S - since),
        }

    url = (
        f"https://api.github.com/repos/{GH_REPO}"
        f"/actions/workflows/{GH_WORKFLOW}/dispatches"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps({"ref": GH_REF}).encode("utf-8"),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "stock-analyst")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise HTTPException(status_code=502, detail=f"GitHub dispatch {e.code}: {body}")
    except Exception as e:  # noqa: BLE001 - surface any network failure
        raise HTTPException(status_code=502, detail=f"GitHub dispatch error: {e}")

    if status not in (201, 202, 204):
        raise HTTPException(status_code=502, detail=f"GitHub dispatch HTTP {status}")

    _last_scan_trigger = now
    baseline = None
    try:
        baseline = get_scan(force=False).get("fetched_at")
    except Exception:  # noqa: BLE001 - baseline is best-effort
        pass
    return {"status": "triggered", "baseline_fetched_at": baseline, "eta_seconds": 480}


@app.get("/api/holdings/trump")
def trump_holdings() -> dict[str, Any]:
    return get_trump_holdings()


@app.get("/api/global-liquidity")
def global_liquidity(force: bool = Query(False)) -> dict[str, Any]:
    try:
        snap = get_global_liquidity(force=force)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"FRED fetch failed: {e}")
    return snapshot_to_dict(snap)


@app.get("/api/behavior-sentiment")
def behavior_sentiment(symbol: str = Query(...), force: bool = Query(False)) -> dict[str, Any]:
    try:
        return get_behavior_sentiment(symbol, force=force)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Behavior sentiment fetch failed: {e}")


@app.get("/api/quote")
def quote(symbol: str = Query(...)) -> dict[str, Any]:
    t = _ticker(symbol)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    fast = getattr(t, "fast_info", None)

    price = _safe_float(getattr(fast, "last_price", None)) or _safe_float(info.get("currentPrice"))
    prev = _safe_float(getattr(fast, "previous_close", None)) or _safe_float(info.get("previousClose"))
    change_pct = None
    if price is not None and prev not in (None, 0):
        change_pct = (price - prev) / prev * 100.0

    return {
        "symbol": symbol.upper(),
        "name": info.get("shortName") or info.get("longName"),
        "currency": info.get("currency") or getattr(fast, "currency", None),
        "price": price,
        "prev_close": prev,
        "change_pct": change_pct,
        "market_cap": _safe_float(info.get("marketCap")) or _safe_float(getattr(fast, "market_cap", None)),
        "pe": _safe_float(info.get("trailingPE")),
        "pb": _safe_float(info.get("priceToBook")),
        "dividend_yield": _safe_float(info.get("dividendYield")),
        "beta": _safe_float(info.get("beta")),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        # Extras used by the long-term matrix
        "debt_to_equity": _safe_float(info.get("debtToEquity")),
        "free_cashflow": _safe_float(info.get("freeCashflow")),
        "operating_cashflow": _safe_float(info.get("operatingCashflow")),
        "shares_outstanding": _safe_float(info.get("sharesOutstanding")),
        "total_cash": _safe_float(info.get("totalCash")),
        "total_debt": _safe_float(info.get("totalDebt")),
        "current_ratio": _safe_float(info.get("currentRatio")),
        "quick_ratio": _safe_float(info.get("quickRatio")),
        "profit_margin": _safe_float(info.get("profitMargins")),
        "operating_margin": _safe_float(info.get("operatingMargins")),
        "return_on_equity": _safe_float(info.get("returnOnEquity")),
        "revenue_growth": _safe_float(info.get("revenueGrowth")),
        "earnings_growth": _safe_float(info.get("earningsGrowth")),
        "eps": _safe_float(info.get("trailingEps")),
        # Company profile for the description panel
        "description": info.get("longBusinessSummary") or info.get("shortBusinessSummary"),
        "description_he": translate_to_hebrew(
            info.get("longBusinessSummary") or info.get("shortBusinessSummary")
        ),
        "website": info.get("website"),
        "country": info.get("country"),
        "employees": info.get("fullTimeEmployees"),
    }


@app.get("/api/history")
def history(symbol: str = Query(...), period: str = Query("2y")) -> dict[str, Any]:
    df = _history(symbol, period)
    candles = [
        {
            "time": int(idx.timestamp()),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        }
        for idx, row in df.iterrows()
    ]
    return {"symbol": symbol.upper(), "candles": candles}


@app.get("/api/analyze")
def analyze(symbol: str = Query(...), period: str = Query("2y")) -> dict[str, Any]:
    df = _history(symbol, period)
    q = quote(symbol)

    close = df["close"]
    ma20 = sma(close, 20)
    ma50 = sma(close, 50)
    ma150 = sma(close, 150)
    ma200 = sma(close, 200)
    rsi14 = rsi(close, 14)
    atr14 = atr(df["high"], df["low"], close, 14)
    macd_line, macd_signal, macd_histogram = macd(close)
    bb_upper, bb_middle, bb_lower, bb_width_pct = bollinger_bands(close)
    vwap20 = vwap(df["high"], df["low"], close, df["volume"], 20)

    last_price = float(close.iloc[-1])
    last_ma20 = _safe_float(ma20.iloc[-1])
    last_ma50 = _safe_float(ma50.iloc[-1])
    last_ma150 = _safe_float(ma150.iloc[-1])
    last_ma200 = _safe_float(ma200.iloc[-1])
    last_rsi = _safe_float(rsi14.iloc[-1])
    last_atr = _safe_float(atr14.iloc[-1])
    last_macd = _safe_float(macd_line.iloc[-1])
    last_macd_signal = _safe_float(macd_signal.iloc[-1])
    last_macd_histogram = _safe_float(macd_histogram.iloc[-1])
    last_bb_upper = _safe_float(bb_upper.iloc[-1])
    last_bb_middle = _safe_float(bb_middle.iloc[-1])
    last_bb_lower = _safe_float(bb_lower.iloc[-1])
    last_bb_width_pct = _safe_float(bb_width_pct.iloc[-1])
    last_vwap = _safe_float(vwap20.iloc[-1])
    atr_pct = (last_atr / last_price * 100.0) if last_atr and last_price else None

    # Quote-derived price overrides last close if live trading day is present
    quote_price = q.get("price") or last_price
    if q.get("price") is None:
        q["price"] = last_price
        if q.get("prev_close") is not None:
            q["change_pct"] = (last_price - q["prev_close"]) / q["prev_close"] * 100.0

    candles = [
        {
            "time": int(idx.timestamp()),
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "volume": float(row.volume),
        }
        for idx, row in df.iterrows()
    ]

    indicators = {
        "ma20": last_ma20,
        "ma50": last_ma50,
        "ma150": last_ma150,
        "ma200": last_ma200,
        "rsi14": last_rsi,
        "atr14": last_atr,
        "atr_pct": atr_pct,
        "macd": last_macd,
        "macd_signal": last_macd_signal,
        "macd_histogram": last_macd_histogram,
        "bb_upper": last_bb_upper,
        "bb_middle": last_bb_middle,
        "bb_lower": last_bb_lower,
        "bb_width_pct": last_bb_width_pct,
        "vwap": last_vwap,
        "ma20_series": to_nullable_list(ma20),
        "ma50_series": to_nullable_list(ma50),
        "ma150_series": to_nullable_list(ma150),
        "ma200_series": to_nullable_list(ma200),
        "rsi_series": to_nullable_list(rsi14),
        "macd_series": to_nullable_list(macd_line),
        "macd_signal_series": to_nullable_list(macd_signal),
        "macd_histogram_series": to_nullable_list(macd_histogram),
        "bb_upper_series": to_nullable_list(bb_upper),
        "bb_middle_series": to_nullable_list(bb_middle),
        "bb_lower_series": to_nullable_list(bb_lower),
        "vwap_series": to_nullable_list(vwap20),
    }

    support, resistance = find_support_resistance(df, quote_price, last_atr)
    patterns = detect_patterns(df, quote_price, last_atr)
    try:
        fg = get_fear_greed(force=False)
        fear_greed_data = {
            "score": fg.score,
            "rating": fg.rating,
            "label": fg.label,
            "previous_close": fg.previous_close,
            "previous_week": fg.previous_week,
            "previous_month": fg.previous_month,
            "previous_year": fg.previous_year,
            "updated_at": fg.updated_at,
            "fetched_at": fg.fetched_at,
        }
    except Exception:
        fear_greed_data = None

    try:
        behavior_sentiment_data = get_behavior_sentiment(symbol, force=False)
    except Exception:
        behavior_sentiment_data = None

    sector_status = get_sector_status_for_symbol(symbol, q.get("sector"))
    try:
        gli_data = snapshot_to_dict(get_global_liquidity(force=False))
    except Exception:
        gli_data = None

    result = compute_score(
        price=quote_price,
        ma20=last_ma20, ma50=last_ma50, ma150=last_ma150, ma200=last_ma200,
        rsi14=last_rsi,
        atr_pct=atr_pct,
        volume_series=df["volume"],
        pe=q.get("pe"), pb=q.get("pb"), beta=q.get("beta"),
        macd_histogram=last_macd_histogram,
        bb_lower=last_bb_lower,
        bb_upper=last_bb_upper,
        vwap=last_vwap,
        patterns=patterns,
        fear_greed=fear_greed_data,
        behavior_sentiment=behavior_sentiment_data,
        sector_status=sector_status,
        global_liquidity=gli_data,
    )

    short_entry = compute_short_term_entry(
        price=quote_price,
        resistance=resistance.price if resistance else None,
        vwap=last_vwap,
        ma20=last_ma20,
        atr14=last_atr,
    )
    long_entry = compute_long_term_entry(
        price=quote_price,
        ma150=last_ma150,
        ma200=last_ma200,
        pe=q.get("pe"),
        eps=q.get("eps"),
    )

    plan = build_risk_plan(
        entry_price=short_entry.price if short_entry is not None else quote_price,
        atr14=last_atr,
        support_price=support.price if support else None,
        resistance_price=resistance.price if resistance else None,
        direction="long",
    )

    # Long-term plan: stop + TPs anchored to the long-term entry price,
    # not the current price. Fixes the "long-term entry below short-term
    # stop" inconsistency that surfaced in the NVDA validation.
    # Sanity check: if the long entry was blocked by the DCF overvaluation
    # gate, we do not produce a plan — there is no defensible long-term
    # entry to anchor stops/TPs against.
    long_plan = (
        build_long_term_plan(
            entry_price=long_entry.price,
            atr14=last_atr,
            support_price=support.price if support else None,
            resistance_price=resistance.price if resistance else None,
        )
        if long_entry is not None and not getattr(long_entry, "blocked", False)
        else None
    )

    def _plan_dict(p):  # noqa: ANN001 — small inline helper
        if p is None:
            return None
        return {
            "entry_price": p.entry_price,
            "direction": p.direction,
            "stop": None if p.stop_loss is None else {
                "price": p.stop_loss.price,
                "distance_pct": p.stop_loss.distance_pct,
                "risk_per_share": p.stop_loss.risk_per_share,
                "reason": p.stop_loss.reason,
            },
            "take_profit_1": None if p.take_profit_1 is None else {
                "price": p.take_profit_1.price,
                "distance_pct": p.take_profit_1.distance_pct,
                "rr": p.take_profit_1.rr,
                "reason": p.take_profit_1.reason,
            },
            "take_profit_2": None if p.take_profit_2 is None else {
                "price": p.take_profit_2.price,
                "distance_pct": p.take_profit_2.distance_pct,
                "rr": p.take_profit_2.rr,
                "reason": p.take_profit_2.reason,
            },
            "notes": p.notes,
        }

    # Swing trading does NOT carry a predetermined stop/TP. The user-level
    # decision is intentionally discretionary (chart, ATR, news context) and
    # the UI exposes an override input for entering one manually. The
    # long-term plan still ships with its anchored stop/TPs because value
    # entry/exit are inherently mathematical.
    risk_management = {
        "entry_price": plan.entry_price,
        "direction": plan.direction,
        "stop_loss": None,
        "take_profit_1": None,
        "take_profit_2": None,
        "notes": [
            "סווינג ללא ניהול סיכון מתמטי קבוע מראש. "
            "להגדיר stop/TP — הזן מחיר כניסה ידני בפאנל ניהול הסיכון."
        ],
        **entries_to_dict(short_entry, long_entry),
        # New long-term plan — stop+TPs anchored to long-term entry price.
        "long_term_plan": _plan_dict(long_plan),
        "calculation_inputs": {
            "atr14": last_atr,
            "support_price": support.price if support else None,
            "resistance_price": resistance.price if resistance else None,
        },
    }

    levels = {
        "support": None if support is None else {
            "price": round(float(support.price), 4),
            "touches": support.touches,
            "distance_pct": round((support.price - quote_price) / quote_price * 100.0, 2),
        },
        "resistance": None if resistance is None else {
            "price": round(float(resistance.price), 4),
            "touches": resistance.touches,
            "distance_pct": round((resistance.price - quote_price) / quote_price * 100.0, 2),
        },
        "risk_reward": None,
    }
    if support is not None and resistance is not None:
        risk_anchor = plan.entry_price
        risk = risk_anchor - support.price
        reward = resistance.price - risk_anchor
        if risk > 0:
            levels["risk_reward"] = round(reward / risk, 2)

    # ── Dual-matrix scoring (short term / long term) ───────────────────────
    rvol = compute_rvol(df["volume"])
    gap_pct = compute_gap_pct(df)

    trump_flag = is_trump_held(symbol)

    short_term = compute_short_term_score(
        price=quote_price,
        ma20=last_ma20,
        ma50=last_ma50,
        rsi14=last_rsi,
        vwap=last_vwap,
        rvol=rvol,
        gap_pct=gap_pct,
        patterns=patterns,
        behavior=behavior_sentiment_data,
        sector_status=sector_status,
        global_liquidity=gli_data,
        trump_held=trump_flag,
    )

    long_term = compute_long_term_score(
        price=quote_price,
        ma50=last_ma50,
        ma150=last_ma150,
        ma200=last_ma200,
        pe=q.get("pe"),
        pb=q.get("pb"),
        beta=q.get("beta"),
        debt_to_equity=q.get("debt_to_equity"),
        free_cashflow=q.get("free_cashflow"),
        market_cap=q.get("market_cap"),
        shares_outstanding=q.get("shares_outstanding"),
        operating_cashflow=q.get("operating_cashflow"),
        total_cash=q.get("total_cash"),
        total_debt=q.get("total_debt"),
        current_ratio=q.get("current_ratio"),
        quick_ratio=q.get("quick_ratio"),
        profit_margin=q.get("profit_margin"),
        operating_margin=q.get("operating_margin"),
        return_on_equity=q.get("return_on_equity"),
        revenue_growth=q.get("revenue_growth"),
        earnings_growth=q.get("earnings_growth"),
        fear_greed=fear_greed_data,
        behavior=behavior_sentiment_data,
        sector_status=sector_status,
        global_liquidity=gli_data,
        rvol=rvol,
        patterns=patterns,
        trump_held=trump_flag,
        overvaluation_gate=getattr(long_entry, "blocked", False) if long_entry else False,
    )

    matrices = {
        "short_term": matrix_to_dict(short_term),
        "long_term": matrix_to_dict(long_term),
        "rvol": rvol,
        "gap_pct": gap_pct,
        "sector_status": sector_status,
        "global_liquidity": gli_data,
    }

    return {
        "symbol": symbol.upper(),
        "quote": q,
        "candles": candles,
        "indicators": indicators,
        "levels": levels,
        "risk_management": risk_management,
        "patterns": patterns,
        "fear_greed": fear_greed_data,
        "behavior_sentiment": behavior_sentiment_data,
        "matrices": matrices,
        "score": round(result.score, 2),
        "score_breakdown": result.breakdown,
        "rationale": result.rationale,
    }
