import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime as dt, timedelta

PROJECT_ROOT = r"g:\Poovendan\AI\Trading\Share\ReadyToDeploy\Prod_code_01\Price_Action_Strategy"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from common import position_monitor
from common import trade_db

class TestNearT1AndGainLocks(unittest.TestCase):
    def setUp(self):
        import threading
        self.lock = threading.Lock()
        self.mock_kite = MagicMock()
        self.dummy_log = MagicMock()

    def test_option_near_t1_lock_and_clamping(self):
        """Test that an option reaching >=90% of T1 triggers the Near-T1 lock, and clamps safely 2% below live LTP."""
        sym = "SIEMENS"
        entry_p = 24.60
        t1 = 43.80 # Target distance = 19.20, 90% level = 41.88, 70% lock = 38.04
        
        positions = {
            sym: {
                "symbol": sym,
                "contract": "SIEMENS26SEP3950CE",
                "option_token": 27972354,
                "token": 27972354,
                "entry_spot": entry_p,
                "current_sl": 27.05, # was previously trailed to +10%
                "t1": t1,
                "t2": 51.0,
                "position_size": 1,
                "quantity": 175,
                "lot_size": 175,
                "trailing_stage": 1,
                "side": "CE",
                "timeframe": "15minute",
                "engine": "nifty50",
                "entry_time": (dt.now() - timedelta(hours=2)).isoformat(),
                "created_at": (dt.now() - timedelta(hours=2)).isoformat()
            }
        }
        
        mock_df = pd.DataFrame([{
            "date": (dt.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
            "open": 30.0,
            "high": 42.85, # Spiked to 42.85!
            "low": 29.0,
            "close": 37.45,
            "volume": 5000
        }])

        self.mock_kite.quote.return_value = {"NFO:SIEMENS26SEP3950CE": {"last_price": 37.45}}
        
        with patch("common.position_monitor._load_program_config_file", return_value={}), \
             patch("common.position_monitor.fetch_and_resample_candles", return_value=mock_df), \
             patch("common.trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "NRML", "nifty50",
                "15minute", trade_db, self.dummy_log, live=False
            )

            # Expected: Near-T1 target is 38.05. Live LTP is 37.45.
            # Since 38.05 >= 37.45, clamp applies: round(37.45 * 0.98 / 0.05) * 0.05 = 36.70.
            # 36.70 is strictly greater than 27.05, so current_sl must ratchet to 36.70!
            self.assertIn(sym, positions)
            self.assertEqual(positions[sym]["current_sl"], 36.70)
            print(f"[TEST 1 OK] Trailed SL successfully ratcheted to {positions[sym]['current_sl']} (safely clamped below LTP 37.45)")

    def test_option_multi_tier_gain_locks(self):
        """Test extended gain tiers (+30% -> +20%, +40% -> +25%, +50% -> +35%, +70% -> +50%)."""
        sym = "TCS"
        entry_p = 100.0
        
        positions = {
            sym: {
                "symbol": sym,
                "contract": "TCS26SEP3500CE",
                "option_token": 11111,
                "token": 11111,
                "entry_spot": entry_p,
                "current_sl": 110.0, # at +10%
                "t1": 200.0, # T1 is far away
                "position_size": 1,
                "quantity": 175,
                "trailing_stage": 1,
                "side": "CE",
                "engine": "nifty50",
                "entry_time": (dt.now() - timedelta(hours=2)).isoformat()
            }
        }
        
        mock_df = pd.DataFrame([{
            "date": (dt.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
            "open": 110.0,
            "high": 145.0, # +45% gain!
            "low": 105.0,
            "close": 142.0,
            "volume": 2000
        }])
        self.mock_kite.quote.return_value = {"NFO:TCS26SEP3500CE": {"last_price": 142.0}}

        with patch("common.position_monitor._load_program_config_file", return_value={}), \
             patch("common.position_monitor.fetch_and_resample_candles", return_value=mock_df), \
             patch("common.trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {}, positions, self.lock, "NRML", "nifty50",
                "15minute", trade_db, self.dummy_log, live=False
            )

            # At +45% gain (>= 40% tier), SL locks at Entry + 25% = 125.00
            self.assertEqual(positions[sym]["current_sl"], 125.00)
            print(f"[TEST 2 OK] +45% peak gain successfully locked SL at {positions[sym]['current_sl']} (+25% gain lock)")

    def test_short_stock_near_t1_and_gain_lock(self):
        """Test bearish equity Near-T1 lock (falling to within 90% of target distance)."""
        sym = "INFY"
        entry_p = 1000.0
        t1 = 900.0 # Target dist = 100. 90% level = 910. 70% lock = 930.
        
        positions = {
            sym: {
                "symbol": sym,
                "contract": "INFY",
                "option_token": 408065,
                "token": 408065,
                "entry_spot": entry_p,
                "current_sl": 1020.0,
                "t1": t1,
                "t2": 850.0, # has higher targets
                "position_size": 10,
                "quantity": 10,
                "trailing_stage": 0,
                "side": "SELL",
                "direction": "BEAR",
                "position_type": "stock",
                "engine": "stock_bearish",
                "entry_time": (dt.now() - timedelta(hours=2)).isoformat()
            }
        }
        
        # Price drops to 910 (<= 910 Near-T1 threshold), but above T1 buffer
        mock_df = pd.DataFrame([{
            "date": (dt.now() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S"),
            "open": 950.0,
            "high": 960.0,
            "low": 910.0,
            "close": 915.0,
            "volume": 2000
        }])
        self.mock_kite.quote.return_value = {"NSE:INFY": {"last_price": 915.0}}

        with patch("common.position_monitor._load_program_config_file", return_value={"tranche_mode": False}), \
             patch("common.position_monitor.fetch_and_resample_candles", return_value=mock_df), \
             patch("common.trade_db.update_trade"):

            position_monitor.monitor_active_positions(
                self.mock_kite, {"INFY": {"token": 408065}}, positions, self.lock, "MIS", "stock_bearish",
                "15minute", trade_db, self.dummy_log, live=False
            )

            # Short SL ratchets downwards to 930.00 (locking in 70% of the drop)
            self.assertEqual(positions[sym]["current_sl"], 930.00)
            print(f"[TEST 3 OK] Short equity Near-T1 successfully ratcheted SL down to {positions[sym]['current_sl']}")

if __name__ == "__main__":
    unittest.main()
