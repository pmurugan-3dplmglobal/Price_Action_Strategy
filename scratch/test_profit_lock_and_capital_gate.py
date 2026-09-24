"""
Unit and Regression Test Suite for ISSUE-088:
1. Pre-Execution Cash Affordability Gate: Prioritize avail['cash'] over live_balance and clamp >= 0.0.
2. Capital affordability rejection when required capital > available cash * 0.90.
3. Spot-anchored candle-close SL guard: Suppress option SL when spot flash-wicks below SL but latest completed candle closed above SL.
4. Spot-anchored guard catastrophic option loss override (>28%).
5. Single-lot mode preserving EXIT_AT_T1 for DTE > 5.
6. Intraday +15% Profit Lock Ratchet (+8% SL lock) & +25% (+15% SL lock) with physical sanity clamp.
"""

import os
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime as dt

# Canonical import path setup
_COMMON_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common"))
if _COMMON_PATH not in sys.path:
    sys.path.insert(0, _COMMON_PATH)

import portfolio_risk
import position_monitor
import trade_db

# Standard active morning session timestamp for intraday monitoring tests (avoids EOD 15:15 squareoff)
MOCK_MARKET_TIME = dt(2026, 9, 15, 10, 0, 0)


class TestProfitLockAndCapitalGate(unittest.TestCase):
    def setUp(self):
        self.mock_kite = MagicMock()
        self.lock = threading.Lock()
        self.dummy_log = lambda *args, **kwargs: None
        # Reset portfolio cash cache before each test
        with portfolio_risk._CASH_LOCK:
            portfolio_risk._LIVE_CASH_CACHE["timestamp"] = 0.0
            portfolio_risk._LIVE_CASH_CACHE["cash"] = 100000.0

    def test_01_cash_vs_live_balance_prioritization(self):
        """
        Verify get_live_available_cash prioritizes avail['cash'] over live_balance
        and enforces non-negative live_bal >= 0.0.
        """
        # Scenario A: Real Zerodha RMS case where cash is low (630.60) but collateral/live_balance is high (24540.60)
        self.mock_kite.margins.return_value = {
            "available": {
                "cash": 630.60,
                "live_balance": 24540.60,
                "collateral": 23910.00
            },
            "net": 24540.60
        }
        cash = portfolio_risk.get_live_available_cash(self.mock_kite, cache_ttl=0)
        self.assertEqual(cash, 630.60, "Must strictly prioritize avail['cash'] over collateral live_balance")

        # Scenario B: Negative cash balance (due to ledger debit / charges) -> Clamped to 0.0
        self.mock_kite.margins.return_value = {
            "available": {
                "cash": -450.50,
                "live_balance": 12000.00
            }
        }
        cash_neg = portfolio_risk.get_live_available_cash(self.mock_kite, cache_ttl=0)
        self.assertEqual(cash_neg, 0.0, "Negative cash balance must be clamped to 0.0")

        # Scenario C: Cash is missing / None -> Fall back to live_balance
        self.mock_kite.margins.return_value = {
            "available": {
                "cash": None,
                "live_balance": 35000.00
            }
        }
        cash_fallback = portfolio_risk.get_live_available_cash(self.mock_kite, cache_ttl=0)
        self.assertEqual(cash_fallback, 35000.00, "Should fall back to live_balance when cash is None")

        # Scenario D: Kite is None -> Fall back to default
        cash_none = portfolio_risk.get_live_available_cash(None, default=50000.0)
        self.assertEqual(cash_none, 50000.0, "Should return default when kite session is None")

    def test_02_capital_affordability_rejection(self):
        """
        Verify check_capital_affordability rejects orders exceeding 90% of available cash.
        """
        # Cash is ₹630.60; 90% budget is ₹567.54
        self.mock_kite.margins.return_value = {
            "available": {
                "cash": 630.60,
                "live_balance": 24540.60
            }
        }

        # Trade requiring ₹2,000 must be rejected
        is_afford, msg, live_cash = portfolio_risk.check_capital_affordability(self.mock_kite, 2000.0, max_utilization_pct=0.90)
        self.assertFalse(is_afford, "Trade requiring ₹2,000 must fail affordability check when cash is ₹630.60")
        self.assertIn("exceeds 90% of available cash", msg)
        self.assertEqual(live_cash, 630.60)

        # Trade requiring ₹500 must pass (₹500 <= ₹567.54)
        is_afford_ok, msg_ok, _ = portfolio_risk.check_capital_affordability(self.mock_kite, 500.0, max_utilization_pct=0.90)
        self.assertTrue(is_afford_ok, "Trade requiring ₹500 should pass affordability check")
        self.assertEqual(msg_ok, "Affordability check passed")

    def test_03_spot_candle_close_sl_guard_suppression(self):
        """
        Datta Invariant: Stop Loss is strictly on a CLOSING BASIS (wicks ignored).
        When spot flash-wicks below SL during uncompleted bar, but latest completed
        candle closed safely above SL, option SL exit must be suppressed.
        """
        sym = "NIFTY"
        mock_spot_df = pd.DataFrame([
            {
                "date": "2026-09-15 09:15:00",
                "open": 24820.0,
                "high": 24860.0,
                "low": 24810.0,
                "close": 24850.0,  # iloc[-2]: Completed candle closed strictly ABOVE spot_sl (24800.0)
                "volume": 50000
            },
            {
                "date": "2026-09-15 09:30:00",
                "open": 24850.0,
                "high": 24855.0,
                "low": 24740.0,
                "close": 24760.0,  # iloc[-1]: Live incomplete bar
                "volume": 10000
            }
        ])

        positions = {
            sym: {
                "symbol": sym,
                "contract": "NIFTY2691525000CE",
                "option_token": 12345,
                "token": 12345,
                "entry_spot": 100.0,
                "current_sl": 90.0,  # Option SL at 90.0, breached by option close 88.0
                "t1": 150.0,
                "position_size": 1,
                "quantity": 25,
                "lot_size": 25,
                "trailing_stage": 0,
                "side": "CE",
                "timeframe": "15minute",
                "engine": "index",
                "spot_token": 256265,
                "spot_sl": 24800.0,
                "df_spot": mock_spot_df,
                "created_at": "2026-09-15 08:00:00",
                "entry_time": "2026-09-15 08:00:00"
            }
        }

        # Option candle: closes at 88.0 (12% loss, breaches 90.0 SL)
        mock_opt_df = pd.DataFrame([{
            "date": "2026-09-15 09:30:00",
            "open": 92.0,
            "high": 93.0,
            "low": 87.5,
            "close": 88.0,
            "volume": 1000
        }])

        cfg = {
            "max_option_loss_pct": 28.0,
            "enable_spot_sl_guard": True,
            "failsafe_start_time": "09:15",
            "sl_mode": "candle_close"
        }

        # Live spot quote flash-wicks down to 24750.0 (< 24800.0 SL)
        self.mock_kite.ltp.return_value = {
            256265: {"last_price": 24750.0}
        }

        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_opt_df), \
             patch("position_monitor.get_ist_now", return_value=MOCK_MARKET_TIME), \
             patch("position_monitor.close_position") as mock_close, \
             patch("trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "index",
                "15minute", trade_db, self.dummy_log, live=False
            )

            # Option exit MUST be suppressed because latest completed spot bar closed at 24850.0 > 24800.0 SL!
            self.assertFalse(mock_close.called, "Option SL must be suppressed when completed spot candle holds above SL")
            self.assertIn(sym, positions, "Position must remain open and protected by spot candle close guard")

    def test_04_catastrophic_option_loss_override(self):
        """
        Verify that option catastrophic collapse (>28% loss) overrides spot candle close guard
        to prevent total capital loss in sudden black-swan events.
        """
        sym = "NIFTY"
        mock_spot_df = pd.DataFrame([
            {
                "date": "2026-09-15 09:15:00",
                "open": 24820.0,
                "high": 24860.0,
                "low": 24810.0,
                "close": 24850.0,  # Spot completed bar closed above spot_sl
                "volume": 50000
            },
            {
                "date": "2026-09-15 09:30:00",
                "open": 24850.0,
                "high": 24855.0,
                "low": 24830.0,
                "close": 24840.0,
                "volume": 10000
            }
        ])

        positions = {
            sym: {
                "symbol": sym,
                "contract": "NIFTY2691525000CE",
                "option_token": 12345,
                "token": 12345,
                "entry_spot": 100.0,
                "current_sl": 90.0,
                "t1": 150.0,
                "position_size": 1,
                "quantity": 25,
                "lot_size": 25,
                "trailing_stage": 0,
                "side": "CE",
                "timeframe": "15minute",
                "engine": "index",
                "spot_token": 256265,
                "spot_sl": 24800.0,
                "df_spot": mock_spot_df,
                "created_at": "2026-09-15 08:00:00",
                "entry_time": "2026-09-15 08:00:00"
            }
        }

        # Option plunges to 70.0 (30% drop > 28% catastrophic cap)
        mock_opt_df = pd.DataFrame([{
            "date": "2026-09-15 09:30:00",
            "open": 85.0,
            "high": 85.0,
            "low": 69.0,
            "close": 70.0,
            "volume": 1000
        }])

        cfg = {
            "max_option_loss_pct": 28.0,
            "enable_spot_sl_guard": True,
            "failsafe_start_time": "09:15",
            "sl_mode": "candle_close"
        }

        self.mock_kite.ltp.return_value = {
            256265: {"last_price": 24845.0}  # Spot is comfortably holding above 24800
        }

        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_opt_df), \
             patch("position_monitor.get_ist_now", return_value=MOCK_MARKET_TIME), \
             patch("position_monitor.close_position", return_value={"success": True}) as mock_close, \
             patch("trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "index",
                "15minute", trade_db, self.dummy_log, live=False
            )

            # Catastrophic option emergency exit MUST be triggered regardless of spot holding!
            self.assertTrue(mock_close.called, "Catastrophic option loss (>28%) must override spot guard")
            self.assertNotIn(sym, positions, "Position must be closed out")

    def test_05_single_lot_mode_preserves_exit_at_t1_for_dte_gt_5(self):
        """
        Verify that single_lot_mode='EXIT_AT_T1' is preserved for DTE > 5
        and NOT overridden to 'TRAIL_BE'. Single-lot traders must bank 100% profit at T1.
        """
        sym = "RELIANCE"
        positions = {
            sym: {
                "symbol": sym,
                "contract": "RELIANCE26OCT3000CE",
                "option_token": 54321,
                "token": 54321,
                "entry_spot": 50.0,
                "current_sl": 42.0,
                "t1": 60.0,
                "position_size": 1,
                "quantity": 250,
                "lot_size": 250,
                "trailing_stage": 0,
                "side": "CE",
                "timeframe": "15minute",
                "engine": "nifty50",
                "created_at": "2026-09-15 08:00:00",
                "entry_time": "2026-09-15 08:00:00"
            }
        }

        # Option high hits 61.0 (touches T1 at 60.0)
        mock_df = pd.DataFrame([{
            "date": "2026-09-15 09:30:00",
            "open": 58.0,
            "high": 61.0,
            "low": 57.0,
            "close": 60.5,
            "volume": 2000
        }])

        cfg = {
            "single_lot_target_mode": "EXIT_AT_T1",
            "tranche_mode": True,
            "failsafe_start_time": "09:15"
        }

        # DTE is 15 (> 5)
        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_df), \
             patch("position_monitor.get_contract_days_to_expiry", return_value=15), \
             patch("position_monitor.get_ist_now", return_value=MOCK_MARKET_TIME), \
             patch("position_monitor.close_position", return_value={"success": True}) as mock_close, \
             patch("trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "nifty50",
                "15minute", trade_db, self.dummy_log, live=False
            )

            # Single-lot position MUST be fully closed at T1 even though DTE > 5!
            self.assertTrue(mock_close.called, "Single-lot position configured for EXIT_AT_T1 must exit at T1 for DTE > 5")
            self.assertNotIn(sym, positions, "Position must be cleared upon banking 100% at T1")

    def test_06_intraday_profit_lock_ratchet_and_clamp(self):
        """
        Verify Trailing Ratchet:
        - gain >= 15.0% ratchets SL to +8% (entry * 1.08)
        - gain >= 25.0% ratchets SL to +15% (entry * 1.15)
        - If price pulls back, clamp logic clamps safely 2% below live LTP if above curr_sl.
        """
        sym = "SBIN"
        positions = {
            sym: {
                "symbol": sym,
                "contract": "SBIN26SEP850CE",
                "option_token": 99999,
                "token": 99999,
                "entry_spot": 100.0,
                "current_sl": 85.0,
                "t1": 140.0,
                "position_size": 2,
                "quantity": 1500,
                "lot_size": 750,
                "trailing_stage": 0,
                "side": "CE",
                "timeframe": "15minute",
                "engine": "nifty50",
                "created_at": "2026-09-15 08:00:00",
                "entry_time": "2026-09-15 08:00:00"
            }
        }

        # Step A: Gain reaches +16% (high=116.0, close=115.0) -> Triggers +15% gain lock -> SL locked to +8% (108.0)
        mock_df_1 = pd.DataFrame([{
            "date": "2026-09-15 09:30:00",
            "open": 105.0,
            "high": 116.0,
            "low": 104.0,
            "close": 115.0,
            "volume": 2000
        }])

        cfg = {"failsafe_start_time": "09:15"}

        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_df_1), \
             patch("position_monitor.get_ist_now", return_value=MOCK_MARKET_TIME), \
             patch("trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "nifty50",
                "15minute", trade_db, self.dummy_log, live=False
            )

            self.assertEqual(positions[sym]["trailing_stage"], 1)
            self.assertEqual(positions[sym]["current_sl"], 108.0, "+15% gain must lock SL to +8% (100 * 1.08 = 108.0)")

        # Step B: Gain reaches +26% (high=126.0, close=125.0) -> Triggers +25% gain lock -> SL upgraded to +15% (115.0)
        mock_df_2 = pd.DataFrame([{
            "date": "2026-09-15 09:45:00",
            "open": 115.0,
            "high": 126.0,
            "low": 114.0,
            "close": 125.0,
            "volume": 2000
        }])

        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_df_2), \
             patch("position_monitor.get_ist_now", return_value=MOCK_MARKET_TIME), \
             patch("trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "nifty50",
                "15minute", trade_db, self.dummy_log, live=False
            )

            self.assertEqual(positions[sym]["current_sl"], 115.0, "+25% gain must lock SL to +15% (100 * 1.15 = 115.0)")

        # Step C: Physical sanity clamp: High reached 132.0 (+32% -> candidate +20% SL = 120.0),
        # but live tick pulled back to 118.0 (below candidate 120.0).
        # Clamped SL should be 118.0 * 0.98 = 115.65 (> curr_sl 115.0).
        mock_df_3 = pd.DataFrame([{
            "date": "2026-09-15 10:00:00",
            "open": 125.0,
            "high": 132.0,
            "low": 117.0,
            "close": 118.0,
            "volume": 2000
        }])

        self.mock_kite.quote.return_value = {
            "NFO:SBIN26SEP850CE": {"last_price": 118.0}
        }

        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_df_3), \
             patch("position_monitor.get_ist_now", return_value=MOCK_MARKET_TIME), \
             patch("trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "nifty50",
                "15minute", trade_db, self.dummy_log, live=False
            )

            # Candidate was 120.0, but clamped to 2% below 118.0 = round(118 * 0.98 / 0.05) * 0.05 = 115.65
            self.assertEqual(positions[sym]["current_sl"], 115.65, "Must safely clamp to 2% below live LTP when candidate exceeds LTP")


if __name__ == "__main__":
    unittest.main()
