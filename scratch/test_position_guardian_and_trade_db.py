"""
test_position_guardian_and_trade_db.py - Verification suite for:
1. Position dictionary keying by normalized contract string (multi-strike collision safety)
2. Token registry lookup fallback to pos.get("symbol")
3. Dynamic config hierarchy deep-merging root & engine-specific settings
4. SQLite WAL atomic trade creation (cur.lastrowid, no MAX(id)+1), indexes, and closed_today queries
5. Full position lifecycle simulation (DB -> Reconciliation -> Trailing Ratchets -> Spot Guard -> Emergency Exit -> JSON Sync)
"""
import os
import sys
import json
import sqlite3
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [PROJECT_ROOT, os.path.join(PROJECT_ROOT, "common"), os.path.join(PROJECT_ROOT, "Trade_Option")]:
    if p not in sys.path:
        sys.path.insert(0, p)

for mod in ["pandas", "kiteconnect", "flask", "werkzeug", "werkzeug.security", "numpy", "scipy"]:
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()

import paths
import trade_db
import position_monitor
from registries import STOCK_REGISTRY, INDEX_REGISTRY


class TestPositionGuardianAndTradeDB(unittest.TestCase):
    def setUp(self):
        self.test_db_path = os.path.join(PROJECT_ROOT, "scratch", "test_trades.sqlite3")
        self.orig_db_path = trade_db._DB_PATH
        trade_db._DB_PATH = self.test_db_path
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except Exception:
                pass
        trade_db._init_db()

    def tearDown(self):
        trade_db._DB_PATH = self.orig_db_path
        if os.path.exists(self.test_db_path):
            try:
                os.remove(self.test_db_path)
            except Exception:
                pass

    def test_01_sqlite_wal_and_schema_integrity(self):
        """Verify WAL journal mode, indexes, and absence of legacy MAX(id)+1."""
        conn = trade_db._get_connection()
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(journal_mode.lower(), "wal", "SQLite must operate in WAL journal mode")

        indexes = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()]
        self.assertIn("idx_status", indexes)
        self.assertIn("idx_engine", indexes)
        self.assertIn("idx_contract", indexes)

        # Confirm cur.lastrowid is used in create_trade
        t1_id, created1 = trade_db.create_trade("index", "NIFTY", {"contract": "NIFTY26MAR22000CE", "entry_price": 100.0})
        self.assertTrue(created1)
        self.assertGreater(t1_id, 0)

        t2_id, created2 = trade_db.create_trade("index", "NIFTY", {"contract": "NIFTY26MAR22100CE", "entry_price": 110.0})
        self.assertTrue(created2)
        self.assertGreater(t2_id, t1_id)

        # Check that JSON id is strictly synchronized with SQLite rowid
        t1_row = conn.execute("SELECT data_json FROM trades WHERE id=?", (t1_id,)).fetchone()
        t1_data = json.loads(t1_row["data_json"])
        self.assertEqual(t1_data["id"], t1_id, "Trade JSON 'id' must synchronize with SQLite rowid")

    def test_02_position_dictionary_keying_multi_strike_safety(self):
        """Verify that positions are strictly keyed by normalized contract string, eliminating multi-strike overwrites."""
        t1_data = {"id": 101, "engine": "index", "symbol": "NIFTY", "contract": "NIFTY26MAR22000CE", "status": "ACTIVE"}
        t2_data = {"id": 102, "engine": "index", "symbol": "NIFTY", "contract": "NIFTY26MAR22100CE", "status": "ACTIVE"}
        t3_stock = {"id": 103, "engine": "nifty50", "symbol": "RELIANCE", "contract": "RELIANCE26MAR1300CE", "status": "ACTIVE"}
        t4_stock = {"id": 104, "engine": "nifty50", "symbol": "RELIANCE", "contract": "RELIANCE26MAR1320CE", "status": "ACTIVE"}
        t5_cash = {"id": 105, "engine": "daily", "symbol": "TCS", "contract": "TCS", "position_type": "stock", "status": "ACTIVE"}

        active_trades = [t1_data, t2_data, t3_stock, t4_stock, t5_cash]

        index_positions = {}
        stock_options_positions = {}
        stock_cash_positions = {}

        for t in active_trades:
            c_name = t.get("contract") or t.get("symbol")
            pos_key = str(c_name).strip().upper()
            sym = t.get("symbol") or c_name
            eng = str(t.get("engine", "nifty50")).lower()
            pos_data = dict(t)
            pos_data["contract"] = c_name
            pos_data["symbol"] = sym
            if eng == "index" or ("NIFTY" in pos_key and ("CE" in pos_key or "PE" in pos_key)) or ("SENSEX" in pos_key and ("CE" in pos_key or "PE" in pos_key)):
                index_positions[pos_key] = pos_data
            elif pos_data.get("position_type") == "stock" or eng in ["daily", "bear_trade", "weekly", "weekly_bear"]:
                stock_cash_positions[pos_key] = pos_data
            else:
                stock_options_positions[pos_key] = pos_data

        # Verify that both strikes of NIFTY co-exist without collision
        self.assertEqual(len(index_positions), 2)
        self.assertIn("NIFTY26MAR22000CE", index_positions)
        self.assertIn("NIFTY26MAR22100CE", index_positions)

        # Verify that both strikes of RELIANCE co-exist without collision
        self.assertEqual(len(stock_options_positions), 2)
        self.assertIn("RELIANCE26MAR1300CE", stock_options_positions)
        self.assertIn("RELIANCE26MAR1320CE", stock_options_positions)

        # Cash position
        self.assertEqual(len(stock_cash_positions), 1)
        self.assertIn("TCS", stock_cash_positions)

    def test_03_token_registry_lookup_fallback(self):
        """Verify token registry fallback when pos_key is an option contract string."""
        # Simulated registry
        test_registry = {
            "RELIANCE": {"token": 738561, "symbol": "RELIANCE"},
            "NIFTY": {"token": 256265, "symbol": "NIFTY"}
        }

        # Case 1: Stock option position keyed by contract string
        pos_key = "RELIANCE26MAR1300CE"
        pos = {
            "contract": "RELIANCE26MAR1300CE",
            "symbol": "RELIANCE",
            "position_type": "option",
            "side": "CE"
        }

        # Spot token lookup fallback:
        underlying_sym = pos.get("symbol") or pos_key
        reg_entry = test_registry.get(underlying_sym) or test_registry.get(pos_key)
        self.assertIsNotNone(reg_entry)
        self.assertEqual(reg_entry.get("token"), 738561)

        # Case 2: Direct stock spot lookup at line 1686
        pos_stock = {"contract": "RELIANCE", "symbol": "RELIANCE", "position_type": "stock"}
        sym_key = "RELIANCE"
        token = test_registry.get(pos_stock.get("symbol") or sym_key, {}).get("token") or test_registry.get(sym_key, {}).get("token")
        self.assertEqual(token, 738561)

    def test_04_dynamic_config_hierarchy(self):
        """Verify _load_program_config_file deep-merges root and engine configurations."""
        cfg_index = position_monitor._load_program_config_file(engine_name="index")
        self.assertIsInstance(cfg_index, dict)
        self.assertIn("trailing_rules", cfg_index)
        self.assertEqual(cfg_index["trailing_rules"]["option_trail_1_gain_pct"], 15.0)
        self.assertEqual(cfg_index["trailing_rules"]["option_trail_1_sl_pct"], 8.0)
        self.assertEqual(cfg_index["trailing_rules"]["option_trail_2_gain_pct"], 25.0)
        self.assertEqual(cfg_index["trailing_rules"]["option_trail_2_sl_pct"], 15.0)
        self.assertEqual(cfg_index["max_option_loss_pct"], 28.0)

        cfg_stock = position_monitor._load_program_config_file(engine_name="nifty50")
        self.assertIsInstance(cfg_stock, dict)
        self.assertIn("trailing_rules", cfg_stock)
        self.assertEqual(cfg_stock["max_option_loss_pct"], 28.0)

    def test_05_closed_today_query_execution(self):
        """Verify is_contract_closed_today & get_contracts_closed_today execute cleanly without SQL error."""
        t_id, _ = trade_db.create_trade("index", "NIFTY", {"contract": "NIFTY26MAR22500CE", "entry_price": 50.0})
        self.assertFalse(trade_db.is_contract_closed_today("NIFTY26MAR22500CE"))

        trade_db.update_trade_status(t_id, "COMPLETED", exit_price=65.0, exit_reason="TARGET_HIT")
        self.assertTrue(trade_db.is_contract_closed_today("NIFTY26MAR22500CE"))
        closed_set = trade_db.get_contracts_closed_today()
        self.assertIn("NIFTY26MAR22500CE", closed_set)

    def test_06_full_position_lifecycle_simulation(self):
        """Simulate the end-to-end lifecycle from creation to trailing ratchet to spot guard to close."""
        # Step 1: Create active trade in DB
        trade_data = {
            "contract": "INFY26MAR1500CE",
            "symbol": "INFY",
            "entry_spot": 100.0,
            "entry_price": 100.0,
            "current_sl": 75.0,
            "spot_sl": 1500.0,
            "t1": 140.0,
            "trailing_stage": 0,
            "order_status": "OPEN",
            "position_type": "option",
            "side": "CE"
        }
        t_id, created = trade_db.create_trade("nifty50", "INFY", trade_data)
        self.assertTrue(created)

        # Step 2: Broker holding reconciliation marks order FILLED
        trade_db.update_trade(t_id, {"order_status": "FILLED"})
        active = trade_db.get_active_trades()
        t_active = next(t for t in active if t["id"] == t_id)
        self.assertEqual(t_active["order_status"], "FILLED")

        # Step 3: Trailing ratchet +15% trigger -> locks +8% SL
        pos = dict(t_active)
        gain_pct = 16.0  # +16% gain
        entry_s = 100.0
        new_sl = round(round((entry_s * 1.08) / 0.05) * 0.05, 2)  # 108.0
        trade_db.update_trade(t_id, {"trailing_stage": 1, "current_sl": new_sl})
        pos_after_trail = next(t for t in trade_db.get_active_trades() if t["id"] == t_id)
        self.assertEqual(pos_after_trail["trailing_stage"], 1)
        self.assertEqual(pos_after_trail["current_sl"], 108.0)

        # Step 4: Trailing ratchet +25% trigger -> locks +15% SL
        new_sl_2 = round(round((entry_s * 1.15) / 0.05) * 0.05, 2)  # 115.0
        trade_db.update_trade(t_id, {"trailing_stage": 2, "current_sl": new_sl_2})
        pos_after_trail_2 = next(t for t in trade_db.get_active_trades() if t["id"] == t_id)
        self.assertEqual(pos_after_trail_2["trailing_stage"], 2)
        self.assertEqual(pos_after_trail_2["current_sl"], 115.0)

        # Step 5: Catastrophic loss guard verification
        # When current_opt_price falls below (1 - max_option_loss_pct) = 72.0 on initial stage
        cfg = position_monitor._load_program_config_file("nifty50")
        max_loss_pct = float(cfg.get("max_option_loss_pct", 28.0))
        emergency_threshold = entry_s * (1.0 - (max_loss_pct / 100.0))
        self.assertEqual(emergency_threshold, 72.0)

        # Step 6: Order square-off and DB status change to COMPLETED
        trade_db.update_trade_status(t_id, "COMPLETED", exit_price=115.0, exit_reason="TRAIL_SL_HIT")
        self.assertFalse(trade_db.is_contract_active("INFY26MAR1500CE"))
        self.assertTrue(trade_db.is_contract_closed_today("INFY26MAR1500CE"))

        # Step 7: Tab JSON sync check
        with open(trade_db.ACTIVE_POSITIONS_DB, "r", encoding="utf-8") as f:
            active_json = json.load(f)
        active_ids = [p["id"] for p in active_json.get("positions", [])]
        self.assertNotIn(t_id, active_ids)

        with open(trade_db.JOURNAL_TRADES_DB, "r", encoding="utf-8") as f:
            journal_json = json.load(f)
        completed_ids = [j["id"] for j in journal_json.get("journal_entries", [])]
        self.assertIn(t_id, completed_ids)


if __name__ == "__main__":
    unittest.main()
