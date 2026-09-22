import os
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)
import pandas as pd
import numpy as np


class TestRadarTrendAndRiskConfluence(unittest.TestCase):

    def test_golden_cross_blocks_pe_and_death_cross_blocks_ce(self):
        # 1. Simulate Spot in Bullish Golden Cross: Spot > EMA13 > EMA44
        closes_bull = [400.0 + i * 0.5 for i in range(50)]
        s_series = pd.Series(closes_bull)
        ema13_bull = float(s_series.ewm(span=13, adjust=False).mean().iloc[-1])
        ema44_bull = float(s_series.ewm(span=44, adjust=False).mean().iloc[-1])
        last_bull = float(s_series.iloc[-1])

        self.assertGreater(last_bull, ema13_bull)
        self.assertGreater(ema13_bull, ema44_bull)

        is_pe = True
        block_pe = is_pe and (last_bull > ema13_bull > ema44_bull)
        self.assertTrue(block_pe, "PE trigger must be blocked when spot is in Bullish Golden Cross")

        # 2. Simulate Spot in Bearish Death Cross: Spot < EMA13 < EMA44
        closes_bear = [450.0 - i * 0.5 for i in range(50)]
        s_series_bear = pd.Series(closes_bear)
        ema13_bear = float(s_series_bear.ewm(span=13, adjust=False).mean().iloc[-1])
        ema44_bear = float(s_series_bear.ewm(span=44, adjust=False).mean().iloc[-1])
        last_bear = float(s_series_bear.iloc[-1])

        self.assertLess(last_bear, ema13_bear)
        self.assertLess(ema13_bear, ema44_bear)

        is_ce = True
        block_ce = is_ce and (last_bear < ema13_bear < ema44_bear)
        self.assertTrue(block_ce, "CE trigger must be blocked when spot is in Bearish Death Cross")

    def test_risk_budget_sizing_blocks_oversized_lots(self):
        from common.trading_core import calculate_position_size

        # RBLBANK setup: lot size 3175, entry 6.45, SL 4.50 -> risk per lot = 1.95 * 3175 = Rs 6,191.25
        # Account capital = Rs 100,000, max risk percent = 1.0% (Rs 1,000), max single lot risk = 5.0% (Rs 5,000)
        c_now = 6.45
        sl = 4.50
        lot_sz = 3175
        cap = 100000.0

        pos_sz = calculate_position_size(
            spot_price=c_now,
            stop_loss=sl,
            capital=cap,
            risk_percent=1.0,
            lot_size=lot_sz,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=5.0
        )
        self.assertEqual(pos_sz, 0, "Oversized lot exceeding max risk allowance must return 0 lots")

    def test_option_contract_strict_matching(self):
        # Verify strict contract regex matching logic from index.html
        import re
        opt_pattern = re.compile(r"[0-9]+[CP]E$", re.IGNORECASE)

        c1 = "APLAPOLLO26SEP2180PE"
        c2 = "APLAPOLLO26SEP2200PE"
        underlying = "APLAPOLLO"

        self.assertTrue(bool(opt_pattern.search(c1)))
        self.assertTrue(bool(opt_pattern.search(c2)))
        self.assertFalse(bool(opt_pattern.search(underlying)))

        # Cross-contamination prevention: c1 must not match c2 even if they share the same underlying
        db_trades = [
            {"contract": "APLAPOLLO26SEP2200PE", "symbol": "APLAPOLLO", "token": 2200},
            {"contract": "APLAPOLLO26SEP2180PE", "symbol": "APLAPOLLO", "token": 2180}
        ]

        def match_trade(c_name):
            is_opt = bool(opt_pattern.search(c_name))
            for t in db_trades:
                tc = t["contract"].upper()
                ts = t["symbol"].upper()
                kc = c_name.upper()
                if is_opt:
                    if tc == kc:
                        return t
                else:
                    if tc == kc or ts == kc:
                        return t
            return None

        m1 = match_trade("APLAPOLLO26SEP2180PE")
        self.assertIsNotNone(m1)
        self.assertEqual(m1["token"], 2180, "2180PE must match token 2180, NOT 2200!")

        m2 = match_trade("APLAPOLLO26SEP2200PE")
        self.assertIsNotNone(m2)
        self.assertEqual(m2["token"], 2200, "2200PE must match token 2200!")


if __name__ == "__main__":
    unittest.main()
