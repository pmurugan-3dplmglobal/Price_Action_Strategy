import unittest
from unittest.mock import MagicMock
import sys
import os

# Ensure canonical imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))

from common.portfolio_risk import (
    check_portfolio_risk_caps,
    _extract_underlying_symbol,
    _load_portfolio_risk_config
)


class TestPortfolioRiskAndSpreadMode(unittest.TestCase):

    def test_extract_underlying_symbol(self):
        self.assertEqual(_extract_underlying_symbol("NIFTY2691523400CE"), "NIFTY")
        self.assertEqual(_extract_underlying_symbol("BANKNIFTY26SEP56400CE"), "BANKNIFTY")
        self.assertEqual(_extract_underlying_symbol("SENSEX2691074700CE"), "SENSEX")
        self.assertEqual(_extract_underlying_symbol("ADANIENSOL26SEP1440CE"), "ADANIENSOL")
        self.assertEqual(_extract_underlying_symbol("ADANIENSOL26SEP1500CE"), "ADANIENSOL")
        self.assertEqual(_extract_underlying_symbol("ADANIPOWER26SEP210PE"), "ADANIPOWER")
        self.assertEqual(_extract_underlying_symbol("UNITDSPR26SEP1400CE"), "UNITDSPR")
        self.assertEqual(_extract_underlying_symbol("360ONE26SEP1120CE"), "360ONE")
        self.assertEqual(_extract_underlying_symbol("INFY"), "INFY")
        self.assertEqual(_extract_underlying_symbol("TCS"), "TCS")

    def test_broker_ground_truth_blocks_when_6_scripts_held(self):
        # Mock Kite session returning 6 open positions across diverse instruments
        mock_kite = MagicMock()
        mock_kite.positions.return_value = {
            "net": [
                {"tradingsymbol": "INFY", "quantity": -1, "product": "MIS", "pnl": 10.0},
                {"tradingsymbol": "NIFTY2691523400CE", "quantity": 130, "product": "NRML", "pnl": 1500.0},
                {"tradingsymbol": "BANKNIFTY26SEP56400CE", "quantity": 30, "product": "NRML", "pnl": 800.0},
                {"tradingsymbol": "UNITDSPR26SEP1400CE", "quantity": 400, "product": "NRML", "pnl": 1200.0},
                {"tradingsymbol": "SENSEX2691074700CE", "quantity": 20, "product": "NRML", "pnl": 400.0},
                {"tradingsymbol": "ADANIPOWER26SEP210PE", "quantity": 3550, "product": "NRML", "pnl": -500.0}
            ]
        }

        # Candidate #7 (e.g. INDUSINDBK) must be blocked
        allowed, reason, details = check_portfolio_risk_caps(
            engine="nifty50",
            symbol="INDUSINDBK",
            candidate_tier=1,
            capital=100000.0,
            live_positions={},
            config={"enable": True, "max_concurrent_positions": 6, "max_daily_loss_pct": 5.0},
            include_db_trades=False,
            kite=mock_kite
        )
        self.assertFalse(allowed, f"Expected 7th script to be blocked, but was allowed: {reason}")
        self.assertIn("MAX_CONCURRENT_POSITIONS_REACHED", reason)
        self.assertEqual(details["active_count"], 6)

    def test_debit_spread_counted_as_single_script(self):
        # Mock Kite session returning a 2-leg Debit Spread on ADANIENSOL (1 Long Call + 1 Short Call)
        mock_kite = MagicMock()
        mock_kite.positions.return_value = {
            "net": [
                {"tradingsymbol": "ADANIENSOL26SEP1440CE", "quantity": 675, "product": "NRML", "pnl": 200.0},
                {"tradingsymbol": "ADANIENSOL26SEP1500CE", "quantity": -675, "product": "NRML", "pnl": -100.0}
            ]
        }

        # With 1 script active out of 6, candidate #2 (TCS) must be ALLOWED
        allowed, reason, details = check_portfolio_risk_caps(
            engine="nifty50",
            symbol="TCS",
            candidate_tier=1,
            capital=100000.0,
            live_positions={},
            config={"enable": True, "max_concurrent_positions": 6, "max_daily_loss_pct": 5.0},
            include_db_trades=False,
            kite=mock_kite
        )
        self.assertTrue(allowed, f"Expected candidate to be allowed with 1 active script, got: {reason}")

    def test_spread_mode_evaluation_logic(self):
        # Test all configuration values for execution_mode
        def compute_use_spread(exec_mode, tf_entry):
            em = str(exec_mode).upper()
            return (em in ["DEBIT_SPREAD", "SPREAD_ONLY"]) or (
                em == "AUTO" and tf_entry in ["15minute", "30minute", "60minute", "day"]
            )

        self.assertTrue(compute_use_spread("DEBIT_SPREAD", "15minute"))
        self.assertTrue(compute_use_spread("DEBIT_SPREAD", "3minute"))
        self.assertTrue(compute_use_spread("SPREAD_ONLY", "15minute"))
        self.assertTrue(compute_use_spread("AUTO", "15minute"))
        self.assertTrue(compute_use_spread("AUTO", "30minute"))
        self.assertFalse(compute_use_spread("AUTO", "3minute"))
        self.assertFalse(compute_use_spread("NAKED_ONLY", "15minute"))
        self.assertFalse(compute_use_spread("NAKED_ONLY", "30minute"))


if __name__ == "__main__":
    unittest.main()
