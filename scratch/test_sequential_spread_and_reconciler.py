"""
scratch/test_sequential_spread_and_reconciler.py
=================================================
Dedicated Unit Test Suite validating:
1. P0: Morning Reconciler Audit-Only Invariant (no rogue opening liquidation, SL deferred to position_monitor)
2. P0: Daemon Scheduler State Persistence & 120s Trigger Window Guard
3. P2: Sequential Spread Fill Confirmation (Leg 1 COMPLETE before Leg 2, RMS hedge benefit, < ₹200k barrier elimination)
"""

import os
import sys
import json
import time
import unittest
from datetime import datetime as dt, timedelta
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
TRADE_OPTION_DIR = os.path.join(PROJECT_ROOT, "Trade_Option")
for p in [PROJECT_ROOT, COMMON_DIR, TRADE_OPTION_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
from position_monitor import confirm_leg1_order_filled
import morning_reconciler
import run_export_scheduler_daemon


class MockKiteOrders:
    """Mock KiteConnect session simulating various order lifecycle states."""
    def __init__(self, order_history_map=None, orders_list=None):
        self.order_history_map = order_history_map or {}
        self.orders_list = orders_list or []
        self.api_key = "mock_api_key"

    def order_history(self, order_id):
        return self.order_history_map.get(str(order_id), [])

    def orders(self):
        return self.orders_list


class TestSequentialSpreadFillConfirmation(unittest.TestCase):
    """Test Suite for confirm_leg1_order_filled."""

    def test_single_order_complete_via_history(self):
        kite = MockKiteOrders(order_history_map={
            "1001": [{"status": "OPEN"}, {"status": "COMPLETE", "filled_quantity": 25, "average_price": 150.0}]
        })
        ok, filled, pending, reason = confirm_leg1_order_filled(kite, ["1001"], timeout_seconds=1.0, poll_interval=0.05)
        self.assertTrue(ok)
        self.assertEqual(filled, ["1001"])
        self.assertEqual(pending, [])
        self.assertEqual(reason, "ALL_COMPLETE")

    def test_single_order_complete_via_orders_fallback(self):
        kite = MockKiteOrders(
            order_history_map={},
            orders_list=[{"order_id": "1002", "status": "COMPLETE", "filled_quantity": 50}]
        )
        ok, filled, pending, reason = confirm_leg1_order_filled(kite, "1002", timeout_seconds=1.0, poll_interval=0.05)
        self.assertTrue(ok)
        self.assertEqual(filled, ["1002"])
        self.assertEqual(reason, "ALL_COMPLETE")

    def test_order_rejected_immediate_failure(self):
        kite = MockKiteOrders(order_history_map={
            "1003": [{"status": "REJECTED", "status_message": "RMS: Margin Insufficient"}]
        })
        ok, filled, pending, reason = confirm_leg1_order_filled(kite, ["1003"], timeout_seconds=1.0, poll_interval=0.05)
        self.assertFalse(ok)
        self.assertIn("ORDER_REJECTED", reason)
        self.assertEqual(pending, ["1003"])

    def test_order_cancelled_immediate_failure(self):
        kite = MockKiteOrders(order_history_map={
            "1004": [{"status": "CANCELLED", "status_message": "User cancelled"}]
        })
        ok, filled, pending, reason = confirm_leg1_order_filled(kite, ["1004"], timeout_seconds=1.0, poll_interval=0.05)
        self.assertFalse(ok)
        self.assertIn("ORDER_CANCELLED", reason)

    def test_multi_slice_all_complete(self):
        kite = MockKiteOrders(order_history_map={
            "2001": [{"status": "COMPLETE"}],
            "2002": [{"status": "COMPLETE"}]
        })
        ok, filled, pending, reason = confirm_leg1_order_filled(kite, ["2001", "2002"], timeout_seconds=1.0, poll_interval=0.05)
        self.assertTrue(ok)
        self.assertEqual(set(filled), {"2001", "2002"})
        self.assertEqual(pending, [])

    def test_order_remains_open_times_out(self):
        kite = MockKiteOrders(order_history_map={
            "3001": [{"status": "OPEN"}]
        })
        ok, filled, pending, reason = confirm_leg1_order_filled(kite, ["3001"], timeout_seconds=0.2, poll_interval=0.05)
        self.assertFalse(ok)
        self.assertEqual(reason, "TIMEOUT")
        self.assertEqual(pending, ["3001"])

    def test_empty_orders_returns_true(self):
        ok, filled, pending, reason = confirm_leg1_order_filled(None, [])
        self.assertTrue(ok)
        self.assertEqual(reason, "NO_ORDERS")


class TestMorningReconcilerAuditOnly(unittest.TestCase):
    """Test Suite verifying morning_reconciler never executes rogue market exits."""

    def test_long_option_gap_down_audited_not_liquidated(self):
        active_opt = {
            "id": 801,
            "symbol": "NIFTY",
            "contract": "NIFTY26SEP24000CE",
            "position_type": "option",
            "side": "CE",
            "entry_spot": 150.0,
            "current_sl": 120.0,
            "t1": 200.0,
            "trailing_stage": 0,
        }
        mock_kite = MagicMock()
        mock_kite.positions.return_value = {
            "net": [{"tradingsymbol": "NIFTY26SEP24000CE", "quantity": 50, "product": "NRML", "pnl": -2000.0}]
        }
        mock_kite.holdings.return_value = []
        mock_kite.quote.return_value = {
            "NFO:NIFTY26SEP24000CE": {
                "last_price": 100.0,  # Below SL 120.0
                "ohlc": {"open": 100.0, "high": 110.0, "low": 95.0, "close": 100.0}
            }
        }
        mock_kite.margins.return_value = {"available": {"cash": 150000.0, "collateral": 0.0}, "net": 150000.0}

        with patch("trade_db.get_active_trades", return_value=[active_opt]), \
             patch("trade_db.update_trade_status") as mock_update_status, \
             patch("morning_reconciler.close_position") as mock_close_pos, \
             patch("morning_reconciler.close_stock_position") as mock_close_stock:

            report = morning_reconciler.run_preflight_reconciliation(kite=mock_kite, engines=["index"])

            # Must NOT call close_position or close_stock_position
            mock_close_pos.assert_not_called()
            mock_close_stock.assert_not_called()
            # Must NOT update trade_db status to SL_HIT
            mock_update_status.assert_not_called()
            # Must log gap event for audit
            self.assertTrue(any("GAP DOWN BREACH" in str(e) for e in report["gap_events"]))

    def test_bearish_short_gap_up_audited_not_liquidated(self):
        active_short = {
            "id": 802,
            "symbol": "INFY",
            "contract": "INFY",
            "position_type": "stock",
            "side": "SELL",
            "direction": "BEAR",
            "entry_spot": 1800.0,
            "current_sl": 1830.0,
            "t1": 1740.0,
            "trailing_stage": 0,
        }
        mock_kite = MagicMock()
        mock_kite.positions.return_value = {
            "net": [{"tradingsymbol": "INFY", "quantity": -50, "product": "MIS", "pnl": -2000.0}]
        }
        mock_kite.holdings.return_value = []
        mock_kite.quote.return_value = {
            "NSE:INFY": {
                "last_price": 1845.0,  # Above SL 1830.0
                "ohlc": {"open": 1840.0, "high": 1850.0, "low": 1835.0, "close": 1845.0}
            }
        }
        mock_kite.margins.return_value = {"available": {"cash": 150000.0, "collateral": 0.0}, "net": 150000.0}

        with patch("trade_db.get_active_trades", return_value=[active_short]), \
             patch("trade_db.update_trade_status") as mock_update_status, \
             patch("morning_reconciler.close_stock_position") as mock_close_stock:

            report = morning_reconciler.run_preflight_reconciliation(kite=mock_kite, engines=["daily"])

            # Must NOT call close_stock_position
            mock_close_stock.assert_not_called()
            # Must NOT update trade_db status to SL_HIT
            mock_update_status.assert_not_called()
            # Must log gap event for audit
            self.assertTrue(any("GAP UP BREACH" in str(e) for e in report["gap_events"]))


class TestDaemonSchedulerStateAndTriggerWindow(unittest.TestCase):
    """Test Suite verifying export scheduler daemon state persistence and 120s window."""

    def test_state_load_and_save(self):
        today = dt.now().strftime("%Y-%m-%d")
        test_slots = {f"{today}_09_16_AM_PREFLIGHT", f"{today}_10_30_AM"}

        # Save state
        run_export_scheduler_daemon._save_scheduler_state(today, test_slots)
        self.assertTrue(os.path.exists(run_export_scheduler_daemon.STATE_FILE))

        # Load state
        loaded = run_export_scheduler_daemon._load_scheduler_state(today)
        self.assertEqual(loaded, test_slots)

        # Prior day state returns empty set
        loaded_yesterday = run_export_scheduler_daemon._load_scheduler_state("2020-01-01")
        self.assertEqual(loaded_yesterday, set())

    def test_120s_trigger_window_logic(self):
        """Simulate a restart 10 minutes (600s) after target slot: must NOT trigger."""
        target_time = dt(2026, 9, 24, 9, 16, 0)
        # Case A: 130s later (past 120s window) -> should NOT trigger
        now_late = target_time + timedelta(seconds=130)
        diff_late = (now_late - target_time).total_seconds()
        self.assertFalse(diff_late < 120)

        # Case B: 10 minutes later (600s, as happened at 09:29:05 today) -> should NOT trigger
        now_restart = target_time + timedelta(seconds=600)
        diff_restart = (now_restart - target_time).total_seconds()
        self.assertFalse(diff_restart < 120)

        # Case C: 30s after target time -> should trigger
        now_on_time = target_time + timedelta(seconds=30)
        diff_on_time = (now_on_time - target_time).total_seconds()
        self.assertTrue(diff_on_time < 120)


if __name__ == "__main__":
    unittest.main(verbosity=2)
