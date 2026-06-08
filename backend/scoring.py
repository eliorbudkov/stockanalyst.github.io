"""Entry score 1-10: technicals, risk, fundamentals, patterns, and sentiment."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class ScoreResult:
    score: float
    breakdown: dict[str, float]
    rationale: list[str]


def _clip(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return float(max(lo, min(hi, v)))


def trend_score(
    price: float,
    ma20: float | None,
    ma50: float | None,
    ma150: float | None,
    ma200: float | None,
) -> tuple[float, str]:
    if price is None or any(v is None or np.isnan(v) for v in [ma20, ma50, ma150, ma200]):
        return 5.0, "מגמה: נתונים חלקיים - ציון ניטרלי"

    pts = 0.0
    if price > ma20:
        pts += 2.0
    if price > ma50:
        pts += 2.0
    if price > ma150:
        pts += 1.5
    if price > ma200:
        pts += 1.5
    if ma20 > ma50 > ma150 > ma200:
        pts += 3.0
    elif ma20 > ma50 > ma200:
        pts += 1.5

    score = _clip(pts)
    if score >= 8:
        msg = "מגמה חיובית חזקה - מחיר מעל רוב/כל הממוצעים ויישור שורי"
    elif score >= 5:
        msg = "מגמה מעורבת - חלק מהממוצעים תומכים וחלק עדיין במבחן"
    else:
        msg = "מגמה שלילית - מחיר מתחת לרוב הממוצעים"
    return score, msg


def momentum_score(rsi14: float | None) -> tuple[float, str]:
    if rsi14 is None or np.isnan(rsi14):
        return 5.0, "מומנטום: RSI לא זמין"

    r = float(rsi14)
    if 50 <= r <= 65:
        s = 10.0 - (65 - r) * 0.1
    elif 45 <= r < 50:
        s = 8.5 - (50 - r) * 0.3
    elif 65 < r <= 75:
        s = 7.0 - (r - 65) * 0.3
    elif r > 75:
        s = max(2.0, 7.0 - (r - 65) * 0.3)
    elif 35 <= r < 45:
        s = 7.0 - (45 - r) * 0.4
    elif 25 <= r < 35:
        s = 4.0 - (35 - r) * 0.2
    else:
        s = 2.0

    if r >= 70:
        label = "RSI בקניית יתר - סיכון לתיקון"
    elif r <= 30:
        label = "RSI במכירת יתר - אפשרות לריבאונד אך עדיין מסוכן"
    else:
        label = f"RSI בטווח בריא ({r:.1f})"
    return _clip(s), f"מומנטום: {label}"


def volatility_score(atr_pct: float | None) -> tuple[float, str]:
    if atr_pct is None or np.isnan(atr_pct):
        return 5.0, "תנודתיות: ATR לא זמין"

    a = float(atr_pct)
    if a <= 1.5:
        s = 10.0
    elif a <= 3.0:
        s = 9.0 - (a - 1.5) * 1.0
    elif a <= 5.0:
        s = 7.5 - (a - 3.0) * 1.5
    elif a <= 8.0:
        s = 4.5 - (a - 5.0) * 0.8
    else:
        s = 2.0

    if a <= 2.5:
        label = "תנודתיות נמוכה - סטופ צמוד וניהול סיכון נוח"
    elif a <= 5:
        label = "תנודתיות מתונה"
    else:
        label = "תנודתיות גבוהה - נדרש סטופ רחב יותר"
    return _clip(s), f"תנודתיות: {label} (ATR כ-{a:.2f}% מהמחיר)"


def volume_score(vol: pd.Series) -> tuple[float, str]:
    if vol is None or len(vol) < 50:
        return 5.0, "נפח: נתונים חלקיים"
    recent = float(vol.tail(5).mean())
    base = float(vol.tail(50).mean())
    if base <= 0:
        return 5.0, "נפח: לא זמין"

    ratio = recent / base
    if ratio >= 1.5:
        s, label = 9.0, f"נפח גבוה במיוחד (x{ratio:.2f}) - עניין שוק"
    elif ratio >= 1.1:
        s, label = 7.5, f"נפח מעל הממוצע (x{ratio:.2f})"
    elif ratio >= 0.8:
        s, label = 6.0, f"נפח תקין (x{ratio:.2f})"
    else:
        s, label = 4.0, f"נפח נמוך (x{ratio:.2f}) - פחות אישור לתנועה"
    return s, f"נפח: {label}"


def fundamentals_score(pe: float | None, pb: float | None, beta: float | None) -> tuple[float, str]:
    parts: list[float] = []
    notes: list[str] = []

    if pe is not None and not np.isnan(pe):
        if pe <= 0:
            parts.append(3.0)
            notes.append("חברה לא רווחית / P/E שלילי")
        elif pe <= 15:
            parts.append(9.0)
            notes.append(f"P/E אטרקטיבי ({pe:.1f})")
        elif pe <= 25:
            parts.append(7.0)
            notes.append(f"P/E סביר ({pe:.1f})")
        elif pe <= 40:
            parts.append(5.0)
            notes.append(f"P/E גבוה ({pe:.1f})")
        else:
            parts.append(3.0)
            notes.append(f"P/E מתוח ({pe:.1f})")

    if pb is not None and not np.isnan(pb):
        if pb <= 1.5:
            parts.append(9.0)
        elif pb <= 3:
            parts.append(7.0)
        elif pb <= 6:
            parts.append(5.0)
        else:
            parts.append(3.5)

    if beta is not None and not np.isnan(beta):
        b = abs(float(beta))
        if 0.7 <= b <= 1.3:
            parts.append(8.0)
        elif b <= 1.7:
            parts.append(6.0)
        else:
            parts.append(4.0)

    if not parts:
        return 5.0, "פונדמנטלס: לא זמינים"

    label = "; ".join(notes) if notes else "נתונים מעורבים"
    return _clip(sum(parts) / len(parts)), f"פונדמנטלס: {label}"


def advanced_technicals_score(
    *,
    price: float,
    macd_histogram: float | None,
    bb_lower: float | None,
    bb_upper: float | None,
    vwap: float | None,
) -> tuple[float, str]:
    parts: list[float] = []
    notes: list[str] = []

    if macd_histogram is not None and not np.isnan(macd_histogram):
        if macd_histogram > 0:
            parts.append(8.0)
            notes.append("MACD חיובי")
        elif macd_histogram < 0:
            parts.append(4.0)
            notes.append("MACD שלילי")
        else:
            parts.append(5.0)
            notes.append("MACD ניטרלי")

    if bb_lower is not None and bb_upper is not None and not any(np.isnan(v) for v in [bb_lower, bb_upper]):
        if price > bb_upper:
            parts.append(5.5)
            notes.append("מעל Bollinger עליון - חזק אך מתוח")
        elif price < bb_lower:
            parts.append(4.5)
            notes.append("מתחת Bollinger תחתון - חולשה/ריבאונד אפשרי")
        else:
            parts.append(7.0)
            notes.append("בתוך רצועות Bollinger")

    if vwap is not None and not np.isnan(vwap) and vwap > 0:
        diff = (price - vwap) / vwap * 100.0
        if diff >= 0:
            parts.append(8.0 if diff <= 8 else 6.5)
            notes.append(f"מעל VWAP ({diff:.1f}%)")
        else:
            parts.append(4.0)
            notes.append(f"מתחת VWAP ({diff:.1f}%)")

    if not parts:
        return 5.0, "אינדיקטורים משלימים: לא זמינים"

    return _clip(sum(parts) / len(parts)), "אינדיקטורים משלימים: " + "; ".join(notes)


def patterns_score(patterns: dict | None) -> tuple[float, str]:
    if not patterns:
        return 5.0, "תבניות: לא זמינות"

    detected = [p for p in patterns.values() if isinstance(p, dict) and p.get("detected")]
    if not detected:
        return 5.5, "תבניות: לא זוהתה תבנית פעילה - ניטרלי"

    scores: list[float] = []
    notes: list[str] = []
    for pattern in detected:
        confidence = float(pattern.get("confidence") or 0.0)
        direction = pattern.get("direction")
        name = pattern.get("name", "Pattern")
        if direction == "bullish":
            scores.append(5.0 + confidence / 20.0)
            notes.append(f"{name} שורי ({confidence:.0f}%)")
        elif direction == "bearish":
            scores.append(5.0 - confidence / 18.0)
            notes.append(f"{name} דובי ({confidence:.0f}%)")
        else:
            scores.append(5.5)
            notes.append(f"{name} ניטרלי ({confidence:.0f}%)")

    return _clip(sum(scores) / len(scores)), "תבניות: " + "; ".join(notes[:3])


def fear_greed_score(fear_greed: dict | None) -> tuple[float, str]:
    if not fear_greed or fear_greed.get("score") is None:
        return 5.0, "מדד פחד וחמדנות: לא זמין"

    fg_score = float(fear_greed["score"])
    label = fear_greed.get("label") or fear_greed.get("rating") or "לא ידוע"

    # Contrarian weighting: fear can improve entry, extreme greed hurts entry risk.
    if fg_score <= 24:
        score = 6.5
        msg = f"מדד פחד וחמדנות: {label} ({fg_score:.0f}) - פחד קיצוני, הזדמנות אפשרית אך תנודתית"
    elif fg_score <= 44:
        score = 8.0
        msg = f"מדד פחד וחמדנות: {label} ({fg_score:.0f}) - פחד בשוק, יחס כניסה נוח יותר"
    elif fg_score <= 55:
        score = 6.5
        msg = f"מדד פחד וחמדנות: {label} ({fg_score:.0f}) - סנטימנט ניטרלי"
    elif fg_score <= 74:
        score = 5.0
        msg = f"מדד פחד וחמדנות: {label} ({fg_score:.0f}) - חמדנות, להקפיד על סטופ"
    else:
        score = 3.0
        msg = f"מדד פחד וחמדנות: {label} ({fg_score:.0f}) - חמדנות קיצונית, סיכון לתיקון"

    return _clip(score), msg


def behavior_sentiment_score(behavior_sentiment: dict | None) -> tuple[float, str]:
    """Human behavior score using only insider activity and short interest."""
    if not behavior_sentiment:
        return 5.0, "התנהגות: Insider ו-Short Interest לא זמינים"

    parts: list[str] = []
    insider = behavior_sentiment.get("insider_trading") or {}
    short_interest = behavior_sentiment.get("short_interest") or {}
    scores: list[float] = []
    if insider.get("score") is not None:
        scores.append(float(insider["score"]))
        parts.append(f"Insider {float(insider['score']):.1f}")
    if short_interest.get("score") is not None:
        scores.append(float(short_interest["score"]))
        parts.append(f"Short {float(short_interest['score']):.1f}")

    if not scores:
        return 5.0, "התנהגות: Insider ו-Short Interest לא זמינים"
    score = sum(scores) / len(scores)
    return _clip(score), "התנהגות: " + "; ".join(parts)


def heatmap_score(sector_status: dict | None) -> tuple[float, str]:
    """Standalone sector heatmap category, based on sector breadth (avg change).

    Global liquidity and Fear & Greed are intentionally excluded — they are no
    longer part of the general entry score.
    """
    if not sector_status:
        return 5.0, "Heatmap סקטור: נתונים לא זמינים"

    avg = float(sector_status.get("avg_change_pct") or 0.0)
    heatmap = 9.0 if avg >= 1.5 else 7.5 if avg >= 0.3 else 5.5 if avg > -0.3 else 4.0 if avg > -1.5 else 2.5
    return _clip(heatmap), f"Heatmap סקטור: {avg:+.2f}%"


WEIGHTS = {
    "trend": 0.20,
    "momentum": 0.13,
    "advanced_technicals": 0.13,
    "volatility": 0.10,
    "volume": 0.10,
    "fundamentals": 0.13,
    "patterns": 0.08,
    "heatmap": 0.08,
    "behavior_sentiment": 0.05,
}


def compute_score(
    *,
    price: float,
    ma20: float | None,
    ma50: float | None,
    ma150: float | None,
    ma200: float | None,
    rsi14: float | None,
    atr_pct: float | None,
    volume_series: pd.Series,
    pe: float | None,
    pb: float | None,
    beta: float | None,
    macd_histogram: float | None = None,
    bb_lower: float | None = None,
    bb_upper: float | None = None,
    vwap: float | None = None,
    patterns: dict | None = None,
    fear_greed: dict | None = None,
    behavior_sentiment: dict | None = None,
    sector_status: dict | None = None,
    global_liquidity: dict | None = None,
) -> ScoreResult:
    trend, t_msg = trend_score(price, ma20, ma50, ma150, ma200)
    mom, m_msg = momentum_score(rsi14)
    adv, a_msg = advanced_technicals_score(
        price=price,
        macd_histogram=macd_histogram,
        bb_lower=bb_lower,
        bb_upper=bb_upper,
        vwap=vwap,
    )
    vol, v_msg = volatility_score(atr_pct)
    volu, vol_msg = volume_score(volume_series)
    fund, f_msg = fundamentals_score(pe, pb, beta)
    patt, p_msg = patterns_score(patterns)
    heat, heat_msg = heatmap_score(sector_status)
    beh, beh_msg = behavior_sentiment_score(behavior_sentiment)

    final = _clip(
        trend * WEIGHTS["trend"]
        + mom * WEIGHTS["momentum"]
        + adv * WEIGHTS["advanced_technicals"]
        + vol * WEIGHTS["volatility"]
        + volu * WEIGHTS["volume"]
        + fund * WEIGHTS["fundamentals"]
        + patt * WEIGHTS["patterns"]
        + heat * WEIGHTS["heatmap"]
        + beh * WEIGHTS["behavior_sentiment"]
    )

    return ScoreResult(
        score=final,
        breakdown={
            "trend": round(trend, 2),
            "momentum": round(mom, 2),
            "advanced_technicals": round(adv, 2),
            "volatility": round(vol, 2),
            "volume": round(volu, 2),
            "fundamentals": round(fund, 2),
            "patterns": round(patt, 2),
            "heatmap": round(heat, 2),
            "behavior_sentiment": round(beh, 2),
        },
        rationale=[t_msg, m_msg, a_msg, v_msg, vol_msg, f_msg, p_msg, heat_msg, beh_msg],
    )
