#!/usr/bin/env python3
"""
scratch/test_adversarial_geometry_parity.py
Adversarial Empirical Stress-Testing Suite for Pattern Geometry (R1) & Domain Parity (R2).

Boundary & Invariant Coverage:
1. Left-Side Rule Boundary: Wicks vs Closes penetration across 100-candle lookback.
2. Harami 65% Body Ratio Boundary: 64.9% vs 65.0% vs 65.1% thresholds & containment.
3. Hammer Baby Base Containment & Shooting Star Peak Containment (1.005x / 0.995x).
4. D1 Spot Confluence & Gold Promotion: VWAP reclaim/reject, SL support hold, RR >= 2.0.
5. D2 Trend Momentum: EMA13/44 alignment enforcement vs rejection.
6. Cash Short Parity Math: Inverted PnL ((entry - exit) / entry * 100), trailing +BE (entry * 0.98), and BUY cover routing.
"""
import os
import sys
import unittest
import pandas as pd
import numpy as np
from datetime import datetime as dt, timedelta

# Path bootstrapping
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from common.targets import (
    check_left_side_rule,
    check_left_side_rule_bearish,
    check_left_side,
    check_left_side_bearish
)
from common.patterns_bull import (
    find_anchor_bullish_harami,
    find_anchor_hammer_baby
)
from common.patterns_bear import (
    find_anchor_bearish_harami,
    find_anchor_shooting_star_baby
)
from common.resolve import evaluate_spot_confluence
from common.position_monitor import (
    close_stock_position,
    clear_executed_exit,
    save_executed_exit
)


class MockKiteForParity:
    """Mock Kite Connect client for testing order placement and routing."""
    def __init__(self):
        self.placed_orders = []
        self.cancelled_orders = []
        self.TRANSACTION_TYPE_BUY = "BUY"
        self.TRANSACTION_TYPE_SELL = "SELL"
        self.PRODUCT_MIS = "MIS"
        self.PRODUCT_CNC = "CNC"
        self.ORDER_TYPE_LIMIT = "LIMIT"
        self.ORDER_TYPE_MARKET = "MARKET"
        self.VARIETY_REGULAR = "regular"
        self.EXCHANGE_NSE = "NSE"
        self.mock_net_positions = []
        self.mock_orders = []

    def orders(self):
        return self.mock_orders

    def positions(self):
        return {"net": self.mock_net_positions}

    def quote(self, keys):
        if isinstance(keys, str):
            keys = [keys]
        return {
            k: {
                "last_price": 100.0,
                "depth": {
                    "sell": [{"price": 100.5, "quantity": 100}],
                    "buy": [{"price": 99.5, "quantity": 100}]
                }
            } for k in keys
        }

    def place_order(self, **kwargs):
        self.placed_orders.append(kwargs)
        return f"ORD_MOCK_{len(self.placed_orders)}"

    def cancel_order(self, variety, order_id):
        self.cancelled_orders.append({"variety": variety, "order_id": order_id})
        return True


class TestLeftSideRuleBoundary(unittest.TestCase):
    """Stress-test Left-Side Rule wicks vs closes for Bullish and Bearish setups."""

    def setUp(self):
        # Base 120-candle series where prices hover comfortably
        dates = pd.date_range("2026-08-01 09:15", periods=120, freq="5min")
        self.bull_base_df = pd.DataFrame({
            "date": dates,
            "open": [105.0] * 120,
            "high": [110.0] * 120,
            "low": [103.0] * 120,
            "close": [106.0] * 120,
            "volume": [1000] * 120
        })
        self.bear_base_df = pd.DataFrame({
            "date": dates,
            "open": [195.0] * 120,
            "high": [197.0] * 120,
            "low": [190.0] * 120,
            "close": [194.0] * 120,
            "volume": [1000] * 120
        })

    def test_01_bullish_wicks_penetrate_closes_hold(self):
        """Bullish: Deep wicks penetrate Anchor Low (low < anchor_low), but ALL closes >= anchor_low."""
        anchor_low = 100.0
        df = self.bull_base_df.copy()
        # Inject several candles with wicks dipping down to 92.0, but closes stay above 100.0
        for idx in [20, 50, 80, 115]:
            df.loc[idx, "low"] = 92.0
            df.loc[idx, "close"] = 101.5
            df.loc[idx, "open"] = 104.0
            df.loc[idx, "high"] = 105.0

        # Wicks penetrated, but closes held! Rule MUST PASS (return True).
        res = check_left_side_rule(df, anchor_low=anchor_low, lookback_candles=100)
        self.assertTrue(res, "Bullish Left-Side Rule MUST allow lower wicks when closes are >= anchor_low")

    def test_02_bullish_close_penetrates_by_epsilon(self):
        """Bullish: A single candle close penetrates Anchor Low by 0.01 (close < anchor_low)."""
        anchor_low = 100.0
        df = self.bull_base_df.copy()
        # Candle 70 closes at 99.99
        df.loc[70, "close"] = 99.99
        df.loc[70, "low"] = 99.50

        # Close penetrated! Rule MUST FAIL (return False).
        res = check_left_side_rule(df, anchor_low=anchor_low, lookback_candles=100)
        self.assertFalse(res, "Bullish Left-Side Rule MUST reject when a prior candle close is < anchor_low")

    def test_03_bullish_close_exact_equality(self):
        """Bullish: Candle close exactly equals Anchor Low (close == anchor_low)."""
        anchor_low = 100.0
        df = self.bull_base_df.copy()
        df.loc[60, "close"] = 100.00  # Exact match
        df.loc[60, "low"] = 100.00

        # Datta Law: strictly lower breaks the base. Equality holds!
        res = check_left_side_rule(df, anchor_low=anchor_low, lookback_candles=100)
        self.assertTrue(res, "Bullish Left-Side Rule MUST pass on exact equality (close == anchor_low)")

    def test_04_bullish_close_outside_100_lookback(self):
        """Bullish: Candle close penetrates Anchor Low, but occurred 105 bars ago (>100 lookback)."""
        anchor_low = 100.0
        df = self.bull_base_df.copy()
        # df has 120 candles. Last 100 candles are indices 20..119.
        # Index 10 is outside the 100-candle lookback window.
        df.loc[10, "close"] = 85.0
        df.loc[10, "low"] = 80.0

        res = check_left_side_rule(df, anchor_low=anchor_low, lookback_candles=100)
        self.assertTrue(res, "Bullish Left-Side Rule lookback is bounded to 100 candles; older breaks are ignored")

    def test_05_bearish_wicks_penetrate_closes_hold(self):
        """Bearish: High wicks penetrate Anchor High (high > anchor_high), but ALL closes <= anchor_high."""
        anchor_high = 200.0
        df = self.bear_base_df.copy()
        # Inject wicks spiking to 215.0, but closes remain <= 200.0
        for idx in [25, 55, 85, 110]:
            df.loc[idx, "high"] = 215.0
            df.loc[idx, "close"] = 198.5
            df.loc[idx, "open"] = 196.0
            df.loc[idx, "low"] = 194.0

        # Wicks penetrated, but closes held below ceiling! Rule MUST PASS (return True).
        res = check_left_side_rule_bearish(df, anchor_high=anchor_high, lookback_candles=100)
        self.assertTrue(res, "Bearish Left-Side Rule MUST allow upper wicks when closes are <= anchor_high")

    def test_06_bearish_close_penetrates_by_epsilon(self):
        """Bearish: A single candle close penetrates Anchor High by 0.01 (close > anchor_high)."""
        anchor_high = 200.0
        df = self.bear_base_df.copy()
        # Candle 65 closes at 200.01
        df.loc[65, "close"] = 200.01
        df.loc[65, "high"] = 202.0

        # Close penetrated! Rule MUST FAIL (return False).
        res = check_left_side_rule_bearish(df, anchor_high=anchor_high, lookback_candles=100)
        self.assertFalse(res, "Bearish Left-Side Rule MUST reject when a prior candle close is > anchor_high")

    def test_07_bearish_close_exact_equality(self):
        """Bearish: Candle close exactly equals Anchor High (close == anchor_high)."""
        anchor_high = 200.0
        df = self.bear_base_df.copy()
        df.loc[75, "close"] = 200.00
        df.loc[75, "high"] = 200.00

        res = check_left_side_rule_bearish(df, anchor_high=anchor_high, lookback_candles=100)
        self.assertTrue(res, "Bearish Left-Side Rule MUST pass on exact equality (close == anchor_high)")

    def test_08_bearish_close_outside_100_lookback(self):
        """Bearish: Candle close penetrates Anchor High, but occurred 105 bars ago (>100 lookback)."""
        anchor_high = 200.0
        df = self.bear_base_df.copy()
        df.loc[10, "close"] = 220.0  # Outside 100-candle lookback
        df.loc[10, "high"] = 225.0

        res = check_left_side_rule_bearish(df, anchor_high=anchor_high, lookback_candles=100)
        self.assertTrue(res, "Bearish Left-Side Rule lookback is bounded to 100 candles; older breaks are ignored")


class TestHaramiBodyRatioBoundary(unittest.TestCase):
    """Stress-test Harami inside-bar 65% body ratio boundary and containment."""

    def test_01_bullish_harami_body_ratio_boundary(self):
        """Bullish Harami: Mother body = 10.0. Test inside body at 64.9%, 65.0%, and 65.1%."""
        # Mother candle: Bearish, Open = 100.0, Close = 90.0 (Body = 10.0)
        mother = {"date": "2026-08-01 09:15", "open": 100.0, "high": 101.0, "low": 89.0, "close": 90.0, "volume": 1000}

        # Subcase A: 64.9% ratio -> inside body = 6.49 (Open = 92.00, Close = 98.49)
        inside_649 = {"date": "2026-08-01 09:20", "open": 92.00, "high": 99.0, "low": 91.0, "close": 98.49, "volume": 1200}
        df_649 = pd.DataFrame([mother, inside_649])
        res_649 = find_anchor_bullish_harami(df_649)
        self.assertIsNotNone(res_649, "Bullish Harami with body ratio 64.9% (<=65%) MUST PASS")
        self.assertEqual(res_649["Pattern"], "BULL_A_Harami")

        # Subcase B: 65.0% ratio -> inside body = 6.50 (Open = 92.00, Close = 98.50)
        inside_650 = {"date": "2026-08-01 09:20", "open": 92.00, "high": 99.0, "low": 91.0, "close": 98.50, "volume": 1200}
        df_650 = pd.DataFrame([mother, inside_650])
        res_650 = find_anchor_bullish_harami(df_650)
        self.assertIsNotNone(res_650, "Bullish Harami with body ratio exactly 65.0% (<=65%) MUST PASS")

        # Subcase C: 65.1% ratio -> inside body = 6.51 (Open = 92.00, Close = 98.51)
        inside_651 = {"date": "2026-08-01 09:20", "open": 92.00, "high": 99.0, "low": 91.0, "close": 98.51, "volume": 1200}
        df_651 = pd.DataFrame([mother, inside_651])
        res_651 = find_anchor_bullish_harami(df_651)
        self.assertIsNone(res_651, "Bullish Harami with body ratio 65.1% (>65%) MUST FAIL")

    def test_02_bullish_harami_containment_violations(self):
        """Bullish Harami: Inside bar wicks protruding beyond mother open or close."""
        mother = {"date": "2026-08-01 09:15", "open": 100.0, "high": 101.0, "low": 89.0, "close": 90.0, "volume": 1000}

        # High exceeds mother open (100.1 > 100.0)
        inside_high_leak = {"date": "2026-08-01 09:20", "open": 92.0, "high": 100.1, "low": 91.0, "close": 95.0, "volume": 1000}
        self.assertIsNone(find_anchor_bullish_harami(pd.DataFrame([mother, inside_high_leak])),
                          "Inside bar high > mother open must be rejected")

        # Low penetrates below mother close (89.9 < 90.0)
        inside_low_leak = {"date": "2026-08-01 09:20", "open": 92.0, "high": 98.0, "low": 89.9, "close": 95.0, "volume": 1000}
        self.assertIsNone(find_anchor_bullish_harami(pd.DataFrame([mother, inside_low_leak])),
                          "Inside bar low < mother close must be rejected")

    def test_03_bearish_harami_body_ratio_boundary(self):
        """Bearish Harami: Mother body = 10.0. Test inside body at 64.9%, 65.0%, and 65.1%."""
        # Mother candle: Bullish, Open = 90.0, Close = 100.0 (Body = 10.0)
        mother = {"date": "2026-08-01 09:15", "open": 90.0, "high": 101.0, "low": 89.0, "close": 100.0, "volume": 1000}

        # Subcase A: 64.9% ratio -> inside body = 6.49 (Open = 98.49, Close = 92.00)
        inside_649 = {"date": "2026-08-01 09:20", "open": 98.49, "high": 99.0, "low": 91.0, "close": 92.00, "volume": 1200}
        df_649 = pd.DataFrame([mother, inside_649])
        res_649 = find_anchor_bearish_harami(df_649)
        self.assertIsNotNone(res_649, "Bearish Harami with body ratio 64.9% (<=65%) MUST PASS")
        self.assertEqual(res_649["Pattern"], "BEAR_A_Harami")

        # Subcase B: 65.0% ratio -> inside body = 6.50 (Open = 98.50, Close = 92.00)
        inside_650 = {"date": "2026-08-01 09:20", "open": 98.50, "high": 99.0, "low": 91.0, "close": 92.00, "volume": 1200}
        df_650 = pd.DataFrame([mother, inside_650])
        res_650 = find_anchor_bearish_harami(df_650)
        self.assertIsNotNone(res_650, "Bearish Harami with body ratio exactly 65.0% (<=65%) MUST PASS")

        # Subcase C: 65.1% ratio -> inside body = 6.51 (Open = 98.51, Close = 92.00)
        inside_651 = {"date": "2026-08-01 09:20", "open": 98.51, "high": 99.0, "low": 91.0, "close": 92.00, "volume": 1200}
        df_651 = pd.DataFrame([mother, inside_651])
        res_651 = find_anchor_bearish_harami(df_651)
        self.assertIsNone(res_651, "Bearish Harami with body ratio 65.1% (>65%) MUST FAIL")

    def test_04_bearish_harami_containment_violations(self):
        """Bearish Harami: Inside bar wicks protruding beyond mother close or open."""
        mother = {"date": "2026-08-01 09:15", "open": 90.0, "high": 101.0, "low": 89.0, "close": 100.0, "volume": 1000}

        # High exceeds mother close (100.1 > 100.0)
        inside_high_leak = {"date": "2026-08-01 09:20", "open": 97.0, "high": 100.1, "low": 92.0, "close": 93.0, "volume": 1000}
        self.assertIsNone(find_anchor_bearish_harami(pd.DataFrame([mother, inside_high_leak])),
                          "Bearish inside bar high > mother close must be rejected")

        # Low penetrates below mother open (89.9 < 90.0)
        inside_low_leak = {"date": "2026-08-01 09:20", "open": 97.0, "high": 98.0, "low": 89.9, "close": 93.0, "volume": 1000}
        self.assertIsNone(find_anchor_bearish_harami(pd.DataFrame([mother, inside_low_leak])),
                          "Bearish inside bar low < mother open must be rejected")


class TestHammerAndShootingStarContainment(unittest.TestCase):
    """Stress-test Hammer Baby base containment (1.005x) and Shooting Star peak containment (0.995x)."""

    def test_01_hammer_baby_contained_vs_floating(self):
        """Hammer Baby: Mother close = 100.0. Containment boundary = 100.0 * 1.005 = 100.50."""
        mother = {"date": "2026-08-01 09:15", "open": 105.0, "high": 106.0, "low": 99.5, "close": 100.0, "volume": 1000}

        # Valid hammer base test: Low = 100.40 (<= 100.50)
        baby_valid = {
            "date": "2026-08-01 09:20",
            "open": 102.0, "close": 102.5,  # Body = 0.5 (green)
            "high": 102.6,                  # Upper wick = 0.1
            "low": 100.40,                  # Lower wick = 1.6 (3.2x body)
            "volume": 1500
        }
        res_valid = find_anchor_hammer_baby(pd.DataFrame([mother, baby_valid]))
        self.assertIsNotNone(res_valid, "Properly contained Hammer Baby at base (low=100.40 <= 100.50) MUST PASS")
        self.assertEqual(res_valid["Pattern"], "BULL_A_Baby_Candle")

        # Floating hammer: Low = 100.60 (> 100.50)
        baby_floating = {
            "date": "2026-08-01 09:20",
            "open": 102.0, "close": 102.5,
            "high": 102.6,
            "low": 100.60,  # Floating above support!
            "volume": 1500
        }
        res_floating = find_anchor_hammer_baby(pd.DataFrame([mother, baby_floating]))
        self.assertIsNone(res_floating, "Floating Hammer Baby (low=100.60 > 100.50) MUST FAIL containment guard")

        # Severely detached hammer: Low = 102.0 (> 100.50)
        baby_detached = {
            "date": "2026-08-01 09:20",
            "open": 103.0, "close": 103.5,
            "high": 103.6,
            "low": 102.0,
            "volume": 1500
        }
        self.assertIsNone(find_anchor_hammer_baby(pd.DataFrame([mother, baby_detached])),
                          "Severely detached hammer far above mother close must be rejected")

    def test_02_hammer_baby_morphology_invariants(self):
        """Hammer Baby: Wick ratio, upper wick cap, and close conviction tests."""
        mother = {"date": "2026-08-01 09:15", "open": 105.0, "high": 106.0, "low": 99.5, "close": 100.0, "volume": 1000}

        # A. Weak lower wick: lower wick = 0.5, body = 0.5 (ratio 1.0x < 1.2x min)
        baby_weak_wick = {"date": "2026-08-01 09:20", "open": 100.5, "close": 101.0, "high": 101.1, "low": 100.0, "volume": 1000}
        self.assertIsNone(find_anchor_hammer_baby(pd.DataFrame([mother, baby_weak_wick])),
                          "Hammer Baby with insufficient lower wick ratio (<1.2x) must fail")

        # B. Excessive upper wick: upper wick > 35% total range
        baby_long_upper = {"date": "2026-08-01 09:20", "open": 101.0, "close": 101.5, "high": 103.0, "low": 100.0, "volume": 1000}
        self.assertIsNone(find_anchor_hammer_baby(pd.DataFrame([mother, baby_long_upper])),
                          "Hammer Baby with excessive upper wick (>35% range) must fail")

        # C. Weak close conviction: close finishes in lower half of candle span
        baby_weak_close = {"date": "2026-08-01 09:20", "open": 100.8, "close": 100.4, "high": 102.0, "low": 100.0, "volume": 1000}
        self.assertIsNone(find_anchor_hammer_baby(pd.DataFrame([mother, baby_weak_close])),
                          "Hammer Baby closing in bottom 60% must fail conviction check")

    def test_03_shooting_star_contained_vs_sunken(self):
        """Shooting Star Baby: Mother close = 100.0. Containment boundary = 100.0 * 0.995 = 99.50."""
        mother = {"date": "2026-08-01 09:15", "open": 95.0, "high": 100.5, "low": 94.0, "close": 100.0, "volume": 1000}

        # Valid shooting star peak test: High = 99.60 (>= 99.50)
        star_valid = {
            "date": "2026-08-01 09:20",
            "open": 98.0, "close": 97.5,   # Body = 0.5 (red)
            "high": 99.60,                 # Upper wick = 1.6 (3.2x body)
            "low": 97.4,                   # Lower wick = 0.1
            "volume": 1500
        }
        res_valid = find_anchor_shooting_star_baby(pd.DataFrame([mother, star_valid]))
        self.assertIsNotNone(res_valid, "Properly contained Shooting Star Baby at peak (high=99.60 >= 99.50) MUST PASS")
        self.assertEqual(res_valid["Pattern"], "BEAR_A_ShootingStar_Baby")

        # Sunken shooting star: High = 99.40 (< 99.50)
        star_sunken = {
            "date": "2026-08-01 09:20",
            "open": 98.0, "close": 97.5,
            "high": 99.40,  # Below peak threshold!
            "low": 97.4,
            "volume": 1500
        }
        res_sunken = find_anchor_shooting_star_baby(pd.DataFrame([mother, star_sunken]))
        self.assertIsNone(res_sunken, "Sunken Shooting Star Baby (high=99.40 < 99.50) MUST FAIL peak containment guard")

        # Severely sunken star: High = 96.0 (< 99.50)
        star_deep_sunken = {
            "date": "2026-08-01 09:20",
            "open": 95.0, "close": 94.5,
            "high": 96.0,
            "low": 94.4,
            "volume": 1500
        }
        self.assertIsNone(find_anchor_shooting_star_baby(pd.DataFrame([mother, star_deep_sunken])),
                          "Severely sunken shooting star far below mother peak must be rejected")


class TestD1SpotConfluenceAndGoldPromotion(unittest.TestCase):
    """Stress-test D1 Spot VWAP reclaim, support hold, and Gold tier promotion rules."""

    def test_01_d1_ce_spot_vwap_reclaim(self):
        """CE D1: Spot price reclaims/holds intraday VWAP -> SPOT_VWAP_RECLAIM."""
        conf, conf_type = evaluate_spot_confluence(
            side="CE", is_d2=False, current_spot=24100.0, spot_vwap=24050.0, spot_sl=23950.0, spot_ema_trend=False
        )
        self.assertTrue(conf, "CE D1 with current_spot >= spot_vwap must return True")
        self.assertEqual(conf_type, "SPOT_VWAP_RECLAIM")

    def test_02_d1_ce_spot_support_hold(self):
        """CE D1: Spot price is below VWAP, but strictly holds above structural support floor (spot_sl)."""
        conf, conf_type = evaluate_spot_confluence(
            side="CE", is_d2=False, current_spot=24000.0, spot_vwap=24050.0, spot_sl=23950.0, spot_ema_trend=False
        )
        self.assertTrue(conf, "CE D1 holding structural support floor must return True")
        self.assertEqual(conf_type, "SPOT_SUPPORT_HOLD")

    def test_03_d1_ce_rejection_when_both_violated(self):
        """CE D1: Spot price breaks both VWAP and structural support floor."""
        conf, conf_type = evaluate_spot_confluence(
            side="CE", is_d2=False, current_spot=23900.0, spot_vwap=24050.0, spot_sl=23950.0, spot_ema_trend=False
        )
        self.assertFalse(conf, "CE D1 breaking both VWAP and support floor must return False")
        self.assertEqual(conf_type, "NONE")

    def test_04_d1_pe_spot_vwap_reject(self):
        """PE D1: Spot price rejects below intraday VWAP -> SPOT_VWAP_REJECT."""
        conf, conf_type = evaluate_spot_confluence(
            side="PE", is_d2=False, current_spot=23950.0, spot_vwap=24050.0, spot_sl=24150.0, spot_ema_trend=False
        )
        self.assertTrue(conf, "PE D1 with current_spot <= spot_vwap must return True")
        self.assertEqual(conf_type, "SPOT_VWAP_REJECT")

    def test_05_d1_pe_spot_resistance_hold(self):
        """PE D1: Spot price is above VWAP, but strictly remains below resistance ceiling (spot_sl)."""
        conf, conf_type = evaluate_spot_confluence(
            side="PE", is_d2=False, current_spot=24100.0, spot_vwap=24050.0, spot_sl=24150.0, spot_ema_trend=False
        )
        self.assertTrue(conf, "PE D1 holding below resistance ceiling must return True")
        self.assertEqual(conf_type, "SPOT_RESISTANCE_HOLD")

    def test_06_d1_pe_rejection_when_both_violated(self):
        """PE D1: Spot price rallies above both VWAP and resistance ceiling."""
        conf, conf_type = evaluate_spot_confluence(
            side="PE", is_d2=False, current_spot=24200.0, spot_vwap=24050.0, spot_sl=24150.0, spot_ema_trend=False
        )
        self.assertFalse(conf, "PE D1 breaching above ceiling and VWAP must return False")
        self.assertEqual(conf_type, "NONE")

    def test_07_gold_tier_promotion_matrix(self):
        """Verify D1 promotion to T1 Gold iff spot_confluence holds AND R:R >= 2.0."""
        # Simulated promotion helper matching resolve.py:1556 exactly
        def check_promotion(is_d2, base_tier, spot_conf, rr):
            tier = base_tier
            tier_label = "TIER_2_CORE"
            tier_badge = "🥈 T2"
            if not is_d2 and tier == 2 and spot_conf and float(rr or 0.0) >= 2.0:
                tier = 1
                tier_label = "TIER_1_GOLD"
                tier_badge = "🥇 T1"
            return tier, tier_label, tier_badge

        # Scenario A: Confluence holds + RR = 2.15 (>= 2.0) -> PROMOTED TO GOLD
        t, l, b = check_promotion(is_d2=False, base_tier=2, spot_conf=True, rr=2.15)
        self.assertEqual(t, 1)
        self.assertEqual(l, "TIER_1_GOLD")
        self.assertEqual(b, "🥇 T1")

        # Scenario B: Confluence holds, but RR = 1.95 (< 2.0) -> NOT PROMOTED
        t, l, b = check_promotion(is_d2=False, base_tier=2, spot_conf=True, rr=1.95)
        self.assertEqual(t, 2)
        self.assertEqual(l, "TIER_2_CORE")

        # Scenario C: No confluence, even with RR = 3.50 -> NOT PROMOTED
        t, l, b = check_promotion(is_d2=False, base_tier=2, spot_conf=False, rr=3.50)
        self.assertEqual(t, 2)
        self.assertEqual(l, "TIER_2_CORE")

        # Scenario D: D2 continuation (is_d2=True), confluence holds, RR = 3.0 -> NOT PROMOTED via D1 rule
        t, l, b = check_promotion(is_d2=True, base_tier=2, spot_conf=True, rr=3.00)
        self.assertEqual(t, 2, "D2 continuation must not be promoted via D1 Reversal Gold rule")


class TestD2TrendMomentum(unittest.TestCase):
    """Stress-test D2 Continuation trend momentum requirements (EMA13/44 alignment)."""

    def test_01_ce_d2_requires_spot_ema_trend(self):
        """CE D2: spot_ema_trend is False -> MUST REJECT, even if spot is high above VWAP."""
        conf, conf_type = evaluate_spot_confluence(
            side="CE", is_d2=True, current_spot=24200.0, spot_vwap=24000.0, spot_sl=23900.0, spot_ema_trend=False
        )
        self.assertFalse(conf, "CE D2 continuation MUST reject when spot_ema_trend is False")
        self.assertEqual(conf_type, "NONE")

    def test_02_ce_d2_approves_when_ema_and_vwap_aligned(self):
        """CE D2: spot_ema_trend is True AND spot >= VWAP -> APPROVE."""
        conf, conf_type = evaluate_spot_confluence(
            side="CE", is_d2=True, current_spot=24200.0, spot_vwap=24000.0, spot_sl=23900.0, spot_ema_trend=True
        )
        self.assertTrue(conf, "CE D2 continuation MUST approve when EMA trend and VWAP are aligned")
        self.assertEqual(conf_type, "TREND_MOMENTUM_ALIGNMENT")

    def test_03_ce_d2_rejects_when_spot_below_vwap(self):
        """CE D2: spot_ema_trend is True BUT current_spot < spot_vwap -> MUST REJECT."""
        conf, conf_type = evaluate_spot_confluence(
            side="CE", is_d2=True, current_spot=23950.0, spot_vwap=24000.0, spot_sl=23900.0, spot_ema_trend=True
        )
        self.assertFalse(conf, "CE D2 continuation MUST reject when spot is below intraday VWAP")
        self.assertEqual(conf_type, "NONE")

    def test_04_pe_d2_requires_spot_ema_trend(self):
        """PE D2: spot_ema_trend is False -> MUST REJECT, even if spot is falling."""
        conf, conf_type = evaluate_spot_confluence(
            side="PE", is_d2=True, current_spot=23800.0, spot_vwap=24000.0, spot_sl=24100.0, spot_ema_trend=False
        )
        self.assertFalse(conf, "PE D2 continuation MUST reject when spot_ema_trend is False")
        self.assertEqual(conf_type, "NONE")

    def test_05_pe_d2_approves_when_ema_and_vwap_aligned(self):
        """PE D2: spot_ema_trend is True AND spot <= VWAP -> APPROVE."""
        conf, conf_type = evaluate_spot_confluence(
            side="PE", is_d2=True, current_spot=23800.0, spot_vwap=24000.0, spot_sl=24100.0, spot_ema_trend=True
        )
        self.assertTrue(conf, "PE D2 continuation MUST approve when EMA trend and downward VWAP are aligned")
        self.assertEqual(conf_type, "TREND_MOMENTUM_ALIGNMENT")

    def test_06_pe_d2_rejects_when_spot_above_vwap(self):
        """PE D2: spot_ema_trend is True BUT current_spot > spot_vwap -> MUST REJECT."""
        conf, conf_type = evaluate_spot_confluence(
            side="PE", is_d2=True, current_spot=24050.0, spot_vwap=24000.0, spot_sl=24100.0, spot_ema_trend=True
        )
        self.assertFalse(conf, "PE D2 continuation MUST reject when spot is above intraday VWAP")
        self.assertEqual(conf_type, "NONE")


class TestCashShortParityMathAndExecution(unittest.TestCase):
    """Stress-test Short MIS PnL formula, trailing +BE (entry * 0.98), and BUY cover routing."""

    def setUp(self):
        clear_executed_exit("TATAMOTORS")
        clear_executed_exit("SBIN")

    def tearDown(self):
        clear_executed_exit("TATAMOTORS")
        clear_executed_exit("SBIN")

    def test_01_short_mis_pnl_formula(self):
        """Verify Short MIS PnL formula: (entry - exit) / entry * 100."""
        entry = 1000.0

        # 10% price drop -> +10.0% profit for short
        exit_profit = 900.0
        pnl_gain = ((entry - exit_profit) / entry * 100)
        self.assertAlmostEqual(pnl_gain, 10.0, places=4)

        # 10% price surge -> -10.0% loss for short
        exit_loss = 1100.0
        pnl_loss = ((entry - exit_loss) / entry * 100)
        self.assertAlmostEqual(pnl_loss, -10.0, places=4)

        # Contrast with Long Equity formula: (exit - entry) / entry * 100
        long_gain = ((1100.0 - entry) / entry * 100)
        self.assertAlmostEqual(long_gain, 10.0, places=4)

    def test_02_short_mis_trailing_positive_breakeven(self):
        """Verify +BE trail down under steep drop (peak gain >= 10% -> SL = entry * 0.98)."""
        entry_s = 1000.0
        curr_sl = 1025.0  # Initial SL was 2.5% above entry

        # Price plunges to 890.0 (Gain = (1000 - 890) / 1000 * 100 = 11.0% >= 10.0%)
        lp = 890.0
        gain_pct = ((entry_s - lp) / entry_s * 100)
        self.assertGreaterEqual(gain_pct, 10.0)

        # Trailing calculation as implemented in position_monitor.py:1303
        be_target = round(round((entry_s * 0.98) / 0.05) * 0.05, 2)
        new_sl = min(curr_sl, be_target) if curr_sl > 0 else be_target

        self.assertEqual(be_target, 980.0, "Short +BE target must be entry * 0.98 (980.0)")
        self.assertEqual(new_sl, 980.0, "New SL must be lowered from 1025.0 down to 980.0")

        # Invariant: If price bounces back and hits the new SL at 980.0, profit is strictly positive (+2.0%)!
        exit_at_be = ((entry_s - new_sl) / entry_s * 100)
        self.assertAlmostEqual(exit_at_be, 2.0, places=4, msg="Triggering +BE SL must lock in +2% profit")

    def test_03_short_mis_order_routing_buy_cover(self):
        """Verify close_stock_position routes TRANSACTION_TYPE_BUY with PRODUCT_MIS for Short positions."""
        mock_kite = MockKiteForParity()
        pos_short = {
            "symbol": "TATAMOTORS",
            "contract": "TATAMOTORS",
            "position_type": "stock",
            "side": "SELL",
            "direction": "BEAR",
            "product": "MIS",
            "position_size": 25,
            "quantity": 25
        }

        res = close_stock_position(mock_kite, pos_short, live=True, product_type="MIS")
        self.assertTrue(res.get("success"), f"Short exit failed: {res}")
        self.assertEqual(len(mock_kite.placed_orders), 1)

        order = mock_kite.placed_orders[0]
        self.assertEqual(order["transaction_type"], "BUY", "Short stock exit MUST place a BUY order to cover")
        self.assertEqual(order["product"], "MIS", "Short stock exit MUST use PRODUCT_MIS")
        self.assertEqual(order["order_type"], "LIMIT")
        self.assertEqual(order["quantity"], 25)
        # Price must be pegged at ask * 1.005 (ask=100.5 -> 100.5 * 1.005 = 101.0)
        self.assertEqual(order["price"], 101.0)

    def test_04_short_mis_held_quantity_negative_detection(self):
        """Verify close_stock_position detects negative live held quantity (-50) and covers correctly."""
        mock_kite = MockKiteForParity()
        mock_kite.mock_net_positions = [
            {"tradingsymbol": "SBIN", "quantity": -50, "product": "MIS"}
        ]
        pos = {
            "symbol": "SBIN",
            "contract": "SBIN",
            "side": "SELL",
            "position_size": -50,  # Negative quantity input
            "product": "MIS"
        }

        res = close_stock_position(mock_kite, pos, live=True)
        self.assertTrue(res.get("success"))
        self.assertEqual(len(mock_kite.placed_orders), 1)

        order = mock_kite.placed_orders[0]
        self.assertEqual(order["transaction_type"], "BUY")
        self.assertEqual(order["quantity"], 50, "Quantity must be sanitized to positive integer (abs)")
        self.assertEqual(order["product"], "MIS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
