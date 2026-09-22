import os
import sys
import unittest
import json
from unittest.mock import MagicMock
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import trade_db
import portfolio_risk


class TestPortfolioRiskGhostTradeReconciliation(unittest.TestCase):

    def setUp(self):
        self.test_engine = "unit_test_risk_engine"
        for t in trade_db.get_active_trades(self.test_engine):
            trade_db.update_trade_status(t["id"], "CLOSED_EXTERNALLY")

    def tearDown(self):
        for t in trade_db.get_active_trades(self.test_engine):
            trade_db.update_trade_status(t["id"], "CLOSED_EXTERNALLY")

    def test_ghost_trades_ignored_and_auto_reconciled_when_broker_connected(self):
        # 1. Create 2 ghost trades in trade_db with prior timestamps (> 5 mins ago)
        tid1, _ = trade_db.create_trade(
            self.test_engine,
            "GHOSTSTOCKA",
            {
                "contract": "GHOSTSTOCKA26SEP100CE",
                "status": "ACTIVE",
                "entry_spot": 100.0,
                "current_sl": 90.0,
                "t1": 120.0
            }
        )
        tid2, _ = trade_db.create_trade(
            self.test_engine,
            "GHOSTSTOCKB",
            {
                "contract": "GHOSTSTOCKB26SEP200PE",
                "status": "ACTIVE",
                "entry_spot": 200.0,
                "current_sl": 210.0,
                "t1": 180.0
            }
        )

        self.assertIsNotNone(tid1)
        self.assertIsNotNone(tid2)

        # Backdate both ghost trades in the DB so they are older than the 60s in-flight grace window
        old_time = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
        with trade_db._get_connection() as conn:
            for tid in [tid1, tid2]:
                row = conn.execute("SELECT data_json FROM trades WHERE id=?", (tid,)).fetchone()
                if row:
                    d = json.loads(row["data_json"])
                    d["entry_time"] = old_time
                    d["created_at"] = old_time
                    conn.execute("UPDATE trades SET created_at=?, data_json=? WHERE id=?", (old_time, json.dumps(d), tid))

        # Verify they are currently active in trade_db
        active_before = [x["id"] for x in trade_db.get_active_trades(self.test_engine)]
        self.assertIn(tid1, active_before)
        self.assertIn(tid2, active_before)

        # 2. Mock Kite session returning only 1 real active position (RELIANCE)
        mock_kite = MagicMock()
        mock_kite.positions.return_value = {
            "net": [
                {"tradingsymbol": "RELIANCE26SEP3000CE", "quantity": 250, "exchange": "NFO"},
                {"tradingsymbol": "GHOSTSTOCKA26SEP100CE", "quantity": 0, "exchange": "NFO"}
            ]
        }
        mock_kite.holdings.return_value = []

        # 3. Check portfolio risk for a candidate symbol (e.g. INFY)
        is_allowed, reason, meta = portfolio_risk.check_portfolio_risk_caps(
            engine=self.test_engine,
            symbol="INFY",
            candidate_tier=1,
            capital=100000.0,
            kite=mock_kite
        )

        # Candidate INFY must be allowed because real broker only has 1 position (RELIANCE)
        self.assertTrue(is_allowed, f"Expected allowed, got reason: {reason}")
        self.assertEqual(reason, "PORTFOLIO_RISK_APPROVED")

        # 4. Verify ghost trades were auto-reconciled in trade_db
        active_after = [x["id"] for x in trade_db.get_active_trades(self.test_engine)]
        self.assertNotIn(tid1, active_after)
        self.assertNotIn(tid2, active_after)

    def test_actual_broker_capacity_full_blocks_trade(self):
        # Mock Kite session returning 6 real positions on broker
        mock_kite = MagicMock()
        mock_kite.positions.return_value = {
            "net": [
                {"tradingsymbol": "RELIANCE26SEP3000CE", "quantity": 250, "exchange": "NFO"},
                {"tradingsymbol": "TCS26SEP4000CE", "quantity": 175, "exchange": "NFO"},
                {"tradingsymbol": "INFY26SEP1800CE", "quantity": 400, "exchange": "NFO"},
                {"tradingsymbol": "HDFCBANK26SEP1600CE", "quantity": 550, "exchange": "NFO"},
                {"tradingsymbol": "ICICIBANK26SEP1200CE", "quantity": 700, "exchange": "NFO"},
                {"tradingsymbol": "AXISBANK26SEP1100CE", "quantity": 625, "exchange": "NFO"},
            ]
        }
        mock_kite.holdings.return_value = []

        is_allowed, reason, meta = portfolio_risk.check_portfolio_risk_caps(
            engine=self.test_engine,
            symbol="SBIN",
            candidate_tier=1,
            capital=100000.0,
            kite=mock_kite
        )

        self.assertFalse(is_allowed)
        self.assertIn("MAX_CONCURRENT_POSITIONS_REACHED", reason)


if __name__ == "__main__":
    unittest.main()
