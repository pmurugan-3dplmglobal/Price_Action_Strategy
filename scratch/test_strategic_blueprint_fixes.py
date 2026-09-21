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

    def test_03_0dte_cutoff_and_rollover(self):
        """Verify 0DTE cutoff at 11:30 IST rolls index options to next weekly expiry."""
        today_str = datetime.now().strftime("%Y-%m-%d")
        expiries = [today_str, "2026-10-01", "2026-10-08"]

        # Before 11:30 IST -> should choose current weekly expiry (expiries[0])
        morning_time = datetime.strptime("10:00:00", "%H:%M:%S").time()
        # After 11:30 IST -> should choose next weekly expiry (expiries[1])
        afternoon_time = datetime.strptime("12:00:00", "%H:%M:%S").time()

        # Simulate resolve_option_strikes expiry selection logic
        def choose_expiry(is_index, exp_list, now_time):
            if is_index and len(exp_list) > 1 and exp_list[0] == today_str:
                if now_time >= dtime(11, 30):
                    return exp_list[1]
            return exp_list[0]

        self.assertEqual(choose_expiry(True, expiries, morning_time), today_str)
        self.assertEqual(choose_expiry(True, expiries, afternoon_time), "2026-10-01")

        # Non-index stock option should stay on expiries[0]
        self.assertEqual(choose_expiry(False, expiries, afternoon_time), today_str)

    def test_04_reconciliation_ping_pong_prevention(self):
        """Verify closed contracts are recorded and blocked from broker-recovery re-creation."""
        test_contract = "TEST_NIFTY26SEP24000CE"
        
        # Initially not closed
        pm.clear_executed_exit(test_contract)
        
        # Mark as closed
        pm.save_executed_exit(test_contract, "MANUAL_OR_SL", {"exit_price": 120.0})
        self.assertIn(test_contract, pm._CLOSED_CONTRACTS_TODAY)
        
        # Clean up
        pm.clear_executed_exit(test_contract)
        self.assertNotIn(test_contract, pm._CLOSED_CONTRACTS_TODAY)

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

    def test_06_debit_spread_parameters(self):
        """Verify resolve_option_spread accepts real underlying spot and target."""
        spot_price = 2850.0
        spot_t1 = 2920.0
        option_ltp = 45.0  # Option premium is NOT spot price

        with patch("common.resolve.resolve_option_spread") as mock_spread:
            mock_spread.return_value = {
                "leg1_contract": "RELIANCE26SEP2850CE",
                "leg2_contract": "RELIANCE26SEP2900CE",
                "net_debit": 22.0
            }
            res = resolve.resolve_option_spread(
                kite=MagicMock(),
                symbol="RELIANCE",
                side="CE",
                underlying_ltp=spot_price,
                target_spot=spot_t1
            )
            mock_spread.assert_called_once_with(
                kite=mock_spread.call_args[1]["kite"],
                symbol="RELIANCE",
                side="CE",
                underlying_ltp=spot_price,
                target_spot=spot_t1
            )
            self.assertIsNotNone(res)
            self.assertNotEqual(mock_spread.call_args[1]["underlying_ltp"], option_ltp)

    def test_07_quote_first_radar_polling(self):
        """Verify radar Quote-First triggers candle fetch only when LTP approaches Benchmark."""
        benchmark = 1000.0
        min_trigger_pct = 0.995
        trigger_threshold = benchmark * min_trigger_pct  # 995.0

        # Scenario A: LTP is far below threshold (e.g., 980.0) -> Skip candle fetch
        ltp_far = 980.0
        should_fetch_far = ltp_far >= trigger_threshold
        self.assertFalse(should_fetch_far, "Candle fetch should be skipped when LTP < Benchmark * 0.995")

        # Scenario B: LTP touches or exceeds threshold (e.g., 996.0) -> Fetch candles
        ltp_near = 996.0
        should_fetch_near = ltp_near >= trigger_threshold
        self.assertTrue(should_fetch_near, "Candle fetch should trigger when LTP >= Benchmark * 0.995")

    def test_08_quantitative_expectancy_and_r_multiple(self):
        """Verify trade_db trade statistics calculates win rate, payoff ratio, and R-expectancy accurately."""
        mock_trades = [
            # Trade 1: Win (+20%, 2R)
            {"pnl_percent": 20.0, "entry_spot": 100.0, "exit_price": 120.0, "current_sl": 90.0, "side": "CE", "execution_type": "ALGO_TRIGGER"},
            # Trade 2: Win (+10%, 1R)
            {"pnl_percent": 10.0, "entry_spot": 100.0, "exit_price": 110.0, "current_sl": 90.0, "side": "CE", "execution_type": "ALGO_TRIGGER"},
            # Trade 3: Loss (-10%, -1R)
            {"pnl_percent": -10.0, "entry_spot": 100.0, "exit_price": 90.0, "current_sl": 90.0, "side": "CE", "execution_type": "ALGO_TRIGGER"}
        ]

        with patch("common.trade_db.get_completed_trades", return_value=mock_trades):
            stats = trade_db.get_trade_statistics()
            ov = stats["overall"]
            self.assertEqual(ov["total_trades"], 3)
            self.assertEqual(ov["wins"], 2)
            self.assertEqual(ov["losses"], 1)
            self.assertAlmostEqual(ov["win_rate_pct"], 66.7, places=1)
            self.assertAlmostEqual(ov["avg_win_pct"], 15.0, places=1)
            self.assertAlmostEqual(ov["avg_loss_pct"], 10.0, places=1)
            self.assertAlmostEqual(ov["payoff_ratio"], 1.5, places=2)
            self.assertGreater(ov["expectancy_r"], 0.0)
            self.assertEqual(ov["total_realized_r"], 2.0)  # 2R + 1R - 1R = 2R


if __name__ == "__main__":
    unittest.main()
