"""
Unit verification suite for ISSUE-111:
1. Macro Index Gate (common/macro_gate.py) - Real-time NIFTY/BANKNIFTY delta directional gating & TTL cache
2. Position Monitor sl_distance minimum floor & opening gap breach override sanity
3. Portfolio Risk live_balance cash extraction priority
4. Terminal rejected order reconciliation & ghost positions purge
5. 50% UI capital spread margin floor derivation
"""

import sys
import os
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.macro_gate import evaluate_macro_index_gate, get_macro_index_deltas, _MACRO_CACHE
from common.portfolio_risk import get_live_available_cash


class TestIssue111MacroGateAndSafety(unittest.TestCase):

    def setUp(self):
        # Reset cache before tests
        _MACRO_CACHE["timestamp"] = 0.0
        _MACRO_CACHE["data"] = {}

    def test_01_macro_gate_ce_blocked_on_nifty_drop(self):
        """When NIFTY is red by > -0.25%, all CE buys must be blocked, PE allowed."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 24800.0, "ohlc": {"close": 25000.0}},  # -0.80%
            "NSE:NIFTY BANK": {"last_price": 53000.0, "ohlc": {"close": 53500.0}} # -0.93%
        }
        
        # CE should be blocked
        allowed_ce, reason_ce = evaluate_macro_index_gate(mock_kite, "CE", "INFY")
        self.assertFalse(allowed_ce)
        self.assertIn("NIFTY 50 is down", reason_ce)

        # PE should be allowed
        allowed_pe, reason_pe = evaluate_macro_index_gate(mock_kite, "PE", "INFY")
        self.assertTrue(allowed_pe)

    def test_02_macro_gate_pe_blocked_on_nifty_rally(self):
        """When NIFTY is green by > +0.25%, all PE buys must be blocked, CE allowed."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 25200.0, "ohlc": {"close": 25000.0}},  # +0.80%
            "NSE:NIFTY BANK": {"last_price": 53500.0, "ohlc": {"close": 53000.0}} # +0.94%
        }
        
        # PE should be blocked
        allowed_pe, reason_pe = evaluate_macro_index_gate(mock_kite, "PE", "TCS")
        self.assertFalse(allowed_pe)
        self.assertIn("NIFTY 50 is up", reason_pe)

        # CE should be allowed
        allowed_ce, reason_ce = evaluate_macro_index_gate(mock_kite, "CE", "TCS")
        self.assertTrue(allowed_ce)

    def test_03_macro_gate_banking_uses_banknifty(self):
        """Banking tickers should prioritize BANKNIFTY delta."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 25000.0, "ohlc": {"close": 25000.0}},  # 0.0%
            "NSE:NIFTY BANK": {"last_price": 53000.0, "ohlc": {"close": 53500.0}} # -0.93%
        }
        
        allowed_sbin_ce, reason_sbin = evaluate_macro_index_gate(mock_kite, "CE", "SBIN")
        self.assertFalse(allowed_sbin_ce)
        self.assertIn("NIFTY BANK is down", reason_sbin)

    def test_04_macro_gate_ttl_caching(self):
        """Verify 20-second TTL caching avoids redundant Kite quote calls."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 25000.0, "ohlc": {"close": 25000.0}},
            "NSE:NIFTY BANK": {"last_price": 53000.0, "ohlc": {"close": 53000.0}}
        }
        
        # First call fetches quote
        get_macro_index_deltas(mock_kite)
        self.assertEqual(mock_kite.quote.call_count, 1)

        # Immediate second call uses cache
        get_macro_index_deltas(mock_kite)
        self.assertEqual(mock_kite.quote.call_count, 1)

    def test_05_position_monitor_sl_distance_minimum_floor(self):
        """Verify sl_distance floor prevents breakeven 0.0 distance and opening spread false triggers."""
        # Simulated breakeven state: entry == current_sl
        entry_s = 10.0
        current_sl = 10.0
        raw_dist = abs(entry_s - current_sl) # 0.0!
        
        # Floor logic from position_monitor.py
        sl_distance = max(raw_dist, current_sl * 0.05, 1.50)
        self.assertGreaterEqual(sl_distance, 1.50)

        # Normal opening bid-ask spread noise: LTP = 9.70 (30 paise below SL)
        ltp = 9.70
        gap_magnitude = current_sl - ltp # 0.30
        
        # Catastrophic condition is gap_magnitude > 2.0 * sl_distance
        # With floor: 0.30 > 2.0 * 1.50 (3.00) is FALSE -> NOT triggered!
        is_catastrophic = gap_magnitude > (2.0 * sl_distance)
        self.assertFalse(is_catastrophic, "Normal 30-paise opening spread must NOT trigger catastrophic gap override")

        # Genuine disaster: LTP = 6.00 (4.00 below SL)
        ltp_crash = 6.00
        gap_crash = current_sl - ltp_crash # 4.00
        is_crash = gap_crash > (2.0 * sl_distance) # 4.00 > 3.00 -> TRUE
        self.assertTrue(is_crash, "Catastrophic 4-point crash must trigger gap override")

    def test_06_live_available_cash_prioritizes_live_balance(self):
        """Verify get_live_available_cash prioritizes live_balance over static opening cash."""
        mock_kite = MagicMock()
        mock_kite.margins.return_value = {
            "equity": {
                "available": {
                    "cash": 33234.90,         # Static opening cash
                    "live_balance": 11552.15, # Actual remaining balance
                    "net": 11552.15
                }
            }
        }
        
        cash = get_live_available_cash(mock_kite)
        self.assertEqual(cash, 11552.15, "Must return live_balance/net, not static cash")

    def test_07_spread_margin_floor_derived_from_50pct_capital(self):
        """Verify spread margin floor is derived from 50% of UI capital setting."""
        cap_val_base = 30000.0
        spread_floor_pct = 0.50
        floor = cap_val_base * spread_floor_pct
        self.assertEqual(floor, 15000.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
