import os
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime as dt

# Ensure common is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))
import position_monitor
import trade_db

class TestProfitHarvestingAndGuards(unittest.TestCase):
    def setUp(self):
        self.mock_kite = MagicMock()
        self.lock = threading.Lock()
        self.dummy_log = lambda *args, **kwargs: None

    def test_single_lot_t1_exit_at_t1(self):
        """Test that single_lot_target_mode == 'EXIT_AT_T1' executes 100% exit and banks profit at T1"""
        sym = "TATAMOTORS"
        positions = {
            sym: {
                "symbol": sym,
                "contract": "TATAMOTORS26SEP950CE",
                "option_token": 12345,
                "token": 12345,
                "entry_spot": 30.0,
                "current_sl": 24.0,
                "t1": 38.0,
                "t2": 44.0,
                "position_size": 1,
                "quantity": 550,
                "lot_size": 550,
                "trailing_stage": 0,
                "side": "CE",
                "timeframe": "15minute",
                "engine": "nifty50",
                "entry_time": "2026-09-15 08:00:00",
                "created_at": "2026-09-15 08:00:00"
            }
        }
        mock_df = pd.DataFrame([{
            "date": "2026-09-15 09:30:00",
            "open": 36.0,
            "high": 39.0, # Touched T1 (38.0)
            "low": 35.0,
            "close": 38.5,
            "volume": 1000
        }])

        cfg = {
            "single_lot_target_mode": "EXIT_AT_T1",
            "tranche_mode": True,
            "failsafe_start_time": "09:15"
        }

        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_df), \
             patch("position_monitor.close_position", return_value={"success": True}) as mock_close, \
             patch("trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "nifty50",
                "15minute", trade_db, self.dummy_log, live=False
            )
            
            # Verify position closed at T1
            self.assertTrue(mock_close.called)
            self.assertNotIn(sym, positions, "Single lot position should be cleared after T1 exit")

    def test_single_lot_t1_trail_be(self):
        """Test that single_lot_target_mode == 'TRAIL_BE' preserves position and trails SL to +BE"""
        sym = "TATAMOTORS"
        positions = {
            sym: {
                "symbol": sym,
                "contract": "TATAMOTORS26SEP950CE",
                "option_token": 12345,
                "token": 12345,
                "entry_spot": 30.0,
                "current_sl": 24.0,
                "t1": 38.0,
                "t2": 44.0,
                "position_size": 1,
                "quantity": 550,
                "lot_size": 550,
                "trailing_stage": 0,
                "side": "CE",
                "timeframe": "15minute",
                "engine": "nifty50",
                "entry_time": "2026-09-15 08:00:00",
                "created_at": "2026-09-15 08:00:00"
            }
        }
        mock_df = pd.DataFrame([{
            "date": "2026-09-15 09:30:00",
            "open": 36.0,
            "high": 39.0, # Touched T1
            "low": 35.0,
            "close": 38.5,
            "volume": 1000
        }])

        cfg = {
            "single_lot_target_mode": "TRAIL_BE",
            "tranche_mode": True,
            "failsafe_start_time": "09:15"
        }

        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_df), \
             patch("position_monitor.get_contract_days_to_expiry", return_value=10), \
             patch("position_monitor.close_position") as mock_close, \
             patch("trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "nifty50",
                "15minute", trade_db, self.dummy_log, live=False
            )
            
            # Verify position NOT closed, but trailed
            self.assertFalse(mock_close.called)
            self.assertIn(sym, positions)
            self.assertEqual(positions[sym]["trailing_stage"], 1)
            self.assertGreaterEqual(positions[sym]["current_sl"], 30.0)

    def test_multi_lot_t1_tranche_exit(self):
        """Test that holding 2 lots executes 50% partial exit at T1 and runs 1 lot"""
        sym = "TATAMOTORS"
        positions = {
            sym: {
                "symbol": sym,
                "contract": "TATAMOTORS26SEP950CE",
                "option_token": 12345,
                "token": 12345,
                "entry_spot": 30.0,
                "current_sl": 24.0,
                "t1": 38.0,
                "t2": 44.0,
                "position_size": 2,
                "quantity": 1100,
                "lot_size": 550,
                "trailing_stage": 0,
                "side": "CE",
                "timeframe": "15minute",
                "engine": "nifty50",
                "entry_time": "2026-09-15 08:00:00",
                "created_at": "2026-09-15 08:00:00"
            }
        }
        mock_df = pd.DataFrame([{
            "date": "2026-09-15 09:30:00",
            "open": 36.0,
            "high": 39.0, # Touched T1
            "low": 35.0,
            "close": 38.5,
            "volume": 1000
        }])

        cfg = {
            "tranche_mode": True,
            "single_lot_target_mode": "EXIT_AT_T1",
            "failsafe_start_time": "09:15"
        }

        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_df), \
             patch("position_monitor.close_position", return_value={"success": True}) as mock_close, \
             patch("trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "nifty50",
                "15minute", trade_db, self.dummy_log, live=False
            )
            
            self.assertTrue(mock_close.called)
            # Verify qty_override was 550 (half of 1100)
            self.assertEqual(mock_close.call_args[1]["qty_override"], 550)
            # Remaining position has 1 lot / 550 qty
            self.assertIn(sym, positions)
            self.assertEqual(positions[sym]["position_size"], 1)
            self.assertEqual(positions[sym]["quantity"], 550)
            self.assertEqual(positions[sym]["trailing_stage"], 1)

    def test_earlier_trailing_ratchet_12_pct(self):
        """Test that options trail to +3% at +12% gain, and upgrade to +10% at +18% gain"""
        sym = "INFY"
        positions = {
            sym: {
                "symbol": sym,
                "contract": "INFY26SEP1800CE",
                "option_token": 12345,
                "token": 12345,
                "entry_spot": 50.0,
                "current_sl": 42.0,
                "t1": 65.0,
                "t2": 72.0,
                "position_size": 1,
                "quantity": 400,
                "lot_size": 400,
                "trailing_stage": 0,
                "side": "CE",
                "timeframe": "15minute",
                "engine": "nifty50",
                "entry_time": "2026-09-15 08:00:00",
                "created_at": "2026-09-15 08:00:00"
            }
        }
        # Peak reaches 56.5 (+13% gain, >= +12% trigger, < +18%)
        mock_df = pd.DataFrame([{
            "date": "2026-09-15 09:30:00",
            "open": 54.0,
            "high": 56.5,
            "low": 53.0,
            "close": 55.0,
            "volume": 1000
        }])

        cfg = {
            "trailing_rules": {
                "option_trail_1_gain_pct": 12.0,
                "option_trail_1_sl_pct": 3.0,
                "option_trail_2_gain_pct": 18.0,
                "option_trail_2_sl_pct": 10.0
            },
            "failsafe_start_time": "09:15"
        }

        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_df), \
             patch("trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "nifty50",
                "15minute", trade_db, self.dummy_log, live=False
            )
            
            self.assertEqual(positions[sym]["trailing_stage"], 1)
            # SL locked at entry + 3% = 50 * 1.03 = 51.5
            self.assertEqual(positions[sym]["current_sl"], 51.5)

        # Now peak reaches 60.0 (+20% gain, >= +18% trigger) -> Upgrades SL to +10% = 55.0
        mock_df_high = pd.DataFrame([{
            "date": "2026-09-15 09:45:00",
            "open": 58.0,
            "high": 60.0,
            "low": 57.0,
            "close": 59.0,
            "volume": 1000
        }])

        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_df_high), \
             patch("trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "nifty50",
                "15minute", trade_db, self.dummy_log, live=False
            )
            
            # SL upgraded to entry + 10% = 50 * 1.10 = 55.0
            self.assertEqual(positions[sym]["current_sl"], 55.0)

    def test_option_emergency_cap_22_pct(self):
        """Test that live LTP dropping > 22% triggers emergency exit regardless of spot support"""
        sym = "NIFTY"
        positions = {
            sym: {
                "symbol": sym,
                "contract": "NIFTY2691525000CE",
                "option_token": 12345,
                "token": 12345,
                "entry_spot": 100.0,
                "current_sl": 85.0, # SL at -15%, breached by close 77.0
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
                "created_at": "2026-09-15 08:00:00",
                "entry_time": "2026-09-15 08:00:00"
            }
        }
        # Option drops to 77.0 (-23% loss, breaches 85.0 SL AND 22% emergency cap)
        mock_df = pd.DataFrame([{
            "date": "2026-09-15 09:30:00",
            "open": 82.0,
            "high": 83.0,
            "low": 76.5,
            "close": 77.0,
            "volume": 1000
        }])

        cfg = {
            "max_option_loss_pct": 22.0,
            "enable_spot_sl_guard": True,
            "failsafe_start_time": "09:15",
            "sl_mode": "candle_close"
        }

        with patch("position_monitor._load_program_config_file", return_value=cfg), \
             patch("position_monitor.fetch_and_resample_candles", return_value=mock_df), \
             patch("position_monitor.close_position", return_value={"success": True}) as mock_close, \
             patch("trade_db.update_trade"):

            self.mock_kite.ltp.return_value = {
                256265: {"last_price": 24900.0} # Spot is strictly holding above spot_sl (24800)
            }

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "MIS", "index",
                "15minute", trade_db, self.dummy_log, live=False
            )
            
            # Catastrophic cap must override spot guard and exit!
            self.assertTrue(mock_close.called)
            self.assertNotIn(sym, positions)

if __name__ == "__main__":
    unittest.main()
