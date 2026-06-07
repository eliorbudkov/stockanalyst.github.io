"""Per-timeframe entry-price calculation.

Two distinct entry prices per asset — one for swing traders, one for long-term
investors. Returned via the risk_management block so the same UI surface that
shows stop loss / take profit can also show "where to actually click buy".

Short-term entry: nearest of
  • Breakout trigger above the nearest resistance (+ small ATR buffer), or
  • Pullback to VWAP (intraday support), or
  • Pullback to SMA20 (dynamic support).
Whichever is closest to the current price is the most actionable.

Long-term entry: pick a demand zone or a DCF-margin-of-safety price.
  • SMA200 retest (the textbook long-term demand zone)
  • SMA150 retest (intermediate, only if it's not basically the same as SMA200)
  • DCF / Graham proxy: EPS × min(15, current_PE × 0.7) × 0.75
Prefer the highest candidate STILL BELOW current price (reachable on a
pullback); if none, surface the closest above-current target and label it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class EntryPrice:
    price: float
    distance_pct: float    # positive if above current, negative if below
    method: str            # one of: breakout, vwap_pullback, vwap_reclaim, sma20, sma150, sma200, dcf, current, discount, overvalued
    reason: str            # Hebrew explanation
    blocked: bool = False  # NEW: True → UI must hide the price; long-term only
    fair_value: float | None = None  # NEW: raw DCF fair value (pre-MoS)


def _to_dict(e: EntryPrice | None) -> dict[str, Any] | None:
    if e is None:
        return None
    return {
        "price": round(e.price, 4),
        "distance_pct": round(e.distance_pct, 2),
        "method": e.method,
        "reason": e.reason,
        "blocked": e.blocked,
        "fair_value": round(e.fair_value, 4) if e.fair_value is not None else None,
    }


# ── Short term ────────────────────────────────────────────────────────────────
def compute_short_term_entry(
    *,
    price: float,
    resistance: float | None,
    vwap: float | None,
    ma20: float | None,
    atr14: float | None,
) -> EntryPrice | None:
    if price is None or price <= 0:
        return None

    buffer = (atr14 * 0.2) if (atr14 and atr14 > 0) else (price * 0.005)
    candidates: list[dict[str, Any]] = []

    # Breakout trigger above the nearest resistance
    if resistance and resistance > price:
        trig = resistance + buffer
        candidates.append({
            "price": trig,
            "method": "breakout",
            "reason": (
                f"כניסת פריצה — limit מעל ההתנגדות הקרובה (${resistance:.2f}) "
                f"במחיר ${trig:.2f}"
            ),
        })

    # VWAP — pullback (if price is above) or reclaim (if below)
    if vwap and vwap > 0:
        if vwap < price:
            candidates.append({
                "price": vwap,
                "method": "vwap_pullback",
                "reason": (
                    f"כניסה בהתקרבות חזרה ל-VWAP (${vwap:.2f}) — תמיכה תוך-יומית"
                ),
            })
        else:
            trig = vwap + buffer
            candidates.append({
                "price": trig,
                "method": "vwap_reclaim",
                "reason": (
                    f"כניסה כאשר המחיר משחזר מעל VWAP (${vwap:.2f}) — סיגנל היפוך"
                ),
            })

    # SMA20 dynamic support — only if price is currently above
    if ma20 and ma20 > 0 and price > ma20:
        candidates.append({
            "price": ma20,
            "method": "sma20",
            "reason": f"כניסה במגע חוזר עם SMA20 (${ma20:.2f})",
        })

    if not candidates:
        return EntryPrice(
            price=round(price, 2),
            distance_pct=0.0,
            method="current",
            reason="אין רמת פריצה / VWAP זמינים — כניסה מיידית במחיר השוק",
        )

    # Most actionable = closest to current price
    best = min(candidates, key=lambda c: abs(c["price"] - price))
    distance_pct = (best["price"] - price) / price * 100.0
    return EntryPrice(
        price=best["price"],
        distance_pct=distance_pct,
        method=best["method"],
        reason=best["reason"],
    )


# ── Long term ─────────────────────────────────────────────────────────────────
def compute_long_term_entry(
    *,
    price: float,
    ma150: float | None,
    ma200: float | None,
    pe: float | None,
    eps: float | None,
) -> EntryPrice | None:
    if price is None or price <= 0:
        return None

    # Precompute fair value for both the DCF candidate AND the post-selection
    # overvaluation gate. The gate is INTENTIONALLY deferred until after the
    # algorithm picks an anchor — see the bottom of this function.
    fair_value: float | None = None
    target_pe: float | None = None
    if pe is not None and eps is not None and pe > 0 and eps > 0:
        target_pe = min(15.0, pe * 0.7)
        fair_value = eps * target_pe

    candidates: list[dict[str, Any]] = []

    # SMA200 — textbook long-term demand zone
    if ma200 and ma200 > 0:
        candidates.append({
            "price": ma200,
            "method": "sma200",
            "reason": f"אזור ביקוש היסטורי על SMA200 (${ma200:.2f}) — כניסה איסוף בנגיעה",
        })

    # SMA150 — only if meaningfully different from SMA200
    if ma150 and ma150 > 0:
        if not ma200 or abs(ma150 - ma200) / max(ma200, 1e-6) > 0.02:
            candidates.append({
                "price": ma150,
                "method": "sma150",
                "reason": f"אזור ביקוש ביניים על SMA150 (${ma150:.2f})",
            })

    # DCF margin of safety (Graham-style proxy)
    if fair_value is not None and target_pe is not None and eps is not None:
        margin_safety_price = fair_value * 0.75  # 25% MoS
        candidates.append({
            "price": margin_safety_price,
            "method": "dcf",
            "reason": (
                f"מרווח ביטחון 25% מהשווי ההוגן (EPS ${eps:.2f} × P/E יעד "
                f"{target_pe:.1f} × 0.75 = ${margin_safety_price:.2f})"
            ),
        })

    if not candidates:
        return EntryPrice(
            price=round(price * 0.95, 2),
            distance_pct=-5.0,
            method="discount",
            reason="אין מספיק נתונים — שקול לחכות לירידה של לפחות 5% מהמחיר הנוכחי",
        )

    # Prefer the highest candidate still BELOW current price (reachable on a
    # pullback). If everything is above, surface the closest above-current.
    below = [c for c in candidates if c["price"] <= price]
    if below:
        best = max(below, key=lambda c: c["price"])
    else:
        best = min(candidates, key=lambda c: c["price"])

    # ── DCF Sanity Check — POST-SELECTION, fundamentals-only ──
    # The overvaluation gate fires ONLY when the algorithm landed on the DCF
    # anchor. Technical anchors (sma150/sma200) are exempt: a large gap from
    # a moving average is a legitimate technical setup (e.g. PNC, where
    # SMA150 sits well below price even though the stock isn't fundamentally
    # cheap). Without this gate the value strategy would publish a DCF
    # entry that the market would never reach.
    if (
        best["method"] == "dcf"
        and fair_value is not None
        and fair_value > 0
        and price > fair_value * 1.2
    ):
        overvaluation_pct = (price / fair_value - 1.0) * 100.0
        eps_for_msg = eps if eps is not None else 0.0
        target_pe_for_msg = target_pe if target_pe is not None else 0.0
        return EntryPrice(
            price=0.0,
            distance_pct=0.0,
            method="overvalued",
            reason=(
                "תמחור יתר (Overvalued) – לא מתאים לאסטרטגיית ערך. "
                f"מחיר השוק (${price:.2f}) גבוה ב-{overvaluation_pct:.1f}% "
                f"משווי הוגן (${fair_value:.2f}, מבוסס EPS ${eps_for_msg:.2f} × "
                f"P/E יעד {target_pe_for_msg:.1f}). העוגן היחיד שמצא האלגוריתם "
                "הוא DCF — אין כניסה טכנית חלופית מתחת למחיר השוק."
            ),
            blocked=True,
            fair_value=round(fair_value, 2),
        )

    distance_pct = (best["price"] - price) / price * 100.0
    return EntryPrice(
        price=best["price"],
        distance_pct=distance_pct,
        method=best["method"],
        reason=best["reason"],
    )


def entries_to_dict(
    short_term: EntryPrice | None,
    long_term: EntryPrice | None,
) -> dict[str, Any]:
    return {
        "short_term_entry": _to_dict(short_term),
        "long_term_entry": _to_dict(long_term),
    }
