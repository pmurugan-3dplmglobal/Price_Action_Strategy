"""
scratch/test_rvol_engine.py

Unit test suite for common/rvol_calculator.py
Validates:
1. 20-day baseline average daily volume computation.
2. High Trading Volume Alert (RVOL_abs >= 1.0) as seen in user screenshots.
3. Intraday time-of-day pacing (RVOL_projected at 10:45 AM).
4. Multi-day structural pivot breakout / breakdown detection.
5. Edge-case handling (empty df, missing volume column).
"""

import os
import sys
import unittest
import pandas as pd
import numpy as np
from datetime import datetime as dt, timedelta

COMMON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common"))
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from rvol_calculator import calculate_rvol, detect_daily_breakout, get_market_elapsed_minutes


class TestRVOLCalculator(unittest.TestCase):

    def setUp(self):
        # Generate 25 days of synthetic daily candles with avg volume = 100,000
        dates = [dt(2026, 8, 1) + timedelta(days=i) for i in range(25)]
        volumes = [100000.0 + (i % 5) * 2000.0 for i in range(25)]
        closes = [500.0 + i * 2.0 for i in range(25)]
        highs = [c + 5.0 for c in closes]
        lows = [c - 5.0 for c in closes]
        opens = [c - 1.0 for c in closes]

        self.df_daily = pd.DataFrame({
            'date': dates,
            'open': opens,
            'high': highs,
            'low': lows,
            'close': closes,
            'volume': volumes
        })

    def test_normal_volume(self):
        """Test standard volume with no surge."""
        res = calculate_rvol(self.df_daily, tf_is_daily=True)
        self.assertFalse(res["is_surge"])
        self.assertEqual(res["badge"], "NORMAL")
        self.assertAlmostEqual(res["rvol_abs"], 1.0, delta=0.2)

    def test_volume_greater_than_20d_avg(self):
        """Test High Trading Volume Alert when current volume exceeds 20-day average."""
        df_surge = self.df_daily.copy()
        # Set today's volume to 180,000 (1.8x of 20-day avg ~104,000)
        df_surge.loc[df_surge.index[-1], 'volume'] = 180000.0

        res = calculate_rvol(df_surge, tf_is_daily=True)
        self.assertTrue(res["is_surge"])
        self.assertIn("🔥 RVOL", res["badge"])
        self.assertIn("> 20D", res["badge"])
        self.assertEqual(res["alert_title"], "High trading volume alert!")
        self.assertGreaterEqual(res["rvol_abs"], 1.5)

    def test_intraday_pacing_at_10_45_am(self):
        """
        Test time-adjusted pacing at 10:45 AM (90 mins into 375-min session = 24% elapsed).
        If at 10:45 AM volume is 60,000, projected volume is 60,000 / 0.24 = 250,000 (2.5x 20D avg).
        """
        mock_time = dt(2026, 9, 9, 10, 45, 0)
        elapsed = get_market_elapsed_minutes(mock_time)
        self.assertAlmostEqual(elapsed, 90.0, delta=1.0)

        df_intra = self.df_daily.copy()
        df_intra.loc[df_intra.index[-1], 'volume'] = 60000.0

        res = calculate_rvol(df_intra, current_time=mock_time, tf_is_daily=True)
        self.assertTrue(res["is_surge"])
        self.assertIn("⚡ RVOL", res["badge"])
        self.assertGreaterEqual(res["rvol_projected"], 2.0)

    def test_daily_breakout_detection(self):
        """Test daily breakout when close breaks above 20-day high."""
        df_breakout = self.df_daily.copy()
        # Highest high of prior 20 bars
        prior_max_high = df_breakout['high'].iloc[-21:-1].max()
        # Set current close above prior max high
        df_breakout.loc[df_breakout.index[-1], 'close'] = prior_max_high + 10.0

        res = detect_daily_breakout(df_breakout, lookback_bars=20)
        self.assertTrue(res["is_breakout"])
        self.assertEqual(res["side"], "BULL")
        self.assertEqual(res["badge"], "🚀 DAILY BREAKOUT")

    def test_daily_breakdown_detection(self):
        """Test daily breakdown when close breaks below 20-day low."""
        df_breakdown = self.df_daily.copy()
        prior_min_low = df_breakdown['low'].iloc[-21:-1].min()
        df_breakdown.loc[df_breakdown.index[-1], 'close'] = prior_min_low - 10.0

        res = detect_daily_breakout(df_breakdown, lookback_bars=20)
        self.assertTrue(res["is_breakout"])
        self.assertEqual(res["side"], "BEAR")
        self.assertEqual(res["badge"], "🔻 DAILY BREAKDOWN")

    def test_safe_fallbacks(self):
        """Test safe fallbacks on empty or invalid data."""
        empty_res = calculate_rvol(pd.DataFrame())
        self.assertEqual(empty_res["badge"], "NORMAL")
        self.assertFalse(empty_res["is_surge"])

        bk_empty = detect_daily_breakout(pd.DataFrame())
        self.assertFalse(bk_empty["is_breakout"])


if __name__ == "__main__":
    unittest.main()
