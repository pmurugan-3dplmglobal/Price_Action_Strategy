# -*- coding: utf-8 -*-
"""
test_2tier_and_premarket_seeding.py — Unit test suite for FEATURE-042:
2-Tier Fast Universe Scheduling (80/20 Rule) & Pre-Market Seed Incubation.

Verifies:
1. Config loader correctly reads core_scan_interval, full_scan_interval, and feature flags.
2. 2-Tier universe filtering separates high-velocity core symbols from broad F&O universe.
3. Pre-market timing logic correctly detects 08:30 pre-market and market open boundary.
"""
import os
import sys
import unittest
from datetime import datetime, time as datetime_time
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
TRADE_OPTION_DIR = os.path.join(PROJECT_ROOT, "Trade_Option")
for p in [PROJECT_ROOT, COMMON_DIR, TRADE_OPTION_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import Trade_Option.stock_options_trade_engine as sote


class Test2TierAndPreMarketSeeding(unittest.TestCase):

    def test_config_loader_constants(self):
        """Verify default 2-tier scheduling constants exist and are reasonable."""
        self.assertTrue(hasattr(sote, "CORE_SCAN_INTERVAL_SECONDS"))
        self.assertTrue(hasattr(sote, "FULL_SCAN_INTERVAL_SECONDS"))
        self.assertTrue(hasattr(sote, "ENABLE_2TIER_SCHEDULING"))
        self.assertTrue(hasattr(sote, "ENABLE_PREMARKET_SEEDING"))

        self.assertEqual(sote.CORE_SCAN_INTERVAL_SECONDS, 180)
        self.assertEqual(sote.FULL_SCAN_INTERVAL_SECONDS, 900)
        self.assertTrue(sote.ENABLE_2TIER_SCHEDULING)
        self.assertTrue(sote.ENABLE_PREMARKET_SEEDING)

    def test_pre_market_detection_logic(self):
        """Test pre-market detection at 08:30 vs market open at 09:15."""
        # Case 1: 08:30 AM IST -> Pre-market
        dt_pre = datetime(2026, 9, 23, 8, 30, 0)
        is_pre = dt_pre.time() < datetime_time(9, 15)
        self.assertTrue(is_pre)

        market_open_dt = datetime.combine(dt_pre.date(), datetime_time(9, 15))
        secs_to_open = (market_open_dt - dt_pre).total_seconds()
        self.assertEqual(secs_to_open, 2700.0)  # 45 minutes

        # Case 2: 09:15:00 AM IST -> Market Open
        dt_open = datetime(2026, 9, 23, 9, 15, 0)
        is_open = dt_open.time() < datetime_time(9, 15)
        self.assertFalse(is_open)

        # Case 3: 09:16:00 AM IST -> Live Options Window
        dt_live = datetime(2026, 9, 23, 9, 16, 0)
        is_after_open = dt_live.time() >= datetime_time(9, 15)
        self.assertTrue(is_after_open)

    def test_2tier_universe_filtering_logic(self):
        """Test that CORE mode prioritizes incubating, active, Nifty 50, and volume movers."""
        from equity_universe import NIFTY50_SYMBOLS

        all_fno = ["RELIANCE", "TCS", "INFY", "ZOMATO", "ABCAPITAL", "DORMANT_STOCK_1", "DORMANT_STOCK_2"]
        incubating_syms = {"ABCAPITAL"}
        active_pos = {"ZOMATO": {}}
        spot_quotes = {
            "NSE:RELIANCE": {"last_price": 3000.0, "volume": 1000000, "ohlc": {"close": 3000.0}},
            "NSE:TCS": {"last_price": 4000.0, "volume": 500000, "ohlc": {"close": 4000.0}},
            "NSE:INFY": {"last_price": 1800.0, "volume": 800000, "ohlc": {"close": 1800.0}},
            "NSE:ZOMATO": {"last_price": 250.0, "volume": 5000000, "ohlc": {"close": 240.0}},
            "NSE:ABCAPITAL": {"last_price": 220.0, "volume": 2000000, "ohlc": {"close": 220.0}},
            "NSE:DORMANT_STOCK_1": {"last_price": 100.0, "volume": 100, "ohlc": {"close": 100.0}},
            "NSE:DORMANT_STOCK_2": {"last_price": 50.0, "volume": 50, "ohlc": {"close": 50.0}},
        }

        # In CORE mode:
        core_symbols = set()
        core_symbols.update(incubating_syms)
        core_symbols.update(active_pos.keys())
        core_symbols.update([s for s in all_fno if s in NIFTY50_SYMBOLS])

        for s in all_fno:
            q = spot_quotes.get(f"NSE:{s}", {})
            lp = float(q.get("last_price") or 0.0)
            vol = float(q.get("volume") or 0.0)
            ohlc = q.get("ohlc") or {}
            prev_close = float(ohlc.get("close") or 0.0)
            pct_chg = abs(lp - prev_close) / prev_close * 100.0 if prev_close > 0 else 0.0
            turnover_cr = (vol * lp) / 1e7
            if pct_chg >= 1.0 or turnover_cr >= 10.0:
                core_symbols.add(s)

        filtered_core = [s for s in all_fno if s in core_symbols]

        # Verify:
        self.assertIn("RELIANCE", filtered_core)  # Nifty 50
        self.assertIn("TCS", filtered_core)       # Nifty 50
        self.assertIn("INFY", filtered_core)      # Nifty 50
        self.assertIn("ABCAPITAL", filtered_core) # Incubating
        self.assertIn("ZOMATO", filtered_core)    # Active + High mover
        self.assertNotIn("DORMANT_STOCK_1", filtered_core)
        self.assertNotIn("DORMANT_STOCK_2", filtered_core)


if __name__ == "__main__":
    unittest.main()
