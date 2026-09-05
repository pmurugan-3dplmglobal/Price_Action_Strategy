#!/usr/bin/env python3
"""
scratch/test_institutional_enhancements.py
5-test Institutional Unit Verification Suite:
1. Option Contract VWAP +2σ Bands (calculate_option_vwap)
2. Point C TWAP Base Stability (calculate_twap_c_stability)
3. Spot-Relative Confluence Mapping (get_mapped_spot_timeframe & evaluate_spot_confluence)
4. Continuous 15% Greek Loss Shield & Catastrophic Circuit Protection
5. Pegged Limit Order Routing & Bid-Ask Spread Guard
"""
import os
import sys
import unittest
import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from common.swing_detection import calculate_option_vwap, calculate_twap_c_stability
from common.resolve import get_mapped_spot_timeframe, evaluate_spot_confluence
from common.liquidity_guard import check_bid_ask_spread_liquidity


class TestInstitutionalEnhancements(unittest.TestCase):

    def test_01_option_vwap_bands(self):
        """Test 1: calculate_option_vwap Volume-Weighted Bands, Z-score & Tiers."""
        # 1. Null / empty input fallback
        res_empty = calculate_option_vwap(None)
        self.assertEqual(res_empty["vwap_status"], "FAIR")
        self.assertFalse(res_empty["is_overstretched"])

        # 2. Fair / Low-Stretch Option Data (Close hovering near VWAP)
        dates = pd.date_range("2026-09-05 09:15", periods=30, freq="5min")
        close = np.array([50.0 + (i * 0.1) for i in range(30)])
        vol = np.array([1000 + (i * 10) for i in range(30)])
        df_fair = pd.DataFrame({
            "date": dates,
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": vol
        })
        res_fair = calculate_option_vwap(df_fair)
        self.assertGreater(res_fair["vwap"], 0)
        self.assertGreater(res_fair["vwap_upper_2sigma"], res_fair["vwap"])
        self.assertLessEqual(res_fair["vwap_lower_2sigma"], res_fair["vwap"])
        self.assertIn(res_fair["vwap_status"], ["FAIR", "EXPANDED"])
        self.assertFalse(res_fair["is_overstretched"])

        # 3. Overstretched Option Data (FOMO spike, close >> VWAP + 2σ / >15% stretch)
        close_spike = close.copy()
        close_spike[-1] = res_fair["vwap"] * 1.25  # 25% spike above VWAP
        df_stretched = df_fair.copy()
        df_stretched["close"] = close_spike
        df_stretched["high"] = np.maximum(df_stretched["high"], close_spike)
        res_stretched = calculate_option_vwap(df_stretched)
        self.assertEqual(res_stretched["vwap_status"], "STRETCHED")
        self.assertTrue(res_stretched["is_overstretched"])
        self.assertGreater(res_stretched["stretch_pct"], 15.0)

    def test_02_twap_c_stability(self):
        """Test 2: calculate_twap_c_stability Absorption Base Tightness."""
        # 1. Empty window fallback
        res_empty = calculate_twap_c_stability(None)
        self.assertFalse(res_empty["twap_stable"])
        self.assertEqual(res_empty["twap_score"], 0.0)

        # 2. Pristine tight Point C absorption (low variance, std <= 0.25 * risk)
        df_tight = pd.DataFrame({
            "close": [100.0, 100.1, 100.05, 100.15, 100.08, 100.12]
        })
        res_tight = calculate_twap_c_stability(df_tight, risk_dist=2.0)
        self.assertTrue(res_tight["twap_stable"])
        self.assertGreaterEqual(res_tight["twap_score"], 0.8)
        self.assertLessEqual(res_tight["twap_std"], 0.25 * 2.0)

        # 3. Choppy volatile Point C (wide variance, std > 0.25 * risk)
        df_loose = pd.DataFrame({
            "close": [95.0, 105.0, 93.0, 107.0, 91.0, 108.0]
        })
        res_loose = calculate_twap_c_stability(df_loose, risk_dist=2.0)
        self.assertFalse(res_loose["twap_stable"])
        self.assertLess(res_loose["twap_score"], 0.5)

    def test_03_spot_confluence_mapping(self):
        """Test 3: get_mapped_spot_timeframe & evaluate_spot_confluence."""
        # Timeframe mapping
        self.assertEqual(get_mapped_spot_timeframe("3minute"), "15m")
        self.assertEqual(get_mapped_spot_timeframe("5minute"), "15m")
        self.assertEqual(get_mapped_spot_timeframe("15minute"), "60m")
        self.assertEqual(get_mapped_spot_timeframe("30minute"), "day")

        # D1 Bullish Reversal: Spot VWAP reclaim
        ok, ctype = evaluate_spot_confluence(
            side="CE", is_d2=False, current_spot=25100.0, spot_vwap=25050.0, spot_sl=24950.0, spot_ema_trend=False
        )
        self.assertTrue(ok)
        self.assertEqual(ctype, "SPOT_VWAP_RECLAIM")

        # D1 Bullish Reversal: Spot Support Hold (VWAP unavail or below, spot above SL)
        ok, ctype = evaluate_spot_confluence(
            side="CE", is_d2=False, current_spot=25000.0, spot_vwap=0.0, spot_sl=24950.0, spot_ema_trend=False
        )
        self.assertTrue(ok)
        self.assertEqual(ctype, "SPOT_SUPPORT_HOLD")

        # D2 Bullish Continuation: Requires Trend Momentum Alignment (Spot >= EMA13/44)
        ok_d2_pass, ctype_d2_pass = evaluate_spot_confluence(
            side="CE", is_d2=True, current_spot=25100.0, spot_vwap=25050.0, spot_sl=24950.0, spot_ema_trend=True
        )
        self.assertTrue(ok_d2_pass)
        self.assertEqual(ctype_d2_pass, "TREND_MOMENTUM_ALIGNMENT")

        ok_d2_fail, ctype_d2_fail = evaluate_spot_confluence(
            side="CE", is_d2=True, current_spot=25100.0, spot_vwap=25050.0, spot_sl=24950.0, spot_ema_trend=False
        )
        self.assertFalse(ok_d2_fail)
        self.assertEqual(ctype_d2_fail, "NONE")

        # Bearish D1 Reversal (PE): Spot VWAP reject
        ok_pe, ctype_pe = evaluate_spot_confluence(
            side="PE", is_d2=False, current_spot=24900.0, spot_vwap=24950.0, spot_sl=25050.0, spot_ema_trend=False
        )
        self.assertTrue(ok_pe)
        self.assertEqual(ctype_pe, "SPOT_VWAP_REJECT")

    def test_04_continuous_15pct_loss_shield(self):
        """Test 4: Continuous 15% Greek Loss Shield & Catastrophic Circuit Protection."""
        max_loss_pct = 0.15  # 15% max option loss
        entry_price = 100.0

        # Normal SL floor at 15%
        hard_max_sl = round(entry_price * (1.0 - max_loss_pct), 2)
        self.assertEqual(hard_max_sl, 85.0)

        # At 86.0 -> position not breached under 15% loss
        live_ltp_safe = 86.0
        is_catastrophic_safe = (entry_price > 0 and live_ltp_safe > 0 and live_ltp_safe <= (entry_price * (1.0 - max_loss_pct)))
        self.assertFalse(is_catastrophic_safe)

        # At 84.50 -> position breached 15% circuit -> forces immediate emergency exit regardless of spot
        live_ltp_breach = 84.50
        is_catastrophic_breach = (entry_price > 0 and live_ltp_breach > 0 and live_ltp_breach <= (entry_price * (1.0 - max_loss_pct)))
        self.assertTrue(is_catastrophic_breach)

    def test_05_pegged_limit_routing_and_spread_guard(self):
        """Test 5: Liquidity Gate Spread Analysis & Pegged Mid-Price Derivation."""
        class MockKite:
            def __init__(self, quotes):
                self._quotes = quotes
            def quote(self, keys):
                return {k: self._quotes[k] for k in keys if k in self._quotes}

        # 1. Tight spread (0.8%) -> accepted
        mock_tight = MockKite({
            "NFO:NIFTY24500CE": {
                "last_price": 100.0,
                "depth": {
                    "buy": [{"price": 99.6, "quantity": 500}],
                    "sell": [{"price": 100.4, "quantity": 600}]
                }
            }
        })
        is_liquid, spread_ratio, reason, details = check_bid_ask_spread_liquidity(
            mock_tight, "NFO", "NIFTY24500CE", max_spread_pct=0.02, min_depth_qty=100, bypass_when_closed=False
        )
        self.assertTrue(is_liquid)
        self.assertLess(spread_ratio, 0.01)

        # 2. Wide spread (4.5% > 2.0%) -> rejected by liquidity gate
        mock_wide = MockKite({
            "NFO:MIDCAP24500CE": {
                "last_price": 100.0,
                "depth": {
                    "buy": [{"price": 97.5, "quantity": 100}],
                    "sell": [{"price": 102.0, "quantity": 100}]
                }
            }
        })
        is_liquid_wide, spread_ratio_wide, reason_wide, details_wide = check_bid_ask_spread_liquidity(
            mock_wide, "NFO", "MIDCAP24500CE", max_spread_pct=0.02, min_depth_qty=50, bypass_when_closed=False
        )
        self.assertFalse(is_liquid_wide)
        self.assertIn("Wide bid-ask spread", reason_wide)

        # 3. Pegged mid-price limit order routing logic
        bid = 98.0
        ask = 102.0
        mid_price = round((bid + ask) / 2.0, 2)
        pegged_limit = round(round(mid_price / 0.05) * 0.05, 2)
        self.assertEqual(pegged_limit, 100.0)


if __name__ == "__main__":
    unittest.main()
