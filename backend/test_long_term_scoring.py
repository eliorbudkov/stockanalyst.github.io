import unittest

from matrices import compute_long_term_score


def score_company(**overrides):
    values = {
        "price": 100.0,
        "ma50": 110.0,
        "ma150": 115.0,
        "ma200": 120.0,
        "pe": 14.0,
        "pb": 1.8,
        "beta": 1.0,
        "debt_to_equity": 35.0,
        "free_cashflow": 8_000_000_000.0,
        "market_cap": 100_000_000_000.0,
        "shares_outstanding": 1_000_000_000.0,
        "operating_cashflow": 10_000_000_000.0,
        "total_cash": 20_000_000_000.0,
        "total_debt": 10_000_000_000.0,
        "current_ratio": 2.0,
        "quick_ratio": 1.5,
        "profit_margin": 0.22,
        "operating_margin": 0.24,
        "return_on_equity": 0.28,
        "revenue_growth": 0.12,
        "earnings_growth": 0.14,
        "fear_greed": None,
        "behavior": None,
        "sector_status": None,
        "global_liquidity": None,
        "rvol": 0.6,
        "patterns": None,
    }
    values.update(overrides)
    return compute_long_term_score(**values)


class LongTermScoringTests(unittest.TestCase):
    def test_missing_momentum_does_not_penalize_base_score(self):
        weak_timing = score_company()
        no_timing_data = score_company(ma50=None, ma150=None, ma200=None, rvol=None)
        self.assertEqual(weak_timing.raw_score, no_timing_data.raw_score)
        self.assertEqual(weak_timing.bonus, 0.0)
        self.assertEqual(no_timing_data.bonus, 0.0)

    def test_positive_timing_only_adds_bonus(self):
        base = score_company()
        timed = score_company(
            ma50=90.0,
            ma150=85.0,
            ma200=80.0,
            rvol=1.8,
            patterns={
                "double_bottom": {
                    "detected": True,
                    "direction": "bullish",
                    "confidence": 75.0,
                }
            },
        )
        self.assertEqual(base.raw_score, timed.raw_score)
        self.assertGreater(timed.bonus, 0.0)
        self.assertGreater(timed.score, base.score)

    def test_missing_fundamental_category_is_normalized(self):
        complete = score_company()
        partial = score_company(
            current_ratio=None,
            quick_ratio=None,
            total_cash=None,
            total_debt=None,
            debt_to_equity=None,
        )
        balance = next(c for c in partial.categories if c.name == "מאזן, חוב ונזילות")
        self.assertTrue(balance.skipped)
        self.assertGreater(partial.raw_score, 0.0)
        self.assertLessEqual(partial.raw_score, 10.0)
        self.assertGreaterEqual(partial.raw_score, complete.raw_score - 1.0)

    def test_fundamental_weights_are_ninety_percent(self):
        result = score_company()
        fundamental_names = {
            "הערכת שווי ו-DCF",
            "יציבות ורווחיות",
            "מאזן, חוב ונזילות",
            "איכות תזרים מזומנים",
        }
        weight = sum(c.weight for c in result.categories if c.name in fundamental_names)
        self.assertAlmostEqual(weight, 0.90)

    def test_long_term_profile_categories_and_weights(self):
        """Insider is a standalone category; Fear & Greed and Global Liquidity
        are removed; the requested weight map sums to 1.0."""
        result = score_company(behavior={"insider_trading": {"score": 8.0}})
        weights = {c.name: c.weight for c in result.categories}
        self.assertAlmostEqual(weights["הערכת שווי ו-DCF"], 0.30)
        self.assertAlmostEqual(weights["יציבות ורווחיות"], 0.25)
        self.assertAlmostEqual(weights["מאזן, חוב ונזילות"], 0.20)
        self.assertAlmostEqual(weights["איכות תזרים מזומנים"], 0.15)
        self.assertAlmostEqual(weights["פעילות אינסיידרים"], 0.05)
        self.assertAlmostEqual(weights["הקשר סקטוריאלי"], 0.05)
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        names = set(weights)
        self.assertNotIn("מאקרו ואינסיידרים", names)
        self.assertNotIn("Global Liquidity Index", names)
        insider = next(c for c in result.categories if c.name == "פעילות אינסיידרים")
        self.assertFalse(insider.skipped)
        self.assertEqual(insider.score, 8.0)


if __name__ == "__main__":
    unittest.main()
