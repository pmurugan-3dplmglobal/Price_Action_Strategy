"""
Comprehensive Adversarial Stress Test Suite for Price Action Geometry & Quantitative Invariants
Authored by challenger_geometry_invariants_2.

Audits:
1. Anchor Pattern Edge Cases:
   - LL Sweep: L2 RED condition, floor protection, inter-swing spacing > 2 bars.
   - HH Sweep: H2 GREEN condition, ceiling protection, inter-swing spacing > 2 bars.
   - Harami: inside body ratio <= 65% of mother candle.
   - Hammer / Shooting Star: shadow to body ratio >= 2x and mother base containment.
2. Left-Side Rule Boundary Conditions:
   - 100-bar lookback closing basis (wicks permitted, closes rejected).
   - Adaptive 30-bar lookback for option contracts to prevent penny-price false invalidation.
3. Point D Volume Gate:
   - Dry-volume breakouts (d_vol < 1.2 * avg_vol_20) on completed candles rejected.
   - Institutional volume breakouts (d_vol >= 1.2 * avg_vol_20) on completed candles accepted.
   - Bearish Point D volume breakdown: dry-volume (<1.2x) rejected, institutional (>=1.2x) accepted.
"""

import os
import sys
import unittest
import pandas as pd
import numpy as np

# Canonical imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from common.patterns_bull import (
    find_anchor_bullish_engulfing,
    find_anchor_ll_sweep,
    find_anchor_hammer_baby,
    find_anchor_bullish_harami,
    find_anchor_two_higher_highs,
    scan_anchor_bcd_breakout
)
from common.patterns_bear import (
    find_anchor_bearish_engulfing,
    find_anchor_hh_sweep,
    find_anchor_shooting_star_baby,
    find_anchor_bearish_harami,
    find_anchor_two_lower_lows,
    scan_anchor_bcd_breakout_bearish
)
from common.targets import (
    check_left_side_rule,
    check_left_side_rule_bearish
)


class TestLLSweepAdversarial(unittest.TestCase):
    """Adversarial stress-test of find_anchor_ll_sweep."""

    def _build_ll_sweep_df(self, inbetween_count=3, l2_is_red=True, bounce_breaks_floor=False):
        candles = []
        candles.append({"date": "2026-08-01 09:15", "open": 105.0, "high": 106.0, "low": 104.0, "close": 104.5, "volume": 1000})
        candles.append({"date": "2026-08-01 09:20", "open": 104.5, "high": 105.0, "low": 100.0, "close": 101.0, "volume": 1000})
        candles.append({"date": "2026-08-01 09:25", "open": 101.0, "high": 102.0, "low": 98.0, "close": 98.5, "volume": 1000})
        # Low 1 candle
        candles.append({"date": "2026-08-01 09:30", "open": 98.5, "high": 99.0, "low": 95.0, "close": 96.0, "volume": 1000})

        # In-between candles: visible bounce >= 95 + 1.5 = 96.5, all closes >= 95.0
        for i in range(inbetween_count):
            h = 99.0 if i == 0 else 98.0
            candles.append({
                "date": f"2026-08-01 09:{35 + i*5}",
                "open": 96.5, "high": h, "low": 95.5, "close": 97.0, "volume": 1000
            })

        # L2 sweep candle (low = 93.0 < 95.0)
        if l2_is_red:
            sweep = {"date": "2026-08-01 10:00", "open": 96.0, "high": 96.5, "low": 93.0, "close": 95.5, "volume": 1500}
        else:
            sweep = {"date": "2026-08-01 10:00", "open": 94.0, "high": 96.5, "low": 93.0, "close": 96.0, "volume": 1500}
        candles.append(sweep)

        # Bounce candle: must close > sweep high (96.5)
        bounce_low = 92.0 if bounce_breaks_floor else 94.5
        bounce = {
            "date": "2026-08-01 10:05",
            "open": 95.5, "high": 98.0, "low": bounce_low, "close": 97.5, "volume": 2000
        }
        candles.append(bounce)
        return pd.DataFrame(candles)

    def test_ll_sweep_spacing_boundary(self):
        """Adversarial Test: Inter-swing spacing for LL Sweep."""
        df_1 = self._build_ll_sweep_df(inbetween_count=1)
        res_1 = find_anchor_ll_sweep(df_1)
        self.assertIsNone(res_1, "LL Sweep with only 1 in-between candle MUST fail")

        df_2 = self._build_ll_sweep_df(inbetween_count=2)
        res_2 = find_anchor_ll_sweep(df_2)
        code_allows_2_bars = (res_2 is not None)
        print(f"\n[EMPIRICAL FINDING] LL Sweep 2-bar spacing: code_allows_2_bars = {code_allows_2_bars}")

        df_3 = self._build_ll_sweep_df(inbetween_count=3)
        res_3 = find_anchor_ll_sweep(df_3)
        self.assertIsNotNone(res_3, "LL Sweep with 3 in-between candles MUST pass")
        self.assertEqual(res_3["Pattern"], "BULL_A_LL_Sweep_Var1")

    def test_ll_sweep_l2_red_vs_green(self):
        """Test L2 candle color: Var 1 enforces Red candle; Var 2 allows Green candle."""
        df_red = self._build_ll_sweep_df(inbetween_count=3, l2_is_red=True)
        res_red = find_anchor_ll_sweep(df_red)
        self.assertIsNotNone(res_red)
        self.assertEqual(res_red["Pattern"], "BULL_A_LL_Sweep_Var1")

        df_green = self._build_ll_sweep_df(inbetween_count=3, l2_is_red=False)
        res_green = find_anchor_ll_sweep(df_green)
        self.assertIsNotNone(res_green)
        self.assertEqual(res_green["Pattern"], "BULL_A_LL_Sweep_Var2")

    def test_ll_sweep_floor_protection_edge_case(self):
        """Adversarial Test: Floor Protection."""
        df_floor_breach = self._build_ll_sweep_df(inbetween_count=3, l2_is_red=True, bounce_breaks_floor=True)
        res = find_anchor_ll_sweep(df_floor_breach)
        allows_bounce_floor_breach = (res is not None)
        print(f"[EMPIRICAL FINDING] LL Sweep Floor Protection in anchor fn: allows_bounce_floor_breach = {allows_bounce_floor_breach}")
        if allows_bounce_floor_breach:
            print("  -> VULNERABILITY CONFIRMED: find_anchor_ll_sweep does NOT check if bounce_candle breaks L2 floor (bounce_low < sweep_low).")


class TestHHSweepAdversarial(unittest.TestCase):
    """Adversarial stress-test of find_anchor_hh_sweep."""

    def _build_hh_sweep_df(self, inbetween_count=3, h2_is_green=True, rejection_breaks_ceiling=False):
        candles = []
        candles.append({"date": "2026-08-01 09:15", "open": 95.0, "high": 96.0, "low": 94.0, "close": 95.5, "volume": 1000})
        candles.append({"date": "2026-08-01 09:20", "open": 95.5, "high": 100.0, "low": 95.0, "close": 99.0, "volume": 1000})
        candles.append({"date": "2026-08-01 09:25", "open": 99.0, "high": 102.0, "low": 98.0, "close": 101.5, "volume": 1000})
        # High 1 candle
        candles.append({"date": "2026-08-01 09:30", "open": 101.5, "high": 105.0, "low": 101.0, "close": 104.0, "volume": 1000})

        # In-between candles: pullback <= 105 - 1.5 = 103.5, all closes <= 105.0
        for i in range(inbetween_count):
            l = 101.0 if i == 0 else 102.0
            candles.append({
                "date": f"2026-08-01 09:{35 + i*5}",
                "open": 103.5, "high": 104.5, "low": l, "close": 103.0, "volume": 1000
            })

        # H2 sweep candle (high = 107.0 > 105.0)
        if h2_is_green:
            sweep = {"date": "2026-08-01 10:00", "open": 104.0, "high": 107.0, "low": 103.5, "close": 104.5, "volume": 1500}
        else:
            sweep = {"date": "2026-08-01 10:00", "open": 106.0, "high": 107.0, "low": 103.5, "close": 104.0, "volume": 1500}
        candles.append(sweep)

        # Rejection candle: must close < sweep low (103.5)
        rej_high = 108.0 if rejection_breaks_ceiling else 105.5
        rejection = {
            "date": "2026-08-01 10:05",
            "open": 104.5, "high": rej_high, "low": 102.0, "close": 102.5, "volume": 2000
        }
        candles.append(rejection)
        return pd.DataFrame(candles)

    def test_hh_sweep_spacing_boundary(self):
        """Adversarial Test: Inter-swing spacing for HH Sweep."""
        df_1 = self._build_hh_sweep_df(inbetween_count=1)
        res_1 = find_anchor_hh_sweep(df_1)
        self.assertIsNone(res_1, "HH Sweep with only 1 in-between candle MUST fail")

        df_2 = self._build_hh_sweep_df(inbetween_count=2)
        res_2 = find_anchor_hh_sweep(df_2)
        code_allows_2_bars = (res_2 is not None)
        print(f"[EMPIRICAL FINDING] HH Sweep 2-bar spacing: code_allows_2_bars = {code_allows_2_bars}")

        df_3 = self._build_hh_sweep_df(inbetween_count=3)
        res_3 = find_anchor_hh_sweep(df_3)
        self.assertIsNotNone(res_3, "HH Sweep with 3 in-between candles MUST pass")
        self.assertEqual(res_3["Pattern"], "BEAR_A_HH_Sweep_Var1")

    def test_hh_sweep_ceiling_protection_edge_case(self):
        """Adversarial Test: Ceiling Protection."""
        df_ceiling_breach = self._build_hh_sweep_df(inbetween_count=3, h2_is_green=True, rejection_breaks_ceiling=True)
        res = find_anchor_hh_sweep(df_ceiling_breach)
        allows_rejection_ceiling_breach = (res is not None)
        print(f"[EMPIRICAL FINDING] HH Sweep Ceiling Protection in anchor fn: allows_rejection_ceiling_breach = {allows_rejection_ceiling_breach}")
        if allows_rejection_ceiling_breach:
            print("  -> VULNERABILITY CONFIRMED: find_anchor_hh_sweep does NOT check if rejection_candle breaks H2 ceiling (rej_high > sweep_high).")


class TestHaramiPrecision(unittest.TestCase):
    """Adversarial stress-test of Harami 65% body ratio threshold."""

    def test_bullish_harami_ratio_sub_percent_precision(self):
        mother = {"date": "2026-08-01 09:15", "open": 100.0, "high": 101.0, "low": 89.0, "close": 90.0, "volume": 1000}
        c_650 = {"date": "2026-08-01 09:20", "open": 92.0, "high": 99.0, "low": 91.0, "close": 98.50, "volume": 1000}
        self.assertIsNotNone(find_anchor_bullish_harami(pd.DataFrame([mother, c_650])))

        c_6501 = {"date": "2026-08-01 09:20", "open": 92.0, "high": 99.0, "low": 91.0, "close": 98.501, "volume": 1000}
        self.assertIsNone(find_anchor_bullish_harami(pd.DataFrame([mother, c_6501])))

    def test_bearish_harami_ratio_sub_percent_precision(self):
        mother = {"date": "2026-08-01 09:15", "open": 90.0, "high": 101.0, "low": 89.0, "close": 100.0, "volume": 1000}
        c_650 = {"date": "2026-08-01 09:20", "open": 98.50, "high": 99.0, "low": 91.0, "close": 92.0, "volume": 1000}
        self.assertIsNotNone(find_anchor_bearish_harami(pd.DataFrame([mother, c_650])))

        c_6501 = {"date": "2026-08-01 09:20", "open": 98.501, "high": 99.0, "low": 91.0, "close": 92.0, "volume": 1000}
        self.assertIsNone(find_anchor_bearish_harami(pd.DataFrame([mother, c_6501])))


class TestHammerShootingStarShadowRatioAdversarial(unittest.TestCase):
    """
    Adversarial comparison of Hammer & Shooting star shadow-to-body ratios:
    - Current code in patterns_bull.py line 170: min_wick_ratio = 1.2 for green, 1.8 for red.
    - Datta Rulebook & USER_REQUEST: shadow to body ratio >= 2x.
    """

    def test_hammer_shadow_ratio_empirical_check(self):
        mother = {"date": "2026-08-01 09:15", "open": 105.0, "high": 106.0, "low": 99.5, "close": 100.0, "volume": 1000}
        baby_15x = {
            "date": "2026-08-01 09:20",
            "open": 101.0, "close": 102.0, "high": 102.1,
            "low": 99.50,  # Lower wick = 1.5, Body = 1.0, Ratio = 1.5x (< 2.0x)
            "volume": 1000
        }
        res_15x = find_anchor_hammer_baby(pd.DataFrame([mother, baby_15x]))
        code_permits_sub_2x = (res_15x is not None)
        print(f"[EMPIRICAL FINDING] Hammer wick ratio 1.5x (sub-2.0x): code_permits_sub_2x = {code_permits_sub_2x}")

        baby_20x = {
            "date": "2026-08-01 09:20",
            "open": 101.0, "close": 102.0, "high": 102.1,
            "low": 99.00,  # Lower wick = 2.0, Body = 1.0, Ratio = 2.0x (>= 2.0x)
            "volume": 1000
        }
        res_20x = find_anchor_hammer_baby(pd.DataFrame([mother, baby_20x]))
        self.assertIsNotNone(res_20x, "Hammer with 2.0x lower wick MUST PASS")

    def test_shooting_star_shadow_ratio_empirical_check(self):
        mother = {"date": "2026-08-01 09:15", "open": 95.0, "high": 100.5, "low": 94.0, "close": 100.0, "volume": 1000}
        star_15x = {
            "date": "2026-08-01 09:20",
            "open": 98.0, "close": 97.0, "low": 96.9,
            "high": 99.50,  # Upper wick = 1.5, Body = 1.0, Ratio = 1.5x (< 2.0x)
            "volume": 1000
        }
        res_15x = find_anchor_shooting_star_baby(pd.DataFrame([mother, star_15x]))
        code_permits_sub_2x = (res_15x is not None)
        print(f"[EMPIRICAL FINDING] Shooting Star wick ratio 1.5x (sub-2.0x): code_permits_sub_2x = {code_permits_sub_2x}")

        star_20x = {
            "date": "2026-08-01 09:20",
            "open": 98.0, "close": 97.0, "low": 96.9,
            "high": 100.0,  # Upper wick = 2.0, Body = 1.0, Ratio = 2.0x (>= 2.0x)
            "volume": 1000
        }
        res_20x = find_anchor_shooting_star_baby(pd.DataFrame([mother, star_20x]))
        self.assertIsNotNone(res_20x, "Shooting Star with 2.0x upper wick MUST PASS")


class TestLeftSideRuleLookbackAdversarial(unittest.TestCase):
    """
    Adversarial stress-test of Left-Side Rule lookback:
    1. 100-bar lookback with closing basis (wicks pass, closes fail).
    2. Adaptive 30-bar lookback for option contracts to prevent penny-price false invalidation.
    """

    def test_left_side_100_bar_closing_basis_stress(self):
        n_bars = 120
        closes = [105.0] * n_bars
        lows = [105.0] * n_bars
        anchor_low = 100.0

        # Bar 50: Deep wick down to 80.0, but close is 102.0
        lows[50] = 80.0
        closes[50] = 102.0
        df = pd.DataFrame({"close": closes, "low": lows})
        self.assertTrue(check_left_side_rule(df, anchor_low=anchor_low, lookback_candles=100),
                        "Historical wick piercing below anchor low MUST NOT invalidate setup")

        # Bar 50: Close drops to 99.99 (< anchor_low)
        closes[50] = 99.99
        df_breach = pd.DataFrame({"close": closes, "low": lows})
        self.assertFalse(check_left_side_rule(df_breach, anchor_low=anchor_low, lookback_candles=100),
                         "Historical close below anchor low MUST invalidate setup")

    def test_adaptive_30_bar_option_lookback_prevents_penny_false_invalidation(self):
        n_bars = 60
        closes = [12.0] * n_bars
        lows = [11.0] * n_bars

        # 45 bars ago (index 15): Penny price close = 2.50
        closes[15] = 2.50
        lows[15] = 2.00
        df = pd.DataFrame({"close": closes, "low": lows})
        anchor_low = 8.00

        # With 100-bar lookback: False Invalidation!
        res_100 = check_left_side_rule(df, anchor_low=anchor_low, lookback_candles=100)
        self.assertFalse(res_100, "100-bar lookback sees the 45-bar-old penny close and invalidates")

        # With adaptive 30-bar lookback for options: Preserves setup!
        res_30 = check_left_side_rule(df, anchor_low=anchor_low, lookback_candles=30)
        self.assertTrue(res_30, "Adaptive 30-bar lookback correctly isolates intraday option window and PASSES")

        # If penny close is within 30 bars (e.g. 10 bars ago), 30-bar lookback MUST invalidate
        closes[50] = 2.50
        df_recent = pd.DataFrame({"close": closes, "low": lows})
        res_30_recent = check_left_side_rule(df_recent, anchor_low=anchor_low, lookback_candles=30)
        self.assertFalse(res_30_recent, "Close below anchor low within 30 bars MUST invalidate setup")


class TestPointDVolumeGateAdversarial(unittest.TestCase):
    """
    Adversarial stress-test of Point D Volume Gate (ISSUE-086):
    - Dry-volume breakouts (d_vol < 1.2 * avg_vol_20) on completed candles rejected.
    - Institutional volume breakouts (d_vol >= 1.2 * avg_vol_20) on completed candles accepted.
    """

    def _build_bull_df(self, d_vol):
        rows = []
        base_vol = 1000.0
        for i in range(24):
            h = 120.0 if i == 5 else 101.0
            rows.append({
                "date": f"2026-08-01 {9 + i//12:02d}:{(i%12)*5:02d}",
                "open": 100.0, "high": h, "low": 99.0, "close": 100.0, "volume": base_vol
            })
        rows.append({"date": "2026-08-01 11:05", "open": 101.0, "high": 101.5, "low": 98.0, "close": 98.5, "volume": base_vol})
        rows.append({"date": "2026-08-01 11:10", "open": 98.0, "high": 102.0, "low": 97.0, "close": 101.8, "volume": base_vol})
        rows.append({"date": "2026-08-01 11:15", "open": 101.5, "high": 103.5, "low": 101.0, "close": 103.0, "volume": base_vol})
        rows.append({"date": "2026-08-01 11:20", "open": 102.8, "high": 102.9, "low": 101.5, "close": 101.8, "volume": base_vol * 0.7})
        rows.append({"date": "2026-08-01 11:25", "open": 102.0, "high": 104.0, "low": 101.9, "close": 103.5, "volume": d_vol})
        rows.append({"date": "2026-08-01 11:30", "open": 102.0, "high": 102.0, "low": 100.5, "close": 101.0, "volume": base_vol})
        rows.append({"date": "2026-08-01 11:35", "open": 101.0, "high": 101.5, "low": 100.0, "close": 100.5, "volume": base_vol})
        return pd.DataFrame(rows)

    def _build_bear_df(self, d_vol):
        rows = []
        base_vol = 1000.0
        for i in range(24):
            l = 80.0 if i == 5 else 99.0
            rows.append({
                "date": f"2026-08-01 {9 + i//12:02d}:{(i%12)*5:02d}",
                "open": 100.0, "high": 101.0, "low": l, "close": 100.0, "volume": base_vol
            })
        rows.append({"date": "2026-08-01 11:05", "open": 99.0, "high": 101.5, "low": 98.5, "close": 101.0, "volume": base_vol})
        rows.append({"date": "2026-08-01 11:10", "open": 102.0, "high": 102.5, "low": 97.0, "close": 97.5, "volume": base_vol})
        rows.append({"date": "2026-08-01 11:15", "open": 97.5, "high": 98.0, "low": 95.5, "close": 96.0, "volume": base_vol})
        rows.append({"date": "2026-08-01 11:20", "open": 96.5, "high": 97.5, "low": 96.0, "close": 97.2, "volume": base_vol * 0.7})
        rows.append({"date": "2026-08-01 11:25", "open": 97.0, "high": 97.1, "low": 95.0, "close": 95.5, "volume": d_vol})
        rows.append({"date": "2026-08-01 11:30", "open": 96.0, "high": 97.5, "low": 95.8, "close": 97.0, "volume": base_vol})
        rows.append({"date": "2026-08-01 11:35", "open": 97.0, "high": 98.0, "low": 96.5, "close": 97.5, "volume": base_vol})
        return pd.DataFrame(rows)

    def test_bull_point_d_volume_rejection_at_0_8x(self):
        df = self._build_bull_df(d_vol=800.0)
        res = scan_anchor_bcd_breakout(df, df, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        self.assertIsNone(res, "Bullish breakout with 0.8x dry volume MUST be rejected")

    def test_bull_point_d_exact_boundary_1_19x_vs_1_20x(self):
        # 20-bar avg volume prior to bar 28 is 985.0 -> 1.2x threshold = 1182.0
        df_119 = self._build_bull_df(d_vol=1181.9)
        res_119 = scan_anchor_bcd_breakout(df_119, df_119, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        self.assertIsNone(res_119, "Bullish breakout at 1.1999x volume MUST be rejected")

        df_120 = self._build_bull_df(d_vol=1182.0)
        res_120 = scan_anchor_bcd_breakout(df_120, df_120, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        self.assertIsNotNone(res_120, "Bullish breakout at 1.2000x volume MUST be accepted")

    def test_bull_point_d_volume_acceptance_at_1_5x(self):
        df = self._build_bull_df(d_vol=1500.0)
        res = scan_anchor_bcd_breakout(df, df, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        self.assertIsNotNone(res, "Bullish breakout with 1.5x institutional volume MUST be accepted")

    def test_bear_point_d_volume_rejection_at_0_8x(self):
        df = self._build_bear_df(d_vol=800.0)
        res = scan_anchor_bcd_breakout_bearish(df, df, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        self.assertIsNone(res, "Bearish breakdown with 0.8x dry volume MUST be rejected")

    def test_bear_point_d_exact_boundary_1_19x_vs_1_20x(self):
        df_119 = self._build_bear_df(d_vol=1181.9)
        res_119 = scan_anchor_bcd_breakout_bearish(df_119, df_119, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        self.assertIsNone(res_119, "Bearish breakdown at 1.1999x volume MUST be rejected")

        df_120 = self._build_bear_df(d_vol=1182.0)
        res_120 = scan_anchor_bcd_breakout_bearish(df_120, df_120, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        self.assertIsNotNone(res_120, "Bearish breakdown at 1.2000x volume MUST be accepted")

    def test_bear_point_d_volume_acceptance_at_1_5x(self):
        df = self._build_bear_df(d_vol=1500.0)
        res = scan_anchor_bcd_breakout_bearish(df, df, anchor_tf="5minute", entry_tf="5minute", enable_swing_filter=False)
        self.assertIsNotNone(res, "Bearish breakdown with 1.5x institutional volume MUST be accepted")


if __name__ == "__main__":
    unittest.main(verbosity=2)
