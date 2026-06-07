"""CNN Fear & Greed Index — fetch from their public dataviz endpoint.

The index updates once per day after US market close. We cache results
in-process for 30 minutes to avoid hammering CNN.

Endpoint discovered from cnn.com/markets/fear-and-greed — undocumented but
stable since 2021. Requires a browser-like User-Agent.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from curl_cffi import requests as curl_requests

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
CACHE_TTL_SECONDS = 1800  # 30 min


@dataclass
class FearGreed:
    score: float
    rating: str
    label: str            # Hebrew label
    previous_close: float | None
    previous_week: float | None
    previous_month: float | None
    previous_year: float | None
    updated_at: str | None
    fetched_at: float     # unix seconds


_cache: dict[str, Any] = {"data": None, "ts": 0.0}


def _label_for(score: float) -> tuple[str, str]:
    """Return (cnn_rating, hebrew_label)."""
    if score <= 24:
        return "extreme fear", "פחד קיצוני"
    if score <= 44:
        return "fear", "פחד"
    if score <= 55:
        return "neutral", "ניטרלי"
    if score <= 74:
        return "greed", "חמדנות"
    return "extreme greed", "חמדנות קיצונית"


def _parse(payload: dict[str, Any]) -> FearGreed:
    fg = payload.get("fear_and_greed") or {}
    score = float(fg.get("score", 0.0))
    rating, label = _label_for(score)
    # CNN may also send their own rating; prefer ours for consistent thresholds.
    return FearGreed(
        score=round(score, 1),
        rating=rating,
        label=label,
        previous_close=_safe(fg.get("previous_close")),
        previous_week=_safe(fg.get("previous_1_week")),
        previous_month=_safe(fg.get("previous_1_month")),
        previous_year=_safe(fg.get("previous_1_year")),
        updated_at=fg.get("timestamp"),
        fetched_at=time.time(),
    )


def _safe(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        return round(f, 1)
    except (TypeError, ValueError):
        return None


def get_fear_greed(force: bool = False) -> FearGreed:
    now = time.time()
    if not force and _cache["data"] is not None and now - _cache["ts"] < CACHE_TTL_SECONDS:
        return _cache["data"]

    # curl_cffi impersonates Chrome — avoids 403 from CNN's bot filter.
    resp = curl_requests.get(
        CNN_URL,
        impersonate="chrome",
        headers={
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://edition.cnn.com/markets/fear-and-greed",
            "Origin": "https://edition.cnn.com",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = _parse(resp.json())
    _cache["data"] = data
    _cache["ts"] = now
    return data
