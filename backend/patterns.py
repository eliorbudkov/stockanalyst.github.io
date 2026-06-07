"""Heuristic chart-pattern detection for daily OHLCV data.

The detectors intentionally return confidence scores instead of hard truth.
Patterns are noisy, subjective, and should be combined with trend, volume,
support/resistance, and risk rules.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class Pivot:
    idx: int
    price: float


def _pct(a: float, b: float) -> float:
    if b == 0:
        return 0.0
    return (a - b) / b * 100.0


def _safe_round(value: float | None, digits: int = 4) -> float | None:
    if value is None or np.isnan(value) or np.isinf(value):
        return None
    return round(float(value), digits)


def _pivots(values: list[float], k: int, mode: str) -> list[Pivot]:
    out: list[Pivot] = []
    for i in range(k, len(values) - k):
        window = values[i - k : i + k + 1]
        if mode == "high" and values[i] == max(window):
            out.append(Pivot(i, float(values[i])))
        elif mode == "low" and values[i] == min(window):
            out.append(Pivot(i, float(values[i])))
    return out


def _empty(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "detected": False,
        "direction": "neutral",
        "confidence": 0,
        "level": None,
        "target": None,
        "stop": None,
        "explanation": "לא זוהתה תבנית אמינה בחלון הנוכחי.",
    }


def _trend_slope(values: pd.Series) -> float:
    if len(values) < 3:
        return 0.0
    x = np.arange(len(values), dtype=float)
    y = values.to_numpy(dtype=float)
    slope, _ = np.polyfit(x, y, 1)
    mean = float(np.nanmean(y)) or 1.0
    return slope / mean * 100.0


def _double_top_bottom(
    highs: list[Pivot],
    lows: list[Pivot],
    timestamps: list[int],
    current_price: float,
    tolerance_pct: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    top = _empty("Double Top")
    bottom = _empty("Double Bottom")

    def ts(idx: int) -> int:
        if 0 <= idx < len(timestamps):
            return int(timestamps[idx])
        return 0

    for a, b in zip(highs[-8:], highs[-7:]):
        if b.idx - a.idx < 10:
            continue
        similarity = abs(_pct(b.price, a.price))
        if similarity > tolerance_pct:
            continue
        between_lows = [p for p in lows if a.idx < p.idx < b.idx]
        if not between_lows:
            continue
        neckline_pivot = min(between_lows, key=lambda p: p.price)
        neckline = neckline_pivot.price
        height = max(a.price, b.price) - neckline
        if height <= 0:
            continue
        broke = current_price < neckline
        confidence = 58 + min(22, (tolerance_pct - similarity) * 5) + (15 if broke else 0)
        top = {
            "name": "Double Top",
            "detected": True,
            "direction": "bearish",
            "confidence": round(min(confidence, 95)),
            "level": round(neckline, 4),
            "target": round(neckline - height, 4),
            "stop": round(max(a.price, b.price) * 1.01, 4),
            "explanation": "שני שיאים קרובים עם neckline ביניהם; שבירה מטה מחזקת את התבנית."
            if broke
            else "שני שיאים קרובים; נדרשת שבירה מתחת ל-neckline לאישור מלא.",
            "geometry": {
                "kind": "double_top",
                "first": {"time": ts(a.idx), "price": _safe_round(a.price)},
                "second": {"time": ts(b.idx), "price": _safe_round(b.price)},
                "neckline": {
                    "time": ts(neckline_pivot.idx),
                    "price": _safe_round(neckline),
                },
                "broke": bool(broke),
                "in_formation": not bool(broke),
                "height_pct": round(height / max(a.price, b.price) * 100.0, 2),
                "similarity_pct": round(similarity, 2),
            },
        }

    for a, b in zip(lows[-8:], lows[-7:]):
        if b.idx - a.idx < 10:
            continue
        similarity = abs(_pct(b.price, a.price))
        if similarity > tolerance_pct:
            continue
        between_highs = [p for p in highs if a.idx < p.idx < b.idx]
        if not between_highs:
            continue
        neckline_pivot = max(between_highs, key=lambda p: p.price)
        neckline = neckline_pivot.price
        height = neckline - min(a.price, b.price)
        if height <= 0:
            continue
        broke = current_price > neckline
        confidence = 58 + min(22, (tolerance_pct - similarity) * 5) + (15 if broke else 0)
        bottom = {
            "name": "Double Bottom",
            "detected": True,
            "direction": "bullish",
            "confidence": round(min(confidence, 95)),
            "level": round(neckline, 4),
            "target": round(neckline + height, 4),
            "stop": round(min(a.price, b.price) * 0.99, 4),
            "explanation": "שני שפלים קרובים עם neckline ביניהם; פריצה מעלה מחזקת את התבנית."
            if broke
            else "שני שפלים קרובים; נדרשת פריצה מעל ה-neckline לאישור מלא.",
            "geometry": {
                "kind": "double_bottom",
                "first": {"time": ts(a.idx), "price": _safe_round(a.price)},
                "second": {"time": ts(b.idx), "price": _safe_round(b.price)},
                "neckline": {
                    "time": ts(neckline_pivot.idx),
                    "price": _safe_round(neckline),
                },
                "broke": bool(broke),
                "in_formation": not bool(broke),
                "height_pct": round(height / max(neckline, 1.0) * 100.0, 2),
                "similarity_pct": round(similarity, 2),
            },
        }

    return top, bottom


def _head_shoulders(
    highs: list[Pivot],
    lows: list[Pivot],
    current_price: float,
    tolerance_pct: float,
) -> dict[str, Any]:
    out = _empty("Head and Shoulders")
    for left, head, right in zip(highs[-10:], highs[-9:], highs[-8:]):
        if not (left.idx < head.idx < right.idx):
            continue
        if head.price <= left.price or head.price <= right.price:
            continue
        shoulder_diff = abs(_pct(left.price, right.price))
        head_gap = min(_pct(head.price, left.price), _pct(head.price, right.price))
        if shoulder_diff > tolerance_pct * 1.7 or head_gap < 3:
            continue
        neck_lows = [p for p in lows if left.idx < p.idx < right.idx]
        if len(neck_lows) < 2:
            continue
        neckline = float(np.mean([p.price for p in neck_lows[-2:]]))
        height = head.price - neckline
        if height <= 0:
            continue
        broke = current_price < neckline
        confidence = 60 + min(20, head_gap * 2) + (15 if broke else 0) - min(10, shoulder_diff)
        out = {
            "name": "Head and Shoulders",
            "detected": True,
            "direction": "bearish",
            "confidence": round(max(50, min(confidence, 95))),
            "level": round(neckline, 4),
            "target": round(neckline - height, 4),
            "stop": round(right.price * 1.01, 4),
            "explanation": "מבנה כתף-ראש-כתף עם neckline; שבירה מטה היא אישור דובי."
            if broke
            else "מבנה כתף-ראש-כתף אפשרי; נדרש אישור בשבירת neckline.",
        }
    return out


def _flag(df: pd.DataFrame, current_price: float) -> dict[str, Any]:
    out = _empty("Bull/Bear Flag")
    if len(df) < 45:
        return out

    recent = df.tail(45).reset_index(drop=True)
    impulse = recent.iloc[:20]
    flag = recent.iloc[20:]
    impulse_change = _pct(float(impulse["close"].iloc[-1]), float(impulse["close"].iloc[0]))
    flag_change = _pct(float(flag["close"].iloc[-1]), float(flag["close"].iloc[0]))
    flag_slope = _trend_slope(flag["close"])
    flag_range_pct = (float(flag["high"].max()) - float(flag["low"].min())) / current_price * 100.0

    if impulse_change > 8 and -8 <= flag_change <= 3 and flag_slope <= 0.05 and flag_range_pct <= 12:
        breakout = float(flag["high"].max())
        pole = float(impulse["close"].iloc[-1]) - float(impulse["close"].iloc[0])
        out = {
            "name": "Bull Flag",
            "detected": True,
            "direction": "bullish",
            "confidence": round(min(92, 58 + impulse_change + max(0, 8 - abs(flag_change)))),
            "level": round(breakout, 4),
            "target": round(breakout + pole, 4),
            "stop": round(float(flag["low"].min()) * 0.99, 4),
            "explanation": "עלייה חדה ואחריה דשדוש/ירידה מתונה; פריצה מעל הדגל מאשרת המשך.",
        }
    elif impulse_change < -8 and -3 <= flag_change <= 8 and flag_slope >= -0.05 and flag_range_pct <= 12:
        breakdown = float(flag["low"].min())
        pole = float(impulse["close"].iloc[0]) - float(impulse["close"].iloc[-1])
        out = {
            "name": "Bear Flag",
            "detected": True,
            "direction": "bearish",
            "confidence": round(min(92, 58 + abs(impulse_change) + max(0, 8 - abs(flag_change)))),
            "level": round(breakdown, 4),
            "target": round(breakdown - pole, 4),
            "stop": round(float(flag["high"].max()) * 1.01, 4),
            "explanation": "ירידה חדה ואחריה דשדוש/עלייה מתונה; שבירה מתחת לדגל מאשרת המשך.",
        }
    return out


def _cup_and_handle(
    df: pd.DataFrame,
    timestamps: list[int],
    current_price: float,
    atr14: float | None,
) -> dict[str, Any]:
    """Classical O'Neil Cup & Handle.

    Steps:
      1. In a 150-bar window, locate the cup bottom (lowest low in the middle 65%).
      2. Identify left rim (max high before bottom) and right rim (max high after).
      3. Validate U-shape: depth 10-40%, rims within 8% of each other, width ≥ 25 bars.
      4. Look for a handle after the right rim — shallow pullback (< 50% of cup depth).
      5. Breakout above the right rim confirms the pattern.
    """
    out = _empty("Cup & Handle")
    if len(df) < 80:
        return out

    window = df.tail(150).reset_index(drop=True)
    n = len(window)
    window_ts = timestamps[-n:] if len(timestamps) >= n else timestamps
    highs = window["high"].to_numpy(dtype=float)
    lows = window["low"].to_numpy(dtype=float)

    # Search for cup bottom in the middle 65% of the window (leave room for both rims).
    bottom_lo = int(n * 0.20)
    bottom_hi = int(n * 0.85)
    if bottom_hi - bottom_lo < 20:
        return out
    bottom_idx = int(np.argmin(lows[bottom_lo:bottom_hi])) + bottom_lo
    bottom_price = float(lows[bottom_idx])

    # Left rim: highest high BEFORE the bottom.
    if bottom_idx < 5:
        return out
    left_rim_idx = int(np.argmax(highs[: bottom_idx + 1]))
    left_rim_price = float(highs[left_rim_idx])
    if left_rim_idx >= bottom_idx:
        return out

    # Right rim: highest high AFTER the bottom (allow handle in last ~30 bars).
    right_search_end = max(bottom_idx + 10, n - 5)
    if right_search_end <= bottom_idx + 5 or right_search_end > n:
        return out
    right_rim_idx = int(np.argmax(highs[bottom_idx + 1 : right_search_end])) + bottom_idx + 1
    right_rim_price = float(highs[right_rim_idx])
    if right_rim_idx <= bottom_idx:
        return out

    # Cup geometry checks — loosened to capture patterns in formation.
    # Ideal: depth 10-40%, rim diff ≤ 8%, width ≥ 25 — full confidence.
    # Formation: depth 8-45%, rim diff ≤ 12%, width ≥ 18 — reduced confidence
    # so the scanner & matrices still see them but at lower weight.
    rim = max(left_rim_price, right_rim_price)
    cup_depth_abs = rim - bottom_price
    cup_depth_pct = cup_depth_abs / rim * 100.0
    rim_diff_pct = abs(left_rim_price - right_rim_price) / rim * 100.0
    cup_width = right_rim_idx - left_rim_idx
    if not (8.0 <= cup_depth_pct <= 45.0):
        return out
    if rim_diff_pct > 12.0:
        return out
    if cup_width < 18:
        return out

    is_ideal = (
        10.0 <= cup_depth_pct <= 40.0
        and rim_diff_pct <= 8.0
        and cup_width >= 25
    )
    in_formation = not is_ideal

    # U-shape sanity: left half should descend on average, right half ascend.
    left_half_slope = _trend_slope(window["close"].iloc[left_rim_idx : bottom_idx + 1])
    right_half_slope = _trend_slope(window["close"].iloc[bottom_idx : right_rim_idx + 1])
    if left_half_slope >= 0.0 or right_half_slope <= 0.0:
        return out

    # Handle: data after the right rim (if any). Valid handle = shallow pullback
    # less than half the cup depth and at least ~2% deep.
    handle_section = window.iloc[right_rim_idx + 1 :]
    handle_detected = False
    handle_low = right_rim_price
    handle_low_idx: int | None = None
    handle_depth_pct = 0.0
    if len(handle_section) >= 3:
        handle_low_local = int(handle_section["low"].idxmin())
        handle_low_idx = handle_low_local
        handle_low = float(window["low"].iloc[handle_low_idx])
        handle_depth_abs = right_rim_price - handle_low
        handle_depth_pct = max(0.0, handle_depth_abs / right_rim_price * 100.0)
        handle_ratio = handle_depth_abs / cup_depth_abs if cup_depth_abs > 0 else 1.0
        handle_detected = handle_depth_pct >= 1.5 and handle_ratio < 0.5

    # Breakout: current price ≥ right rim (with small tolerance).
    breakout_buffer = (atr14 or current_price * 0.005) * 0.5
    broke_out = current_price >= right_rim_price - breakout_buffer

    # Near-breakout: handle is in place, price within 3% of the right rim
    # but hasn't crossed it yet. This is the "התגבשות לפני קו הפריצה"
    # state the swing strategy wants to surface.
    proximity_to_rim = abs(current_price - right_rim_price) / right_rim_price
    near_breakout = (
        handle_detected
        and not broke_out
        and proximity_to_rim <= 0.03
        and current_price <= right_rim_price
    )

    # Confidence — blend of geometry quality + handle presence + breakout.
    depth_score = 100.0 - abs(cup_depth_pct - 22.0) * 2.0       # ideal ~22% depth
    rim_score = 100.0 - rim_diff_pct * 8.0                       # tighter rims = better
    confidence = 50.0 + 0.10 * depth_score + 0.10 * rim_score
    if handle_detected:
        confidence += 12.0
    if broke_out:
        confidence += 10.0
    if near_breakout:
        # Setup priced inside the handle, primed for breakout — give it a
        # smaller-but-meaningful boost so the swing scanner picks it up.
        confidence += 7.0
    if in_formation:
        # Patterns outside the ideal geometric envelope get a confidence
        # haircut so the scanner doesn't over-reward marginal shapes.
        confidence -= 15.0
    confidence = max(45.0, min(95.0, confidence))

    # Breakout level + measured move target (rim height + cup depth).
    level = right_rim_price
    target = level + cup_depth_abs
    # Stop: just below handle low if handle present, otherwise mid-cup.
    if handle_detected:
        stop = handle_low - (atr14 or right_rim_price * 0.01) * 0.5
    else:
        stop = bottom_price + cup_depth_abs * 0.4

    if broke_out:
        explanation = (
            f"גביע U עם רימים בקרבת {rim_diff_pct:.1f}% וידית קטנה — "
            "כרגע מעל קו הפריצה, תבנית פעילה."
            if handle_detected
            else f"גביע U עם רימים קרובים (~{rim_diff_pct:.1f}%); אין ידית מובהקת — "
            "פריצה ישירה כרגע."
        )
    elif near_breakout:
        explanation = (
            f"גביע U עם ידית בהתגבשות — מחיר במרחק {proximity_to_rim*100:.2f}% "
            f"מקו הפריצה (${right_rim_price:.2f}). מועמד לסווינג עם אישור נפח."
        )
    else:
        explanation = (
            "גביע U הושלם וידית בהתהוות — נדרשת פריצה מעל הרים הימני לאישור מלא."
            if handle_detected
            else "גביע U הושלם אך אין ידית עדיין — להמתין לידית או לפריצה מעל הרים."
        )

    geometry: dict[str, Any] = {
        "kind": "cup_and_handle",
        "left_rim": {"time": int(window_ts[left_rim_idx]), "price": _safe_round(left_rim_price)},
        "bottom": {"time": int(window_ts[bottom_idx]), "price": _safe_round(bottom_price)},
        "right_rim": {"time": int(window_ts[right_rim_idx]), "price": _safe_round(right_rim_price)},
        "handle_low": (
            {"time": int(window_ts[handle_low_idx]), "price": _safe_round(handle_low)}
            if handle_detected and handle_low_idx is not None
            else None
        ),
        "cup_depth_pct": round(cup_depth_pct, 2),
        "rim_diff_pct": round(rim_diff_pct, 2),
        "cup_width_days": int(cup_width),
        "broke_out": bool(broke_out),
        "near_breakout": bool(near_breakout),
        "in_formation": bool(in_formation),
        "proximity_to_rim_pct": round(proximity_to_rim * 100.0, 2),
    }

    return {
        "name": "Cup & Handle",
        "detected": True,
        "direction": "bullish",
        "confidence": round(confidence),
        "level": _safe_round(level),
        "target": _safe_round(target),
        "stop": _safe_round(stop),
        "explanation": explanation,
        "geometry": geometry,
    }


def _triangle(df: pd.DataFrame, current_price: float) -> dict[str, Any]:
    out = _empty("Triangle")
    if len(df) < 70:
        return out

    recent = df.tail(60).reset_index(drop=True)
    highs = _pivots(recent["high"].tolist(), 3, "high")
    lows = _pivots(recent["low"].tolist(), 3, "low")
    if len(highs) < 3 or len(lows) < 3:
        return out

    high_slope = _trend_slope(pd.Series([p.price for p in highs[-5:]]))
    low_slope = _trend_slope(pd.Series([p.price for p in lows[-5:]]))
    high_range = max(p.price for p in highs[-5:]) - min(p.price for p in highs[-5:])
    low_range = max(p.price for p in lows[-5:]) - min(p.price for p in lows[-5:])
    avg_range_pct = (high_range + low_range) / 2 / current_price * 100.0

    kind = None
    direction = "neutral"
    if high_slope < -0.08 and low_slope > 0.08:
        kind = "Symmetrical Triangle"
    elif abs(high_slope) <= 0.08 and low_slope > 0.08:
        kind = "Ascending Triangle"
        direction = "bullish"
    elif high_slope < -0.08 and abs(low_slope) <= 0.08:
        kind = "Descending Triangle"
        direction = "bearish"

    if kind is None:
        return out

    upper = float(np.mean([p.price for p in highs[-3:]]))
    lower = float(np.mean([p.price for p in lows[-3:]]))
    height = max(upper - lower, 0.0)
    confidence = 58 + min(22, max(0, 8 - avg_range_pct) * 2.5)
    target = None
    stop = None
    level = upper if direction != "bearish" else lower
    if direction == "bullish":
        target = upper + height
        stop = lower * 0.99
    elif direction == "bearish":
        target = lower - height
        stop = upper * 1.01

    return {
        "name": kind,
        "detected": True,
        "direction": direction,
        "confidence": round(min(confidence, 90)),
        "level": _safe_round(level),
        "target": _safe_round(target),
        "stop": _safe_round(stop),
        "explanation": "התכנסות בין קו שיאים וקו שפלים; כיוון האישור נקבע בפריצה/שבירה.",
    }


def detect_patterns(df: pd.DataFrame, current_price: float, atr14: float | None) -> dict[str, Any]:
    if df is None or len(df) < 80 or current_price <= 0:
        return {
            "cup_and_handle": _empty("Cup & Handle"),
            "head_and_shoulders": _empty("Head and Shoulders"),
            "double_top": _empty("Double Top"),
            "double_bottom": _empty("Double Bottom"),
            "flag": _empty("Bull/Bear Flag"),
            "triangle": _empty("Triangle"),
        }

    recent_with_index = df.tail(180)
    try:
        recent_timestamps = [int(idx.timestamp()) for idx in recent_with_index.index]
    except Exception:
        recent_timestamps = []
    recent = recent_with_index.reset_index(drop=True)
    tolerance_pct = max(1.5, min(4.5, ((atr14 or current_price * 0.02) / current_price) * 100.0 * 1.25))
    highs = _pivots(recent["high"].tolist(), 3, "high")
    lows = _pivots(recent["low"].tolist(), 3, "low")

    double_top, double_bottom = _double_top_bottom(
        highs, lows, recent_timestamps, current_price, tolerance_pct
    )
    return {
        "cup_and_handle": _cup_and_handle(recent, recent_timestamps, current_price, atr14),
        "head_and_shoulders": _head_shoulders(highs, lows, current_price, tolerance_pct),
        "double_top": double_top,
        "double_bottom": double_bottom,
        "flag": _flag(recent, current_price),
        "triangle": _triangle(recent, current_price),
    }
