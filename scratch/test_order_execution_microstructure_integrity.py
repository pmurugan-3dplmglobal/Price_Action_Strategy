import unittest
import threading
import time
import os
import sys
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [PROJECT_ROOT, os.path.join(PROJECT_ROOT, "common"), os.path.join(PROJECT_ROOT, "Trade_Option")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
import stock_options_trade_engine as sote
import app_option_Trade as aot
from portfolio_risk import check_capital_affordability, get_live_available_cash
from position_monitor import clamp_lpp_buy_price
from exploded_state_guard import check_exploded_state_guard


class TestOrderExecutionMicrostructureIntegrity(unittest.TestCase):
    def test_execution_lock_present_and_serializes(self):
        """Verify _EXECUTION_LOCK exists and wraps execution logic."""
        self.assertTrue(hasattr(sote, "_EXECUTION_LOCK"))
        self.assertIsInstance(sote._EXECUTION_LOCK, type(threading.Lock()))

        # Verify execute_highest_rr_trade uses _EXECUTION_LOCK
        lock_acquired = []
        orig_locked = sote._execute_highest_rr_trade_locked

        def mock_locked(kite, staged):
            # Assert lock is held while inside locked func
            acquired = sote._EXECUTION_LOCK.acquire(blocking=False)
            if not acquired:
                lock_acquired.append(True)
            else:
                sote._EXECUTION_LOCK.release()
                lock_acquired.append(False)
            return "EXECUTED"

        try:
            sote._execute_highest_rr_trade_locked = mock_locked
            staged = [{"symbol": "TEST", "contract": "TEST26CE", "benchmark": 100.0, "current_sl": 90.0, "t1": 120.0}]
            res = sote.execute_highest_rr_trade(None, staged)
            self.assertEqual(res, "EXECUTED")
            self.assertTrue(lock_acquired[0], "Lock was not held during execution!")
        finally:
            sote._execute_highest_rr_trade_locked = orig_locked

    def test_point_of_execution_anti_exploded_state_guard_metrics(self):
        """Verify spot_ltp, spot_trigger, and spot_t1 are passed to check_exploded_state_guard."""
        # 1. Normal safe state
        safe, reason, metrics = check_exploded_state_guard(
            live_price=102.0,
            benchmark_price=100.0,
            t1_target=120.0,
            stop_loss=90.0,
            symbol="INFY",
            contract="INFY26SEP1500CE",
            is_option=True,
            spot_ltp=1505.0,
            spot_trigger=1500.0,
            spot_t1=1530.0,
            max_target_consumed_pct=0.20,
            max_chase_pct=0.08,
            min_live_rr=1.00
        )
        self.assertTrue(safe)
        self.assertEqual(reason, "SAFE_EXECUTION_STATE")

        # 2. Exploded option state (> 20% consumed)
        safe_exp, reason_exp, _ = check_exploded_state_guard(
            live_price=106.0,
            benchmark_price=100.0,
            t1_target=120.0,
            stop_loss=90.0,
            symbol="INFY",
            contract="INFY26SEP1500CE",
            is_option=True,
            spot_ltp=1505.0,
            spot_trigger=1500.0,
            spot_t1=1530.0,
            max_target_consumed_pct=0.20,
            max_chase_pct=0.08,
            min_live_rr=1.00
        )
        self.assertFalse(safe_exp)
        self.assertIn("MOVE ALREADY EXPLODED", reason_exp)

        # 3. Exploded underlying spot state (> 35% consumed)
        safe_spot, reason_spot, _ = check_exploded_state_guard(
            live_price=101.0,
            benchmark_price=100.0,
            t1_target=120.0,
            stop_loss=90.0,
            symbol="INFY",
            contract="INFY26SEP1500CE",
            is_option=True,
            spot_ltp=1515.0,  # 15/30 = 50% consumed > 35%
            spot_trigger=1500.0,
            spot_t1=1530.0,
            max_target_consumed_pct=0.20,
            max_chase_pct=0.08,
            min_live_rr=1.00
        )
        self.assertFalse(safe_spot)
        self.assertIn("UNDERLYING SPOT OVEREXTENDED", reason_spot)

    def test_lpp_clamp_uses_cp_ltp_primary_reference(self):
        """Verify clamp_lpp_buy_price clamps to 1.08x of LTP."""
        ltp = 100.0
        # If limit is 120.0, clamp should cap it at 108.0
        clamped = clamp_lpp_buy_price(120.0, ltp, lpp_factor=1.08)
        self.assertEqual(clamped, 108.0)

        # If limit is 105.0, within ceiling, should stay 105.0
        clamped_low = clamp_lpp_buy_price(105.0, ltp, lpp_factor=1.08)
        self.assertEqual(clamped_low, 105.0)

    def test_capital_affordability_gates_at_90_percent(self):
        """Verify check_capital_affordability enforces max 90% liquid cash utilization."""
        mock_kite = MagicMock()
        mock_kite.margins.return_value = {
            "equity": {
                "available": {
                    "cash": 100000.0,
                    "live_balance": 100000.0,
                    "collateral": 0.0
                }
            }
        }
        # 1. Trade requiring 80,000 (80%) -> Allowed
        ok, msg, cash = check_capital_affordability(mock_kite, required_capital=80000.0, max_utilization_pct=0.90)
        self.assertTrue(ok)

        # 2. Trade requiring 95,000 (95%) -> Rejected (> 90%)
        ok_rej, msg_rej, cash_rej = check_capital_affordability(mock_kite, required_capital=95000.0, max_utilization_pct=0.90)
        self.assertFalse(ok_rej)
        self.assertIn("exceeds 90% of available cash", msg_rej)

    def test_1click_buy_capital_affordability_integration(self):
        """Verify 1-Click Buy route /api/buy-scanned-trade rejects trades exceeding 90% capital."""
        client = aot.app.test_client()
        with client.session_transaction() as sess:
            sess["user"] = "admin"
            sess["role"] = "admin"

        mock_kite = MagicMock()
        mock_kite.margins.return_value = {
            "equity": {
                "available": {
                    "cash": 2000.0,
                    "live_balance": 2000.0,
                    "collateral": 0.0
                }
            }
        }
        mock_kite.quote.return_value = {
            "NFO:NIFTY26SEP24000CE": {"last_price": 100.0, "depth": {"buy": [{"price": 99.0}], "sell": [{"price": 100.0}]}}
        }

        with patch.object(aot, "_kite_session", mock_kite), \
             patch("trading_core.is_market_open", return_value=True), \
             patch("common.position_monitor.is_new_entry_allowed", return_value=True), \
             patch("common.position_monitor.get_contract_days_to_expiry", return_value=5), \
             patch("vix_guard.evaluate_vix_regime", return_value=(True, "OK", {})), \
             patch("portfolio_risk.get_live_available_cash", return_value=2000.0):
            # Order requiring 25 * 100.5 = 2,512.50 > 90% of 2,000 (1,800)
            resp = client.post("/api/buy-scanned-trade", json={
                "symbol": "NIFTY",
                "contract": "NIFTY26SEP24000CE",
                "lot_size": 25,
                "engine": "index",
                "side": "CE",
                "direction": "BULL",
                "force": False
            })
            self.assertEqual(resp.status_code, 400)
            data = resp.get_json()
            self.assertFalse(data["ok"])
            self.assertIn("Capital Affordability", data["error"])


if __name__ == "__main__":
    unittest.main()
