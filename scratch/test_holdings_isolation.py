import unittest
from unittest.mock import MagicMock
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from portfolio_risk import check_portfolio_risk_caps

class TestHoldingsIsolation(unittest.TestCase):
    def test_personal_demat_holdings_not_counted_in_active_fno_slots(self):
        """Verify that Demat CNC holdings (e.g. SGB, GoldBees, long-term stocks)
        do not consume active trading slots for F&O and intraday engines."""
        mock_kite = MagicMock()
        # Mock 0 net positions
        mock_kite.positions.return_value = {"net": []}
        # Mock 7 personal Demat holdings
        mock_kite.holdings.return_value = [
            {"tradingsymbol": "BATAINDIA", "quantity": 10},
            {"tradingsymbol": "GOLDBEES", "quantity": 2},
            {"tradingsymbol": "INDIASHLTR", "quantity": 10},
            {"tradingsymbol": "NIFTYBEES", "quantity": 1},
            {"tradingsymbol": "SGBJUN28-GB", "quantity": 10},
            {"tradingsymbol": "SILVERBEES", "quantity": 281},
            {"tradingsymbol": "UTIAMC", "quantity": 10},
        ]
        
        allowed, reason, diag = check_portfolio_risk_caps(
            engine="nifty50",
            symbol="INFY",
            candidate_tier=1,
            capital=100000.0,
            live_positions={},
            include_db_trades=False,
            kite=mock_kite
        )
        
        self.assertTrue(allowed, f"Candidate should be allowed when 0 active trades exist, but got: {reason}")
        self.assertEqual(diag.get("active_count", 0), 0, f"Active count should be 0, got {diag.get('active_count')}")

if __name__ == "__main__":
    unittest.main()
