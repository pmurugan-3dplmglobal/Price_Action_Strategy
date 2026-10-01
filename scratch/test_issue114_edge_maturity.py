import os
import sys
import unittest
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from resolve import check_spot_anchor_confirmation, evaluate_spot_confluence

class TestIssue114EdgeMaturity(unittest.TestCase):
    def setUp(self):
        # Create base test candles
        dates = pd.date_range("2026-10-01 09:15", periods=20, freq="15min")
        self.base_df = pd.DataFrame({
            "date": dates,
            "open": [100.0 + i for i in range(20)],
            "high": [102.0 + i for i in range(20)],
            "low": [99.0 + i for i in range(20)],
            "close": [101.0 + i for i in range(20)],
            "volume": [10000 + i * 500 for i in range(20)]
        })

    def test_runner_vwap_acceptance_ce(self):
        """Verify strong breakout stocks accepted above VWAP receive valid confluence without requiring a pullback wick."""
        df_runner = self.base_df.copy()
        # Last candle closes strongly above VWAP
        current_spot = 125.0
        spot_vwap = 120.0
        df_runner.iloc[-1, df_runner.columns.get_loc("open")] = 123.0
        df_runner.iloc[-1, df_runner.columns.get_loc("close")] = 125.0
        df_runner.iloc[-1, df_runner.columns.get_loc("high")] = 126.0
        df_runner.iloc[-1, df_runner.columns.get_loc("low")] = 122.5 # Does not test VWAP (120.0)

        has_conf, conf_type = evaluate_spot_confluence(
            side="CE", is_d2=False, current_spot=current_spot, spot_vwap=spot_vwap,
            spot_sl=118.0, spot_ema_trend=True, df_spot=df_runner
        )
        self.assertTrue(has_conf, "Strong runner above VWAP should have confluence")
        self.assertEqual(conf_type, "SPOT_TREND_VWAP_ACCEPTANCE")

    def test_runner_vwap_rejection_pe(self):
        """Verify strong breakdown stocks accepted below VWAP receive valid PE confluence."""
        df_breakdown = self.base_df.copy()
        current_spot = 95.0
        spot_vwap = 100.0
        df_breakdown.iloc[-1, df_breakdown.columns.get_loc("open")] = 97.0
        df_breakdown.iloc[-1, df_breakdown.columns.get_loc("close")] = 95.0
        df_breakdown.iloc[-1, df_breakdown.columns.get_loc("high")] = 97.5 # Does not test VWAP (100.0)
        df_breakdown.iloc[-1, df_breakdown.columns.get_loc("low")] = 94.0

        has_conf, conf_type = evaluate_spot_confluence(
            side="PE", is_d2=False, current_spot=current_spot, spot_vwap=spot_vwap,
            spot_sl=102.0, spot_ema_trend=True, df_spot=df_breakdown
        )
        self.assertTrue(has_conf, "Strong breakdown runner below VWAP should have PE confluence")
        self.assertEqual(conf_type, "SPOT_TREND_VWAP_REJECTION")

    def test_anchor_invalidation_guard_ce(self):
        """Verify that an anchor formed previously but breached by subsequent candles or current spot is rejected."""
        df_test = pd.DataFrame({
            "date": pd.date_range("2026-10-01 09:15", periods=15, freq="30min"),
            "open": [100.0] * 15,
            "high": [105.0] * 15,
            "low": [95.0] * 15,
            "close": [102.0] * 15,
            "volume": [50000] * 15
        })
        # Setup candle -6 as bullish engulfing
        # Bearish candle at -7: open 105, close 98
        df_test.iloc[-7, df_test.columns.get_loc("open")] = 105.0
        df_test.iloc[-7, df_test.columns.get_loc("close")] = 98.0
        # Bullish engulfing at -6: open 97, close 106, low 96
        df_test.iloc[-6, df_test.columns.get_loc("open")] = 97.0
        df_test.iloc[-6, df_test.columns.get_loc("close")] = 106.0
        df_test.iloc[-6, df_test.columns.get_loc("high")] = 107.0
        df_test.iloc[-6, df_test.columns.get_loc("low")] = 96.0

        # Now simulate subsequent collapse at candle -2: close falls to 92.0 (below anchor low 96.0)
        df_test.iloc[-2, df_test.columns.get_loc("open")] = 95.0
        df_test.iloc[-2, df_test.columns.get_loc("close")] = 92.0
        df_test.iloc[-2, df_test.columns.get_loc("low")] = 91.0
        df_test.iloc[-1, df_test.columns.get_loc("close")] = 93.0

        is_conf, anc_name = check_spot_anchor_confirmation(df_test, "CE", spot_vwap=100.0)
        # Anchor was invalidated by candle -2 closing at 92 < 96!
        self.assertFalse(is_conf, "Invalidated anchor must not confirm CE trade")
        self.assertNotEqual(anc_name, "SPOT_BULL_ENGULFING")

if __name__ == "__main__":
    unittest.main()
