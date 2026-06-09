import unittest
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd
import scanner
from fastapi.testclient import TestClient
from entries import compute_long_term_entry
from main import app, _calculate_beta, _fallback_descriptions, _growth_rate, _timeseries_value
from matrices import compute_long_term_score, compute_short_term_score
from scanner import (
    ETF_THRESHOLD,
    LONG_TERM_OVERALL_THRESHOLD,
    MIN_FINAL_SCORE,
    SWING_OVERALL_THRESHOLD,
    SWING_THRESHOLD,
    SWING_MIN_RISK_REWARD,
    SWING_MIN_RVOL,
    SWING_MIN_SUCCESS_RATE,
    ScanSeedUnavailable,
    _etf_entry_score,
    _is_etf_long_qualified,
    _is_etf_qualified,
    _is_etf_short_qualified,
    _is_long_term_qualified,
    _is_swing_qualified,
    _build_prebreakout_swing_setup,
    _compute_prebreakout_swing_setup,
    _fetch_stock_context,
    _long_term_prefilter_score,
    _merge_tier2_candidates,
    _passes_final_gate,
    _passes_universal_asset_gate,
    _select_long_term_tier1,
    _select_swing_tier1,
    compute_session_adjusted_rvol,
    _sanitize_scan_payload,
)
from scoring import WEIGHTS, behavior_sentiment_score, heatmap_score
from trump_holdings import SOURCE_DATE, is_source_fresh, is_trump_held


class GeneralScoreProfileTests(unittest.TestCase):
    def test_universal_final_gate_uses_rounded_final_score(self):
        self.assertEqual(MIN_FINAL_SCORE, 7.0)
        self.assertEqual(ETF_THRESHOLD, 7.0)
        self.assertTrue(_passes_final_gate(7.0))
        self.assertTrue(_passes_final_gate(6.999))
        self.assertFalse(_passes_final_gate(6.994))
        self.assertFalse(_is_etf_qualified({
            "etf_score": 6.99,
            "short_term_score": 8.0,
            "long_term_score": 8.0,
        }))
        self.assertTrue(_is_etf_qualified({
            "etf_score": 7.0,
            "short_term_score": 8.0,
            "long_term_score": 7.0,
        }))

    def test_etf_short_qualification_uses_setup_not_scores(self):
        etf = {
            "kind": "etf",
            "overall_score": 7.3,
            "etf_score": 7.3,
            "etf_matrix_score": 9.0,
            "short_term_score": 8.1,
            "long_term_score": 6.9,
            "swing_setup": {"qualified": True},
        }
        self.assertEqual(_etf_entry_score(etf), 7.3)
        self.assertTrue(_is_etf_qualified(etf))
        self.assertTrue(_is_etf_short_qualified(etf))
        self.assertFalse(_is_etf_long_qualified(etf))

        etf["short_term_score"] = 1.0
        etf["overall_score"] = 1.0
        self.assertTrue(_is_etf_short_qualified(etf))

        etf["swing_setup"] = {"qualified": False}
        etf["overall_score"] = 6.9
        self.assertFalse(_is_etf_qualified(etf))

    def test_etf_short_setup_and_long_score_gates_are_independent(self):
        short_only = {
            "kind": "etf",
            "overall_score": 7.2,
            "short_term_score": 7.2,
            "long_term_score": 6.9,
            "swing_setup": {"qualified": True},
        }
        long_only = {
            "kind": "etf",
            "overall_score": 7.7,
            "short_term_score": 6.9,
            "long_term_score": 7.2,
            "swing_setup": {"qualified": False},
        }
        self.assertTrue(_is_etf_short_qualified(short_only))
        self.assertFalse(_is_etf_long_qualified(short_only))
        self.assertFalse(_is_etf_short_qualified(long_only))
        self.assertTrue(_is_etf_long_qualified(long_only))

    def test_stock_without_kind_is_not_filtered_as_etf(self):
        stock = {
            "symbol": "LEGACY",
            "short_term_score": 8.1,
            "long_term_score": 8.0,
            "overall_score": 7.6,
        }
        cleaned = _sanitize_scan_payload({
            "threshold": 8.0,
            "top_swing_stocks": [stock],
            "top_invest_stocks": [stock],
            "top_stocks": [stock],
            "top_etfs": [],
            "top": [stock],
        })
        self.assertEqual(cleaned["top_swing_stocks"], [])
        self.assertEqual(cleaned["top_invest_stocks"], [stock])

    def test_scan_rvol_projects_incomplete_market_session(self):
        dates = pd.bdate_range("2026-05-11", periods=21)
        dates = dates[:-1].append(pd.DatetimeIndex(["2026-06-08"]))
        volumes = pd.Series([1_000_000] * 20 + [250_000], index=dates)
        market_now = datetime(
            2026, 6, 8, 11, 0,
            tzinfo=ZoneInfo("America/New_York"),
        )

        self.assertEqual(
            compute_session_adjusted_rvol(volumes, dates[-1], market_now),
            1.3,
        )

    def test_scan_rvol_does_not_project_completed_session(self):
        dates = pd.bdate_range("2026-05-11", periods=21)
        dates = dates[:-1].append(pd.DatetimeIndex(["2026-06-08"]))
        volumes = pd.Series([1_000_000] * 20 + [250_000], index=dates)
        after_close = datetime(
            2026, 6, 8, 16, 30,
            tzinfo=ZoneInfo("America/New_York"),
        )

        self.assertEqual(
            compute_session_adjusted_rvol(volumes, dates[-1], after_close),
            0.25,
        )

    def test_vercel_deployment_origin_is_allowed_by_cors(self):
        origin = (
            "https://stockanalyst-github-io-emy4-"
            "2vmqwlv8m-elior-projects.vercel.app"
        )
        response = TestClient(app).options(
            "/api/auth/check",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["access-control-allow-origin"], origin)

    def test_auxiliary_lists_cannot_leak_sub_seven_assets(self):
        self.assertFalse(
            _passes_universal_asset_gate(
                {"kind": "etf", "symbol": "QQQ", "etf_score": 6.99}
            )
        )
        self.assertTrue(
            _passes_universal_asset_gate(
                {
                    "kind": "etf",
                    "symbol": "QQQ",
                    "etf_score": 7.0,
                    "short_term_score": 8.0,
                    "long_term_score": 7.0,
                }
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

    def test_cached_lists_are_refiltered_with_current_strategy_gates(self):
        valid_swing = {
            "symbol": "GOOD",
            "short_term_score": 8.0,
            "long_term_score": 6.0,
            "overall_score": 7.0,
            "swing_setup": {"qualified": True},
        }
        invalid_swing = {
            "kind": "stock",
            "symbol": "LOW_ST",
            "short_term_score": 6.99,
            "long_term_score": 6.99,
            "overall_score": 9.0,
        }
        invalid_invest = {
            "kind": "stock",
            "symbol": "LOW_OVERALL",
            "short_term_score": 7.99,
            "long_term_score": 8.5,
            "overall_score": 6.99,
        }
        invalid_etf = {
            "kind": "etf",
            "symbol": "LOW_ETF",
            "etf_score": 6.99,
            "short_term_score": 9.0,
            "long_term_score": 9.0,
            "swing_setup": {"qualified": False},
        }
        payload = {
            "threshold": 8.0,
            "top_swing_stocks": [valid_swing, invalid_swing],
            "top_invest_stocks": [invalid_invest],
            "top_stocks": [valid_swing, invalid_swing],
            "top_etfs": [invalid_etf],
            "top": [valid_swing, invalid_swing, invalid_invest, invalid_etf],
        }

        cleaned = _sanitize_scan_payload(payload)

        self.assertEqual([item["symbol"] for item in cleaned["top_swing_stocks"]], ["GOOD"])
        self.assertEqual(cleaned["top_invest_stocks"], [])
        self.assertEqual(cleaned["top_etfs"], [])
        self.assertEqual(cleaned["top_short_term_etfs"], [])
        self.assertEqual(cleaned["top_long_term_etfs"], [])
        self.assertEqual([item["symbol"] for item in cleaned["top"]], ["GOOD"])

    def test_general_weights_match_new_profile(self):
        self.assertAlmostEqual(sum(WEIGHTS.values()), 1.0)
        self.assertEqual(WEIGHTS["trend"], 0.20)
        self.assertEqual(WEIGHTS["volume"], 0.10)
        self.assertEqual(WEIGHTS["heatmap"], 0.08)
        self.assertEqual(WEIGHTS["behavior_sentiment"], 0.05)
        self.assertNotIn("market_climate", WEIGHTS)

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

    def test_heatmap_uses_sector_status_only(self):
        # Sector breadth of +0.5% maps to the 7.5 band; liquidity / fear inputs
        # are no longer part of the general score.
        score, _ = heatmap_score({"avg_change_pct": 0.5})
        self.assertAlmostEqual(score, 7.5)
        # Missing sector data falls back to a neutral 5.0.
        neutral, _ = heatmap_score(None)
        self.assertAlmostEqual(neutral, 5.0)


class ScanHostingSafetyTests(unittest.TestCase):
    def test_stock_ohlcv_batches_are_render_safe(self):
        self.assertLessEqual(scanner.STOCK_BATCH_CHUNK_SIZE, 50)

    def test_disabled_live_scan_never_computes_without_seed(self):
        empty_cache = {
            "data": None,
            "ts": 0.0,
            "running": False,
            "from_seed": False,
        }
        with (
            patch.object(scanner, "LIVE_SCAN_ENABLED", False),
            patch.object(scanner, "_cache", empty_cache),
            patch.object(scanner, "run_scan") as run_scan,
        ):
            with self.assertRaises(ScanSeedUnavailable):
                scanner.get_scan(force=True)
            run_scan.assert_not_called()

    def test_disabled_live_scan_serves_existing_seed(self):
        seed = {"fetched_at": 123.0, "top": []}
        cached = {
            "data": seed,
            "ts": 123.0,
            "running": False,
            "from_seed": True,
        }
        with (
            patch.object(scanner, "LIVE_SCAN_ENABLED", False),
            patch.object(scanner, "_cache", cached),
            patch.object(scanner, "run_scan") as run_scan,
        ):
            served = scanner.get_scan(force=True)
            self.assertEqual(served["fetched_at"], seed["fetched_at"])
            self.assertEqual(served["threshold"], 7.0)
            self.assertEqual(served["swing_threshold"], 7.0)
            run_scan.assert_not_called()


class TierOneFunnelTests(unittest.TestCase):
    @staticmethod
    def _prices(start: float, end: float, periods: int = 220) -> pd.DataFrame:
        index = pd.bdate_range("2025-08-01", periods=periods)
        step = (end - start) / max(periods - 1, 1)
        close = pd.Series(
            [start + step * offset for offset in range(periods)],
            index=index,
        )
        return pd.DataFrame({
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000.0,
        })

    def test_long_term_funnel_does_not_require_abnormal_rvol(self):
        low_volume_quality = {
            "symbol": "VALUE",
            "rvol": 0.72,
            "sub": self._prices(80.0, 110.0),
        }
        short_history_swing = {
            "symbol": "SWING",
            "rvol": 2.2,
            "sub": self._prices(100.0, 70.0, periods=80),
        }

        self.assertEqual(_select_swing_tier1([low_volume_quality]), [])
        selected = _select_long_term_tier1(
            [low_volume_quality, short_history_swing]
        )
        self.assertEqual([row["symbol"] for row in selected], ["VALUE"])
        self.assertGreater(_long_term_prefilter_score(low_volume_quality["sub"]), 0)

    def test_merged_funnels_keep_strategy_paths_and_cap_expensive_stage(self):
        common = {
            "symbol": "BOTH",
            "rvol": 1.8,
            "sub": self._prices(90.0, 120.0),
        }
        swing = [common] + [
            {"symbol": f"S{index}", "rvol": 2.0, "sub": common["sub"]}
            for index in range(20)
        ]
        long_term = [common] + [
            {
                "symbol": f"L{index}",
                "rvol": 0.8,
                "sub": common["sub"],
                "long_term_prefilter_score": 8.0,
            }
            for index in range(20)
        ]

        merged = _merge_tier2_candidates(swing[:15], long_term[:15])
        self.assertLessEqual(len(merged), 30)
        both = next(row for row in merged if row["symbol"] == "BOTH")
        self.assertEqual(set(both["scan_paths"]), {"swing", "long_term"})


class CompanyProfileFallbackTests(unittest.TestCase):
    def test_builds_description_from_search_profile_fields(self):
        description, description_he = _fallback_descriptions(
            "Apple Inc.", "Technology", "Consumer Electronics", "NASDAQ"
        )
        self.assertIn("Apple Inc.", description)
        self.assertIn("Consumer Electronics", description)
        self.assertIn("Apple Inc.", description_he)
        self.assertIn("NASDAQ", description_he)

    def test_requires_name_and_classification(self):
        self.assertEqual(_fallback_descriptions(None, "Technology", None, None), (None, None))
        self.assertEqual(_fallback_descriptions("Unknown", None, None, None), (None, None))

    def test_reads_reported_and_point_in_time_values(self):
        self.assertEqual(
            _timeseries_value({"reportedValue": {"raw": 123.5}}),
            123.5,
        )
        self.assertEqual(_timeseries_value({"dataValue": 0.004}), 0.004)

    def test_growth_rate_uses_latest_two_periods(self):
        self.assertAlmostEqual(_growth_rate([100.0, 125.0]), 0.25)
        self.assertIsNone(_growth_rate([100.0]))

    def test_calculates_beta_from_aligned_daily_prices(self):
        market = {day: 100.0 + day for day in range(1, 80)}
        stock = {day: 200.0 + 2.0 * day for day in range(1, 80)}
        beta = _calculate_beta(stock, market)
        self.assertIsNotNone(beta)
        self.assertGreater(beta, 0.9)


class SwingProfileTests(unittest.TestCase):
    def test_stock_context_includes_behavioral_inputs(self):
        behavior = {"short_interest": {"short_float_pct": 23.0}}
        with (
            patch.object(scanner, "_fetch_info", return_value={"sector": "Retail"}),
            patch.object(
                scanner,
                "get_behavior_sentiment",
                return_value=behavior,
            ),
        ):
            info, fetched_behavior = _fetch_stock_context("GIII")

        self.assertEqual(info["sector"], "Retail")
        self.assertEqual(fetched_behavior, behavior)

    def test_swing_threshold_is_seven(self):
        self.assertEqual(SWING_THRESHOLD, 7.0)

    def test_short_term_profile_categories_and_weights(self):
        """New short-term profile: no sentiment/flow, no Global Liquidity, a
        standalone ATR% category, and the requested weight map."""
        result = compute_short_term_score(
            price=110,
            ma20=100,
            ma50=95,
            rsi14=65,
            vwap=102,
            rvol=1.8,
            gap_pct=4.0,
            atr_pct=2.0,
            patterns=None,
            behavior=None,
            sector_status={"avg_change_pct": 2.0, "sector_label": "Technology"},
        )
        weights = {c.name: c.weight for c in result.categories}
        self.assertAlmostEqual(weights["טכני קצר"], 0.35)
        self.assertAlmostEqual(weights["נפח וקטליזטורים"], 0.30)
        self.assertAlmostEqual(weights["תבניות פריצה"], 0.15)
        self.assertAlmostEqual(weights["תנודתיות (ATR%)"], 0.10)
        self.assertAlmostEqual(weights["מצב סקטור (Heatmap)"], 0.10)
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        # Removed categories must not appear anymore.
        names = set(weights)
        self.assertNotIn("סנטימנט וזרימה", names)
        self.assertNotIn("Global Liquidity Index", names)

    def test_atr_category_scores_swing_suitability(self):
        result = compute_short_term_score(
            price=110, ma20=100, ma50=95, rsi14=65, vwap=102,
            rvol=1.8, gap_pct=0.0, atr_pct=2.0,
            patterns=None, behavior=None,
            sector_status={"avg_change_pct": 0.0, "sector_label": "Test"},
        )
        atr = next(c for c in result.categories if "ATR" in c.name)
        self.assertFalse(atr.skipped)
        self.assertEqual(atr.score, 9.0)

    def test_short_interest_survives_as_bonus_only(self):
        result = compute_short_term_score(
            price=110, ma20=100, ma50=95, rsi14=65, vwap=102,
            rvol=1.0, gap_pct=0.0, atr_pct=2.0,
            patterns=None,
            behavior={"short_interest": {"short_percent_float": 22.0}},
            sector_status={"avg_change_pct": 0.0, "sector_label": "Test"},
        )
        self.assertGreater(result.bonus, 0.0)
        self.assertGreater(result.score, result.raw_score)

    def test_scan_requires_swing_and_overall_thresholds(self):
        self.assertTrue(_is_swing_qualified({
            "short_term_score": 1.0,
            "overall_score": 1.0,
            "swing_setup": {"qualified": True},
        }))
        self.assertFalse(_is_swing_qualified({
            "short_term_score": 10.0,
            "overall_score": 10.0,
            "swing_setup": {"qualified": False},
        }))

    def test_prebreakout_setup_requires_every_hard_gate(self):
        cup = {
            "detected": True,
            "direction": "bullish",
            "confidence": 64,
            "level": 105,
            "target": 120,
            "stop": 98,
            "geometry": {
                "handle_low": {"price": 99},
                "broke_out": False,
            },
        }
        setup = _build_prebreakout_swing_setup(
            current_price=100,
            rvol=1.8,
            cup_pattern=cup,
            rising_structure=True,
        )
        self.assertEqual(SWING_MIN_RVOL, 1.2)
        self.assertEqual(SWING_MIN_RISK_REWARD, 1.5)
        self.assertEqual(SWING_MIN_SUCCESS_RATE, 60.0)
        self.assertTrue(setup["qualified"])
        self.assertGreaterEqual(setup["risk_reward"], 1.08)

        low_rvol = _build_prebreakout_swing_setup(
            current_price=100,
            rvol=1.19,
            cup_pattern=cup,
            rising_structure=True,
        )
        self.assertFalse(low_rvol["qualified"])
        self.assertFalse(low_rvol["checks"]["elevated_rvol"])

    def test_multi_trigger_setup_accepts_bull_flag_near_breakout(self):
        index = pd.bdate_range("2025-08-01", periods=220)
        # Strong uptrend with small periodic pullbacks so RSI(14) is a real
        # momentum reading (> 60) instead of the divide-by-zero 50 a perfectly
        # monotonic series produces.
        levels = []
        price = 80.0
        for offset in range(220):
            price += -0.30 * 0.6 if offset % 5 == 4 else 0.30
            levels.append(price)
        close = pd.Series(levels, index=index)
        frame = pd.DataFrame({
            "open": close * 0.998,
            "high": close * 1.006,
            "low": close * 0.994,
            "close": close,
            "volume": 1_500_000.0,
        })
        pattern = {
            "detected": True,
            "direction": "bullish",
            "name": "Bull Flag",
            "confidence": 72,
            "level": float(close.iloc[-1] * 1.02),
            "target": float(close.iloc[-1] * 1.12),
            "stop": float(close.iloc[-1] * 0.96),
        }
        patterns = {
            "cup_and_handle": {"detected": False},
            "flag": pattern,
            "double_bottom": {"detected": False},
            "triangle": {"detected": False},
        }

        with patch.object(scanner, "detect_patterns", return_value=patterns):
            setup = _compute_prebreakout_swing_setup(frame, rvol=1.3)

        self.assertTrue(setup["qualified"])
        self.assertEqual(setup["status"], "near_trigger")
        self.assertIn("Bull Flag", setup["trigger_names"])
        self.assertGreaterEqual(setup["risk_reward"], 1.5)

    def test_etf_uses_lower_rvol_threshold_than_stock(self):
        index = pd.bdate_range("2025-08-01", periods=220)
        # Rising trend with minor pullbacks → RSI(14) > 60 (a perfectly
        # monotonic series collapses to RSI 50 via divide-by-zero).
        levels = []
        price = 100.0
        for offset in range(220):
            price += -0.25 * 0.6 if offset % 5 == 4 else 0.25
            levels.append(price)
        close = pd.Series(levels, index=index)
        frame = pd.DataFrame({
            "open": close,
            "high": close * 1.004,
            "low": close * 0.996,
            "close": close,
            "volume": 2_000_000.0,
        })
        pattern = {
            "detected": True,
            "direction": "bullish",
            "name": "Ascending Triangle",
            "confidence": 70,
            "level": float(close.iloc[-1] * 1.02),
            "target": float(close.iloc[-1] * 1.15),
            "stop": float(close.iloc[-1] * 0.96),
        }
        patterns = {
            "cup_and_handle": {"detected": False},
            "flag": {"detected": False},
            "double_bottom": {"detected": False},
            "triangle": pattern,
        }

        with patch.object(scanner, "detect_patterns", return_value=patterns):
            stock_setup = _compute_prebreakout_swing_setup(
                frame, rvol=1.15, is_etf=False,
            )
            etf_setup = _compute_prebreakout_swing_setup(
                frame, rvol=1.15, is_etf=True,
            )

        self.assertFalse(stock_setup["qualified"])
        self.assertTrue(etf_setup["qualified"])

    def test_short_term_setup_rejects_weak_rsi_momentum(self):
        """RSI(14) > 60 is a hard auto-filter for both stocks and ETFs: an
        otherwise-perfect setup whose RSI sits at/below the floor is rejected,
        while the same setup with strong RSI qualifies."""
        index = pd.bdate_range("2025-08-01", periods=220)

        def make_frame(levels):
            close = pd.Series(levels, index=index)
            return pd.DataFrame({
                "open": close * 0.998,
                "high": close * 1.006,
                "low": close * 0.994,
                "close": close,
                "volume": 2_000_000.0,
            })

        # Weak momentum: a perfectly linear rise lands RSI exactly at 50.
        weak_frame = make_frame([80.0 + offset * 0.20 for offset in range(220)])
        # Strong momentum: rising with minor pullbacks pushes RSI well above 60.
        strong_levels = []
        price = 80.0
        for offset in range(220):
            price += -0.30 * 0.6 if offset % 5 == 4 else 0.30
            strong_levels.append(price)
        strong_frame = make_frame(strong_levels)

        def pattern_for(close):
            return {
                "detected": True,
                "direction": "bullish",
                "name": "Ascending Triangle",
                "confidence": 72,
                "level": float(close.iloc[-1] * 1.02),
                "target": float(close.iloc[-1] * 1.15),
                "stop": float(close.iloc[-1] * 0.96),
            }

        def patterns_for(close):
            return {
                "cup_and_handle": {"detected": False},
                "flag": {"detected": False},
                "double_bottom": {"detected": False},
                "triangle": pattern_for(close),
            }

        with patch.object(
            scanner, "detect_patterns",
            return_value=patterns_for(weak_frame["close"]),
        ):
            weak_setup = _compute_prebreakout_swing_setup(weak_frame, rvol=1.5)
        with patch.object(
            scanner, "detect_patterns",
            return_value=patterns_for(strong_frame["close"]),
        ):
            strong_setup = _compute_prebreakout_swing_setup(
                strong_frame, rvol=1.5,
            )

        self.assertFalse(weak_setup["checks"]["momentum_rsi"])
        self.assertFalse(weak_setup["qualified"])
        self.assertTrue(strong_setup["checks"]["momentum_rsi"])
        self.assertTrue(strong_setup["qualified"])

    def test_prebreakout_setup_requires_sixty_percent(self):
        cup = {
            "detected": True,
            "direction": "bullish",
            "confidence": 59,
            "level": 102,
            "target": 110,
            "stop": 98,
            "geometry": {
                "handle_low": {"price": 99},
                "broke_out": False,
            },
        }
        setup = _build_prebreakout_swing_setup(
            current_price=100,
            rvol=2.0,
            cup_pattern=cup,
            rising_structure=True,
        )
        self.assertFalse(setup["qualified"])
        self.assertFalse(setup["checks"]["success_rate"])

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
        self.assertEqual(LONG_TERM_OVERALL_THRESHOLD, 7.0)
        self.assertTrue(_is_long_term_qualified({"long_term_score": 7.0, "overall_score": 7.0}))
        self.assertFalse(_is_long_term_qualified({"long_term_score": 7.0, "overall_score": 6.99}))
        self.assertFalse(_is_long_term_qualified({"long_term_score": 6.99, "overall_score": 9.0}))

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
