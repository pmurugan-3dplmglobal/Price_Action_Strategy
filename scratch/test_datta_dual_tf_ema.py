import os
import sys
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

# Ensure common is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))
import ema_engine

class TestDattaDualTfEmaEngine(unittest.TestCase):
    def setUp(self):
        self.mock_kite = MagicMock()
        self.symbol = "TATAMOTORS"
        self.info = {"token": 884737, "strike_step": 10, "lot_size": 550}

    def _create_mock_df(self, count, base_price, trend="up"):
        dates = pd.date_range("2026-08-01 09:15:00", periods=count, freq="D")
        if trend == "up":
            closes = np.linspace(base_price - 50, base_price, count)
        elif trend == "down":
            closes = np.linspace(base_price + 50, base_price, count)
        else:
            closes = np.full(count, base_price)

        df = pd.DataFrame({
            "date": dates,
            "open": closes - 1.0,
            "high": closes + 2.0,
            "low": closes - 2.0,
            "close": closes,
            "volume": [10000] * count
        })
        return df

    def test_step1_daily_disqualification_fail_fast(self):
        """Test Step 1: When Daily Close <= EMA, rejected immediately without fetching 1H"""
        # Daily candles where price is dropping below both EMAs
        df_daily_bear = self._create_mock_df(60, 900.0, trend="down")
        # Ensure the last close is well below both EMAs
        df_daily_bear.loc[df_daily_bear.index[-1], "close"] = 800.0

        with patch("ema_engine.fetch_and_resample_candles") as mock_fetch:
            mock_fetch.return_value = df_daily_bear

            res = ema_engine.detect_datta_dual_tf_ema_pattern(self.mock_kite, self.symbol, self.info)
            
            self.assertIsNone(res, "Setup should be disqualified at Step 1 (Daily close <= EMA)")
            # Verify fail-fast: Only 1 fetch call was made (Daily). 1-Hour fetch was NEVER called!
            self.assertEqual(mock_fetch.call_count, 1)
            call_tf = mock_fetch.call_args[0][4]
            self.assertEqual(call_tf, "1d", "Only Daily candles should have been fetched")

    def test_step2_1hour_disqualification(self):
        """Test Step 2: When Daily Close > EMA, but 1-Hour Close <= EMA, rejected at Step 2"""
        df_daily_bull = self._create_mock_df(60, 900.0, trend="up")
        # 1-Hour candles where close is below EMAs
        df_1h_bear = self._create_mock_df(60, 850.0, trend="down")
        df_1h_bear.loc[df_1h_bear.index[-1], "close"] = 800.0

        with patch("ema_engine.fetch_and_resample_candles") as mock_fetch:
            # First call returns Daily, second call returns 1-Hour
            mock_fetch.side_effect = [df_daily_bull, df_1h_bear]

            res = ema_engine.detect_datta_dual_tf_ema_pattern(self.mock_kite, self.symbol, self.info)
            self.assertIsNone(res, "Setup should be disqualified at Step 2 (1-Hour close <= EMA)")
            self.assertEqual(mock_fetch.call_count, 2)

    def test_step1_and_step2_qualification_datta_confirmed(self):
        """Test Step 1 & 2 Success: Both Daily & 1-Hour close > EMA -> QUALIFIED DATTA SETUP"""
        df_daily_bull = self._create_mock_df(60, 950.0, trend="up")
        df_1h_bull = self._create_mock_df(60, 955.0, trend="up")

        with patch("ema_engine.fetch_and_resample_candles") as mock_fetch:
            mock_fetch.side_effect = [df_daily_bull, df_1h_bull]

            res = ema_engine.detect_datta_dual_tf_ema_pattern(self.mock_kite, self.symbol, self.info)
            self.assertIsNotNone(res, "Setup must be qualified when both Daily and 1-Hour close > EMA")
            self.assertEqual(res["symbol"], "TATAMOTORS")
            self.assertIn("BULL_", res["pattern"])
            self.assertEqual(res["timeframe"], "BOTH_1D_1HR")
            self.assertGreater(res["spot_price"], res["sl"])
            self.assertGreater(res["t1"], res["spot_price"])
            self.assertGreater(res["t2"], res["t1"])
            self.assertGreater(res["t3"], res["t2"])
            self.assertIn("day_close", res)
            self.assertIn("day_ema13", res)
            self.assertIn("day_ema44", res)

    def test_run_ema_scan_symbol_routes_daily_to_dual_tf(self):
        """Test that run_ema_scan_symbol routes '1d', 'day', 'BOTH_1D_1HR' to dual-TF engine"""
        with patch("ema_engine.detect_datta_dual_tf_ema_pattern") as mock_dual:
            mock_dual.return_value = {"symbol": "TEST", "pattern": "BULL_DAY_1H_EMA_CONFIRMED"}

            for tf in ["1d", "day", "DAILY", "BOTH_1D_1HR", "DATTA_DAY_1HR"]:
                res = ema_engine.run_ema_scan_symbol(self.mock_kite, self.symbol, self.info, timeframe=tf)
                self.assertIsNotNone(res)
                self.assertEqual(res["pattern"], "BULL_DAY_1H_EMA_CONFIRMED")
            
            self.assertEqual(mock_dual.call_count, 5)

    def test_options_and_stock_parity_formatting(self):
        """Test execute_ema_scan_cycle preserves setup pattern, day metrics, and timeframe"""
        mock_setup = {
            "symbol": "TATAMOTORS",
            "spot_price": 950.0,
            "sl": 930.0,
            "t1": 980.0,
            "t2": 1000.0,
            "t3": 1020.0,
            "rr": 1.5,
            "ema13": 945.0,
            "ema44": 935.0,
            "day_close": 950.0,
            "day_ema13": 940.0,
            "day_ema44": 920.0,
            "entry_time": "2026-09-15 10:15:00",
            "candle_a_time": "2026-09-15 10:15:00",
            "pattern": "BULL_DAY_1H_EMA_CONFIRMED",
            "timeframe": "BOTH_1D_1HR"
        }

        with patch("ema_engine.load_kite_session", return_value=("key", "token")), \
             patch("ema_engine.sync_stock_tokens"), \
             patch("ema_engine.get_universe_symbols_and_tokens", return_value=(["TATAMOTORS"], {"TATAMOTORS": 884737})), \
             patch("ema_engine.run_ema_scan_symbol", return_value=mock_setup), \
             patch("ema_engine._atomic_write_json", return_value=True):

            ema_engine._ema_engine_running["option"] = True
            opt_results = ema_engine.execute_ema_scan_cycle(timeframe="1d", is_options_mode=True, target_universe="ALL")
            self.assertEqual(len(opt_results), 1)
            self.assertEqual(opt_results[0]["pattern"], "BULL_DAY_1H_EMA_CONFIRMED")
            self.assertEqual(opt_results[0]["timeframe"], "BOTH_1D_1HR")
            self.assertEqual(opt_results[0]["day_close"], 950.0)

            ema_engine._ema_engine_running["stock"] = True
            stock_results = ema_engine.execute_ema_scan_cycle(timeframe="1d", is_options_mode=False, target_universe="ALL")
            self.assertEqual(len(stock_results), 1)
            self.assertEqual(stock_results[0]["pattern"], "BULL_DAY_1H_EMA_CONFIRMED")
            self.assertEqual(stock_results[0]["timeframe"], "BOTH_1D_1HR")
            self.assertEqual(stock_results[0]["day_close"], 950.0)

if __name__ == "__main__":
    unittest.main()
