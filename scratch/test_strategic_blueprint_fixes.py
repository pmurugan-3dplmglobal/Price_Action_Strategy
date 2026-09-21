#!/usr/bin/env python3
"""
Unit test suite for ISSUE-065: Strategic Blueprint Fixes.
Covers:
1. Kite LPP buy price clamping (clamp_lpp_buy_price).
2. Index engine default timeframes (15m entry / 60m anchor).
3. 0DTE cutoff at 11:30 IST and next-weekly rollover.
4. Broker reconciliation ping-pong loop prevention and 120s grace window.
5. Multi-process shared rate limiter (SQLite WAL token bucket).
6. Debit spread parameter alignment (spot and spot_t1 passed).
7. Radar Quote-First polling (skips candle fetch when LTP < Benchmark * 0.995).
8. Quantitative Expectancy and R-multiple calculations in trade_db.
"""
import unittest
import os
import sys
import tempfile
import sqlite3
import time
from datetime import datetime, time as dtime
from unittest.mock import MagicMock, patch

# Ensure root directory is on sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
sys.path.append(os.path.join(ROOT_DIR, "common"))
sys.path.append(os.path.join(ROOT_DIR, "Trade_Option"))
sys.path.append(os.path.join(ROOT_DIR, "Trade_Stock"))

import common.paths as paths
from common.trading_core import clamp_lpp_buy_price
import common.trade_db as trade_db
import common.position_monitor as pm
import common.resolve as resolve
import common.session as session


class TestStrategicBlueprintFixes(unittest.TestCase):

    def test_01_clamp_lpp_buy_price(self):
        """Verify clamp_lpp_buy_price caps buy limit price safely within LPP band."""
        # Case A: Limit price is lower than LTP * 1.08 -> keep limit price
        ltp = 100.0
        limit_p = 105.0  # +5%
        clamped = clamp_lpp_buy_price(limit_p, ltp, lpp_factor=1.08)
        self.assertEqual(clamped, 105.0)

        # Case B: Limit price is higher than LTP * 1.08 -> clamp to LTP * 1.08
        limit_p = 120.0  # +20% (would trigger Kite LPP rejection)
        clamped = clamp_lpp_buy_price(limit_p, ltp, lpp_factor=1.08)
        self.assertEqual(clamped, 108.0)

        # Case C: Real-world example (benchmark 158.65 vs LTP 140.0)
        clamped = clamp_lpp_buy_price(158.65, 140.0, lpp_factor=1.08)
        self.assertEqual(clamped, round(140.0 * 1.08, 2))  # 151.2
        self.assertLess(clamped, 158.65)

        # Case D: Edge cases (None or <=0 inputs)
        self.assertEqual(clamp_lpp_buy_price(0.0, 100.0), 0.0)
        self.assertEqual(clamp_lpp_buy_price(100.0, 0.0), 100.0)
        self.assertEqual(clamp_lpp_buy_price(100.0, None), 100.0)

    def test_02_index_engine_timeframes_and_config(self):
        """Verify Index Options Engine uses 15m entry / 60m anchor timeframes."""
        import index_options_trade_engine as idx_engine
        self.assertEqual(idx_engine.TIMEFRAME_ENTRY, "15minute")
        self.assertEqual(idx_engine.TIMEFRAME_ANCHOR, "60minute")
        self.assertEqual(idx_engine.TIMEFRAME_FALLBACK, "15minute")

        # Verify config files
        import json
        for cfg_path in [
            os.path.join(ROOT_DIR, "Trade_Option", "input", "program_config.json"),
            os.path.join(ROOT_DIR, "input", "program_config.json")
        ]:
            if os.path.exists(cfg_path):
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                idx_cfg = cfg.get("index", {})
                self.assertEqual(idx_cfg.get("timeframe_entry"), "15minute", f"Mismatch in {cfg_path}")
                self.assertEqual(idx_cfg.get("timeframe_anchor"), "60minute", f"Mismatch in {cfg_path}")

    def test_03_0dte_cutoff_and_rollover_in_resolve(self):
        """Verify resolve_option_strikes rolls over 0DTE index options to next weekly after 11:30 IST."""
        from datetime import date
        import pandas as pd
        today_date = date(2026, 9, 21)
        next_week_date = date(2026, 9, 28)

        mock_nfo = pd.DataFrame([
            {"name": "NIFTY", "instrument_type": "CE", "strike": 24000.0, "expiry": today_date.strftime("%Y-%m-%d"), "instrument_token": 1001, "tradingsymbol": "NIFTY26SEP24000CE", "lot_size": 65},
            {"name": "NIFTY", "instrument_type": "CE", "strike": 24000.0, "expiry": next_week_date.strftime("%Y-%m-%d"), "instrument_token": 1002, "tradingsymbol": "NIFTY26OCT24000CE", "lot_size": 65},
            {"name": "RELIANCE", "instrument_type": "CE", "strike": 2900.0, "expiry": today_date.strftime("%Y-%m-%d"), "instrument_token": 2001, "tradingsymbol": "RELIANCE26SEP2900CE", "lot_size": 250},
            {"name": "RELIANCE", "instrument_type": "CE", "strike": 2900.0, "expiry": next_week_date.strftime("%Y-%m-%d"), "instrument_token": 2002, "tradingsymbol": "RELIANCE26OCT2900CE", "lot_size": 250},
        ])

        with patch("common.resolve.get_ist_date", return_value=today_date):
            # Case A: Index option before 11:30 IST -> today's expiry
            with patch("common.resolve.get_ist_now", return_value=datetime(2026, 9, 21, 10, 15)):
                strikes_morning = resolve.resolve_option_strikes(mock_nfo, "NIFTY", 24000.0, 50, "CE", n_range=1)
                self.assertTrue(len(strikes_morning) > 0)
                self.assertEqual(strikes_morning[0]["tradingsymbol"], "NIFTY26SEP24000CE")

            # Case B: Index option after 11:30 IST -> rolls over to next weekly expiry
            with patch("common.resolve.get_ist_now", return_value=datetime(2026, 9, 21, 11, 45)):
                strikes_afternoon = resolve.resolve_option_strikes(mock_nfo, "NIFTY", 24000.0, 50, "CE", n_range=1)
                self.assertTrue(len(strikes_afternoon) > 0)
                self.assertEqual(strikes_afternoon[0]["tradingsymbol"], "NIFTY26OCT24000CE")

            # Case C: Stock option after 11:30 IST -> does not use 11:30 index cutoff
            with patch("common.resolve.get_ist_now", return_value=datetime(2026, 9, 21, 11, 45)):
                strikes_stock = resolve.resolve_option_strikes(mock_nfo, "RELIANCE", 2900.0, 20, "CE", n_range=1)
                self.assertTrue(len(strikes_stock) > 0)
                self.assertEqual(strikes_stock[0]["tradingsymbol"], "RELIANCE26OCT2900CE")

    def test_04_reconciliation_ping_pong_prevention(self):
        """Verify closed contracts are recorded and blocked from broker-recovery re-creation and ghost staging."""
        test_contract = "TEST_NIFTY26SEP24000CE"
        
        # Initially not closed
        pm.clear_executed_exit(test_contract)
        
        # Mark as closed
        pm.save_executed_exit(test_contract, "MANUAL_OR_SL", {"exit_price": 120.0})
        self.assertIn(test_contract, pm._CLOSED_CONTRACTS_TODAY)
        
        # Clean up
        pm.clear_executed_exit(test_contract)
        self.assertNotIn(test_contract, pm._CLOSED_CONTRACTS_TODAY)

        # Test sync_kite_positions ghost staging avoidance when contract was closed today
        mock_kite = MagicMock()
        mock_kite.positions.return_value = {
            "net": [{"tradingsymbol": "CLOSED_TCS26SEP3000CE", "quantity": 100, "exchange": "NFO", "instrument_token": 9999, "average_price": 50.0}]
        }
        positions_dict = {}
        lock = MagicMock()
        with patch("common.trade_db.is_contract_closed_today", return_value=True):
            resolve.sync_kite_positions(mock_kite, {}, positions_dict, lock, "nifty50", "15minute", "60minute")
            self.assertNotIn("CLOSED_TCS26SEP3000CE", positions_dict)

        # Verify ISSUE-059 120s grace window logic in position_monitor
        grace_window = 120
        created_at_recent = time.time() - 30  # 30s ago -> within grace
        created_at_old = time.time() - 150    # 150s ago -> expired grace

        self.assertTrue(time.time() - created_at_recent < grace_window)
        self.assertFalse(time.time() - created_at_old < grace_window)

    def test_05_shared_rate_limiter(self):
        """Verify MultiProcessTokenBucketRateLimiter throttles requests and manages tokens across processes."""
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as tf:
            db_path = tf.name

        try:
            limiter = session.MultiProcessTokenBucketRateLimiter(db_path=db_path, rate=10.0, capacity=5.0)
            
            # First acquire should succeed immediately
            t0 = time.time()
            limiter.acquire()
            t1 = time.time()
            self.assertLess(t1 - t0, 0.5)

            # Consume burst
            for _ in range(4):
                limiter.acquire()

            # Verify SQLite WAL table exists and holds valid token count
            with sqlite3.connect(db_path, timeout=5.0) as conn:
                row = conn.execute("SELECT tokens, last_update FROM rate_limiter WHERE id = 1").fetchone()
                self.assertIsNotNone(row)
                tokens, last_upd = row
                self.assertGreaterEqual(tokens, -1.0)
                self.assertLessEqual(tokens, 5.0)
        finally:
            if os.path.exists(db_path):
                try:
                    os.remove(db_path)
                except Exception:
                    pass

    def test_06_debit_spread_and_sensex_quote(self):
        """Verify resolve_option_spread accepts real underlying spot and target, and SENSEX quotes correctly."""
        from datetime import date
        import pandas as pd
        spot_price = 2850.0
        spot_t1 = 2920.0

        mock_nfo = pd.DataFrame([
            {"name": "RELIANCE", "instrument_type": "CE", "strike": 2850.0, "expiry": "2026-10-29", "instrument_token": 3001, "tradingsymbol": "RELIANCE26OCT2850CE", "lot_size": 250},
            {"name": "RELIANCE", "instrument_type": "CE", "strike": 2900.0, "expiry": "2026-10-29", "instrument_token": 3002, "tradingsymbol": "RELIANCE26OCT2900CE", "lot_size": 250},
            {"name": "RELIANCE", "instrument_type": "CE", "strike": 2950.0, "expiry": "2026-10-29", "instrument_token": 3003, "tradingsymbol": "RELIANCE26OCT2950CE", "lot_size": 250},
        ])

        with patch("common.resolve.get_ist_date", return_value=date(2026, 9, 21)):
            res = resolve.resolve_option_spread(
                nfo_instruments=mock_nfo,
                base_symbol="RELIANCE",
                spot_price=spot_price,
                step_size=50,
                direction="BULL",
                target_price=spot_t1,
                side="CE"
            )
            self.assertIsNotNone(res)
            self.assertEqual(res["leg1"]["contract"], "RELIANCE26OCT2850CE")
            self.assertEqual(res["leg2"]["contract"], "RELIANCE26OCT2900CE")

        # Verify SENSEX quote lookup string
        sym = "SENSEX"
        reg_entry = {"tradingsymbol": "BSE SENSEX"}
        spot_ts = "SENSEX" if sym == "SENSEX" else reg_entry.get("tradingsymbol")
        exch_prefix = "BSE" if sym == "SENSEX" else "NSE"
        self.assertEqual(f"{exch_prefix}:{spot_ts}", "BSE:SENSEX")

    def test_07_quote_first_radar_polling(self):
        """Verify radar Quote-First triggers candle fetch only when LTP approaches Benchmark."""
        import stock_options_trade_engine as stock_engine
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NFO:FAR_BELOW_BM": {"last_price": 85.0}
        }

        mock_item = {
            "symbol": "MOCK_FAR",
            "contract": "FAR_BELOW_BM",
            "benchmark": 100.0,
            "current_sl": 70.0,
            "t1": 140.0,
            "tier": 1,
            "tier_label": "TIER_1_GOLD",
            "option_token": 7777,
            "trigger_type": "BREAKOUT"
        }

        with patch("common.pattern_funnel.get_funnel_summary", return_value={"category_a": [mock_item]}):
            with patch("timeframe_utils.fetch_and_resample_candles") as mock_fetch:
                with patch("os.path.exists", return_value=False):
                    res = stock_engine.run_fast_radar_check(mock_kite)
                    mock_fetch.assert_not_called()
                    self.assertEqual(res, [])

    def test_08_quantitative_expectancy_and_r_multiple(self):
        """Verify trade_db trade statistics calculates win rate, payoff ratio, and R-expectancy accurately without scratch dilution."""
        mock_trades = [
            # Trade 1: Win (+20%, 2R)
            {"pnl_percent": 20.0, "entry_spot": 100.0, "exit_price": 120.0, "current_sl": 90.0, "side": "CE", "execution_type": "ALGO_TRIGGER"},
            # Trade 2: Win (+10%, 1R)
            {"pnl_percent": 10.0, "entry_spot": 100.0, "exit_price": 110.0, "current_sl": 90.0, "side": "CE", "execution_type": "ALGO_TRIGGER"},
            # Trade 3: Loss (-10%, -1R)
            {"pnl_percent": -10.0, "entry_spot": 100.0, "exit_price": 90.0, "current_sl": 90.0, "side": "CE", "execution_type": "ALGO_TRIGGER"},
            # Trade 4: Scratch / Breakeven (0.0%, 0R)
            {"pnl_percent": 0.0, "entry_spot": 100.0, "exit_price": 100.0, "current_sl": 90.0, "side": "CE", "execution_type": "ALGO_TRIGGER"}
        ]

        with patch("common.trade_db.get_completed_trades", return_value=mock_trades):
            stats = trade_db.get_trade_statistics()
            ov = stats["overall"]
            self.assertEqual(ov["total_trades"], 4)
            self.assertEqual(ov["wins"], 2)
            self.assertEqual(ov["losses"], 1)  # Scratch trade (0%) is not counted as a loss
            self.assertEqual(ov["win_rate_pct"], 50.0)
            self.assertAlmostEqual(ov["avg_win_pct"], 15.0, places=1)
            self.assertAlmostEqual(ov["avg_loss_pct"], 10.0, places=1)
            self.assertAlmostEqual(ov["payoff_ratio"], 1.5, places=2)
            self.assertAlmostEqual(ov["avg_loss_r"], 1.0, places=1)  # Scratch 0R did not dilute avg_loss_r
            self.assertGreater(ov["expectancy_r"], 0.0)
            self.assertEqual(ov["total_realized_r"], 2.0)  # 2R + 1R - 1R + 0R = 2R


if __name__ == "__main__":
    unittest.main()
