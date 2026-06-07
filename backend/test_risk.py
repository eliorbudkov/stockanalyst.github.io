import unittest

from risk import build_risk_plan


class RiskPlanTests(unittest.TestCase):
    def test_long_plan_is_anchored_to_entry(self) -> None:
        plan = build_risk_plan(
            entry_price=100.0,
            atr14=4.0,
            support_price=80.0,
            resistance_price=None,
            direction="long",
        )
        self.assertEqual(plan.entry_price, 100.0)
        self.assertAlmostEqual(plan.stop_loss.price, 92.0)
        self.assertAlmostEqual(plan.take_profit_1.price, 116.0)
        self.assertAlmostEqual(plan.take_profit_2.price, 124.0)
        self.assertEqual(plan.take_profit_1.rr, 2.0)
        self.assertEqual(plan.take_profit_2.rr, 3.0)

    def test_long_stop_is_always_below_entry(self) -> None:
        plan = build_risk_plan(
            entry_price=90.0,
            atr14=4.0,
            support_price=95.0,
            resistance_price=112.0,
            direction="long",
        )
        self.assertLess(plan.stop_loss.price, plan.entry_price)
        self.assertGreater(plan.take_profit_1.price, plan.entry_price)

    def test_short_stop_is_always_above_entry(self) -> None:
        plan = build_risk_plan(
            entry_price=100.0,
            atr14=4.0,
            support_price=88.0,
            resistance_price=106.0,
            direction="short",
        )
        self.assertGreater(plan.stop_loss.price, plan.entry_price)
        self.assertLess(plan.take_profit_1.price, plan.entry_price)
        self.assertLessEqual(plan.take_profit_2.price, plan.take_profit_1.price)

    def test_short_targets_never_become_negative(self) -> None:
        plan = build_risk_plan(
            entry_price=5.0,
            atr14=8.0,
            support_price=None,
            resistance_price=None,
            direction="short",
        )
        self.assertGreater(plan.take_profit_1.price, 0)
        self.assertGreater(plan.take_profit_2.price, 0)


if __name__ == "__main__":
    unittest.main()
