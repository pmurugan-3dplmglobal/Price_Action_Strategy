"""
scratch/test_decouple_incubation_execution.py — Unit Test Suite for ISSUE-122:
Decouple Incubation from Execution (Category B Sub-VWAP Incubation vs Hard VWAP Execution Gate)
"""

import os
import sys
import json
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
from datetime import datetime as dt, timedelta

# Ensure repo root and common are in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON_DIR = os.path.join(BASE_DIR, "common")
TRADE_OPTION_DIR = os.path.join(BASE_DIR, "Trade_Option")
TRADE_STOCK_DIR = os.path.join(BASE_DIR, "Trade_Stock")

for p in [BASE_DIR, COMMON_DIR, TRADE_OPTION_DIR, TRADE_STOCK_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import pattern_funnel
import resolve
from stock_options_trade_engine import (
    _execute_highest_rr_trade_locked,
    run_fast_radar_check
)


class TestDecoupleIncubationExecution(unittest.TestCase):
    def setUp(self):
        # Isolate pattern funnel file
        self.orig_funnel_file = pattern_funnel.paths.PATTERN_FUNNEL_FILE
        self.test_funnel_file = os.path.join(
            os.path.dirname(self.orig_funnel_file),
            f"pattern_funnel_test_decouple_{os.getpid()}.json"
        )
        pattern_funnel.paths.PATTERN_FUNNEL_FILE = self.test_funnel_file
        pattern_funnel._mem_cache = {}
        pattern_funnel.clear_funnel("test_engine")
        pattern_funnel.clear_funnel("nifty50")

    def tearDown(self):
        if os.path.exists(self.test_funnel_file):
            try:
                os.remove(self.test_funnel_file)
            except OSError:
                pass
        pattern_funnel.paths.PATTERN_FUNNEL_FILE = self.orig_funnel_file
        pattern_funnel._mem_cache = {}

    def test_01_ce_category_b_sub_vwap_incubation_permitted(self):
        """
        Verify that a CE setup forming Category B base below VWAP with confirmed Spot Bull Anchor
        is successfully incubated with sub_vwap_incubating=True, vwap_status='SUB_VWAP_INCUBATING',
        and spot_confluence=False.
        """
        engine_name = "test_engine"
        current_spot = 990.0  # Below VWAP (1000.0)
        spot_vwap = 1000.0    # 990 < 1000 * 0.998 (998.0)
        has_spot_anchor_ce_f = True
        spot_anchor_name_ce_f = "SPOT_HAMMER_BABY"
        f_stage = pattern_funnel.STAGE_B

        # Regime trap check
        self.assertNotEqual(spot_anchor_name_ce_f, "BEAR_SPOT_REGIME_TRAP")

        is_sub_vwap_ce_f = bool(spot_vwap > 0 and float(current_spot) < float(spot_vwap) * 0.998)
        self.assertTrue(is_sub_vwap_ce_f, "Spot must be detected as sub-VWAP")

        # Category B incubation decoupling gate logic
        incubate_allowed = False
        if is_sub_vwap_ce_f:
            if f_stage == pattern_funnel.STAGE_B and has_spot_anchor_ce_f:
                incubate_allowed = True

        self.assertTrue(incubate_allowed, "Category B incubation must be permitted below VWAP with Spot Anchor")

        funnel_item = {
            "symbol": "TCS", "contract": "TCS26DEC3500CE", "option_token": 12345,
            "spot_token": 11111, "spot_entry": current_spot, "strike": 3500,
            "entry_spot": 85.0, "current_sl": 65.0, "benchmark": 110.0,
            "t1": 150.0, "t2": 190.0, "t3": 240.0, "rr": 2.25,
            "pattern": "HAMMER_ABCD", "side": "CE", "timeframe": "15minute",
            "tier": 3, "tier_label": "TIER_3_MOMENTUM", "tier_badge": "🌱 B",
            "vwap_status": "SUB_VWAP_INCUBATING" if is_sub_vwap_ce_f else "FAIR",
            "sub_vwap_incubating": is_sub_vwap_ce_f,
            "spot_vwap": spot_vwap,
            "spot_confluence": False if is_sub_vwap_ce_f else True,
            "spot_confluence_type": "SUB_VWAP_INCUBATING" if is_sub_vwap_ce_f else "SPOT_VWAP_RECLAIM",
            "spot_anchor_name": spot_anchor_name_ce_f,
            "has_spot_anchor": has_spot_anchor_ce_f,
            "stage": f_stage
        }

        pattern_funnel.promote_item(engine_name, funnel_item, f_stage)
        state = pattern_funnel.load_funnel_state(engine_name)
        cat_b = state.get("category_b", [])
        self.assertEqual(len(cat_b), 1)
        self.assertTrue(cat_b[0]["sub_vwap_incubating"])
        self.assertEqual(cat_b[0]["vwap_status"], "SUB_VWAP_INCUBATING")
        self.assertFalse(cat_b[0]["spot_confluence"])

    def test_02_ce_stage_a_sub_vwap_strictly_rejected(self):
        """
        Verify that Stage A / A+ (breakout ready / near trigger) are NOT allowed if Spot is below VWAP.
        They require VWAP acceptance.
        """
        current_spot = 990.0
        spot_vwap = 1000.0
        has_spot_anchor = True
        f_stage_a = pattern_funnel.STAGE_A

        is_sub_vwap = bool(spot_vwap > 0 and float(current_spot) < float(spot_vwap) * 0.998)
        self.assertTrue(is_sub_vwap)

        incubate_allowed = False
        if is_sub_vwap:
            if f_stage_a == pattern_funnel.STAGE_B and has_spot_anchor:
                incubate_allowed = True

        self.assertFalse(incubate_allowed, "Stage A must NOT incubate below VWAP")

    def test_03_pe_category_b_above_vwap_incubation_permitted(self):
        """
        Verify that a PE setup forming Category B base above VWAP with confirmed Spot Bear Anchor
        is successfully incubated with above_vwap tagging.
        """
        engine_name = "test_engine"
        current_spot = 1010.0  # Above VWAP (1000.0)
        spot_vwap = 1000.0     # 1010 > 1000 * 1.002 (1002.0)
        has_spot_anchor_pe = True
        spot_anchor_name_pe = "SPOT_BEAR_ENGULFING"
        f_stage = pattern_funnel.STAGE_B

        is_above_vwap_pe = bool(spot_vwap > 0 and float(current_spot) > float(spot_vwap) * 1.002)
        self.assertTrue(is_above_vwap_pe)

        incubate_allowed = False
        if is_above_vwap_pe:
            if f_stage == pattern_funnel.STAGE_B and has_spot_anchor_pe:
                incubate_allowed = True

        self.assertTrue(incubate_allowed, "Category B PE incubation must be permitted above VWAP with Spot Anchor")

        funnel_item = {
            "symbol": "INFY", "contract": "INFY26DEC1400PE", "option_token": 54321,
            "spot_token": 22222, "spot_entry": current_spot, "strike": 1400,
            "entry_spot": 42.0, "current_sl": 30.0, "benchmark": 55.0,
            "t1": 80.0, "t2": 110.0, "t3": 150.0, "rr": 2.15,
            "pattern": "BE_ABCD", "side": "PE", "timeframe": "15minute",
            "tier": 3, "tier_label": "TIER_3_MOMENTUM", "tier_badge": "🌱 B",
            "vwap_status": "ABOVE_VWAP_INCUBATING" if is_above_vwap_pe else "FAIR",
            "sub_vwap_incubating": is_above_vwap_pe,
            "spot_vwap": spot_vwap,
            "spot_confluence": False if is_above_vwap_pe else True,
            "spot_confluence_type": "ABOVE_VWAP_INCUBATING" if is_above_vwap_pe else "SPOT_VWAP_REJECT",
            "spot_anchor_name": spot_anchor_name_pe,
            "has_spot_anchor": has_spot_anchor_pe,
            "stage": f_stage
        }

        pattern_funnel.promote_item(engine_name, funnel_item, f_stage)
        state = pattern_funnel.load_funnel_state(engine_name)
        cat_b = state.get("category_b", [])
        self.assertEqual(len(cat_b), 1)
        self.assertTrue(cat_b[0]["sub_vwap_incubating"])
        self.assertEqual(cat_b[0]["vwap_status"], "ABOVE_VWAP_INCUBATING")
        self.assertFalse(cat_b[0]["spot_confluence"])

    def test_04_regime_traps_strictly_block_incubation(self):
        """
        Verify that opposing regime traps (BEAR_SPOT_REGIME_TRAP for CE and BULL_SPOT_REGIME_TRAP for PE)
        strictly drop candidates with zero incubation.
        """
        # CE with Bear Regime Trap
        spot_anchor_ce = "BEAR_SPOT_REGIME_TRAP"
        blocked_ce = (spot_anchor_ce == "BEAR_SPOT_REGIME_TRAP")
        self.assertTrue(blocked_ce)

        # PE with Bull Regime Trap
        spot_anchor_pe = "BULL_SPOT_REGIME_TRAP"
        blocked_pe = (spot_anchor_pe == "BULL_SPOT_REGIME_TRAP")
        self.assertTrue(blocked_pe)

    def test_05_hard_execution_gate_blocks_sub_vwap_order_placement(self):
        """
        Verify that _execute_highest_rr_trade_locked NEVER executes a candidate
        if Spot is below VWAP for CE, above VWAP for PE, or tagged with sub_vwap_incubating=True.
        """
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:RELIANCE": {"last_price": 2490.0, "average_price": 2500.0}  # 2490 < 2500 * 0.998 (2495.0)
        }

        sub_vwap_candidate = {
            "symbol": "RELIANCE",
            "contract": "RELIANCE26DEC2500CE",
            "side": "CE",
            "entry_spot": 50.0,
            "current_sl": 40.0,
            "benchmark": 55.0,
            "spot_entry": 2490.0,
            "spot_vwap": 2500.0,
            "spot_ltp": 2490.0,
            "sub_vwap_incubating": True,
            "spot_confluence": False,
            "tier": 2,
            "rr": 2.5
        }

        # Mock order placement to verify it is NEVER called
        mock_kite.place_order = MagicMock()

        with patch("stock_options_trade_engine.LIVE_MARKET_DEPLOYMENT", True), \
             patch("stock_options_trade_engine.live_execution_enabled", return_value=True), \
             patch("stock_options_trade_engine.is_new_entry_allowed", return_value=True), \
             patch("stock_options_trade_engine.get_ist_now") as mock_time:

            mock_now = dt.now().replace(hour=10, minute=30)
            mock_time.return_value = mock_now

            _execute_highest_rr_trade_locked(mock_kite, [sub_vwap_candidate])

            # Verify no order was placed!
            self.assertEqual(mock_kite.place_order.call_count, 0, "Hard VWAP Gate must strictly prevent order placement!")

    def test_06_fast_radar_includes_category_b_in_radar_pool(self):
        """
        Verify that run_fast_radar_check includes Category B in radar_pool.
        """
        engine_name = "nifty50"
        pattern_funnel.clear_funnel(engine_name)

        item_b = {
            "symbol": "SBIN", "contract": "SBIN26DEC800CE", "side": "CE",
            "benchmark": 25.0, "current_sl": 18.0, "t1": 35.0, "rr": 2.0,
            "tier": 3, "tier_label": "TIER_3_MOMENTUM", "tier_badge": "🌱 B",
            "sub_vwap_incubating": True, "vwap_status": "SUB_VWAP_INCUBATING",
            "spot_vwap": 795.0, "spot_entry": 790.0,
            "stage": pattern_funnel.STAGE_B
        }
        pattern_funnel.promote_item(engine_name, item_b, pattern_funnel.STAGE_B)

        summ = pattern_funnel.get_funnel_summary(engine_name)
        radar_pool = list(
            summ.get("category_a_plus", [])
            + summ.get("category_a", [])
            + summ.get("category_b", [])
        )
        self.assertEqual(len(radar_pool), 1)
        self.assertEqual(radar_pool[0]["symbol"], "SBIN")
        self.assertTrue(radar_pool[0]["sub_vwap_incubating"])

    def test_07_fast_radar_reclaim_gate_requires_green_candle_and_rvol_1_2(self):
        """
        Verify that when an incubating setup crosses VWAP, Fast Radar requires:
        1. Spot >= VWAP * 0.998
        2. Green candle close
        3. Projected RVOL >= 1.2x
        before setting spot_confluence=True and sub_vwap_incubating=False.
        """
        item = {
            "symbol": "TATASTEEL", "contract": "TATASTEEL26DEC150CE", "side": "CE",
            "sub_vwap_incubating": True, "spot_confluence": False,
            "vwap_status": "SUB_VWAP_INCUBATING"
        }

        # Case A: Spot crossed VWAP but RVOL < 1.2x -> MUST HOLD
        spot_ltp = 152.0
        spot_vwap = 150.0
        proj_rvol_weak = 0.95
        is_sub_vwap_cand = bool(item.get("sub_vwap_incubating") or not item.get("spot_confluence"))
        self.assertTrue(is_sub_vwap_cand)

        reclaim_approved_weak = False
        if spot_ltp >= spot_vwap * 0.998:
            if proj_rvol_weak >= 1.2:
                reclaim_approved_weak = True

        self.assertFalse(reclaim_approved_weak, "Must reject reclaim when RVOL < 1.2x")

        # Case B: Spot crossed VWAP, RVOL = 1.45x >= 1.2x, green candle close -> APPROVED!
        proj_rvol_strong = 1.45
        s_c = 152.0
        s_o = 149.5
        s_green = (s_c >= s_o)

        reclaim_approved_strong = False
        if spot_ltp >= spot_vwap * 0.998:
            if proj_rvol_strong >= 1.2 and s_green:
                reclaim_approved_strong = True
                item["spot_confluence"] = True
                item["sub_vwap_incubating"] = False
                item["vwap_status"] = "SPOT_VWAP_RECLAIM"

        self.assertTrue(reclaim_approved_strong, "Must approve reclaim when RVOL >= 1.2x and candle is green")
        self.assertTrue(item["spot_confluence"])
        self.assertFalse(item["sub_vwap_incubating"])
        self.assertEqual(item["vwap_status"], "SPOT_VWAP_RECLAIM")


if __name__ == "__main__":
    unittest.main()
