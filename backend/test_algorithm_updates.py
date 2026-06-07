import unittest
from datetime import date

from entries import compute_long_term_entry
from matrices import compute_long_term_score, compute_short_term_score
from scanner import (
    ETF_THRESHOLD,
    LONG_TERM_OVERALL_THRESHOLD,
    MIN_FINAL_SCORE,
    SWING_OVERALL_THRESHOLD,
    SWING_THRESHOLD,
    _is_etf_qualified,
    _is_long_term_qualified,
    _is_swing_qualified,
    _passes_final_gate,
    _passes_universal_asset_gate,
)
from scoring import WEIGHTS, behavior_sentiment_score, market_climate_score
from trump_holdings import SOURCE_DATE, is_source_fresh, is_trump_held


class GeneralScoreProfileTests(unittest.TestCase):
    def test_universal_final_gate_uses_rounded_final_score(self):
        self.assertEqual(MIN_FINAL_SCORE, 7.0)
        self.assertEqual(ETF_THRESHOLD, 7.0)
        self.assertTrue(_passes_final_gate(7.0))
        self.assertTrue(_passes_final_gate(6.999))
        self.assertFalse(_passes_final_gate(6.994))
        self.assertFalse(_is_etf_qualified({"etf_score": 6.99}))
        self.assertTrue(_is_etf_qualified({"etf_score": 7.0}))

    def test_auxiliary_lists_cannot_leak_sub_seven_assets(self):
        self.assertFalse(
            _passes_universal_asset_gate(
                {"kind": "etf", "symbol": "QQQ", "etf_score": 6.99}
            )
        )
        self.assertTrue(
            _passes_universal_asset_gate(
                {"kind": "etf", "symbol": "QQQ", "etf_score": 7.0}
            )
        )
        self.assertFalse(
            _passes_universal_asset_gate(
                {
                    "kind": "stock",
                    "short_term_score": 8.0,
                    "long_term_score": 8.0,
                    "overall_score": 6.99,
                }
            )
        )

    def test_general_weights_match_new_profile(self):
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0)
        self.assertEqual(WEIGHTS["trend"], 0.15)
        self.assertEqual(WEIGHTS["market_climate"], 0.15)
        self.assertEqual(WEIGHTS["behavior_sentiment"], 0.05)

    def test_behavior_uses_only_insider_and_short(self):
        behavior = {
            "composite_score": 1.0,
            "social_sentiment": {"score": 1.0},
            "put_call_ratio": {"score": 1.0},
            "vix": {"score": 1.0},
            "insider_trading": {"score": 8.0},
            "short_interest": {"score": 6.0},
        }
        score, label = behavior_sentiment_score(behavior)
        self.assertEqual(score, 7.0)
        self.assertIn("Insider", label)
        self.assertIn("Short", label)
        self.assertNotIn("Social", label)

    def test_market_climate_blends_available_inputs(self):
        score, _ = market_climate_score(
            {"score": 40},
            {"avg_change_pct": 0.5},
            {"score": 6.5},
        )
        self.assertAlmostEqual(score, (8.0 + 7.5 + 6.5) / 3)


class SwingProfileTests(unittest.TestCase):
    def test_swing_threshold_is_eight(self):
        self.assertEqual(SWING_THRESHOLD, 8.0)

    def test_scan_requires_swing_and_overall_thresholds(self):
        self.assertEqual(SWING_OVERALL_THRESHOLD, 7.0)
        self.assertTrue(_is_swing_qualified({"short_term_score": 8.0, "overall_score": 7.0}))
        self.assertFalse(_is_swing_qualified({"short_term_score": 8.0, "overall_score": 6.99}))
        self.assertFalse(_is_swing_qualified({"short_term_score": 7.99, "overall_score": 9.0}))

    def test_breakout_pattern_requires_positive_rvol(self):
        result = compute_short_term_score(
            price=100,
            ma20=95,
            ma50=90,
            rsi14=65,
            vwap=96,
            rvol=1.0,
            gap_pct=0,
            patterns={
                "cup_and_handle": {
                    "detected": True,
                    "direction": "bullish",
                    "confidence": 80,
                    "geometry": {"broke_out": True},
                    "name": "Cup and Handle",
                }
            },
            behavior=None,
            sector_status={"is_red": True, "avg_change_pct": -2.0, "sector_label": "Test"},
            global_liquidity=None,
        )
        pattern = next(c for c in result.categories if "תבניות" in c.name)
        self.assertEqual(pattern.score, 5.0)
        self.assertFalse(result.blocker_applied)
        self.assertEqual(result.score, result.raw_score)


class LongTermSanityTests(unittest.TestCase):
    def test_scan_requires_long_term_and_overall_thresholds(self):
        self.assertEqual(LONG_TERM_OVERALL_THRESHOLD, 7.5)
        self.assertTrue(_is_long_term_qualified({"long_term_score": 8.0, "overall_score": 7.5}))
        self.assertFalse(_is_long_term_qualified({"long_term_score": 8.0, "overall_score": 7.49}))
        self.assertFalse(_is_long_term_qualified({"long_term_score": 7.99, "overall_score": 9.0}))

    def test_dcf_anchor_is_blocked_above_twenty_percent(self):
        entry = compute_long_term_entry(
            price=100,
            ma150=None,
            ma200=None,
            pe=20,
            eps=5,
        )
        self.assertIsNotNone(entry)
        self.assertTrue(entry.blocked)
        self.assertEqual(entry.method, "overvalued")
        self.assertIn("Overvalued", entry.reason)

    def test_technical_anchor_is_exempt(self):
        entry = compute_long_term_entry(
            price=100,
            ma150=None,
            ma200=90,
            pe=20,
            eps=5,
        )
        self.assertIsNotNone(entry)
        self.assertFalse(entry.blocked)
        self.assertEqual(entry.method, "sma200")

    def test_overvaluation_caps_long_term_score_at_four(self):
        result = compute_long_term_score(
            price=100,
            ma50=90,
            ma150=85,
            ma200=80,
            pe=12,
            pb=1.5,
            beta=1,
            debt_to_equity=20,
            free_cashflow=10_000_000_000,
            market_cap=100_000_000_000,
            shares_outstanding=1_000_000_000,
            operating_cashflow=12_000_000_000,
            total_cash=20_000_000_000,
            total_debt=5_000_000_000,
            current_ratio=2,
            quick_ratio=1.5,
            profit_margin=0.25,
            operating_margin=0.25,
            return_on_equity=0.30,
            revenue_growth=0.15,
            earnings_growth=0.15,
            fear_greed=None,
            behavior=None,
            sector_status=None,
            global_liquidity=None,
            rvol=2,
            patterns=None,
            overvaluation_gate=True,
        )
        self.assertEqual(result.score, 4.0)


class TrumpSourceFreshnessTests(unittest.TestCase):
    def test_uses_2026_official_source_date(self):
        self.assertEqual(SOURCE_DATE, date(2026, 5, 8))

    def test_bonus_is_suspended_after_twelve_months(self):
        self.assertTrue(is_source_fresh(date(2027, 5, 8)))
        self.assertFalse(is_source_fresh(date(2027, 5, 9)))

    def test_reported_sales_never_receive_holdings_bonus(self):
        self.assertFalse(is_trump_held("PLTR", date(2026, 6, 7)))


if __name__ == "__main__":
    unittest.main()
