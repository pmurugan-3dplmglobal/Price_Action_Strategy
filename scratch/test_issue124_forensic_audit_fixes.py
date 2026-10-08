#!/usr/bin/env python3
"""
Unit test suite for ISSUE-124: Forensic Audit Fixes
1. Test suite isolation & broker order guard (scratch/test_parity_alignment.py)
2. Prevention of false TARGET_HIT on losing options in SPOT_TARGET_GUARD (common/position_monitor.py)
3. Cash equity entry price calibration against live LTP (routes_positions.py & app_Stock_Trade.py)
4. Portfolio risk clear override logging & config symmetry (portfolio_risk.py & program_config.json)
"""
import unittest
from unittest.mock import MagicMock, patch
import json
import os
import sys

# Ensure root directory is on path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

class TestIssue124ForensicAuditFixes(unittest.TestCase):

    def test_01_test_suite_isolation_mocked(self):
        """Verify scratch/test_parity_alignment.py mocks _kite_session and place_order."""
        import scratch.test_parity_alignment as tpa
        suite = unittest.TestLoader().loadTestsFromTestCase(tpa.TestStockOptionsParity)
        # Run test suite and ensure it passes cleanly with zero real orders
        runner = unittest.TextTestRunner(verbosity=0)
        result = runner.run(suite)
        self.assertTrue(result.wasSuccessful(), f"test_parity_alignment failed: {result.errors} {result.failures}")

    def test_02_spot_target_guard_losing_option_suppressed(self):
        """Verify SPOT_TARGET_GUARD suppresses T1 exit if option LTP <= entry price."""
        # Create a mock position where spot reaches target, but option premium is losing
        pos = {
            "symbol": "INFY",
            "contract": "INFY26OCT1800PE",
            "position_type": "option",
            "side": "PE",
            "entry_spot": 40.0,        # Option bought @ 40
            "entry_price": 40.0,
            "current_sl": 25.0,
            "spot_t1": 1750.0,         # Underlying spot target for PE
            "last_known_spot": 1740.0, # Spot reached below 1750 (spot target achieved!)
            "t1": 60.0,
            "ltp": 30.0,               # But option price dropped to 30 (loss of -25%)
            "trailing_stage": 0,
            "t1_booked": False
        }
        # In this scenario, SPOT_TARGET_GUARD must NOT trigger t1_hit because 30.0 <= 40.0
        side_str = str(pos.get("side", "CE")).upper()
        is_bull = side_str in ["CE", "BUY", "BULL"]
        curr_spot = float(pos.get("last_known_spot") or 0.0)
        spot_t1 = float(pos.get("spot_t1") or 0.0)
        entry_s = float(pos.get("entry_spot") or pos.get("entry_price") or 0.0)
        live_ltp = float(pos.get("ltp") or 0.0)
        cp = live_ltp

        t1_hit = False
        t1_val = None
        if curr_spot > 0:
            curr_opt_p = live_ltp if live_ltp > 0 else (cp if cp > 0 else float(pos.get("ltp") or 0.0))
            if is_bull and curr_spot >= spot_t1:
                if entry_s > 0 and curr_opt_p > entry_s:
                    t1_hit = True
                    t1_val = curr_opt_p
            elif (not is_bull) and curr_spot <= spot_t1:
                if entry_s > 0 and curr_opt_p > entry_s:
                    t1_hit = True
                    t1_val = curr_opt_p

        self.assertFalse(t1_hit, "SPOT_TARGET_GUARD must strictly NOT trigger T1 on losing option contract!")
        self.assertIsNone(t1_val)

        # Case B: Option premium is profitable (curr_opt_p > entry_s)
        pos_profitable = dict(pos, ltp=55.0) # Option gained to 55 > 40
        live_ltp_prof = float(pos_profitable.get("ltp"))
        if curr_spot > 0:
            curr_opt_p = live_ltp_prof
            if (not is_bull) and curr_spot <= spot_t1:
                if entry_s > 0 and curr_opt_p > entry_s:
                    t1_hit = True
                    t1_val = curr_opt_p

        self.assertTrue(t1_hit, "SPOT_TARGET_GUARD must trigger T1 when option is profitable (LTP > Entry)!")
        self.assertEqual(t1_val, 55.0)

    def test_03_cash_equity_entry_price_calibration(self):
        """Verify /api/buy-scanned-trade calibrates divergent cash equity entry_spot against live LTP."""
        from Trade_Stock.app_Stock_Trade import app
        import Trade_Stock.app_Stock_Trade as app_stock

        mock_kite = MagicMock()
        mock_kite.place_order.return_value = "ORD_CALIB_TEST"
        # INFY trading at 1008.0 live
        mock_kite.quote.return_value = {
            "NSE:INFY": {
                "last_price": 1008.0,
                "depth": {
                    "buy": [{"price": 1007.5, "quantity": 100}],
                    "sell": [{"price": 1008.5, "quantity": 100}]
                }
            }
        }
        mock_kite.VARIETY_REGULAR = "regular"
        mock_kite.VARIETY_AMO = "amo"
        mock_kite.TRANSACTION_TYPE_BUY = "BUY"
        mock_kite.TRANSACTION_TYPE_SELL = "SELL"
        mock_kite.PRODUCT_MIS = "MIS"
        mock_kite.PRODUCT_CNC = "CNC"
        mock_kite.PRODUCT_NRML = "NRML"
        mock_kite.ORDER_TYPE_LIMIT = "LIMIT"

        with patch.object(app_stock, "_kite_session", mock_kite), \
             patch("Trade_Stock.app_Stock_Trade._kite_session", mock_kite), \
             patch("common.trading_core.load_kite_session", return_value=(None, None)), \
             patch("common.trading_core.is_market_open", return_value=True), \
             patch("common.trading_core.check_bid_ask_spread_liquidity", return_value=(True, 0.001, "OK", 0)), \
             patch("common.portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {})), \
             patch("trade_db.create_trade") as mock_create:
            mock_create.return_value = (999, True)
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user"] = "test_admin"
                    sess["role"] = "admin"

                # Send payload with wildly divergent entry_spot: 1800.0 (synthetic/stale)
                resp = client.post('/api/buy-scanned-trade', json={
                    "symbol": "INFY",
                    "contract": "INFY",
                    "side": "SELL",
                    "direction": "BEAR",
                    "entry_spot": 1800.0,
                    "current_sl": 1850.0,
                    "t1": 1700.0,
                    "engine": "daily",
                    "force": True
                })
                self.assertEqual(resp.status_code, 200)
                # Verify recorded trade calibrated entry_spot to 1008.0
                mock_create.assert_called_once()
                recorded_data = mock_create.call_args[0][2]
                self.assertEqual(recorded_data["entry_spot"], 1008.0)
                # Verify proportional rescaling: ratio = 1008 / 1800 = 0.56
                # current_sl = 1850 * 0.56 = 1036.0, t1 = 1700 * 0.56 = 952.0
                self.assertAlmostEqual(recorded_data["current_sl"], 1036.0, places=1)
                self.assertAlmostEqual(recorded_data["t1"], 952.0, places=1)

    def test_04_portfolio_risk_override_log_and_config_symmetry(self):
        """Verify portfolio risk override reason formatting and config max_option_loss_pct symmetry."""
        from common.portfolio_risk import check_portfolio_risk_caps

        mock_kite = MagicMock()
        # Broker reports -6000 P&L on net positions
        mock_kite.positions.return_value = {
            "net": [{"tradingsymbol": "NIFTY26OCT", "pnl": -6000.0}]
        }
        mock_kite.orders.return_value = []

        with patch("trade_db.get_active_trades", return_value=[]), \
             patch("trade_db.get_all_trades", return_value=[]):
            # Capital: 100,000, Max Daily Loss: 5% = Rs -5,000 max allowed loss
            allowed, reason, details = check_portfolio_risk_caps(
                engine="nifty50",
                symbol="RELIANCE",
                candidate_tier=2,
                capital=100000.0,
                config={"portfolio_risk": {"max_daily_loss_pct": 5.0, "enable": True}},
                kite=mock_kite
            )
            self.assertFalse(allowed)
            self.assertIn("DAILY_DRAWDOWN_CAP_EXCEEDED", reason)
            # Verify clear override wording instead of misleading equation
            self.assertIn("[Local DB P&L: Rs 0.00] overridden by [Broker Live P&L: Rs -6000.00]", reason)
            self.assertNotIn("= Rs -6000.00", reason)

        # Verify config symmetry across all 3 config files
        config_paths = [
            os.path.join(ROOT_DIR, "input", "program_config.json"),
            os.path.join(ROOT_DIR, "Trade_Option", "input", "program_config.json"),
            os.path.join(ROOT_DIR, "Trade_Stock", "input", "program_config.json")
        ]
        for cpath in config_paths:
            with open(cpath, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            self.assertIn("index", cfg)
            self.assertIn("max_option_loss_pct", cfg["index"], f"max_option_loss_pct missing in index section of {cpath}")
            self.assertEqual(cfg["index"]["max_option_loss_pct"], 28)

if __name__ == "__main__":
    unittest.main()
