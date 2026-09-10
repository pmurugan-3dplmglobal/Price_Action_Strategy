import os
import sys
import unittest
import pandas as pd
from unittest.mock import patch, MagicMock

# Canonical path setup
PROJECT_ROOT = r"g:\Poovendan\AI\Trading\Share\ReadyToDeploy\Prod_code_01\Price_Action_Strategy"
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
from targets import calculate_option_atr_sl, calculate_sl_buffer
from position_monitor import is_global_halt, is_new_entry_allowed
from portfolio_risk import check_portfolio_risk_caps, _load_portfolio_risk_config


class TestP0RiskHardening(unittest.TestCase):
    """Unit tests for P0 Risk Hardening (ISSUE-104)."""

    def setUp(self):
        # Clean up any test HALT file
        if os.path.exists(paths.GLOBAL_HALT_FILE):
            try:
                os.remove(paths.GLOBAL_HALT_FILE)
            except Exception:
                pass

    def tearDown(self):
        if os.path.exists(paths.GLOBAL_HALT_FILE):
            try:
                os.remove(paths.GLOBAL_HALT_FILE)
            except Exception:
                pass

    def test_01_atr_sl_widening_tight_geometric(self):
        """Tight geometric SL on options is widened to at least 1.5 * ATR."""
        entry_price = 100.0
        # Geometric SL only 1 point away (1% drop)
        geometric_sl = 99.0
        # ATR = 4.0 -> 1.5 * ATR = 6.0 points minimum distance
        widened_sl = calculate_option_atr_sl(entry_price=entry_price, geometric_sl=geometric_sl, atr=4.0, multiplier=1.5)
        # Expected SL = 100 - 6.0 = 94.0
        self.assertEqual(widened_sl, 94.0)
        self.assertLess(widened_sl, geometric_sl)

    def test_02_atr_sl_preserves_wider_geometric(self):
        """Wider geometric SL that exceeds ATR distance is preserved."""
        entry_price = 100.0
        geometric_sl = 88.0  # 12 pts distance
        atr = 4.0  # 1.5 * 4 = 6 pts distance
        sl = calculate_option_atr_sl(entry_price=entry_price, geometric_sl=geometric_sl, atr=atr, multiplier=1.5)
        # Should preserve 88.0 since 12 pts > 6 pts
        self.assertEqual(sl, 88.0)

    def test_03_atr_sl_capped_at_max_risk_pct(self):
        """ATR SL distance is capped at max_risk_pct (30%) to prevent excessive drawdown."""
        entry_price = 100.0
        geometric_sl = 95.0
        atr = 30.0  # 1.5 * 30 = 45 pts (would be 45% loss)
        sl = calculate_option_atr_sl(entry_price=entry_price, geometric_sl=geometric_sl, atr=atr, multiplier=1.5, max_risk_pct=0.30)
        # 30% of 100 = 30 pts max risk -> SL = 70.0
        self.assertEqual(sl, 70.0)

    def test_04_atr_sl_from_candle_dataframe(self):
        """ATR SL calculated directly from DataFrame candle history."""
        df = pd.DataFrame({
            "high": [102.0] * 15,
            "low": [100.0] * 15,
            "close": [101.0] * 15
        })
        # TR = 2.0 -> 1.5 * 2.0 = 3.0 pts
        sl = calculate_option_atr_sl(entry_price=101.0, geometric_sl=100.5, df_candles=df, multiplier=1.5)
        # Expected: 101.0 - 3.0 = 98.0
        self.assertEqual(sl, 98.0)

    def test_05_global_halt_file_detection(self):
        """Creating input/HALT causes is_global_halt() to return True."""
        self.assertFalse(is_global_halt())
        os.makedirs(paths.INPUT_DIR, exist_ok=True)
        with open(paths.GLOBAL_HALT_FILE, "w", encoding="utf-8") as f:
            f.write("TEST_HALT\n")
        self.assertTrue(is_global_halt())

    def test_06_global_halt_blocks_new_entries(self):
        """is_new_entry_allowed() returns False when HALT file exists."""
        with open(paths.GLOBAL_HALT_FILE, "w", encoding="utf-8") as f:
            f.write("TEST_HALT\n")
        self.assertFalse(is_new_entry_allowed(live_execution_active=True))
        self.assertFalse(is_new_entry_allowed(live_execution_active=False))

    def test_07_global_halt_blocks_portfolio_risk(self):
        """check_portfolio_risk_caps() returns False when HALT file exists."""
        with open(paths.GLOBAL_HALT_FILE, "w", encoding="utf-8") as f:
            f.write("TEST_HALT\n")
        allowed, reason, details = check_portfolio_risk_caps(
            engine="index", symbol="NIFTY", include_db_trades=False
        )
        self.assertFalse(allowed)
        self.assertEqual(details.get("rule"), "global_halt")
        self.assertIn("GLOBAL_HALT_ACTIVE", reason)

    def test_08_engine_specific_daily_loss_config(self):
        """Index engine resolves 3% max daily loss, while stock defaults to 5%."""
        cfg_index = _load_portfolio_risk_config(engine="index")
        self.assertEqual(cfg_index["max_daily_loss_pct"], 3.0)

        cfg_stock = _load_portfolio_risk_config(engine="nifty50")
        self.assertEqual(cfg_stock["max_daily_loss_pct"], 5.0)

    @patch("portfolio_risk.trade_db.get_all_trades")
    def test_09_phantom_trades_excluded_from_drawdown(self, mock_trades):
        """Phantom trades with zero PnL and RECONCILED are excluded from daily loss sum."""
        from datetime import datetime as dt
        today = dt.now().strftime("%Y-%m-%d")
        mock_trades.return_value = [
            # Real loss: -15% on 200 entry with lot 20 = -₹600
            {
                "created_at": f"{today}T10:00:00",
                "exit_time": f"{today}T10:30:00",
                "status": "SL_HIT",
                "pnl_percent": -15.0,
                "entry_spot": 200.0,
                "lot_size": 20,
                "position_size": 1,
                "exit_reason": "STOP_LOSS"
            },
            # Phantom trade: 0% PnL, BROKER_NET_QTY_ZERO_RECONCILED
            {
                "created_at": f"{today}T11:00:00",
                "exit_time": f"{today}T11:01:00",
                "status": "COMPLETED",
                "pnl_percent": 0.0,
                "entry_spot": 500.0,
                "lot_size": 50,
                "position_size": 1,
                "exit_reason": "BROKER_NET_QTY_ZERO_RECONCILED"
            }
        ]
        allowed, reason, details = check_portfolio_risk_caps(
            engine="index", symbol="BANKNIFTY", capital=100000.0, include_db_trades=True
        )
        self.assertTrue(allowed)
        self.assertEqual(details.get("today_realized_pnl_inr"), -600.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
