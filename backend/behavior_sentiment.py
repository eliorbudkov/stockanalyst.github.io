"""Human sentiment and market-behavior metrics.

Sources used without paid keys:
  - CNN Fear & Greed graphdata subcomponents: Put/Call Ratio and VIX.
  - yfinance: short interest and insider-related fields when Yahoo exposes them.
  - StockTwits public symbol stream, best effort.

Reddit and X require official API credentials, so the provider returns a clear
"not_configured" status instead of inventing data.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from curl_cffi import requests as curl_requests

from fear_greed import CNN_URL

CACHE_TTL_SECONDS = 900
_cache: dict[str, tuple[float, dict[str, Any]]] = {}

POSITIVE_WORDS = {
    "buy", "bull", "bullish", "breakout", "strong", "moon", "long", "beat",
    "upside", "growth", "accumulate", "support", "green", "calls",
}
NEGATIVE_WORDS = {
    "sell", "bear", "bearish", "breakdown", "weak", "short", "miss", "puts",
    "downside", "crash", "dump", "resistance", "red", "lawsuit",
}


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
        return None if np.isnan(f) or np.isinf(f) else f
    except (TypeError, ValueError):
        return None


def _score_label(score: float | None) -> str:
    if score is None:
        return "לא זמין"
    if score >= 7:
        return "חיובי"
    if score <= 4:
        return "שלילי"
    return "ניטרלי"


def _latest_component_value(component: dict[str, Any] | None) -> tuple[float | None, str | None]:
    if not component:
        return None, None
    data = component.get("data") or []
    if not data:
        return _safe_float(component.get("score")), None
    last = data[-1]
    ts = last.get("x")
    updated_at = None
    if ts:
        try:
            updated_at = datetime.fromtimestamp(float(ts) / 1000, tz=timezone.utc).isoformat()
        except Exception:
            updated_at = None
    return _safe_float(last.get("y")), updated_at


def _pcr_score(value: float | None) -> tuple[float | None, str]:
    if value is None:
        return None, "לא זמין"
    if value >= 1.15:
        return 7.5, "פחד גבוה - קונטרה חיובית אך תנודתית"
    if value >= 0.9:
        return 6.5, "פחד מתון"
    if value >= 0.65:
        return 5.5, "מאוזן"
    return 4.0, "חמדנות/אופטימיות גבוהה באופציות"


def _vix_score(value: float | None) -> tuple[float | None, str]:
    if value is None:
        return None, "לא זמין"
    if value >= 35:
        return 2.5, "פאניקה גבוהה"
    if value >= 25:
        return 4.0, "תנודתיות גבוהה"
    if value >= 16:
        return 6.5, "תנודתיות תקינה"
    if value >= 12:
        return 7.5, "תנודתיות נמוכה ונוחה"
    return 5.0, "שאננות גבוהה מדי"


def _cnn_behavior() -> dict[str, Any]:
    resp = curl_requests.get(
        CNN_URL,
        impersonate="chrome",
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://edition.cnn.com/markets/fear-and-greed",
        },
        timeout=10,
    )
    resp.raise_for_status()
    payload = resp.json()

    pcr_value, pcr_updated = _latest_component_value(payload.get("put_call_options"))
    pcr_score, pcr_rating = _pcr_score(pcr_value)
    vix_value, vix_updated = _latest_component_value(payload.get("market_volatility_vix"))
    vix_score, vix_rating = _vix_score(vix_value)

    return {
        "put_call_ratio": {
            "value": pcr_value,
            "score": pcr_score,
            "rating": pcr_rating,
            "source": "CNN Fear & Greed / Put-Call Options",
            "updated_at": pcr_updated,
            "status": "ok" if pcr_value is not None else "unavailable",
        },
        "vix": {
            "value": vix_value,
            "score": vix_score,
            "rating": vix_rating,
            "source": "CNN Fear & Greed / Market Volatility VIX",
            "updated_at": vix_updated,
            "status": "ok" if vix_value is not None else "unavailable",
        },
    }


def _score_text(text: str) -> tuple[int, int]:
    words = {w.strip("$#.,!?:;()[]{}\"'").lower() for w in text.split()}
    return len(words & POSITIVE_WORDS), len(words & NEGATIVE_WORDS)


def _stocktwits(symbol: str) -> dict[str, Any]:
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol.upper()}.json"
    try:
        resp = curl_requests.get(url, impersonate="chrome", timeout=8)
        resp.raise_for_status()
        payload = resp.json()
        messages = payload.get("messages") or []
        pos = neg = 0
        for msg in messages[:40]:
            p, n = _score_text(str(msg.get("body") or ""))
            pos += p
            neg += n
        total = pos + neg
        score = 5.0 if total == 0 else max(0.0, min(10.0, 5.0 + (pos - neg) / total * 5.0))
        return {
            "source": "StockTwits",
            "status": "ok",
            "mentions": len(messages),
            "positive_terms": pos,
            "negative_terms": neg,
            "score": round(score, 2),
            "label": _score_label(score),
        }
    except Exception as exc:
        return {
            "source": "StockTwits",
            "status": "unavailable",
            "mentions": 0,
            "positive_terms": 0,
            "negative_terms": 0,
            "score": None,
            "label": "לא זמין",
            "error": str(exc)[:160],
        }


def _social_sentiment(symbol: str) -> dict[str, Any]:
    providers = [
        _stocktwits(symbol),
        {
            "source": "Reddit",
            "status": "not_configured",
            "score": None,
            "label": "דורש REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET",
            "mentions": 0,
        },
        {
            "source": "X",
            "status": "not_configured",
            "score": None,
            "label": "דורש X_BEARER_TOKEN",
            "mentions": 0,
        },
    ]
    available_scores = [p["score"] for p in providers if isinstance(p.get("score"), (int, float))]
    score = sum(available_scores) / len(available_scores) if available_scores else None
    return {
        "score": None if score is None else round(score, 2),
        "label": _score_label(score),
        "providers": providers,
        "available_sources": [p["source"] for p in providers if p["status"] == "ok"],
        "unavailable_sources": [p["source"] for p in providers if p["status"] != "ok"],
    }


def _short_interest(info: dict[str, Any]) -> dict[str, Any]:
    short_pct = _safe_float(info.get("shortPercentOfFloat"))
    short_ratio = _safe_float(info.get("shortRatio"))
    shares_short = _safe_float(info.get("sharesShort"))
    prev_shares_short = _safe_float(info.get("sharesShortPriorMonth"))
    score = 5.0
    notes: list[str] = []

    if short_pct is not None:
        pct = short_pct * 100 if short_pct <= 1 else short_pct
        if pct >= 25:
            score = 2.5
            notes.append("שורט גבוה מאוד")
        elif pct >= 15:
            score = 3.5
            notes.append("שורט גבוה")
        elif pct >= 8:
            score = 5.0
            notes.append("שורט בינוני")
        else:
            score = 7.0
            notes.append("שורט נמוך")
    if short_ratio is not None and short_ratio > 7:
        score = min(score, 4.0)
        notes.append("ימים לכיסוי גבוהים")

    return {
        "score": round(score, 2) if short_pct is not None or short_ratio is not None else None,
        "label": _score_label(score) if short_pct is not None or short_ratio is not None else "לא זמין",
        "short_percent_float": None if short_pct is None else round(short_pct * 100 if short_pct <= 1 else short_pct, 2),
        "short_ratio": short_ratio,
        "shares_short": shares_short,
        "shares_short_prior_month": prev_shares_short,
        "notes": notes,
        "source": "Yahoo Finance via yfinance",
        "status": "ok" if short_pct is not None or short_ratio is not None else "unavailable",
    }


def _insider_trading(ticker: yf.Ticker, info: dict[str, Any]) -> dict[str, Any]:
    held_pct = _safe_float(info.get("heldPercentInsiders"))
    base = {
        "score": None,
        "label": "לא זמין",
        "net_shares_90d": None,
        "net_value_90d": None,
        "transactions_90d": None,
        "held_percent_insiders": None if held_pct is None else round(held_pct * 100 if held_pct <= 1 else held_pct, 2),
        "source": "Yahoo Finance via yfinance",
        "status": "unavailable",
    }
    try:
        tx = getattr(ticker, "insider_transactions", None)
        if tx is None:
            tx = ticker.get_insider_transactions()
        if tx is None or not isinstance(tx, pd.DataFrame) or tx.empty:
            if held_pct is not None:
                base.update({"score": 5.5, "label": "אחזקת insiders זמינה, עסקאות לא זמינות", "status": "partial"})
            return base

        df = tx.copy()
        date_col = next((c for c in df.columns if "date" in str(c).lower()), None)
        shares_col = next((c for c in df.columns if "shares" in str(c).lower()), None)
        value_col = next((c for c in df.columns if "value" in str(c).lower()), None)
        if date_col:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce", utc=True)
            cutoff = datetime.now(timezone.utc) - timedelta(days=90)
            df = df[df[date_col] >= cutoff]

        net_shares = _safe_float(pd.to_numeric(df[shares_col], errors="coerce").sum()) if shares_col else None
        net_value = _safe_float(pd.to_numeric(df[value_col], errors="coerce").sum()) if value_col else None
        score = 5.0
        if net_shares is not None:
            score = 7.0 if net_shares > 0 else 3.5 if net_shares < 0 else 5.0
        elif held_pct is not None and held_pct > 0.05:
            score = 6.0

        return {
            **base,
            "score": score,
            "label": _score_label(score),
            "net_shares_90d": net_shares,
            "net_value_90d": net_value,
            "transactions_90d": int(len(df)),
            "status": "ok",
        }
    except Exception as exc:
        base["error"] = str(exc)[:160]
        if held_pct is not None:
            base.update({"score": 5.5, "label": "אחזקת insiders זמינה, עסקאות לא זמינות", "status": "partial"})
        return base


def _composite_score(parts: dict[str, Any]) -> tuple[float | None, list[str]]:
    weighted = [
        (parts["put_call_ratio"].get("score"), 0.18, "PCR לא זמין"),
        (parts["vix"].get("score"), 0.18, "VIX לא זמין"),
        (parts["social_sentiment"].get("score"), 0.24, "Social לא זמין/לא מחובר"),
        (parts["insider_trading"].get("score"), 0.18, "Insider Trading לא זמין"),
        (parts["short_interest"].get("score"), 0.22, "Short Interest לא זמין"),
    ]
    total = 0.0
    weight = 0.0
    notes: list[str] = []
    for score, w, missing in weighted:
        if isinstance(score, (int, float)):
            total += float(score) * w
            weight += w
        else:
            notes.append(missing)
    if weight == 0:
        return None, notes
    return round(total / weight, 2), notes


def get_behavior_sentiment(symbol: str, force: bool = False) -> dict[str, Any]:
    key = symbol.upper().strip()
    now = time.time()
    cached = _cache.get(key)
    if not force and cached and now - cached[0] < CACHE_TTL_SECONDS:
        return cached[1]

    ticker = yf.Ticker(key)
    try:
        info = ticker.info or {}
    except Exception:
        info = {}

    try:
        cnn = _cnn_behavior()
    except Exception as exc:
        cnn = {
            "put_call_ratio": {"value": None, "score": None, "rating": "לא זמין", "source": "CNN", "status": "unavailable", "error": str(exc)[:160]},
            "vix": {"value": None, "score": None, "rating": "לא זמין", "source": "CNN", "status": "unavailable", "error": str(exc)[:160]},
        }

    result = {
        **cnn,
        "social_sentiment": _social_sentiment(key),
        "insider_trading": _insider_trading(ticker, info),
        "short_interest": _short_interest(info),
        "fetched_at": now,
    }
    composite, notes = _composite_score(result)
    result["composite_score"] = composite
    result["label"] = _score_label(composite)
    result["notes"] = notes

    _cache[key] = (now, result)
    return result
