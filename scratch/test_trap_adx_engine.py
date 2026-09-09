"""
Unit tests verifying 5M Trap-ADX Index and 45M Stock Breakout Strategy (FEATURE-053).
Verifies:
1. Wilder's DMI (+DI, -DI, ADX) calculation.
2. Index Option 5M Trap Invariants (Sweep, Immediate Green Reclaim, ADX >= 26.0, Risk Cap <= 20.0 pts).
3. Stock 45M High Breakout & Tiered Buffers (<500: 0.60, 500-1000: 1.00, 1000-2000: 2.00, >=2000: 4.00).
4. Serialization to SCAN_DISPLAY_TRAP_ADX.
"""
import os
import sys
import unittest
import pandas as pd
import numpy as np

COMMON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from trap_adx_engine import (
    calculate_dmi,
    calculate_stock_tiered_buffer,
    scan_index_option_trap,
    scan_stock_45m_breakout,
    run_trap_adx_scan_cycle
)
import paths


class TestTrapAdxEngine(unittest.TestCase):

    def test_dmi_calculation_trending_up(self):
        """Test Wilder's DMI produces +DI > -DI and strong ADX in strong uptrend."""
        # 30 candles of steady upmove
        prices = [100.0 + i * 2.0 for i in range(30)]
        df = pd.DataFrame({
            'open': prices,
            'high': [p + 1.5 for p in prices],
            'low': [p - 0.5 for p in prices],
            'close': [p + 1.0 for p in prices],
            'volume': [1000 for _ in prices]
        })
        plus_di, minus_di, adx = calculate_dmi(df, period=14)
        self.assertGreater(float(plus_di.iloc[-1]), float(minus_di.iloc[-1]))
        self.assertGreater(float(plus_di.iloc[-1]), 30.0)

    def test_stock_tiered_buffers(self):
        """Verify peer's exact price-tiered stop-loss buffers for stock cash intraday."""
        self.assertEqual(calculate_stock_tiered_buffer(450.0), 0.60)   # < 500
        self.assertEqual(calculate_stock_tiered_buffer(750.0), 1.00)   # 500 - 1000
        self.assertEqual(calculate_stock_tiered_buffer(1500.0), 2.00)  # 1000 - 2000
        self.assertEqual(calculate_stock_tiered_buffer(3100.0), 4.00)  # >= 2000 (Adani Ent)

    def test_index_trap_valid_setup(self):
        """Verify valid Index Trap: Sweep -> Immediate Green Reclaim -> +DI >= 26 -> Risk <= 20 pts."""
        candles = []
        for i in range(15):
            candles.append({'open': 190.0 + i, 'high': 195.0 + i, 'low': 188.0 + i, 'close': 194.0 + i, 'volume': 1000})

        # Candle -2: Sweep below support (which is 194.0 in prior slice) -> Closes at 192.0, low 190.0
        candles.append({'open': 198.0, 'high': 199.0, 'low': 190.0, 'close': 192.0, 'volume': 1500})
        # Candle -1: Immediate GREEN reclaim -> Opens at 193.0, high 230.0, low 192.0, closes at 208.0 (above 194.0)
        candles.append({'open': 193.0, 'high': 230.0, 'low': 192.0, 'close': 208.0, 'volume': 3000})

        df = pd.DataFrame(candles)
        res = scan_index_option_trap(
            df, symbol="NIFTY", contract="NIFTY26SEP23550CE", side="CE", adx_threshold=26.0, max_sl_points=20.0
        )
        self.assertIsNotNone(res)
        self.assertEqual(res['type'], "INDEX_TRAP")
        self.assertEqual(res['status'], "READY_FOR_BUY")
        self.assertEqual(res['sweep_close'], 192.0)
        self.assertEqual(res['reclaim_close'], 208.0)
        self.assertEqual(res['current_sl'], 190.0)
        self.assertEqual(res['risk_pts'], 18.0)  # 208 - 190 = 18.0 <= 20.0

    def test_index_trap_rejected_if_red_reclaim(self):
        """Condition 2 Invalidation: If reclaim candle is RED, setup must be REJECTED."""
        candles = [{'open': 210.0, 'high': 215.0, 'low': 200.0, 'close': 208.0, 'volume': 1000} for _ in range(20)]
        # Sweep below 200.0
        candles.append({'open': 202.0, 'high': 203.0, 'low': 193.0, 'close': 195.0, 'volume': 1500})
        # Candle -1 is RED (open 206, close 201)
        candles.append({'open': 206.0, 'high': 207.0, 'low': 195.0, 'close': 201.0, 'volume': 2000})

        df = pd.DataFrame(candles)
        res = scan_index_option_trap(df, symbol="NIFTY", contract="NIFTY26SEP23550CE", side="CE")
        self.assertIsNone(res, "Red reclaim candle must be rejected")

    def test_index_trap_rejected_if_risk_exceeds_20_points(self):
        """Hard Risk Filter: If Entry - SL > 20.0 points, setup must be REJECTED."""
        candles = [{'open': 210.0, 'high': 215.0, 'low': 200.0, 'close': 208.0, 'volume': 1000} for _ in range(20)]
        # Sweep with deep low (170.0)
        candles.append({'open': 202.0, 'high': 203.0, 'low': 170.0, 'close': 195.0, 'volume': 1500})
        # Reclaim closes at 205.0 -> Risk = 205 - 170 = 35 points > 20 points!
        candles.append({'open': 196.0, 'high': 230.0, 'low': 190.0, 'close': 205.0, 'volume': 3000})

        df = pd.DataFrame(candles)
        res = scan_index_option_trap(
            df, symbol="NIFTY", contract="NIFTY26SEP23550CE", side="CE", adx_threshold=20.0, max_sl_points=20.0
        )
        self.assertIsNone(res, "Risk exceeding 20 points must be rejected")

    def test_stock_45m_breakout_detection(self):
        """Verify Stock 45M High Breakout detection and Stop-Loss buffer."""
        candles = []
        # 9 candles representing 09:15 to 10:00 AM (45m range): High = 3078.4, Low = 2960.0
        for i in range(9):
            candles.append({'open': 2980.0, 'high': 3078.4, 'low': 2960.0, 'close': 3050.0, 'volume': 5000})
        
        # 10:00 AM candle breaks out above 3078.4 to 3103.0!
        candles.append({'open': 3075.0, 'high': 3120.0, 'low': 3070.0, 'close': 3103.0, 'volume': 15000})

        df = pd.DataFrame(candles)
        res = scan_stock_45m_breakout(df, symbol="ADANIENT", target_contract="ADANIENT26SEP3100CE")
        self.assertIsNotNone(res)
        self.assertEqual(res['type'], "STOCK_45M_BREAKOUT")
        self.assertEqual(res['status'], "BREAKOUT_TRIGGERED")
        self.assertEqual(res['high_45m'], 3078.4)
        self.assertEqual(res['spot_ltp'], 3103.0)
        self.assertEqual(res['buffer_applied'], 4.0)  # > 2000 tier -> 4.0 Rs buffer
        self.assertLess(res['current_sl'], 3103.0)

    def test_run_trap_adx_scan_cycle_serialization(self):
        """Verify run_trap_adx_scan_cycle writes to paths.SCAN_DISPLAY_TRAP_ADX."""
        res = run_trap_adx_scan_cycle(kite=None)
        self.assertIn("timestamp", res)
        self.assertIn("index_traps", res)
        self.assertIn("stock_breakouts", res)
        self.assertTrue(os.path.exists(paths.SCAN_DISPLAY_TRAP_ADX))


if __name__ == "__main__":
    unittest.main()
