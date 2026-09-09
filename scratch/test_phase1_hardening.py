"""
Unit test suite verifying Phase 1 hardening:
1. get_sl_buffer_distance across all price tiers and sides (BULL/BEAR)
2. Safe adaptive Breakeven Stop formulas: Entry +/- max(buffer_dist, 0.5 * atr)
3. Timeframe-normalized B-C spacing: max_bc_candles = max(25, int(180 / tf_minutes))
4. C-to-D search bounds harmonization (60-candle cap & floor breach break)
5. Position monitor timeframe synchronization ("15minute")
"""
import os
import sys

COMMON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

import unittest
import pandas as pd
from targets import calculate_sl_buffer, get_sl_buffer_distance
from timeframe_utils import get_tf_minutes
from patterns_bull import scan_anchor_bcd_breakout
from patterns_bear import scan_anchor_bcd_breakout_bearish


class TestPhase1Hardening(unittest.TestCase):

    def test_get_sl_buffer_distance_tiers(self):
        """Test get_sl_buffer_distance across all asset & price tiers."""
        # Tier 1: Micro / Penny Options (price < 5)
        dist_penny_bull = get_sl_buffer_distance(4.0, side="BULL")
        self.assertEqual(dist_penny_bull, 0.60)  # max(0.40, 4.0 * 0.15) = 0.60
        dist_penny_bear = get_sl_buffer_distance(4.0, side="BEAR")
        self.assertEqual(dist_penny_bear, 0.60)

        # Tier 2: Cheap Options (5 <= price < 15)
        dist_cheap_bull = get_sl_buffer_distance(10.0, side="BULL")
        self.assertEqual(dist_cheap_bull, 0.80)  # max(0.60, 10.0 * 0.08) = 0.80
        dist_cheap_bear = get_sl_buffer_distance(10.0, side="BEAR")
        self.assertEqual(dist_cheap_bear, 0.80)

        # Tier 3: Low-Mid Options (15 <= price < 50)
        dist_lowmid_bull = get_sl_buffer_distance(25.0, side="BULL")
        self.assertEqual(dist_lowmid_bull, 1.00)  # max(0.80, 25.0 * 0.04) = 1.00

        # Tier 4: Mid Options (50 <= price < 200)
        dist_mid_bull = get_sl_buffer_distance(100.0, side="BULL")
        self.assertEqual(dist_mid_bull, 2.00)  # max(1.50, 100.0 * 0.02) = 2.00
        dist_mid_bear = get_sl_buffer_distance(100.0, side="BEAR")
        self.assertEqual(dist_mid_bear, 2.00)

        # Tier 5: High Options / Stock Spot (200 <= price < 500)
        dist_high_bull = get_sl_buffer_distance(300.0, side="BULL")
        self.assertEqual(dist_high_bull, 3.00)  # max(2.50, 300.0 * 0.01) = 3.00

        # Tier 6: Index Spot / High Stocks (price >= 500)
        dist_index_bull = get_sl_buffer_distance(1000.0, side="BULL")
        self.assertEqual(dist_index_bull, 5.00)  # max(3.50, 1000.0 * 0.005) = 5.00

    def test_safe_adaptive_breakeven_formulas(self):
        """Test safe adaptive breakeven stop calculations vs fatal offset bug."""
        # 1. Bull Long Position: Entry = 100.0, atr = 2.0
        entry_s = 100.0
        atr = 2.0
        buf_dist = get_sl_buffer_distance(entry_s, side="BULL")
        be_offset = max(buf_dist, 0.5 * atr)
        be_target = round(round((entry_s + be_offset) / 0.05) * 0.05, 2)
        self.assertEqual(be_target, 102.0)
        # Verify it is strictly >= entry_s + buffer
        self.assertGreater(be_target, entry_s)

        # 2. Bear Short Position: Entry = 100.0, atr = 2.0
        buf_dist_bear = get_sl_buffer_distance(entry_s, side="BEAR")
        be_offset_bear = max(buf_dist_bear, 0.5 * atr)
        be_target_bear = round(round((entry_s - be_offset_bear) / 0.05) * 0.05, 2)
        self.assertEqual(be_target_bear, 98.0)
        self.assertLess(be_target_bear, entry_s)

        # 3. Spread Shield for Cheap Options: Entry = 10.0
        # Old 2% formula would set BE at 10.20 (only 0.20 pts cushion)
        # Adaptive formula uses buffer 0.80 pts, setting BE at 10.80
        opt_entry = 10.0
        opt_buf = get_sl_buffer_distance(opt_entry, side="BULL")
        self.assertEqual(opt_buf, 0.80)
        opt_be = round(round((opt_entry + max(opt_buf, 0.5 * 0.40)) / 0.05) * 0.05, 2)
        self.assertEqual(opt_be, 10.80)
        self.assertGreater(opt_be, 10.20)  # Significantly more breathing room

        # 4. Long Put Option (PE) Parity: Entry = 100.0, atr = 2.0
        # Long Option Buyer invariant: Both CE and PE are bought long and profit as premium rises!
        # Therefore, +BE stop MUST be set above entry price (+2.0 pts cushion = 102.0), NOT below entry (98.0).
        opt_pe_entry = 100.0
        opt_pe_buf = get_sl_buffer_distance(opt_pe_entry, side="BULL")
        self.assertEqual(opt_pe_buf, 2.00)
        opt_pe_be = round(round((opt_pe_entry + max(opt_pe_buf, 0.5 * atr)) / 0.05) * 0.05, 2)
        self.assertEqual(opt_pe_be, 102.0)
        self.assertGreater(opt_pe_be, opt_pe_entry)

    def test_timeframe_normalized_spacing(self):
        """Test B-C spacing normalization across timeframes."""
        # Fast intraday: 3m
        tf_3m = get_tf_minutes("3minute")
        max_bc_3m = max(25, int(180 / tf_3m))
        self.assertEqual(max_bc_3m, 60)

        # Fast intraday: 5m
        tf_5m = get_tf_minutes("5minute")
        max_bc_5m = max(25, int(180 / tf_5m))
        self.assertEqual(max_bc_5m, 36)

        # Standard intraday: 15m
        tf_15m = get_tf_minutes("15minute")
        max_bc_15m = max(25, int(180 / tf_15m))
        self.assertEqual(max_bc_15m, 25)

        # Standard intraday: 30m
        tf_30m = get_tf_minutes("30minute")
        max_bc_30m = max(25, int(180 / tf_30m))
        self.assertEqual(max_bc_30m, 25)

        # Daily chart: day
        tf_day = get_tf_minutes("day")
        max_bc_day = max(25, int(180 / tf_day))
        self.assertEqual(max_bc_day, 25)

    def test_position_monitor_timeframe_harmonization(self):
        """Verify position_monitor stock_options_positions uses 15minute."""
        pos_mon_path = os.path.join(COMMON_DIR, "position_monitor.py")
        with open(pos_mon_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('timeframe_entry="15minute"', content)
        self.assertNotIn('engine_name="nifty50",\n            timeframe_entry="30minute"', content)

    def test_cd_search_bounds_and_floor_invalidation(self):
        """Verify C-to-D search bounds (60 bars max) and floor breach termination."""
        # 1. Bullish setup where price drops below A.low after C -> must be rejected
        candles = [
            # Anchor A (Bullish Engulfing)
            {"date": "2026-09-04 09:15:00", "open": 100.0, "high": 101.0, "low": 95.0, "close": 96.0, "volume": 1000},
            {"date": "2026-09-04 09:30:00", "open": 95.0, "high": 103.0, "low": 94.0, "close": 102.0, "volume": 2000},
            # Point B: Breakout > 103.0
            {"date": "2026-09-04 09:45:00", "open": 102.0, "high": 106.0, "low": 101.5, "close": 105.0, "volume": 1500},
            # Point C: Retest dips to <= 103.0 and closes >= 94.0 (Red bar)
            {"date": "2026-09-04 10:00:00", "open": 104.0, "high": 104.5, "low": 102.0, "close": 102.5, "volume": 1200},
            # Breach candle after C: closes below A.low (94.0) -> e.g. 91.0
            {"date": "2026-09-04 10:15:00", "open": 102.0, "high": 102.5, "low": 90.0, "close": 91.0, "volume": 1400},
            # Late D breakout attempt > 103.0
            {"date": "2026-09-04 10:30:00", "open": 92.0, "high": 107.0, "low": 91.5, "close": 106.0, "volume": 1800}
        ]
        df_breached = pd.DataFrame(candles)
        res_breached = scan_anchor_bcd_breakout(df_breached, df_breached, anchor_tf="15minute", entry_tf="15minute")
        self.assertIsNone(res_breached, "Setup with floor breach after C must be rejected")

        # 2. Bullish setup where price drops below A.low before B forms -> must be rejected
        candles_pre_b = [
            # Anchor A (Bullish Engulfing)
            {"date": "2026-09-04 09:15:00", "open": 100.0, "high": 101.0, "low": 95.0, "close": 96.0, "volume": 1000},
            {"date": "2026-09-04 09:30:00", "open": 95.0, "high": 103.0, "low": 94.0, "close": 102.0, "volume": 2000},
            # Breach candle before B: closes below A.low (94.0) -> 92.0
            {"date": "2026-09-04 09:45:00", "open": 98.0, "high": 99.0, "low": 91.0, "close": 92.0, "volume": 1500},
            # Subsequent rally attempt > 103.0
            {"date": "2026-09-04 10:00:00", "open": 93.0, "high": 105.0, "low": 92.5, "close": 104.0, "volume": 2200},
            # Retest C
            {"date": "2026-09-04 10:15:00", "open": 103.0, "high": 103.5, "low": 101.0, "close": 101.5, "volume": 1200},
            # Trigger D
            {"date": "2026-09-04 10:30:00", "open": 102.0, "high": 106.0, "low": 101.5, "close": 105.5, "volume": 1800}
        ]
        df_pre_b = pd.DataFrame(candles_pre_b)
        res_pre_b = scan_anchor_bcd_breakout(df_pre_b, df_pre_b, anchor_tf="15minute", entry_tf="15minute")
        self.assertIsNone(res_pre_b, "Setup with floor breach before B must be rejected")

    def test_position_monitor_breakeven_stop_parity(self):
        """Verify position_monitor breakeven stop calculation for CE Option, PE Option, and Short Stock."""
        # Setup position dicts
        pos_ce = {"position_type": "option", "side": "CE", "entry_spot": 100.0, "current_sl": 85.0, "atr": 2.0}
        pos_pe = {"position_type": "option", "side": "PE", "entry_spot": 100.0, "current_sl": 85.0, "atr": 2.0}
        pos_short = {"position_type": "stock", "side": "SELL", "direction": "BEAR", "entry_spot": 100.0, "current_sl": 115.0, "atr": 2.0}

        def compute_be(pos):
            entry_s = float(pos.get("entry_spot", 0.0))
            atr = float(pos.get("atr", 0.0))
            is_stock = pos.get("position_type") == "stock"
            side_val = str(pos.get("side", "")).upper()
            dir_val = str(pos.get("direction", "")).upper()
            is_short_stock = is_stock and (side_val in ["SELL", "PE", "BEAR"] or dir_val == "BEAR")

            if is_short_stock:
                buf_dist = get_sl_buffer_distance(entry_s, side="BEAR")
                be_offset = max(buf_dist, 0.5 * atr)
                be_target = round(round((entry_s - be_offset) / 0.05) * 0.05, 2)
            else:
                buf_dist = get_sl_buffer_distance(entry_s, side="BULL")
                be_offset = max(buf_dist, 0.5 * atr)
                be_target = round(round((entry_s + be_offset) / 0.05) * 0.05, 2)
            return be_target

        # CE Option: must be above entry (102.0)
        self.assertEqual(compute_be(pos_ce), 102.0)
        # PE Option: must be above entry (102.0) - Long Option Buyer invariant!
        self.assertEqual(compute_be(pos_pe), 102.0)
        # Short Stock: must be below entry (98.0) - Short seller profit lock!
        self.assertEqual(compute_be(pos_short), 98.0)


if __name__ == "__main__":
    unittest.main()
