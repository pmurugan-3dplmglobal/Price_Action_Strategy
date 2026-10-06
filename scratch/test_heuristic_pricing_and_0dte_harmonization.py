"""
test_heuristic_pricing_and_0dte_harmonization.py — Verification of Heuristic Pricing Fix,
0DTE Index 11:30 IST Cutoff Harmonization, and Daily Session Learning & Evolution Engine.

Verifies:
  1. Authentic Broker Quote Pricing in `common/ema_engine.py`:
     - Real quote query via `kite.quote(f"NFO:{contract}")`
     - Clamped Delta-based Stop Loss (0.65x to 0.90x entry premium)
     - DTE-adaptive profit targets via `calculate_option_profit_targets`
  2. 0DTE Index Cutoff Harmonization to 11:30 IST:
     - `common/position_monitor.py:is_new_entry_allowed()` blocks 0DTE index options at 11:30:01 IST
     - DTE >= 2 non-expiry index options allowed up to 15:00:00 IST
  3. Daily Session Learning & Evolution Logging System:
     - `derive_trade_remarks_and_lesson()` evaluates MFE, MAE, time-of-day, and structural integrity
     - `generate_daily_session_learning_report()` outputs `.md` and `.json`
     - Cumulative strategy evolution log tracks session trajectory and rolling metrics
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime as dt, time as dt_time, date
import os
import sys
import json

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from common.position_monitor import is_new_entry_allowed
import common.ema_engine as ema_engine
import common.daily_trade_journal as dtj


class TestHeuristicPricingFix(unittest.TestCase):
    """Test 1: Verification of Authentic Broker Quote Pricing in common/ema_engine.py"""

    def test_authentic_quote_pricing_and_dte_adaptive_targets(self):
        """Verify that run_ema_screener queries authentic Kite quote and applies DTE-adaptive targets."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NFO:RELIANCE26OCT3000CE": {
                "last_price": 125.50,
                "depth": {
                    "buy": [{"price": 125.40, "quantity": 50}],
                    "sell": [{"price": 125.60, "quantity": 50}]
                }
            }
        }

        mock_setup = {
            "symbol": "RELIANCE",
            "spot_price": 3000.0,
            "sl": 2960.0,
            "t1": 3060.0,
            "t2": 3100.0,
            "t3": 3150.0,
            "status": "EMA_BULLISH_CROSS"
        }

        with patch.object(ema_engine, "load_kite_session", return_value=("fake_api", "fake_token")), \
             patch.object(ema_engine, "KiteConnect", return_value=mock_kite), \
             patch.object(ema_engine, "sync_stock_tokens", return_value=None), \
             patch.object(ema_engine, "get_universe_symbols_and_tokens", return_value=(["RELIANCE"], {"RELIANCE": 12345})), \
             patch.object(ema_engine, "get_days_to_monthly_expiry", return_value=5), \
             patch.object(ema_engine, "run_ema_scan_symbol", return_value=mock_setup), \
             patch.object(ema_engine, "get_atm_strike", return_value=3000.0), \
             patch.object(ema_engine, "get_option_contract_symbol", return_value="RELIANCE26OCT3000CE"), \
             patch.dict(ema_engine._ema_engine_running, {"option": True}, clear=False), \
             patch.object(ema_engine, "_atomic_write_json", return_value=None):

            results = ema_engine.execute_ema_scan_cycle(
                is_options_mode=True,
                target_universe="NIFTY50"
            )

        self.assertGreater(len(results), 0)
        res = results[0]
        # Entry price must be authentic broker quote (125.50), NOT simulated spot * 0.03 (90.0)
        self.assertEqual(res["entry"], 125.50)
        # Clamped Delta SL: 65% to 90% of entry premium
        self.assertGreaterEqual(res["sl"], round(125.50 * 0.65, 2))
        self.assertLessEqual(res["sl"], round(125.50 * 0.90, 2))
        # Targets must be strictly ascending: Entry < T1 < T2 < T3
        self.assertGreater(res["t1"], res["entry"])
        self.assertGreater(res["t2"], res["t1"])
        self.assertGreater(res["t3"], res["t2"])


class Test0DTEHarmonization(unittest.TestCase):
    """Test 2: Verification of 0DTE Index 11:30 IST Cutoff Harmonization across files"""

    def test_position_monitor_0dte_cutoff_boundary(self):
        """Verify is_new_entry_allowed strictly enforces 11:30 IST cutoff for 0DTE index options."""
        # 11:29:59 AM -> 0DTE Allowed
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 24, 11, 29, 59)):
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=0))
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=None))
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=1))

        # 11:30:01 AM -> 0DTE Strictly BLOCKED (harmonized with ISSUE-065)
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 24, 11, 30, 1)):
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=0), "0DTE must be blocked after 11:30")
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=None), "None DTE must be blocked after 11:30")
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=1), "DTE=1 must be blocked after 11:30")

        # Non-expiry contracts (DTE >= 2) remain allowed up to 15:00:00 IST
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 24, 14, 0, 0)):
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=2), "DTE=2 allowed at 14:00")
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=5), "DTE=5 allowed at 14:00")
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=0), "0DTE blocked at 14:00")

        # 15:00:01 PM -> All Index options blocked
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 24, 15, 0, 1)):
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=5), "All index blocked after 15:00")


class TestSessionLearningAndEvolutionSystem(unittest.TestCase):
    """Test 3: Verification of Daily Session Learning & Strategy Evolution System"""

    def test_derive_trade_remarks_and_lesson(self):
        """Verify intelligent forensic remarks and actionable lesson derivation."""
        # Case A: Massive Winner with High MFE
        rem_win, les_win = dtj.derive_trade_remarks_and_lesson(
            symbol="KALYANKJIL",
            outcome="TARGET_HIT",
            pnl_rs=12500.0,
            pattern="BASE_ABCD",
            trade_data={"MFE_Pct": 28.5, "MAE_Pct": -1.2, "PnL_Pct": "+24.0%"}
        )
        self.assertIn("Explosive momentum winner", rem_win)
        self.assertIn("MFE", rem_win)
        self.assertIn("Setup thesis validated", les_win)

        # Case B: Premature Option SL Shakeout (Spot held support)
        rem_shake, les_shake = dtj.derive_trade_remarks_and_lesson(
            symbol="ABCAPITAL",
            outcome="SL_HIT",
            pnl_rs=-1500.0,
            pattern="HAMMER_ABCD",
            trade_data={"spot_breached_on_close": False, "exit_reason": "PREMATURE_OPTION_SL_SHAKEOUT"}
        )
        self.assertIn("Premature option SL shakeout", rem_shake)
        self.assertIn("Spot held structural support", rem_shake)
        self.assertIn("Spot 15m candle-close confirmation", les_shake)

        # Case C: Midday Chop Loss
        rem_mid, les_mid = dtj.derive_trade_remarks_and_lesson(
            symbol="RELIANCE",
            outcome="SL_HIT",
            pnl_rs=-2100.0,
            pattern="BE_ABCD",
            trade_data={"Entry_Time": "2026-10-05 12:15:00", "exit_reason": "SL_HIT"}
        )
        self.assertIn("Midday consolidation trap", rem_mid)
        self.assertIn("Midday Regime Gate", les_mid)

    def test_generate_daily_session_learning_report_schema(self):
        """Verify generate_daily_session_learning_report produces valid Markdown and JSON schemas."""
        rep = dtj.generate_daily_session_learning_report(target_date="2026-10-05")
        self.assertTrue(rep.get("ok"))
        self.assertEqual(rep.get("session_date"), "2026-10-05")
        self.assertIn("summary", rep)
        self.assertIn("by_tier", rep)
        self.assertIn("by_time_window", rep)
        self.assertIn("evolutionary_directives", rep)
        self.assertGreater(len(rep["evolutionary_directives"]), 0)

        # Verify Markdown file existence
        md_file = os.path.join(dtj.JOURNAL_DIR, "daily_learning_session_2026-10-05.md")
        self.assertTrue(os.path.exists(md_file), f"Markdown file must exist: {md_file}")

        # Verify cumulative log existence
        cum_md = os.path.join(dtj.JOURNAL_DIR, "cumulative_strategy_evolution_log.md")
        self.assertTrue(os.path.exists(cum_md), f"Cumulative log must exist: {cum_md}")


if __name__ == "__main__":
    unittest.main()
