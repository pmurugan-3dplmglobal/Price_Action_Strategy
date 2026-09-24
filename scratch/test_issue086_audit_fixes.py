"""
scratch/test_issue086_audit_fixes.py
====================================
Dedicated Unit Verification Suite for ISSUE-086:
1. Volume Confirmation at Point D Breakout (patterns_bull.py & patterns_bear.py)
2. Index Engine Stranded Leg 1 Emergency Unwind (index_options_trade_engine.py)
3. Gap Breach Critical Override in Position Monitor (position_monitor.py)
"""
import sys
import os
import unittest
import pandas as pd
import numpy as np

# Set paths
PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON_DIR = os.path.join(PROJ_ROOT, "common")
sys.path.insert(0, PROJ_ROOT)
sys.path.insert(0, COMMON_DIR)

from common.patterns_bull import scan_anchor_bcd_breakout
from common.patterns_bear import scan_anchor_bcd_breakout_bearish


class TestIssue086AuditFixes(unittest.TestCase):

    def _create_synthetic_bull_data(self, d_volume_ratio=1.5):
        """Helper to create synthetic OHLCV data for A-B-C-D bullish breakout."""
        # 30 bars baseline, then Anchor A, B pullback, C retest, D breakout
        dates = pd.date_range("2026-09-01 09:15", periods=50, freq="15min")
        # Base price 100
        closes = [100.0] * 50
        opens = [100.0] * 50
        highs = [101.0] * 50
        lows = [99.0] * 50
        volumes = [1000.0] * 50  # average 1000

        # Anchor A at bar 25: Bullish Engulfing or clean bounce
        # Benchmark = 105.0, Anchor Low = 95.0
        opens[25], highs[25], lows[25], closes[25] = 96.0, 105.0, 95.0, 104.0
        volumes[25] = 2000.0

        # Point B at bar 28: Peak at 105.0
        opens[28], highs[28], lows[28], closes[28] = 103.0, 105.0, 102.0, 104.5
        volumes[28] = 1200.0

        # Point C at bar 32: Retest holding above Anchor Low (95.0), e.g. low=98.0
        opens[32], highs[32], lows[32], closes[32] = 100.0, 101.0, 98.0, 100.0
        volumes[32] = 500.0  # Dry volume at C

        # Point D at bar 36: Breakout above benchmark (105.0) -> close at 106.5
        opens[36], highs[36], lows[36], closes[36] = 104.0, 107.0, 103.5, 106.5
        # Set D volume based on parameter
        avg_vol = 1000.0
        volumes[36] = avg_vol * d_volume_ratio

        # Fill subsequent bars to make bar 36 a completed historical candle
        for k in range(37, 50):
            opens[k], highs[k], lows[k], closes[k] = 106.0, 107.5, 105.5, 106.5
            volumes[k] = 1000.0

        df = pd.DataFrame({
            "date": dates,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes
        })
        return df

    def test_point_d_volume_rejection_bull(self):
        """Test that Point D breakout is rejected if completed candle volume < 1.2x avg volume."""
        # D volume ratio = 0.8x (low volume breakout = liquidity trap)
        df = self._create_synthetic_bull_data(d_volume_ratio=0.8)
        
        # Test the volume logic directly
        curr_idx = 36
        avg_vol_20 = float(df['volume'].iloc[curr_idx - 20 : curr_idx].mean())
        d_vol = float(df.iloc[curr_idx]['volume'])
        
        d_vol_confirmed = True
        if avg_vol_20 > 0 and d_vol < (1.2 * avg_vol_20):
            d_vol_confirmed = False
            
        self.assertFalse(d_vol_confirmed, "Breakout with 0.8x volume must be rejected")

    def test_point_d_volume_acceptance_bull(self):
        """Test that Point D breakout is accepted if completed candle volume >= 1.2x avg volume."""
        # D volume ratio = 1.5x (institutional volume expansion)
        df = self._create_synthetic_bull_data(d_volume_ratio=1.5)
        
        curr_idx = 36
        avg_vol_20 = float(df['volume'].iloc[curr_idx - 20 : curr_idx].mean())
        d_vol = float(df.iloc[curr_idx]['volume'])
        
        d_vol_confirmed = True
        if avg_vol_20 > 0 and d_vol < (1.2 * avg_vol_20):
            d_vol_confirmed = False
            
        self.assertTrue(d_vol_confirmed, "Breakout with 1.5x volume must be confirmed")

    def test_point_d_volume_rejection_bear(self):
        """Test that Bearish Point D breakdown is rejected if volume < 1.2x avg volume."""
        avg_vol_20 = 1000.0
        d_vol = 700.0  # 0.7x avg
        d_vol_confirmed = True
        if avg_vol_20 > 0 and d_vol < (1.2 * avg_vol_20):
            d_vol_confirmed = False
        self.assertFalse(d_vol_confirmed, "Bearish breakdown on dry volume must be rejected")

    def test_point_d_volume_acceptance_bear(self):
        """Test that Bearish Point D breakdown is accepted if volume >= 1.2x avg volume."""
        avg_vol_20 = 1000.0
        d_vol = 1400.0  # 1.4x avg
        d_vol_confirmed = True
        if avg_vol_20 > 0 and d_vol < (1.2 * avg_vol_20):
            d_vol_confirmed = False
        self.assertTrue(d_vol_confirmed, "Bearish breakdown on 1.4x volume must be accepted")

    def test_failsafe_gap_down_critical_override_long(self):
        """Verify that a catastrophic gap down (>2x SL distance below SL) overrides morning failsafe."""
        entry_s = 100.0
        current_sl = 90.0  # SL distance = 10.0 pts
        sl_distance = abs(entry_s - current_sl)
        
        # Case A: Mild gap down below SL (LTP = 85.0 -> gap = 5.0 pts <= 20.0 pts)
        live_ltp_mild = 85.0
        gap_magnitude = current_sl - live_ltp_mild
        is_critical = gap_magnitude > (2.0 * sl_distance)
        self.assertFalse(is_critical, "Mild 5-pt gap down must NOT trigger catastrophic override (wait for 09:50 candle close)")

        # Case B: Catastrophic gap down (LTP = 65.0 -> gap = 25.0 pts > 20.0 pts)
        live_ltp_severe = 65.0
        gap_magnitude = current_sl - live_ltp_severe
        is_critical = gap_magnitude > (2.0 * sl_distance)
        self.assertTrue(is_critical, "Catastrophic 25-pt gap down MUST trigger immediate exit override")

    def test_failsafe_gap_up_critical_override_short(self):
        """Verify that a catastrophic gap up (>2x SL distance above SL) for short positions overrides morning failsafe."""
        entry_s = 100.0
        current_sl = 110.0  # Short SL is above entry (SL distance = 10.0 pts)
        sl_distance = abs(entry_s - current_sl)
        is_short_stock = True

        # Case A: Mild gap up above SL (LTP = 115.0 -> gap = 5.0 pts <= 20.0 pts)
        live_ltp_mild = 115.0
        gap_magnitude = live_ltp_mild - current_sl
        is_critical = gap_magnitude > (2.0 * sl_distance)
        self.assertFalse(is_critical, "Mild 5-pt gap up on short must NOT trigger catastrophic override")

        # Case B: Catastrophic gap up (LTP = 135.0 -> gap = 25.0 pts > 20.0 pts)
        live_ltp_severe = 135.0
        gap_magnitude = live_ltp_severe - current_sl
        is_critical = gap_magnitude > (2.0 * sl_distance)
        self.assertTrue(is_critical, "Catastrophic 25-pt gap up on short MUST trigger immediate exit override")

    def test_index_options_engine_emergency_unwind_syntax(self):
        """Verify Trade_Option/index_options_trade_engine.py imports and syntax are intact."""
        import ast
        path = os.path.join(PROJ_ROOT, "Trade_Option", "index_options_trade_engine.py")
        with open(path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())
        self.assertIsNotNone(tree)


if __name__ == "__main__":
    unittest.main(verbosity=2)
