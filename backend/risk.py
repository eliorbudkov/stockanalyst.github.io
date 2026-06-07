"""Risk plans anchored exclusively to the effective entry price."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Direction = Literal["long", "short"]


@dataclass
class StopLoss:
    price: float
    distance_pct: float
    risk_per_share: float
    reason: str


@dataclass
class TakeProfit:
    price: float
    distance_pct: float
    rr: float
    reason: str


@dataclass
class RiskPlan:
    entry_price: float
    direction: Direction
    stop_loss: StopLoss | None
    take_profit_1: TakeProfit | None
    take_profit_2: TakeProfit | None
    notes: list[str]


def build_risk_plan(
    *,
    entry_price: float,
    atr14: float | None,
    support_price: float | None,
    resistance_price: float | None,
    direction: Direction = "long",
) -> RiskPlan:
    """Build SL/TP levels using entry_price as the sole calculation anchor."""
    notes: list[str] = []
    if entry_price is None or entry_price <= 0:
        return RiskPlan(0.0, direction, None, None, None, ["מחיר כניסה אינו תקין"])
    if direction not in ("long", "short"):
        raise ValueError(f"Unsupported direction: {direction}")

    atr_value = atr14 if atr14 is not None and atr14 > 0 else None
    if direction == "long":
        atr_stop = entry_price - 2.0 * atr_value if atr_value else entry_price * 0.95
        structural_stop = (
            support_price - 0.5 * atr_value
            if atr_value and support_price is not None and support_price < entry_price
            else None
        )
        valid_stops = [value for value in (atr_stop, structural_stop) if value is not None and 0 < value < entry_price]
        stop_price = max(valid_stops) if valid_stops else entry_price * 0.95
        reason = (
            "סטופ מבני מתחת לתמיכה עם מרווח חצי ATR"
            if structural_stop is not None and stop_price == structural_stop
            else "סטופ תנודתיות 2×ATR מתחת למחיר הכניסה"
        )

        # Hard invariant: a long stop must be strictly below entry.
        if stop_price >= entry_price:
            stop_price = entry_price * 0.95
            reason = "חסם תקינות: הסטופ הוזז ל-5% מתחת למחיר הכניסה"

        risk_per_share = entry_price - stop_price
        target_2r = entry_price + 2.0 * risk_per_share
        target_3r = entry_price + 3.0 * risk_per_share
        valid_resistance = resistance_price if resistance_price is not None and resistance_price > entry_price else None
        tp1_price = min(target_2r, valid_resistance) if valid_resistance else target_2r
        tp2_price = (
            valid_resistance
            if valid_resistance is not None and valid_resistance > tp1_price * 1.005
            else target_3r
        )
    else:
        atr_stop = entry_price + 2.0 * atr_value if atr_value else entry_price * 1.05
        structural_stop = (
            resistance_price + 0.5 * atr_value
            if atr_value and resistance_price is not None and resistance_price > entry_price
            else None
        )
        valid_stops = [value for value in (atr_stop, structural_stop) if value is not None and value > entry_price]
        stop_price = min(valid_stops) if valid_stops else entry_price * 1.05
        reason = (
            "סטופ מבני מעל ההתנגדות עם מרווח חצי ATR"
            if structural_stop is not None and stop_price == structural_stop
            else "סטופ תנודתיות 2×ATR מעל מחיר הכניסה"
        )

        # Hard invariant: a short stop must be strictly above entry.
        if stop_price <= entry_price:
            stop_price = entry_price * 1.05
            reason = "חסם תקינות: הסטופ הוזז ל-5% מעל מחיר הכניסה"

        risk_per_share = stop_price - entry_price
        price_floor = entry_price * 0.01
        target_2r = max(entry_price - 2.0 * risk_per_share, price_floor)
        target_3r = max(entry_price - 3.0 * risk_per_share, price_floor)
        valid_support = support_price if support_price is not None and 0 < support_price < entry_price else None
        tp1_price = max(target_2r, valid_support) if valid_support else target_2r
        tp2_price = (
            valid_support
            if valid_support is not None and valid_support < tp1_price * 0.995
            else target_3r
        )

    if risk_per_share <= 0:
        return RiskPlan(entry_price, direction, None, None, None, ["חסם תקינות: סיכון למניה אינו חיובי"])

    def distance_pct(level: float) -> float:
        return (level - entry_price) / entry_price * 100.0

    def reward(level: float) -> float:
        return level - entry_price if direction == "long" else entry_price - level

    stop = StopLoss(
        price=round(stop_price, 4),
        distance_pct=round(distance_pct(stop_price), 2),
        risk_per_share=round(risk_per_share, 4),
        reason=reason,
    )
    tp1 = TakeProfit(
        price=round(tp1_price, 4),
        distance_pct=round(distance_pct(tp1_price), 2),
        rr=round(reward(tp1_price) / risk_per_share, 2),
        reason="יעד חלקי: רמת מבנה קרובה או יעד 2R, לפי המוקדם",
    )
    tp2 = TakeProfit(
        price=round(tp2_price, 4),
        distance_pct=round(distance_pct(tp2_price), 2),
        rr=round(reward(tp2_price) / risk_per_share, 2),
        reason="יעד מלא: רמת המבנה הבאה או יעד 3R",
    )

    # Final assertions protect future formula changes from violating direction.
    if direction == "long" and not (stop.price < entry_price < tp1.price <= tp2.price):
        raise ValueError("Invalid long risk plan ordering")
    if direction == "short" and not (stop.price > entry_price > tp1.price >= tp2.price):
        raise ValueError("Invalid short risk plan ordering")

    notes.append(f"עוגן חישוב בלעדי: מחיר כניסה ${entry_price:.2f}")
    notes.append(f"סיכון למניה: ${risk_per_share:.2f} ({abs(stop.distance_pct):.2f}%)")
    notes.append("ב-TP1 ניתן לממש חלקית ולהעביר את הסטופ למחיר הכניסה")
    return RiskPlan(entry_price, direction, stop, tp1, tp2, notes)


def build_long_term_plan(
    *,
    entry_price: float,
    atr14: float | None,
    support_price: float | None,
    resistance_price: float | None,
) -> RiskPlan | None:
    if entry_price is None or entry_price <= 0:
        return None
    return build_risk_plan(
        entry_price=entry_price,
        atr14=atr14,
        support_price=support_price,
        resistance_price=resistance_price,
        direction="long",
    )
