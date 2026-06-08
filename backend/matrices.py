"""Dual-matrix scoring system.

Two distinct entry scores for different trading styles:

    • short_term  — swing trading. Emphasises RVOL, gaps, RSI momentum,
                    fast breakout patterns, sector tailwind from the heatmap,
                    and a short-interest / social-buzz contrarian read.
                    **Algorithmic blocker**: if the stock's sector is red
                    in the heatmap (avg change ≤ -1%), the final short-term
                    score is reduced by 1 point.

    • long_term   — investment. Emphasises valuation (DCF proxy / P/E),
                    balance-sheet strength (debt/equity), demand-zone
                    accumulation near SMA150/200, sector rotation, and
                    macro-panic contrarian buying (low F&G + insider buys).

Both return a 1-10 score and a structured breakdown for the UI.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class MatrixCategory:
    name: str             # Hebrew display label
    score: float          # 0..10
    weight: float         # 0..1 — full set sums to 1.0
    notes: list[str] = field(default_factory=list)
    skipped: bool = False  # True when input data is unavailable — excluded
                           # from the weighted sum AND its weight is excluded
                           # from the denominator (score is normalized).


@dataclass
class MatrixResult:
    score: float                    # final 0..10 (after blocker + bonus)
    raw_score: float                # pre-blocker, pre-bonus
    blocker_applied: bool
    blocker_reason: str | None
    categories: list[MatrixCategory]
    rationale: list[str]
    position_size_pct: float | None = None  # recommended max % of portfolio (long-term only)
    bonus: float = 0.0              # rare-parameter additive bonus (RVOL, SI spikes)
    bonus_reasons: list[str] = field(default_factory=list)


def _clip(v: float, lo: float = 0.0, hi: float = 10.0) -> float:
    return float(max(lo, min(hi, v)))


def _flatten_rationale(categories: list[MatrixCategory]) -> list[str]:
    rationale: list[str] = []
    for c in categories:
        for n in c.notes:
            rationale.append(f"{c.name}: {n}")
    return rationale


def _weighted_normalized(categories: list[MatrixCategory]) -> float:
    """Score normalization core. Active (non-skipped) categories form a
    weighted average that is RE-SCALED so the maximum possible value is
    always 10 — regardless of how many categories were dropped.

    Example: base weights {25, 30, 15, 15, 10, 5}. If the 15%-weight sentiment
    category has no input data and is marked skipped, the remaining 85% of
    weight is treated as the new 100% — preventing a healthy stock from being
    capped at 8.5 just because one optional input was unavailable.
    """
    active = [c for c in categories if not c.skipped]
    if not active:
        return 5.0
    weight_sum = sum(c.weight for c in active)
    if weight_sum <= 0:
        return 5.0
    weighted = sum(c.score * c.weight for c in active)
    return weighted / weight_sum


# ── Pre-computed helpers (RVOL, gap) ─────────────────────────────────────────
def compute_rvol(volume_series: pd.Series) -> float | None:
    """Relative Volume = recent 1-bar volume / 20-bar average volume."""
    if volume_series is None or len(volume_series) < 21:
        return None
    last = float(volume_series.iloc[-1])
    base = float(volume_series.iloc[-21:-1].mean())
    if base <= 0:
        return None
    return round(last / base, 2)


def compute_gap_pct(df: pd.DataFrame) -> float | None:
    """Today's open vs yesterday's close, in percent."""
    if df is None or len(df) < 2:
        return None
    try:
        today_open = float(df["open"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])
    except (KeyError, IndexError):
        return None
    if prev_close <= 0:
        return None
    return round((today_open - prev_close) / prev_close * 100.0, 2)


def estimate_dcf_fair_value(
    free_cashflow: float | None,
    shares_outstanding: float | None,
    growth_rate: float | None,
    *,
    discount_rate: float = 0.10,
    terminal_growth: float = 0.025,
) -> float | None:
    """Conservative five-year FCF DCF used by the long-term profile."""
    if (
        free_cashflow is None
        or free_cashflow <= 0
        or shares_outstanding is None
        or shares_outstanding <= 0
        or discount_rate <= terminal_growth
    ):
        return None
    growth = max(-0.05, min(0.15, growth_rate if growth_rate is not None else 0.03))
    projected = free_cashflow
    present_value = 0.0
    for year in range(1, 6):
        projected *= 1.0 + growth
        present_value += projected / ((1.0 + discount_rate) ** year)
    terminal_value = projected * (1.0 + terminal_growth) / (discount_rate - terminal_growth)
    present_value += terminal_value / ((1.0 + discount_rate) ** 5)
    fair_value = present_value / shares_outstanding
    return round(fair_value, 4) if fair_value > 0 else None


def _average_score(scores: list[float]) -> float:
    return sum(scores) / len(scores) if scores else 5.0


# ── Short-term (swing) matrix ────────────────────────────────────────────────
def _gli_category(global_liquidity: dict | None, weight: float) -> MatrixCategory:
    """Global Liquidity Index as a small-weight category.

    Both matrices use the same single category — short-term cares about the
    trend (already in `score`), long-term cares about the same trend at a
    macro level. Trade-off: keeping a single category keeps the weighting
    transparent and the UI tidy.
    """
    if not global_liquidity:
        return MatrixCategory(
            "Global Liquidity Index",
            5.0,
            weight,
            ["Global Liquidity: לא זמין"],
            skipped=True,
        )
    score = float(global_liquidity.get("score") or 5.0)
    label = global_liquidity.get("trend_label") or "—"
    c4 = global_liquidity.get("change_4w_pct")
    c4_str = f"{c4:+.2f}%" if c4 is not None else "—"
    return MatrixCategory(
        "Global Liquidity Index",
        _clip(score),
        weight,
        [f"Global Liquidity: {label} (4W: {c4_str})"],
    )


def compute_short_term_score(
    *,
    price: float,
    ma20: float | None,
    ma50: float | None,
    rsi14: float | None,
    vwap: float | None,
    rvol: float | None,
    gap_pct: float | None,
    atr_pct: float | None = None,
    patterns: dict | None,
    behavior: dict | None,
    sector_status: dict | None,
    global_liquidity: dict | None = None,
    trump_held: bool = False,
) -> MatrixResult:
    categories: list[MatrixCategory] = []

    # 1) Volume + catalysts (25%)
    # NOTE: RVOL >= 2 used to drive this category to 9.5, effectively gating
    # 8+ scores on rare events. Per requirements, rare parameters are now
    # additive bonus points (computed below), so the in-category cap stops
    # at 8.0 for sustained healthy volume.
    vol_score = 5.0
    vol_notes: list[str] = []
    if rvol is not None:
        if rvol >= 1.5:
            vol_score = 8.0
            vol_notes.append(f"RVOL גבוה (×{rvol:.1f})")
        elif rvol >= 1.1:
            vol_score = 6.5
            vol_notes.append(f"RVOL מעל הממוצע (×{rvol:.1f})")
        elif rvol < 0.7:
            vol_score = 3.5
            vol_notes.append(f"RVOL נמוך (×{rvol:.1f}) — חוסר עניין")
        else:
            vol_notes.append(f"RVOL רגיל (×{rvol:.1f})")
    if gap_pct is not None:
        if gap_pct >= 3.0:
            vol_score = min(10.0, vol_score + 1.5)
            vol_notes.append(f"Gap up של {gap_pct:.1f}% — סיגנל פתיחה")
        elif gap_pct <= -3.0:
            vol_score = max(0.0, vol_score - 1.5)
            vol_notes.append(f"Gap down של {gap_pct:.1f}% — סיגנל אזהרה")
    categories.append(MatrixCategory("נפח וקטליזטורים", _clip(vol_score), 0.30, vol_notes))

    # 2) Technical (30%)
    tech_score = 4.0
    tech_notes: list[str] = []
    if ma20 is not None and price > ma20:
        tech_score += 2.0
        tech_notes.append("מחיר מעל SMA20")
    elif ma20 is not None:
        tech_notes.append("מחיר מתחת ל-SMA20 — חולשה קצרת טווח")
    if vwap is not None and price > vwap:
        tech_score += 2.0
        tech_notes.append("מחיר מעל VWAP — תמיכה תוך-יומית")
    elif vwap is not None:
        tech_notes.append("מחיר מתחת ל-VWAP — סיכון תוך-יומי")
    if rsi14 is not None:
        if rsi14 >= 60 and rsi14 <= 78:
            tech_score += 2.0
            tech_notes.append(f"RSI חזק ({rsi14:.0f}) — מומנטום שורי")
        elif rsi14 > 78:
            tech_score += 0.5
            tech_notes.append(f"RSI מתוח ({rsi14:.0f}) — אפשרות לעצירה")
        elif rsi14 >= 50:
            tech_score += 1.0
            tech_notes.append(f"RSI ניטרלי חיובי ({rsi14:.0f})")
        else:
            tech_notes.append(f"RSI חלש ({rsi14:.0f}) — אין מומנטום שורי")
    if ma50 is not None and price > ma50:
        tech_score += 0.5
    categories.append(MatrixCategory("טכני קצר", _clip(tech_score), 0.35, tech_notes))

    # 3) Breakout patterns (15%)
    # Fix #2: pattern absence → 5.0 (neutral). Bearish penalty applies only
    # when the pattern is CONFIRMED (broke=True). "In-formation" bearish
    # patterns get a light haircut, not a full deduction.
    #
    # Swing-strategy add-ons (this revision):
    #  • Cup & Handle "near_breakout" state (price within 3% of right rim,
    #    handle in place) treated as a bullish setup with reduced confidence.
    #  • Breakout patterns demand HIGH VOLUME confirmation — confirmed
    #    breakouts on weak RVOL get downgraded; near-breakout setups need
    #    rising volume to be flagged as actionable.
    pat_score = 5.0
    pat_notes: list[str] = []
    rvol_is_positive = rvol is not None and rvol >= 1.2
    rvol_is_strong = rvol is not None and rvol >= 1.5
    if patterns:
        swing_keys = ("flag", "triangle", "cup_and_handle", "double_bottom")
        warning_keys = ("head_and_shoulders", "double_top")
        for key in swing_keys:
            p = patterns.get(key)
            if isinstance(p, dict) and p.get("detected") and p.get("direction") == "bullish":
                conf = float(p.get("confidence") or 0.0)
                geom = p.get("geometry") or {}
                near_breakout = bool(geom.get("near_breakout"))

                if not rvol_is_positive:
                    pat_notes.append(
                        f"{p.get('name', key)} זוהתה ({conf:.0f}%) אך אינה מאושרת "
                        f"ללא RVOL חיובי (×{(rvol or 0):.1f})"
                    )
                    continue

                if near_breakout:
                    # Setup just before breakout — gate on rising volume.
                    if rvol_is_strong:
                        pat_score = max(pat_score, 5.0 + conf / 22.0)
                        pat_notes.append(
                            f"{p.get('name', key)} בהתגבשות לפני קו הפריצה "
                            f"({conf:.0f}%) + RVOL ×{rvol:.1f} — מועמד סווינג"
                        )
                    else:
                        pat_score = max(pat_score, 5.0 + conf / 35.0)
                        pat_notes.append(
                            f"{p.get('name', key)} בהתגבשות לפני קו הפריצה "
                            f"({conf:.0f}%) — ממתין לאישור נפח"
                        )
                else:
                    pat_score = max(pat_score, 5.0 + conf / 20.0)
                    pat_notes.append(f"{p.get('name', key)} שורית ({conf:.0f}%)")
        for key in warning_keys:
            p = patterns.get(key)
            if isinstance(p, dict) and p.get("detected") and p.get("direction") == "bearish":
                conf = float(p.get("confidence") or 0.0)
                geom = p.get("geometry") or {}
                in_formation = bool(geom.get("in_formation"))
                if in_formation:
                    # Pattern detected but neckline not broken — light penalty.
                    pat_score = max(0.0, pat_score - conf / 80.0)
                    pat_notes.append(
                        f"אזהרה רכה: {p.get('name', key)} דובי בהתהוות "
                        f"({conf:.0f}%) — לא נשבר"
                    )
                else:
                    # Confirmed breakdown — full penalty.
                    pat_score = max(0.0, pat_score - conf / 25.0)
                    pat_notes.append(
                        f"אזהרה: {p.get('name', key)} דובי מאושר ({conf:.0f}%)"
                    )
    else:
        pat_notes.append("אין תבנית טכנית פעילה — ציון ניטרלי")
    categories.append(MatrixCategory("תבניות פריצה", _clip(pat_score), 0.15, pat_notes))

    # 4) Volatility — ATR% (10%)
    # The legacy "סנטימנט וזרימה" category was removed; Short Interest is now
    # rewarded only through the additive bonus path (see below). In its place
    # we score ATR% as a swing-suitability gauge: a moderate range gives clean
    # tradeable moves with manageable stop distance, while extreme volatility
    # is penalised as hard-to-manage risk.
    atr_score = 5.0
    atr_notes: list[str] = []
    atr_skipped = False
    if atr_pct is not None:
        a = float(atr_pct)
        if a <= 1.0:
            atr_score = 6.5
            atr_notes.append(f"תנודתיות נמוכה (ATR ×{a:.2f}%) — תנועה מוגבלת לסווינג")
        elif a <= 3.0:
            atr_score = 9.0
            atr_notes.append(f"תנודתיות אידיאלית לסווינג (ATR ×{a:.2f}%)")
        elif a <= 5.0:
            atr_score = 7.0
            atr_notes.append(f"תנודתיות מוגברת (ATR ×{a:.2f}%) — סטופ רחב יותר")
        elif a <= 8.0:
            atr_score = 4.5
            atr_notes.append(f"תנודתיות גבוהה (ATR ×{a:.2f}%) — סיכון מוגבר")
        else:
            atr_score = 3.0
            atr_notes.append(f"תנודתיות קיצונית (ATR ×{a:.2f}%) — קשה לניהול")
    else:
        atr_skipped = True
        atr_notes.append("תנודתיות: ATR לא זמין — קטגוריה הוצאה מהממוצע")
    categories.append(MatrixCategory("תנודתיות (ATR%)", _clip(atr_score), 0.10, atr_notes, skipped=atr_skipped))

    # 5) Sector tailwind from heatmap (10%)
    sec_score = 5.0
    sec_notes: list[str] = []
    sector_label = "—"
    if sector_status:
        sector_label = sector_status.get("sector_label", "—")
        avg = float(sector_status.get("avg_change_pct") or 0.0)
        if avg >= 1.5:
            sec_score = 9.5
            sec_notes.append(f"רוח גבית חזקה ({sector_label} {avg:+.2f}%)")
        elif avg >= 0.3:
            sec_score = 7.5
            sec_notes.append(f"סקטור חיובי ({sector_label} {avg:+.2f}%)")
        elif avg <= -1.5:
            sec_score = 2.5
            sec_notes.append(f"סקטור חלש מאוד ({sector_label} {avg:+.2f}%)")
        elif avg <= -0.3:
            sec_score = 4.0
            sec_notes.append(f"סקטור שלילי ({sector_label} {avg:+.2f}%)")
        else:
            sec_notes.append(f"סקטור ניטרלי ({sector_label} {avg:+.2f}%)")
    else:
        sec_notes.append("סטטוס סקטור לא זמין")
    categories.append(MatrixCategory("מצב סקטור (Heatmap)", _clip(sec_score), 0.10, sec_notes))

    # Global Liquidity and the sentiment/flow category were removed from the
    # short-term profile. Short Interest survives only as an additive bonus.

    # Fix #1: normalize against active (non-skipped) weight so missing inputs
    # don't permanently cap the achievable raw score.
    raw_score = _weighted_normalized(categories)

    # ── Rare-parameter bonus (additive) ──
    # Base weights sum to 10/10 on their own; bonus compensates for points
    # lost on weaker categories. Hard cap at 10 applied below.
    bonus = 0.0
    bonus_reasons: list[str] = []
    # Group 1: RVOL + SI bonuses share a single +1.0 cap (rare-parameter pair).
    rare_bonus = 0.0
    if rvol is not None and rvol >= 2.0:
        rare_bonus += 0.5
        bonus_reasons.append(f"בונוס +0.5 — RVOL קיצוני (×{rvol:.1f})")
    if behavior:
        # Short Interest is no longer a weighted category — it lives on here as
        # an additive bonus only, so a high short float can lift a strong setup
        # without gating the base score.
        spf = (behavior.get("short_interest") or {}).get("short_percent_float")
        if spf is not None and spf >= 20:
            rare_bonus += 0.5
            bonus_reasons.append(f"בונוס +0.5 — Short interest גבוה ({spf:.0f}%) → squeeze potential")
        elif spf is not None and spf >= 10:
            rare_bonus += 0.3
            bonus_reasons.append(f"בונוס +0.3 — Short interest מוגבר ({spf:.0f}%)")
    bonus += min(rare_bonus, 1.0)
    # Group 2: Trump OGE-holding bonus — always +0.5 if present, never a
    # penalty otherwise. Independent of the rare-parameter cap.
    if trump_held:
        bonus += 0.5
        bonus_reasons.append("בונוס +0.5 — מזוהה בהחזקות OGE 278e של דונלד טראמפ")

    # Sector weakness is already priced into the heatmap category. There is
    # no second hard mathematical penalty in the Swing profile.
    final_score = raw_score + bonus
    # Fix #3 — Hard cap: final score never exceeds 10 even after bonus.
    final_score = min(final_score, 10.0)

    return MatrixResult(
        score=round(_clip(final_score), 2),
        raw_score=round(_clip(raw_score), 2),
        blocker_applied=False,
        blocker_reason=None,
        categories=categories,
        rationale=_flatten_rationale(categories),
        bonus=round(bonus, 2),
        bonus_reasons=bonus_reasons,
    )


# ── Long-term (investment) matrix ────────────────────────────────────────────
def _compute_long_term_score_legacy(
    *,
    price: float,
    ma50: float | None,
    ma150: float | None,
    ma200: float | None,
    pe: float | None,
    pb: float | None,
    beta: float | None,
    debt_to_equity: float | None,
    free_cashflow: float | None,
    market_cap: float | None,
    fear_greed: dict | None,
    behavior: dict | None,
    sector_status: dict | None,
    global_liquidity: dict | None = None,
) -> MatrixResult:
    categories: list[MatrixCategory] = []

    # 1) Valuation — DCF proxy via P/E + P/B + FCF (25%)
    val_score = 5.0
    val_notes: list[str] = []
    if pe is not None and pe > 0:
        if pe <= 15:
            val_score = 9.0
            val_notes.append(f"P/E נמוך ({pe:.1f}) — מרווח ביטחון")
        elif pe <= 25:
            val_score = 7.0
            val_notes.append(f"P/E סביר ({pe:.1f})")
        elif pe <= 40:
            val_score = 4.5
            val_notes.append(f"P/E גבוה ({pe:.1f}) — להמתין לתיקון")
        else:
            val_score = 2.5
            val_notes.append(f"P/E מתוח ({pe:.1f}) — אין מרווח ביטחון")
    elif pe is not None and pe <= 0:
        val_score = 2.5
        val_notes.append("חברה לא רווחית — DCF לא מתאים")
    if pb is not None:
        if pb <= 2:
            val_score = min(10.0, val_score + 0.5)
        elif pb > 6:
            val_score = max(0.0, val_score - 1.0)
            val_notes.append(f"P/B גבוה ({pb:.1f})")
    if free_cashflow is not None:
        if free_cashflow > 0:
            val_score = min(10.0, val_score + 0.5)
            val_notes.append("תזרים מזומנים חופשי חיובי")
        elif free_cashflow < 0:
            val_score = max(0.0, val_score - 1.0)
            val_notes.append("FCF שלילי — אזהרה")
    # Weights re-scaled by 0.95 so the new 5% GLI category brings the total
    # back to 1.0 — see `_gli_category` and the final append below.
    categories.append(MatrixCategory("הערכת שווי (DCF/P&L)", _clip(val_score), 0.2375, val_notes))

    # 2) Balance sheet — debt/equity (20%)
    bs_score = 5.0
    bs_notes: list[str] = []
    if debt_to_equity is not None:
        # yfinance returns D/E sometimes as decimal (0.5) and sometimes as percent (50.0).
        # Heuristic: > 5 means it's likely already a percent → divide by 100.
        de = debt_to_equity / 100.0 if debt_to_equity > 5 else debt_to_equity
        if de <= 0.5:
            bs_score = 9.0
            bs_notes.append(f"חוב/הון נמוך ({de:.2f}) — מאזן חזק")
        elif de <= 1.0:
            bs_score = 7.0
            bs_notes.append(f"חוב/הון סביר ({de:.2f})")
        elif de <= 2.0:
            bs_score = 5.0
            bs_notes.append(f"חוב/הון בינוני ({de:.2f})")
        else:
            bs_score = 3.0
            bs_notes.append(f"חוב/הון גבוה ({de:.2f}) — סיכון פיננסי")
    else:
        bs_notes.append("יחס חוב/הון לא זמין")
    categories.append(MatrixCategory("חוסן פיננסי", _clip(bs_score), 0.19, bs_notes))

    # 3) Long-term trend — accumulation near SMA150/200 (15%)
    trend_score = 5.0
    trend_notes: list[str] = []
    if ma200 is not None and ma200 > 0:
        diff_pct = (price - ma200) / ma200 * 100.0
        if price > ma200:
            if 0 <= diff_pct <= 10:
                trend_score = 9.0
                trend_notes.append(f"מחיר באזור איסוף מעל SMA200 (+{diff_pct:.1f}%)")
            elif diff_pct <= 25:
                trend_score = 7.0
                trend_notes.append(f"מחיר מעל SMA200 (+{diff_pct:.1f}%)")
            else:
                trend_score = 5.5
                trend_notes.append(f"מחיר רחוק מעל SMA200 (+{diff_pct:.1f}%) — מתוח")
        else:
            trend_score = 3.0
            trend_notes.append(f"מחיר מתחת SMA200 ({diff_pct:.1f}%) — מגמה ארוכת טווח שלילית")
    if ma150 is not None and price > ma150 and ma200 is not None and price > ma200:
        trend_score = min(10.0, trend_score + 0.5)
        trend_notes.append("יישור חיובי SMA150+200")
    categories.append(MatrixCategory("מגמה ארוכת טווח", _clip(trend_score), 0.1425, trend_notes))

    # 4) Sector rotation (15%)
    rot_score = 5.0
    rot_notes: list[str] = []
    if sector_status:
        avg = float(sector_status.get("avg_change_pct") or 0.0)
        label = sector_status.get("sector_label", "—")
        if avg >= 1.0:
            rot_score = 8.5
            rot_notes.append(f"רוטציה חיובית לסקטור ({label} {avg:+.2f}%)")
        elif avg >= 0.0:
            rot_score = 6.5
            rot_notes.append(f"סקטור יציב ({label} {avg:+.2f}%)")
        elif avg >= -1.0:
            rot_score = 5.0
            rot_notes.append(f"סקטור שלילי מתון ({label} {avg:+.2f}%)")
        else:
            rot_score = 3.0
            rot_notes.append(f"סקטור בחולשה מערכתית ({label} {avg:+.2f}%) — להימנע")
    categories.append(MatrixCategory("רוטציה סקטוריאלית", _clip(rot_score), 0.1425, rot_notes))

    # 5) Macro sentiment — buy in panic + insider buying (15%)
    macro_score = 5.0
    macro_notes: list[str] = []
    if fear_greed:
        fg = fear_greed.get("score")
        if fg is not None:
            if fg <= 20:
                macro_score = 9.5
                macro_notes.append(f"פאניקת מאקרו (F&G={fg:.0f}) — חלון קנייה היסטורי")
            elif fg <= 35:
                macro_score = 8.0
                macro_notes.append(f"פחד שורר (F&G={fg:.0f}) — תקופה טובה לכניסה")
            elif fg >= 75:
                macro_score = 3.0
                macro_notes.append(f"חמדנות קיצונית (F&G={fg:.0f}) — לא הזמן לקנייה ארוכת טווח")
            elif fg >= 60:
                macro_score = 5.0
                macro_notes.append(f"חמדנות מוגברת (F&G={fg:.0f}) — להמתין")
            else:
                macro_notes.append(f"F&G ניטרלי ({fg:.0f})")
    macro_skipped = False
    if behavior:
        insider = behavior.get("insider_trading") or {}
        ins_score = insider.get("score")
        if ins_score is not None:
            if ins_score >= 7.5:
                macro_score = min(10.0, macro_score + 1.5)
                macro_notes.append("קניות אינסיידרים עקביות — אישור חזק")
            elif ins_score >= 6.0:
                macro_score = min(10.0, macro_score + 0.7)
                macro_notes.append("קניות אינסיידרים מתונות")
            elif ins_score <= 3.5:
                macro_score = max(0.0, macro_score - 1.0)
                macro_notes.append("מכירות אינסיידרים — אזהרה")
    elif fear_greed is None:
        # No macro data at all → drop the category from the weighted average.
        macro_skipped = True
        macro_notes.append("סנטימנט מאקרו: נתונים לא זמינים — קטגוריה הוצאה")
    categories.append(MatrixCategory("סנטימנט מאקרו ואינסיידרים", _clip(macro_score), 0.1425, macro_notes, skipped=macro_skipped))

    # 6) Portfolio risk / position sizing (10%)
    risk_score = 6.5
    risk_notes: list[str] = []
    position_pct = 5.0
    if beta is not None:
        b = abs(beta)
        if b <= 1.2:
            risk_score = 8.5
            position_pct = 5.0
            risk_notes.append(f"ביטא נמוכה ({b:.2f}) — מתאים לגרעין תיק")
        elif b <= 1.7:
            risk_score = 5.5
            position_pct = 3.0
            risk_notes.append(f"ביטא בינונית ({b:.2f}) — הקצאה עד 3%")
        else:
            risk_score = 3.5
            position_pct = 2.0
            risk_notes.append(f"ביטא גבוהה ({b:.2f}) — הקצאה עד 2%")
    if market_cap is not None and market_cap >= 100_000_000_000:
        risk_score = min(10.0, risk_score + 0.5)
        risk_notes.append("Mega cap — נזילות גבוהה ופחות תנודתי")
    elif market_cap is not None and market_cap < 10_000_000_000:
        risk_score = max(0.0, risk_score - 1.0)
        position_pct = min(position_pct, 2.0)
        risk_notes.append("Small cap — סיכון ונזילות מוגבלים")
    categories.append(MatrixCategory("ניהול סיכון בתיק", _clip(risk_score), 0.095, risk_notes))

    # 7) Global Liquidity (5%) — macro tailwind/headwind for risk assets
    categories.append(_gli_category(global_liquidity, 0.05))

    # Fix #1: normalize against active (non-skipped) weight.
    raw_score = _weighted_normalized(categories)
    rationale = _flatten_rationale(categories)
    rationale.append(
        f"המלצת הקצאה מקסימלית: {position_pct:.0f}% מהתיק; לשקול גידור טבעי וגיוון בסקטורים."
    )

    return MatrixResult(
        score=round(_clip(raw_score), 2),
        raw_score=round(_clip(raw_score), 2),
        blocker_applied=False,
        blocker_reason=None,
        categories=categories,
        rationale=rationale,
        position_size_pct=position_pct,
    )


# ── ETF matrix ───────────────────────────────────────────────────────────────
def compute_long_term_score(
    *,
    price: float,
    ma50: float | None,
    ma150: float | None,
    ma200: float | None,
    pe: float | None,
    pb: float | None,
    beta: float | None,
    debt_to_equity: float | None,
    free_cashflow: float | None,
    market_cap: float | None,
    shares_outstanding: float | None,
    operating_cashflow: float | None,
    total_cash: float | None,
    total_debt: float | None,
    current_ratio: float | None,
    quick_ratio: float | None,
    profit_margin: float | None,
    operating_margin: float | None,
    return_on_equity: float | None,
    revenue_growth: float | None,
    earnings_growth: float | None,
    fear_greed: dict | None,
    behavior: dict | None,
    sector_status: dict | None,
    global_liquidity: dict | None = None,
    rvol: float | None = None,
    patterns: dict | None = None,
    trump_held: bool = False,
    overvaluation_gate: bool = False,
) -> MatrixResult:
    """Long-term profile: 80% fundamentals and additive timing bonuses."""
    categories: list[MatrixCategory] = []
    dcf_fair_value = estimate_dcf_fair_value(
        free_cashflow,
        shares_outstanding,
        earnings_growth if earnings_growth is not None else revenue_growth,
    )

    valuation: list[float] = []
    valuation_notes: list[str] = []
    if dcf_fair_value is not None and price > 0:
        upside = (dcf_fair_value / price - 1.0) * 100.0
        valuation.append(9.5 if upside >= 30 else 8.0 if upside >= 10 else 6.0 if upside >= -10 else 4.0 if upside >= -25 else 2.0)
        valuation_notes.append(f"DCF הוגן ${dcf_fair_value:.2f} ({upside:+.1f}% מול המחיר)")
    if pe is not None:
        if pe <= 0:
            valuation.append(2.0)
            valuation_notes.append("חברה אינה רווחית")
        else:
            valuation.append(9.0 if pe <= 15 else 7.0 if pe <= 25 else 4.5 if pe <= 40 else 2.5)
            valuation_notes.append(f"P/E: {pe:.1f}")
    if pb is not None:
        valuation.append(8.5 if pb <= 2 else 6.0 if pb <= 5 else 4.5 if pb <= 6 else 3.0)
        valuation_notes.append(f"P/B: {pb:.1f}")
    categories.append(MatrixCategory(
        "הערכת שווי ו-DCF", _clip(_average_score(valuation)), 0.30,
        valuation_notes or ["נתוני הערכת שווי לא זמינים"], skipped=not valuation,
    ))

    stability: list[float] = []
    stability_notes: list[str] = []
    stability_metrics = (
        (profit_margin, "שולי רווח", ((0.20, 9.0), (0.10, 7.5), (0.03, 6.0), (0.0, 4.0))),
        (operating_margin, "שולי תפעול", ((0.20, 9.0), (0.10, 7.5), (0.03, 6.0), (0.0, 4.0))),
        (return_on_equity, "ROE", ((0.25, 9.0), (0.15, 7.5), (0.08, 6.0), (0.0, 4.0))),
        (revenue_growth, "צמיחת הכנסות", ((0.15, 9.0), (0.07, 7.5), (0.0, 6.0), (-0.10, 3.5))),
        (earnings_growth, "צמיחת רווח", ((0.15, 9.0), (0.05, 7.5), (0.0, 6.0), (-0.10, 3.5))),
    )
    for value, label, bands in stability_metrics:
        if value is None:
            continue
        metric_score = 2.0
        for threshold, candidate in bands:
            if value >= threshold:
                metric_score = candidate
                break
        stability.append(metric_score)
        stability_notes.append(f"{label}: {value * 100:+.1f}%")
    categories.append(MatrixCategory(
        "יציבות ורווחיות", _clip(_average_score(stability)), 0.25,
        stability_notes or ["נתוני רווחיות וצמיחה לא זמינים"], skipped=not stability,
    ))

    balance: list[float] = []
    balance_notes: list[str] = []
    if debt_to_equity is not None:
        de = debt_to_equity / 100.0 if debt_to_equity > 5 else debt_to_equity
        balance.append(9.0 if de <= 0.5 else 7.0 if de <= 1.0 else 5.0 if de <= 2.0 else 2.5)
        balance_notes.append(f"חוב/הון: {de:.2f}")
    if current_ratio is not None:
        balance.append(9.0 if current_ratio >= 2 else 7.0 if current_ratio >= 1.2 else 4.0 if current_ratio >= 0.8 else 2.5)
        balance_notes.append(f"יחס שוטף: {current_ratio:.2f}")
    if quick_ratio is not None:
        balance.append(8.5 if quick_ratio >= 1.5 else 7.0 if quick_ratio >= 1.0 else 4.0 if quick_ratio >= 0.7 else 2.5)
        balance_notes.append(f"יחס מהיר: {quick_ratio:.2f}")
    if total_cash is not None and total_debt is not None and total_debt > 0:
        cash_debt = total_cash / total_debt
        balance.append(9.0 if cash_debt >= 1 else 7.0 if cash_debt >= 0.5 else 4.5 if cash_debt >= 0.25 else 2.5)
        balance_notes.append(f"מזומן/חוב: {cash_debt:.2f}")
    elif total_cash is not None and total_cash > 0 and (total_debt is None or total_debt == 0):
        balance.append(9.5)
        balance_notes.append("מזומן חיובי ללא חוב מהותי")
    categories.append(MatrixCategory(
        "מאזן, חוב ונזילות", _clip(_average_score(balance)), 0.20,
        balance_notes or ["נתוני מאזן לא זמינים"], skipped=not balance,
    ))

    cashflow: list[float] = []
    cashflow_notes: list[str] = []
    if free_cashflow is not None:
        cashflow.append(8.0 if free_cashflow > 0 else 2.0)
        cashflow_notes.append("FCF חיובי" if free_cashflow > 0 else "FCF שלילי")
        if market_cap and market_cap > 0:
            fcf_yield = free_cashflow / market_cap
            cashflow.append(9.0 if fcf_yield >= 0.07 else 7.5 if fcf_yield >= 0.04 else 6.0 if fcf_yield >= 0.02 else 4.0)
            cashflow_notes.append(f"תשואת FCF: {fcf_yield * 100:.1f}%")
    if operating_cashflow is not None:
        cashflow.append(8.0 if operating_cashflow > 0 else 2.0)
        cashflow_notes.append("תזרים תפעולי חיובי" if operating_cashflow > 0 else "תזרים תפעולי שלילי")
        if free_cashflow is not None and operating_cashflow > 0:
            conversion = free_cashflow / operating_cashflow
            cashflow.append(8.5 if conversion >= 0.7 else 7.0 if conversion >= 0.4 else 4.0)
            cashflow_notes.append(f"המרת תזרים ל-FCF: {conversion * 100:.0f}%")
    categories.append(MatrixCategory(
        "איכות תזרים מזומנים", _clip(_average_score(cashflow)), 0.15,
        cashflow_notes or ["נתוני תזרים לא זמינים"], skipped=not cashflow,
    ))

    sector_score = 5.0
    sector_notes: list[str] = []
    if sector_status:
        avg = float(sector_status.get("avg_change_pct") or 0.0)
        sector_score = 8.5 if avg >= 1 else 6.5 if avg >= 0 else 5.0 if avg >= -1 else 3.0
        sector_notes.append(f"שינוי סקטור: {avg:+.2f}%")
    categories.append(MatrixCategory(
        "הקשר סקטוריאלי", sector_score, 0.05,
        sector_notes or ["נתוני סקטור לא זמינים"], skipped=sector_status is None,
    ))

    # פעילות אינסיידרים (5%) — standalone category, insider data only.
    # Fear & Greed and Global Liquidity were removed from the long-term profile;
    # insider activity now stands on its own as a small-weight conviction read.
    insider_score = 5.0
    insider_notes: list[str] = []
    insider_available = False
    if behavior:
        ins = (behavior.get("insider_trading") or {}).get("score")
        if ins is not None:
            insider_available = True
            insider_score = _clip(float(ins))
            insider_notes.append(f"Insider score: {float(ins):.1f}")
    categories.append(MatrixCategory(
        "פעילות אינסיידרים", _clip(insider_score), 0.05,
        insider_notes or ["נתוני אינסיידרים לא זמינים"], skipped=not insider_available,
    ))

    raw_score = _weighted_normalized(categories)
    timing_bonus = 0.0
    bonus_reasons: list[str] = []
    if ma200 is not None and ma150 is not None and price > ma200 and price > ma150:
        timing_bonus += 0.35
        bonus_reasons.append("בונוס תזמון +0.35: מחיר מעל SMA150 ו-SMA200")
    elif ma50 is not None and price > ma50:
        timing_bonus += 0.15
        bonus_reasons.append("בונוס תזמון +0.15: מחיר מעל SMA50")
    if rvol is not None and rvol >= 1.5:
        timing_bonus += 0.30
        bonus_reasons.append(f"בונוס תזמון +0.30: RVOL גבוה (×{rvol:.1f})")
    elif rvol is not None and rvol >= 1.15:
        timing_bonus += 0.15
        bonus_reasons.append(f"בונוס תזמון +0.15: RVOL מעל הממוצע (×{rvol:.1f})")
    best_pattern = 0.0
    if patterns:
        for key in ("cup_and_handle", "double_bottom", "flag", "triangle"):
            pattern = patterns.get(key)
            if isinstance(pattern, dict) and pattern.get("detected") and pattern.get("direction") == "bullish":
                best_pattern = max(best_pattern, float(pattern.get("confidence") or 0.0))
    if best_pattern >= 60:
        pattern_bonus = min(0.35, best_pattern / 250.0)
        timing_bonus += pattern_bonus
        bonus_reasons.append(f"בונוס תזמון +{pattern_bonus:.2f}: תבנית שורית ({best_pattern:.0f}%)")
    timing_bonus = min(1.0, timing_bonus)
    # Trump OGE-holding bonus — always +0.5 if present, never a penalty.
    # Independent of the timing-bonus cap.
    if trump_held:
        timing_bonus += 0.5
        bonus_reasons.append("בונוס +0.5 — מזוהה בהחזקות OGE 278e של דונלד טראמפ")

    position_pct = 5.0
    if beta is not None:
        position_pct = 5.0 if abs(beta) <= 1.2 else 3.0 if abs(beta) <= 1.7 else 2.0
    if market_cap is not None and market_cap < 10_000_000_000:
        position_pct = min(position_pct, 2.0)

    final_score = min(10.0, raw_score + timing_bonus)
    rationale = _flatten_rationale(categories)
    rationale.extend(bonus_reasons)
    # Hard ceiling when the DCF overvaluation gate fired on the long-term
    # entry. Without this cap a stock could carry an LT score of 6.6+ while
    # the recommended entry is hidden as "Overvalued" — an internal
    # contradiction (COO surfaced this).
    LT_OVERVALUATION_CAP = 4.0
    if overvaluation_gate and final_score > LT_OVERVALUATION_CAP:
        rationale.append(
            f"חסימת תמחור יתר פעילה — הציון מוקטן ל-{LT_OVERVALUATION_CAP:.1f} "
            "לעקביות עם חסימת הכניסה הארוכה (DCF Sanity Gate)."
        )
        final_score = LT_OVERVALUATION_CAP
    rationale.append(f"הקצאה מקסימלית מומלצת: {position_pct:.0f}% מהתיק.")
    return MatrixResult(
        score=round(_clip(final_score), 2),
        raw_score=round(_clip(raw_score), 2),
        blocker_applied=False,
        blocker_reason=None,
        categories=categories,
        rationale=rationale,
        position_size_pct=position_pct,
        bonus=round(timing_bonus, 2),
        bonus_reasons=bonus_reasons,
    )


def compute_etf_score(
    *,
    price: float,
    ma20: float | None,
    ma50: float | None,
    ma150: float | None,
    ma200: float | None,
    rsi14: float | None,
    vwap: float | None,
    sector_status: dict | None,
    net_inflows: dict | None,
    weighted_debt_equity: dict | None,
    global_liquidity: dict | None = None,
) -> MatrixResult:
    """ETF scoring. Per requirements, this skips DCF and insider data —
    irrelevant for passive index products — and replaces them with
    sector-heatmap status, net inflows and weighted basket leverage.

    Weights: Technical 35% · Heatmap 30% · Net Inflows 15% · D/E 15% · GLI 5%.
    """
    categories: list[MatrixCategory] = []

    # 1) Technical (35%)
    tech_score = 4.0
    tech_notes: list[str] = []
    if ma20 is not None:
        if price > ma20:
            tech_score += 1.0
            tech_notes.append("מחיר מעל SMA20")
        else:
            tech_notes.append("מחיר מתחת SMA20 — חולשה")
    if ma50 is not None:
        if price > ma50:
            tech_score += 1.0
            tech_notes.append("מחיר מעל SMA50")
    if ma200 is not None:
        if price > ma200:
            tech_score += 1.5
            tech_notes.append("מחיר מעל SMA200 — מגמה ארוכת טווח חיובית")
        else:
            tech_score -= 0.5
            tech_notes.append("מחיר מתחת SMA200 — אזהרה מבנית")
    if rsi14 is not None:
        if 45 <= rsi14 <= 70:
            tech_score += 1.0
            tech_notes.append(f"RSI בריא ({rsi14:.0f})")
        elif rsi14 > 75:
            tech_notes.append(f"RSI מתוח ({rsi14:.0f})")
    if vwap is not None and price > vwap:
        tech_score += 0.5
        tech_notes.append("מחיר מעל VWAP")
    categories.append(MatrixCategory("טכני", _clip(tech_score), 0.35, tech_notes))

    # 2) Heatmap / sector (30%) — same logic as the stock matrix
    sec_score = 5.0
    sec_notes: list[str] = []
    sector_label = "—"
    if sector_status:
        sector_label = sector_status.get("sector_label", "—")
        avg = float(sector_status.get("avg_change_pct") or 0.0)
        if avg >= 1.5:
            sec_score = 9.5
            sec_notes.append(f"רוח גבית חזקה ({sector_label} {avg:+.2f}%)")
        elif avg >= 0.3:
            sec_score = 7.5
            sec_notes.append(f"סקטור חיובי ({sector_label} {avg:+.2f}%)")
        elif avg <= -1.5:
            sec_score = 2.5
            sec_notes.append(f"סקטור חלש מאוד ({sector_label} {avg:+.2f}%)")
        elif avg <= -0.3:
            sec_score = 4.0
            sec_notes.append(f"סקטור שלילי ({sector_label} {avg:+.2f}%)")
        else:
            sec_notes.append(f"סקטור ניטרלי ({sector_label} {avg:+.2f}%)")
    else:
        sec_notes.append("ETF רחב — אין סטטוס סקטור ייחודי")
    categories.append(MatrixCategory("מפת חום סקטוריאלית", _clip(sec_score), 0.30, sec_notes))

    # 3) Net inflows (15%) — mark skipped when shares data unavailable
    inflow_skipped = False
    if net_inflows:
        inflow_score = float(net_inflows.get("score") or 5.0)
        inflow_notes = [f"תזרים: {net_inflows.get('label', '—')}"]
    else:
        inflow_score = 5.0
        inflow_notes = ["תזרים: נתונים לא זמינים — קטגוריה הוצאה"]
        inflow_skipped = True
    categories.append(MatrixCategory(
        "תזרים נכנס (Net Inflows)", _clip(inflow_score), 0.15, inflow_notes,
        skipped=inflow_skipped,
    ))

    # 4) Weighted Debt/Equity of basket (15%) — broad ETFs have no sector
    # → no weighted D/E lookup → mark skipped so it doesn't drag the score.
    de_skipped = False
    if weighted_debt_equity:
        de_score = float(weighted_debt_equity.get("score") or 5.0)
        de_notes = [f"מנוף משוקלל: {weighted_debt_equity.get('label', '—')}"]
    else:
        de_score = 5.0
        de_notes = ["מנוף משוקלל: לא חושב — קטגוריה הוצאה (ETF רחב)"]
        de_skipped = True
    categories.append(MatrixCategory(
        "מנוף משוקלל (D/E)", _clip(de_score), 0.15, de_notes,
        skipped=de_skipped,
    ))

    # 5) GLI (5%)
    categories.append(_gli_category(global_liquidity, 0.05))

    # Fix #1: normalize against active (non-skipped) weight — same treatment
    # as the stock matrices.
    raw_score = _weighted_normalized(categories)

    # Same red-sector blocker applies to ETFs — XLV in red Healthcare is
    # still red Healthcare.
    blocker_applied = False
    blocker_reason: str | None = None
    final_score = raw_score
    if sector_status and sector_status.get("is_red"):
        avg = float(sector_status.get("avg_change_pct") or 0.0)
        final_score = max(0.0, raw_score - 1.0)
        blocker_applied = True
        blocker_reason = (
            f"כלל חוסם: סקטור {sector_label} אדום במפת החום ({avg:+.2f}%) — "
            f"הופחתה נקודה אחת מהציון הסופי."
        )
    # Hard cap.
    final_score = min(final_score, 10.0)

    return MatrixResult(
        score=round(_clip(final_score), 2),
        raw_score=round(_clip(raw_score), 2),
        blocker_applied=blocker_applied,
        blocker_reason=blocker_reason,
        categories=categories,
        rationale=_flatten_rationale(categories),
    )


def matrix_to_dict(result: MatrixResult) -> dict[str, Any]:
    return {
        "score": result.score,
        "raw_score": result.raw_score,
        "blocker_applied": result.blocker_applied,
        "blocker_reason": result.blocker_reason,
        "bonus": result.bonus,
        "bonus_reasons": result.bonus_reasons,
        "categories": [
            {
                "name": c.name,
                "score": round(c.score, 2),
                "weight": c.weight,
                "notes": c.notes,
                "skipped": c.skipped,
            }
            for c in result.categories
        ],
        "rationale": result.rationale,
        "position_size_pct": result.position_size_pct,
    }
