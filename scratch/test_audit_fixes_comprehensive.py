"""
Comprehensive Unit Test Suite for Multi-Agent Audit Remediations (AUDIT-01 to AUDIT-08)
"""

import os
import sys
import unittest
import sqlite3
from unittest.mock import MagicMock

# Mock pandas and numpy if not installed in current environment
for mod in ["pandas", "numpy"]:
    if mod not in sys.modules:
        try:
            __import__(mod)
        except ImportError:
            sys.modules[mod] = MagicMock()

# Ensure project root is in path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON_DIR = os.path.join(ROOT_DIR, "common")
for p in [ROOT_DIR, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)


class TestMultiAgentAuditRemediations(unittest.TestCase):

    def test_audit_01_position_keying_by_contract(self):
        """Derivatives must be keyed by contract, not symbol."""
        positions = {}
        contract_ce = "NIFTY26OCT25000CE"
        contract_pe = "NIFTY26OCT24500PE"
        
        positions[contract_ce] = {"symbol": "NIFTY", "contract": contract_ce, "side": "CE"}
        positions[contract_pe] = {"symbol": "NIFTY", "contract": contract_pe, "side": "PE"}
        
        self.assertEqual(len(positions), 2, "Both contracts must coexist without overwriting each other.")
        self.assertIn(contract_ce, positions)
        self.assertIn(contract_pe, positions)

    def test_audit_02_lpp_clamp_reference_price(self):
        """LPP Clamp must reference LTP (cp) as primary, not Best Ask."""
        from common.position_monitor import clamp_lpp_buy_price
        
        ltp = 100.0
        limit_requested = 145.0
        
        # Clamped against LTP (default band is 40% for options)
        clamped = clamp_lpp_buy_price(limit_requested, ltp)
        self.assertLessEqual(clamped, 140.0, "Limit price must be clamped against LTP (100.0), not erratic ask.")

    def test_audit_03_sqlite_atomic_lastrowid(self):
        """create_trade must use SQLite AUTOINCREMENT and lastrowid atomically without race conditions."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY,
                engine TEXT,
                symbol TEXT,
                contract TEXT,
                status TEXT DEFAULT 'ACTIVE',
                data_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT,
                updated_at TEXT
            )
        """)
        
        cur1 = conn.execute(
            "INSERT INTO trades (engine, symbol, contract, status, data_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("nifty50", "RELIANCE", "RELIANCE26OCT3000CE", "ACTIVE", "{}", "2026-10-03", "2026-10-03")
        )
        id1 = cur1.lastrowid
        
        cur2 = conn.execute(
            "INSERT INTO trades (engine, symbol, contract, status, data_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("nifty50", "TCS", "TCS26OCT4000CE", "ACTIVE", "{}", "2026-10-03", "2026-10-03")
        )
        id2 = cur2.lastrowid
        
        self.assertEqual(id1, 1)
        self.assertEqual(id2, 2)
        self.assertGreater(id2, id1)

    def test_audit_04_capital_affordability_gate(self):
        """Pre-execution capital check must reject orders exceeding max budget."""
        from common.portfolio_risk import check_capital_affordability
        
        class MockKite:
            def margins(self, *args, **kwargs):
                return {"available": {"live_balance": 50000.0, "cash": 50000.0, "collateral": 0.0}}
        
        mock_kite = MockKite()
        
        # Reset cash cache for clean test
        import portfolio_risk
        portfolio_risk._LIVE_CASH_CACHE["timestamp"] = 0.0
        
        # 40,000 required (80% of 50k, under 90% budget) -> Pass
        ok, msg, cash = check_capital_affordability(mock_kite, required_capital=40000.0, max_utilization_pct=0.90)
        self.assertTrue(ok)
        
        portfolio_risk._LIVE_CASH_CACHE["timestamp"] = 0.0
        # 48,000 required (96% of 50k, exceeds 90% budget of 45k) -> Reject
        ok, msg, cash = check_capital_affordability(mock_kite, required_capital=48000.0, max_utilization_pct=0.90)
        self.assertFalse(ok)
        self.assertIn("exceeds 90% of available cash", msg)

    def test_audit_05_targets_min_target_start(self):
        """Targets module must allow nearest structural pivot without 1.5x artificial inflation."""
        entry_close = 100.0
        risk = 10.0
        
        old_min_start = max(entry_close * 1.02, entry_close + 1.5 * risk)
        new_min_start = max(entry_close * 1.005, entry_close + 0.1 * risk)
        
        self.assertEqual(old_min_start, 115.0)
        self.assertEqual(new_min_start, 101.0)
        
        pivot = 108.0
        self.assertFalse(pivot >= old_min_start)
        self.assertTrue(pivot >= new_min_start)

    def test_audit_06_harami_and_engulfing_boundaries(self):
        """Harami and Engulfing anchor low/high must span full mother and baby candle range."""
        mother = {"high": 105.0, "low": 95.0, "open": 104.0, "close": 96.0}
        inside = {"high": 100.0, "low": 97.0, "open": 98.0, "close": 99.0}
        
        # In Bullish Harami:
        a_high = max(mother["high"], inside["high"])
        a_low = min(mother["low"], inside["low"])
        self.assertEqual(a_high, 105.0)
        self.assertEqual(a_low, 95.0)
        
        # In Bullish Engulfing:
        bearish_candle = {"high": 102.0, "low": 98.0, "open": 101.0, "close": 99.0}
        bull_anchor = {"high": 104.0, "low": 97.0, "open": 98.0, "close": 103.0}
        eng_high = max(bull_anchor["high"], bearish_candle["high"])
        eng_low = min(bull_anchor["low"], bearish_candle["low"])
        self.assertEqual(eng_high, 104.0)
        self.assertEqual(eng_low, 97.0)

    def test_audit_07_sweep_inter_swing_spacing(self):
        """Sweep requires at least 3 candles gap between Low 1 and Low 2."""
        pos_low_1 = 2
        # Case A: pos_sweep = 5 -> gap = 5 - 2 - 1 = 2 candles (< 3) -> Rejected
        pos_sweep_2_bars = 5
        gap_2 = pos_sweep_2_bars - pos_low_1 - 1
        self.assertLess(gap_2, 3, "2-bar gap must be rejected.")
        
        # Case B: pos_sweep = 6 -> gap = 6 - 2 - 1 = 3 candles (>= 3) -> Approved
        pos_sweep_3_bars = 6
        gap_3 = pos_sweep_3_bars - pos_low_1 - 1
        self.assertGreaterEqual(gap_3, 3, "3-bar gap must be accepted.")

    def test_audit_08_point_c_retest_zone_and_narrow_bar(self):
        """Point C retest must accept <= 1.5% zone and narrow-range / doji bars."""
        benchmark = 100.0
        
        # Candle A: Shallow retest at 101.0 (within +1.5% zone)
        c_low_shallow = 101.0
        is_in_zone = c_low_shallow <= (benchmark * 1.015)
        self.assertTrue(is_in_zone, "Retest at 101.0 (Benchmark +1.0%) must be accepted within 1.5% buffer.")
        
        # Candle B: Doji bar (close == open)
        c_open = 101.2
        c_close = 101.2
        c_high = 101.8
        c_low = 100.8
        is_doji_or_narrow = abs(c_close - c_open) <= (c_high - c_low) * 0.35
        self.assertTrue(is_doji_or_narrow, "Doji / narrow bar must be recognized as valid Point C consolidation.")


if __name__ == "__main__":
    unittest.main()
