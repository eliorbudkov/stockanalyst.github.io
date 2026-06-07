"""Pivot-based support & resistance detection.

Algorithm:
  1. Take the last ~6 months of bars.
  2. Find pivot highs/lows (bars whose high/low is the local extreme over ±k bars).
  3. Cluster pivots whose prices are within `tolerance` (half-ATR, min 0.5%).
  4. Score each cluster by touch count × recency.
  5. Resistance = highest-scoring cluster ABOVE current price.
     Support    = highest-scoring cluster BELOW current price.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd


@dataclass
class Level:
    price: float
    touches: int
    last_touch_idx: int  # index in the window (higher = more recent)


def _find_pivots(values: list[float], k: int, mode: str) -> list[tuple[int, float]]:
    """mode='high' → local maxima; mode='low' → local minima."""
    out: list[tuple[int, float]] = []
    for i in range(k, len(values) - k):
        window = values[i - k : i + k + 1]
        if mode == "high" and values[i] == max(window):
            out.append((i, values[i]))
        elif mode == "low" and values[i] == min(window):
            out.append((i, values[i]))
    return out


def _cluster(pivots: list[tuple[int, float]], tolerance: float) -> list[Level]:
    if not pivots:
        return []
    pivots_sorted = sorted(pivots, key=lambda x: x[1])
    clusters: list[dict] = []
    for idx, price in pivots_sorted:
        if clusters and abs(clusters[-1]["mean"] - price) <= tolerance:
            c = clusters[-1]
            c["prices"].append(price)
            c["indices"].append(idx)
            c["mean"] = sum(c["prices"]) / len(c["prices"])
        else:
            clusters.append({"prices": [price], "indices": [idx], "mean": price})
    return [
        Level(price=c["mean"], touches=len(c["prices"]), last_touch_idx=max(c["indices"]))
        for c in clusters
    ]


def find_support_resistance(
    df: pd.DataFrame,
    current_price: float,
    atr14: float | None,
    *,
    window: int = 126,
    k: int = 3,
) -> tuple[Level | None, Level | None]:
    if df is None or len(df) < window // 2 or current_price <= 0:
        return None, None

    recent = df.tail(window).reset_index(drop=True)
    highs = recent["high"].tolist()
    lows = recent["low"].tolist()
    n = len(recent)

    tol_atr = (atr14 or 0.0) * 0.5
    tol_pct = current_price * 0.01  # at least 1% of price
    tolerance = max(tol_atr, tol_pct)

    h_clusters = _cluster(_find_pivots(highs, k, "high"), tolerance)
    l_clusters = _cluster(_find_pivots(lows, k, "low"), tolerance)

    def score(lvl: Level) -> float:
        recency = lvl.last_touch_idx / max(n - 1, 1)  # 0..1
        return lvl.touches * 1.5 + recency * 2.5

    # Resistance: clusters above price; support: clusters below.
    # Slight buffer to avoid picking a "level" that is essentially current price.
    buffer = tolerance * 0.5
    res_candidates = [c for c in h_clusters if c.price > current_price + buffer]
    sup_candidates = [c for c in l_clusters if c.price < current_price - buffer]

    resistance = max(res_candidates, key=score) if res_candidates else None
    support = max(sup_candidates, key=score) if sup_candidates else None

    return support, resistance
