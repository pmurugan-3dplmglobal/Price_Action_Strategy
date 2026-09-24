import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime as dt, time as dt_time
import os, sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from common.position_monitor import is_new_entry_allowed
import Trade_Option.index_options_trade_engine as iote

class TestAdaptiveIndexEntryWindow(unittest.TestCase):

    def test_0dte_vs_monthly_cutoff(self):
        """Verify 0DTE/expiry day is strictly blocked after 13:30, but DTE >= 2 is allowed until 15:00."""
        # 13:31 PM
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 23, 13, 31, 0)):
            # 0DTE / None / dte=1 -> Blocked
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=None))
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=0))
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=1))
            # DTE >= 2 (Monthly / Next-Week) -> Allowed!
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=2))
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=5))

        # 14:55 PM (The exact time yesterday's PE setup formed)
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 23, 14, 55, 0)):
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=0), "0DTE must be blocked at 14:55")
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=5), "DTE=5 MUST be allowed at 14:55")

        # 15:00:00 PM (Cutoff boundary)
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 23, 15, 0, 0)):
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=5))

        # 15:01:00 PM (Past 15:00 -> Hard Cutoff for all index options)
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 23, 15, 1, 0)):
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=5), "Index blocked after 15:00")
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True, dte=0), "Index blocked after 15:00")

    def test_engine_late_day_evaluation(self):
        """Verify index trade engine filters candidates by DTE and R:R after 13:30."""
        cand_0dte = {
            "symbol": "NIFTY", "contract": "NIFTY26SEP23500PE", "side": "PE", "pattern": "BE_ABCD",
            "dte": 0, "rr": 2.73, "spot_confluence": True, "entry_spot": 139.3, "timeframe": "5minute",
            "benchmark": 133.9, "current_sl": 115.65, "tier": 1
        }
        cand_low_rr = {
            "symbol": "NIFTY", "contract": "NIFTY26OCT23500PE", "side": "PE", "pattern": "BE_ABCD",
            "dte": 5, "rr": 1.4, "spot_confluence": True, "entry_spot": 139.3, "timeframe": "5minute",
            "benchmark": 133.9, "current_sl": 115.65, "tier": 2
        }
        cand_valid = {
            "symbol": "NIFTY", "contract": "NIFTY26OCT23500PE", "side": "PE", "pattern": "BE_ABCD",
            "dte": 5, "rr": 2.73, "spot_confluence": True, "entry_spot": 139.3, "timeframe": "5minute",
            "benchmark": 133.9, "current_sl": 115.65, "tier": 1
        }

        # Mock dependencies in index engine
        kite_mock = MagicMock()
        kite_mock.margins.return_value = {"equity": {"available": {"live_balance": 250000.0}}}

        mock_spread = {
            "spread_type": "BEAR_PUT_SPREAD",
            "leg1": {"contract": "NIFTY26OCT23500PE", "token": 1001, "strike": 23500.0},
            "leg2": {"contract": "NIFTY26OCT23300PE", "token": 1002, "strike": 23300.0}
        }

        with patch.object(iote, "LIVE_MARKET_DEPLOYMENT", True), \
             patch.object(iote, "live_execution_enabled", return_value=True), \
             patch.object(iote, "BACKTEST_DATE", None), \
             patch.object(iote, "ACTIVE_POSITIONS", {}), \
             patch("timeframe_utils.get_ist_now", return_value=dt(2026, 9, 23, 14, 55, 0)), \
             patch("Trade_Option.index_options_trade_engine.get_live_available_cash", return_value=250000.0), \
             patch("vix_guard.evaluate_vix_regime", return_value=(True, "VIX_OK", 14.5)), \
             patch("portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {})), \
             patch("Trade_Option.index_options_trade_engine.trade_db.is_pattern_executed", return_value=False), \
             patch("Trade_Option.index_options_trade_engine.trade_db.get_active_trades", return_value=[]), \
             patch("Trade_Option.index_options_trade_engine.trade_db.is_contract_active", return_value=False), \
             patch("Trade_Option.index_options_trade_engine.trade_db.is_symbol_active", return_value=False), \
             patch("Trade_Option.index_options_trade_engine.trade_db.create_trade", return_value=(999, True)), \
             patch("Trade_Option.index_options_trade_engine.trade_db.record_executed_pattern", return_value=None), \
             patch("position_monitor.is_contract_held_on_broker", return_value=(False, 0)), \
             patch("common.resolve.resolve_option_spread", return_value=mock_spread), \
             patch.object(iote, "execute_index_entry", return_value=True) as mock_exec:

            # Case A: 0DTE candidate at 14:55 -> Blocked by 0DTE cutoff
            iote.execute_highest_rr_trade(kite_mock, [cand_0dte])
            mock_exec.assert_not_called()

            # Case B: DTE=5 candidate with RR=1.4 < 2.0 -> Blocked by late window RR guard
            iote.execute_highest_rr_trade(kite_mock, [cand_low_rr])
            mock_exec.assert_not_called()

            # Case C: DTE=5 candidate with RR=2.73 >= 2.0 -> APPROVED and executed as spread!
            iote.execute_highest_rr_trade(kite_mock, [cand_valid])
            self.assertTrue(mock_exec.called, "Valid DTE=5 candidate at 14:55 MUST be executed")
            call_args = mock_exec.call_args[0]
            # args: (kite, pos)
            pos_arg = call_args[1]
            self.assertEqual(pos_arg["position_type"], "option_spread", "Post-14:00 entry on >= 2L account MUST enforce option_spread")
            self.assertEqual(pos_arg["contract"], "NIFTY26OCT23500PE")

if __name__ == "__main__":
    unittest.main()
