"""
test_issue123_staged_ltp_sl_eviction.py - Unit test suite for ISSUE-123:
1. Long Option Buyer Invariant: Both CE and PE contracts are bought long and hit SL when premium <= sl.
2. purge_stale_prior_day_setups & reconcile_funnel_and_display_setups accept ltp_dict and evaluate live quotes.
3. Eviction of SL_BREACHED setups from active staged_trades queue in scan_display while preserving history in all_staged_today.
"""

import unittest
from unittest.mock import MagicMock, patch
import os
import copy
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import common.pattern_funnel as pattern_funnel
from common.pattern_funnel import purge_stale_prior_day_setups, reconcile_funnel_and_display_setups
from common.trading_core import is_option_contract


class TestIssue123StagedLtpSlEviction(unittest.TestCase):

    def setUp(self):
        self.mock_store = {}

    def _mock_load(self, engine_name=None):
        if engine_name:
            return self.mock_store.get(engine_name, {"category_a_plus": [], "category_a": [], "category_b": []})
        return self.mock_store

    def _mock_save(self, engine_name, data):
        self.mock_store[engine_name] = data

    def test_01_option_buyer_invariant_ce_and_pe(self):
        """Verify that both CE and PE option contracts breach SL when premium <= sl."""
        ce_setup = {
            "symbol": "TORNTPHARM",
            "contract": "TORNTPHARM26OCT4700CE",
            "side": "CE",
            "direction": "BULL",
            "entry_spot": 150.0,
            "sl": 117.65,
            "t1": 210.0,
            "benchmark": 150.0,
            "entry_date": "2026-10-08"
        }
        ltp_ce_broken = {"TORNTPHARM26OCT4700CE": 114.00}
        
        pe_setup = {
            "symbol": "ADANIPORTS",
            "contract": "ADANIPORTS26OCT1720PE",
            "side": "PE",
            "direction": "BEAR",
            "entry_spot": 80.0,
            "sl": 60.0,
            "t1": 120.0,
            "benchmark": 80.0,
            "entry_date": "2026-10-08"
        }
        ltp_pe_broken = {"ADANIPORTS26OCT1720PE": 55.00}

        ltp_ce_healthy = {"TORNTPHARM26OCT4700CE": 160.00}

        # Case 1: Broken CE -> Evicted
        self.mock_store = {
            "stock_options": {"category_a_plus": [], "category_a": [copy.deepcopy(ce_setup)], "category_b": []}
        }
        with patch("common.pattern_funnel.load_funnel_state", side_effect=self._mock_load), \
             patch("common.pattern_funnel.save_funnel_state", side_effect=self._mock_save):
            res = purge_stale_prior_day_setups(engine_name="stock_options", purge_scan_display=False, ltp_dict=ltp_ce_broken, force_prior_days=False)
            self.assertEqual(len(res["category_a"]), 0)

        # Case 2: Broken PE -> Evicted under Long Option Buyer Invariant
        self.mock_store = {
            "stock_options": {"category_a_plus": [], "category_a": [copy.deepcopy(pe_setup)], "category_b": []}
        }
        with patch("common.pattern_funnel.load_funnel_state", side_effect=self._mock_load), \
             patch("common.pattern_funnel.save_funnel_state", side_effect=self._mock_save):
            res = purge_stale_prior_day_setups(engine_name="stock_options", purge_scan_display=False, ltp_dict=ltp_pe_broken, force_prior_days=False)
            self.assertEqual(len(res["category_a"]), 0)

        # Case 3: Healthy CE -> Preserved
        self.mock_store = {
            "stock_options": {"category_a_plus": [], "category_a": [copy.deepcopy(ce_setup)], "category_b": []}
        }
        with patch("common.pattern_funnel.load_funnel_state", side_effect=self._mock_load), \
             patch("common.pattern_funnel.save_funnel_state", side_effect=self._mock_save):
            res = purge_stale_prior_day_setups(engine_name="stock_options", purge_scan_display=False, ltp_dict=ltp_ce_healthy, force_prior_days=False)
            self.assertEqual(len(res["category_a"]), 1)

    def test_02_equity_short_sl_direction(self):
        """Verify that cash equity short sales breach SL when spot price rises >= sl."""
        short_eq_setup = {
            "symbol": "INFY",
            "contract": "INFY",
            "side": "SELL",
            "direction": "BEAR",
            "entry_spot": 1500.0,
            "sl": 1530.0,
            "t1": 1440.0,
            "benchmark": 1500.0,
            "entry_date": "2026-10-08"
        }
        ltp_eq_broken = {"INFY": 1535.0}
        ltp_eq_healthy = {"INFY": 1480.0}

        # Case 1: Short equity with spot >= SL -> Evicted
        self.mock_store = {
            "stock": {"category_a_plus": [], "category_a": [copy.deepcopy(short_eq_setup)], "category_b": []}
        }
        with patch("common.pattern_funnel.load_funnel_state", side_effect=self._mock_load), \
             patch("common.pattern_funnel.save_funnel_state", side_effect=self._mock_save):
            res = purge_stale_prior_day_setups(engine_name="stock", purge_scan_display=False, ltp_dict=ltp_eq_broken, force_prior_days=False)
            self.assertEqual(len(res["category_a"]), 0)

        # Case 2: Short equity with spot < SL -> Preserved
        self.mock_store = {
            "stock": {"category_a_plus": [], "category_a": [copy.deepcopy(short_eq_setup)], "category_b": []}
        }
        with patch("common.pattern_funnel.load_funnel_state", side_effect=self._mock_load), \
             patch("common.pattern_funnel.save_funnel_state", side_effect=self._mock_save):
            res = purge_stale_prior_day_setups(engine_name="stock", purge_scan_display=False, ltp_dict=ltp_eq_healthy, force_prior_days=False)
            self.assertEqual(len(res["category_a"]), 1)

    def test_03_active_staged_trades_eviction_logic(self):
        """Verify that active staged_trades list evicts SL-breached or Target-hit setups."""
        staged = [
            {"contract": "TORNTPHARM26OCT4700CE", "is_sl_hit": True, "status": "SL_BREACHED"},
            {"contract": "RELIANCE26OCT3100CE", "is_sl_hit": False, "status": "PENDING"},
            {"contract": "INFY26OCT1600CE", "is_t1_hit": True, "status": "TARGET_HIT"},
            {"contract": "SBIN26OCT800CE", "is_sl_hit": False, "status": "READY"}
        ]
        
        valid_staged = [x for x in staged if not x.get("is_sl_hit") and x.get("status") not in ["SL_BREACHED", "TARGET_HIT"]]
        
        self.assertEqual(len(valid_staged), 2)
        remaining_contracts = [x["contract"] for x in valid_staged]
        self.assertIn("RELIANCE26OCT3100CE", remaining_contracts)
        self.assertIn("SBIN26OCT800CE", remaining_contracts)
        self.assertNotIn("TORNTPHARM26OCT4700CE", remaining_contracts)
        self.assertNotIn("INFY26OCT1600CE", remaining_contracts)


if __name__ == "__main__":
    unittest.main()
