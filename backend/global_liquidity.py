"""Global Liquidity Index proxy via FRED WALCL (Fed total assets).

FRED's public CSV endpoint requires no API key. WALCL is the Federal Reserve's
total assets in millions of dollars — the most-watched liquidity barometer
for risk assets. We resample to weekly observations and compute a short-window
trend slope to derive a 0-10 score used by the dual matrices.

Cached for 6 hours since the series only updates weekly.
"""
from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass
from typing import Any

from curl_cffi import requests as curl_requests

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=WALCL"
CACHE_TTL_SECONDS = 6 * 3600  # 6h — WALCL updates Wednesdays


@dataclass
class LiquiditySnapshot:
    series: list[dict[str, Any]]   # [{date, value_b}, ...] (billions of USD)
    latest_value_b: float
    latest_date: str
    change_4w_pct: float | None
    change_13w_pct: float | None
    change_52w_pct: float | None
    trend_label: str               # Hebrew
    score: float                   # 0..10 for matrix integration
    fetched_at: float


_cache: dict[str, Any] = {"data": None, "ts": 0.0}


def _fetch_csv() -> list[dict[str, Any]]:
    """Return the raw WALCL series as a list of {date, value_b} dicts.

    Values are converted from millions of USD to billions (more chart-friendly).
    The curl_cffi client is used because FRED occasionally rate-limits plain
    `requests` user agents.
    """
    resp = curl_requests.get(
        FRED_URL,
        impersonate="chrome",
        timeout=15,
        headers={"Accept": "text/csv,text/plain,*/*"},
    )
    resp.raise_for_status()

    text = resp.text
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict[str, Any]] = []
    for row in reader:
        date = row.get("observation_date") or row.get("DATE")
        raw = row.get("WALCL")
        if not date or not raw or raw == ".":
            continue
        try:
            value_b = float(raw) / 1000.0  # millions → billions
        except ValueError:
            continue
        out.append({"date": date, "value_b": round(value_b, 1)})
    return out


def _pct_change_at(series: list[dict[str, Any]], weeks_back: int) -> float | None:
    if len(series) < weeks_back + 1:
        return None
    latest = series[-1]["value_b"]
    past = series[-(weeks_back + 1)]["value_b"]
    if past == 0:
        return None
    return round((latest - past) / past * 100.0, 2)


def _score_from_trend(c4w: float | None, c13w: float | None) -> tuple[float, str]:
    """0-10 score with Hebrew label. Weighting 4-week change more heavily —
    risk-asset response to balance-sheet shifts is short-cycle."""
    if c4w is None and c13w is None:
        return 5.0, "ניטרלי (אין נתוני מגמה)"
    c4 = c4w if c4w is not None else 0.0
    c13 = c13w if c13w is not None else 0.0
    composite = c4 * 0.65 + c13 * 0.35  # weighted

    if composite >= 1.5:
        return 9.5, "התרחבות חזקה — רוח גבית לנכסי סיכון"
    if composite >= 0.5:
        return 8.0, "התרחבות מתונה — סביבה חיובית"
    if composite >= 0.0:
        return 6.5, "עלייה קלה — תמיכה חלשה"
    if composite >= -0.5:
        return 5.0, "ניטרלי"
    if composite >= -1.5:
        return 3.5, "כיווץ נזילות — רוח נגדית"
    return 2.0, "כיווץ חד — סיכון מערכתי"


def _build() -> LiquiditySnapshot:
    series_all = _fetch_csv()
    # Keep last 2 years for the chart (~104 observations)
    series = series_all[-110:] if len(series_all) > 110 else series_all
    if not series:
        raise RuntimeError("WALCL returned empty series")

    latest = series[-1]
    c4 = _pct_change_at(series_all, 4)
    c13 = _pct_change_at(series_all, 13)
    c52 = _pct_change_at(series_all, 52)
    score, label = _score_from_trend(c4, c13)

    return LiquiditySnapshot(
        series=series,
        latest_value_b=latest["value_b"],
        latest_date=latest["date"],
        change_4w_pct=c4,
        change_13w_pct=c13,
        change_52w_pct=c52,
        trend_label=label,
        score=score,
        fetched_at=time.time(),
    )


def get_global_liquidity(force: bool = False) -> LiquiditySnapshot:
    now = time.time()
    if not force and _cache["data"] is not None and now - _cache["ts"] < CACHE_TTL_SECONDS:
        return _cache["data"]
    data = _build()
    _cache["data"] = data
    _cache["ts"] = now
    return data


def snapshot_to_dict(s: LiquiditySnapshot) -> dict[str, Any]:
    return {
        "series": s.series,
        "latest_value_b": s.latest_value_b,
        "latest_date": s.latest_date,
        "change_4w_pct": s.change_4w_pct,
        "change_13w_pct": s.change_13w_pct,
        "change_52w_pct": s.change_52w_pct,
        "trend_label": s.trend_label,
        "score": s.score,
        "fetched_at": s.fetched_at,
        "indicator": "Federal Reserve Total Assets (WALCL)",
        "source": "FRED — fred.stlouisfed.org",
    }
