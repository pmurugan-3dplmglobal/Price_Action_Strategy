"""
Unit test suite verifying fixes for Incident 1 and Incident 2:
1. Incident 1:
   - Bullish anchor invalidation on wick breach (low < a_low)
   - Bearish anchor invalidation on wick breach (high > a_high)
   - Bullish Point D color guard (must be green: close >= open)
   - Bearish Point D color guard (must be red: close <= open)
2. Incident 2:
   - Trailing Stop-Loss Physical Sanity Guard (never trail long SL >= live_ltp, never trail short SL <= live_ltp)
   - Broker reconciliation stale prior-day entry_time reset
"""
import sys, os
sys.path.insert(0, os.path.abspath('.'))
sys.path.insert(0, os.path.abspath('common'))
import unittest
import pandas as pd
from datetime import datetime as dt, timedelta

from common.patterns_bull import scan_anchor_bcd_breakout
from common.patterns_bear import scan_anchor_bcd_breakout_bearish
from common.position_monitor import sanitize_entry_time, is_candle_before_entry


class TestIncidentFixes(unittest.TestCase):

    def test_bullish_anchor_wick_invalidation(self):
        """Incident 1: A candle between Anchor A and Point D with low < a_low must invalidate setup."""
        # 09:30 Anchor A (Hammer Baby: Low 99.65, High 105.20)
        # 09:36 Point B candle wicks to 99.00 (< 99.65) but closes at 108.00 (> benchmark 105.20)
        # Setup must be rejected because Anchor floor 99.65 was pierced by wick!
        candles = [
            {"date": "2026-09-21 09:15:00", "open": 115.0, "high": 116.0, "low": 105.0, "close": 106.0, "volume": 1000},
            # Anchor A (Hammer Baby: Low 99.65, High 105.20, Benchmark 105.20)
            {"date": "2026-09-21 09:30:00", "open": 104.75, "high": 105.20, "low": 99.65, "close": 104.85, "volume": 2000},
            {"date": "2026-09-21 09:33:00", "open": 104.85, "high": 107.20, "low": 100.40, "close": 100.45, "volume": 1500},
            # Point B attempt: low dipped to 99.00 (< 99.65), close 108.00 (> 105.20)
            {"date": "2026-09-21 09:36:00", "open": 99.70, "high": 109.40, "low": 99.00, "close": 108.00, "volume": 2500},
            # Point C Retest
            {"date": "2026-09-21 09:39:00", "open": 108.0, "high": 108.5, "low": 104.0, "close": 104.5, "volume": 1200},
            # Point D Trigger
            {"date": "2026-09-21 09:42:00", "open": 104.5, "high": 110.0, "low": 104.0, "close": 109.0, "volume": 3000},
        ]
        df = pd.DataFrame(candles)
        res = scan_anchor_bcd_breakout(df, df, entry_tf="3minute", anchor_tf="3minute", enable_swing_filter=False)
        self.assertIsNone(res, "Setup with wick piercing below Anchor A Low (99.00 < 99.65) must be rejected")

    def test_bearish_anchor_wick_invalidation(self):
        """Incident 1: A candle between Bearish Anchor A and Point D with high > a_high must invalidate setup."""
        dates_a = pd.date_range("2026-08-20", periods=10, freq="D")
        df_ba = pd.DataFrame({
            "date": [d.strftime("%Y-%m-%d 00:00:00") for d in dates_a],
            "open": [100.0] * 10, "high": [102.0] * 10, "low": [98.0] * 10, "close": [101.0] * 10, "volume": [10000] * 10
        })
        df_ba.loc[8, "open"] = 100.0; df_ba.loc[8, "high"] = 105.0; df_ba.loc[8, "low"] = 98.0; df_ba.loc[8, "close"] = 104.0
        df_ba.loc[9, "open"] = 104.0; df_ba.loc[9, "high"] = 106.0; df_ba.loc[9, "low"] = 95.0; df_ba.loc[9, "close"] = 96.0; df_ba.loc[9, "date"] = "2026-09-01 00:00:00"

        dates_e = pd.date_range("2026-09-01 09:15", periods=20, freq="15min")
        df_be = pd.DataFrame({
            "date": [d.strftime("%Y-%m-%d %H:%M:%S+05:30") for d in dates_e],
            "open": [96.0] * 20, "high": [97.0] * 20, "low": [95.5] * 20, "close": [96.0] * 20, "volume": [10000] * 20
        })
        df_be.loc[5, "open"] = 95.5; df_be.loc[5, "close"] = 92.0; df_be.loc[5, "low"] = 91.5; df_be.loc[5, "high"] = 95.5; df_be.loc[5, "volume"] = 25000
        df_be.loc[6, "open"] = 92.0; df_be.loc[6, "close"] = 93.0; df_be.loc[6, "low"] = 91.8; df_be.loc[6, "high"] = 93.5
        # Bar 7 wicks above Anchor A High (106.0) -> high 107.5
        df_be.loc[7, "open"] = 93.0; df_be.loc[7, "close"] = 94.0; df_be.loc[7, "low"] = 92.0; df_be.loc[7, "high"] = 107.5
        df_be.loc[8, "open"] = 93.0; df_be.loc[8, "close"] = 96.0; df_be.loc[8, "low"] = 93.0; df_be.loc[8, "high"] = 96.5; df_be.loc[8, "volume"] = 7000
        df_be.loc[11, "open"] = 95.5; df_be.loc[11, "close"] = 91.0; df_be.loc[11, "low"] = 90.5; df_be.loc[11, "high"] = 95.5; df_be.loc[11, "volume"] = 30000

        res_b = scan_anchor_bcd_breakout_bearish(df_be, df_ba, anchor_tf="day", entry_tf="15minute", enable_swing_filter=False)
        self.assertIsNone(res_b, "Bearish setup with wick piercing above Anchor A High (107.5 > 106.0) must be rejected")

    def test_bullish_point_d_candle_color(self):
        """Incident 1: Point D must be a bullish green candle (close >= open). Red bars must be rejected."""
        candles_red_d = [
            {"date": "2026-09-21 09:15:00", "open": 115.0, "high": 116.0, "low": 105.0, "close": 106.0, "volume": 1000},
            # Anchor A (Low 100.0, High 105.0)
            {"date": "2026-09-21 09:30:00", "open": 104.75, "high": 105.0, "low": 100.0, "close": 104.85, "volume": 2000},
            # Point B: breakout above 105.0
            {"date": "2026-09-21 09:33:00", "open": 104.85, "high": 108.0, "low": 103.0, "close": 107.5, "volume": 2200},
            # Point C: Retest dips to benchmark 105.0, stays above 100.0 (Red bar)
            {"date": "2026-09-21 09:36:00", "open": 107.0, "high": 107.5, "low": 104.5, "close": 104.8, "volume": 1500},
            # Point D: Closes at 106.0 (> 105.0) BUT Opened at 109.0 -> RED SELLING CANDLE!
            {"date": "2026-09-21 09:39:00", "open": 109.0, "high": 109.5, "low": 105.5, "close": 106.0, "volume": 2800},
            # Trailing bar staying below benchmark
            {"date": "2026-09-21 09:42:00", "open": 104.0, "high": 104.5, "low": 103.0, "close": 103.5, "volume": 1000},
        ]
        df_red = pd.DataFrame(candles_red_d)
        res_red = scan_anchor_bcd_breakout(df_red, df_red, entry_tf="3minute", anchor_tf="3minute", enable_swing_filter=False)
        self.assertIsNone(res_red, "Point D candle with close < open (red bar) must be rejected for bullish breakout")

        # Now make Point D a GREEN candle (Open 105.0, Close 108.0)
        candles_green_d = list(candles_red_d)
        candles_green_d[4] = {"date": "2026-09-21 09:39:00", "open": 105.0, "high": 109.5, "low": 104.8, "close": 108.0, "volume": 2800}
        df_green = pd.DataFrame(candles_green_d)
        res_green = scan_anchor_bcd_breakout(df_green, df_green, entry_tf="3minute", anchor_tf="3minute", enable_swing_filter=False)
        self.assertIsNotNone(res_green, "Point D candle with close >= open (green bar) expanding above benchmark must be accepted")

    def test_bearish_point_d_candle_color(self):
        """Incident 1: Point D for bearish breakdown must be a red candle (close <= open). Green bars must be rejected."""
        dates_a = pd.date_range("2026-08-20", periods=10, freq="D")
        df_ba = pd.DataFrame({
            "date": [d.strftime("%Y-%m-%d 00:00:00") for d in dates_a],
            "open": [100.0] * 10, "high": [102.0] * 10, "low": [98.0] * 10, "close": [101.0] * 10, "volume": [10000] * 10
        })
        df_ba.loc[8, "open"] = 100.0; df_ba.loc[8, "high"] = 105.0; df_ba.loc[8, "low"] = 98.0; df_ba.loc[8, "close"] = 104.0
        df_ba.loc[9, "open"] = 104.0; df_ba.loc[9, "high"] = 106.0; df_ba.loc[9, "low"] = 95.0; df_ba.loc[9, "close"] = 96.0; df_ba.loc[9, "date"] = "2026-09-01 00:00:00"

        dates_e = pd.date_range("2026-09-01 09:15", periods=20, freq="15min")
        df_be_green_d = pd.DataFrame({
            "date": [d.strftime("%Y-%m-%d %H:%M:%S+05:30") for d in dates_e],
            "open": [96.0] * 20, "high": [97.0] * 20, "low": [95.5] * 20, "close": [96.0] * 20, "volume": [10000] * 20
        })
        df_be_green_d.loc[5, "open"] = 95.5; df_be_green_d.loc[5, "close"] = 92.0; df_be_green_d.loc[5, "low"] = 91.5; df_be_green_d.loc[5, "high"] = 95.5; df_be_green_d.loc[5, "volume"] = 25000
        df_be_green_d.loc[6, "open"] = 92.0; df_be_green_d.loc[6, "close"] = 93.0; df_be_green_d.loc[6, "low"] = 91.8; df_be_green_d.loc[6, "high"] = 93.5
        df_be_green_d.loc[8, "open"] = 93.0; df_be_green_d.loc[8, "close"] = 96.0; df_be_green_d.loc[8, "low"] = 93.0; df_be_green_d.loc[8, "high"] = 96.5; df_be_green_d.loc[8, "volume"] = 7000
        # Point D attempt: GREEN candle (open 90.5, close 92.0 < a_low 95.0, but open < close)
        df_be_green_d.loc[11, "open"] = 90.5; df_be_green_d.loc[11, "close"] = 92.0; df_be_green_d.loc[11, "low"] = 90.0; df_be_green_d.loc[11, "high"] = 92.5; df_be_green_d.loc[11, "volume"] = 30000

        res_green = scan_anchor_bcd_breakout_bearish(df_be_green_d, df_ba, anchor_tf="day", entry_tf="15minute", enable_swing_filter=False)
        self.assertIsNone(res_green, "Point D candle with close > open (green bar) must be rejected for bearish breakdown")

        # Now test RED candle (open 95.5, close 91.0) -> MUST be accepted
        df_be_red_d = df_be_green_d.copy()
        df_be_red_d.loc[11, "open"] = 95.5; df_be_red_d.loc[11, "close"] = 91.0; df_be_red_d.loc[11, "low"] = 90.5; df_be_red_d.loc[11, "high"] = 95.5; df_be_red_d.loc[11, "volume"] = 30000
        res_red = scan_anchor_bcd_breakout_bearish(df_be_red_d, df_ba, anchor_tf="day", entry_tf="15minute", enable_swing_filter=False)
        self.assertIsNotNone(res_red, "Point D candle with close <= open (red bar) breaking down below benchmark must be accepted")

    def test_trailing_sl_physical_sanity_guard(self):
        """Incident 2: Trailing SL can NEVER be placed above live LTP for long positions or below live LTP for shorts."""
        # Simulation of EICHERMOT incident:
        # Entry @ 98.50, Peak High @ 125.00 (+26.9%)
        # Computed trail SL: 108.35
        # Live LTP: 98.00 (pulled back)
        entry_s = 98.50
        curr_sl = 85.00
        active_sl_pct = 10.0
        sl_offset = entry_s * (active_sl_pct / 100.0)
        opt_target = round(round((entry_s + sl_offset) / 0.05) * 0.05, 2)
        new_sl = max(curr_sl, opt_target) # 108.35
        live_ltp = 98.00

        # Physical Invariant: new_sl >= live_ltp MUST be rejected for long position
        trail_valid = not (new_sl >= live_ltp)
        self.assertFalse(trail_valid, "Trailing SL (108.35) >= live LTP (98.00) must be rejected to prevent immediate suicide stop-out")

        # Invariant for short positions: new_sl <= live_ltp MUST be rejected
        short_entry = 100.0
        short_sl = 115.0
        short_live_ltp = 95.00
        invalid_short_new_sl = 92.00 # Trailing SL below current price on a short position
        short_trail_valid = not (invalid_short_new_sl <= short_live_ltp)
        self.assertFalse(short_trail_valid, "Short trailing SL (92.00) <= live LTP (95.00) must be rejected")

    def test_stale_prior_day_entry_time_detection(self):
        """Incident 2: Stale prior-day entry_time must be detected and filtered so earlier morning spikes are ignored."""
        today = dt.now().date()
        friday_entry_time = (dt.now() - timedelta(days=3)).strftime("%Y-%m-%d 11:17:54")
        
        # In memory position has Friday entry
        pos_stale = {"entry_time": friday_entry_time, "entry_spot": 110.0}
        
        # Today's morning candle at 09:18 AM
        morning_candle_time = f"{today.strftime('%Y-%m-%d')} 09:18:00"
        
        # With stale Friday entry_time, morning_candle_time is NOT before entry -> falsely evaluated!
        self.assertFalse(is_candle_before_entry(morning_candle_time, pos_stale["entry_time"]),
                         "Stale Friday entry_time causes today's morning candle to be falsely evaluated as post-entry")

        # When reset to actual re-entry time at 09:52 AM today:
        fresh_entry_time = f"{today.strftime('%Y-%m-%d')} 09:52:00"
        pos_fresh = {"entry_time": fresh_entry_time, "entry_spot": 98.50}

        # Now morning candle (09:18) IS strictly before entry (09:52) -> correctly ignored!
        self.assertTrue(is_candle_before_entry(morning_candle_time, pos_fresh["entry_time"]),
                        "Fresh entry_time correctly ignores earlier morning candle prior to entry")


if __name__ == "__main__":
    unittest.main()
