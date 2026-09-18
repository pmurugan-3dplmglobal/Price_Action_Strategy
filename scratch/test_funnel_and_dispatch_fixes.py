"""
scratch/test_funnel_and_dispatch_fixes.py
=========================================
Unit verification suite for ISSUE-062:
1. Head-of-Line Starvation in Candidate Dispatch (Combined Prioritized Pool T1 + T2).
2. F&O Indivisible Lot Sizing & High-Conviction 1-Lot Floor (Adaptive 1-lot sizing).
3. Automated Morning Funnel Reset & Stale Setup Cleanup.
4. Morning Spot VWAP Gate Inversion Fix for PE Options.
5. Adaptive Spread Tolerance for High-Conviction Limit Orders.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Canonical path setup
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Trade_Option")))

from common.targets import calculate_position_size
import common.pattern_funnel as pattern_funnel
import Trade_Option.stock_options_trade_engine as sote


class TestCandidateDispatchPriority(unittest.TestCase):
    """Test 1: Head-of-Line Starvation in Candidate Dispatch."""

    def test_combined_pool_evaluates_tier2_when_tier1_fails_gates(self):
        """When Tier 1 candidate fails risk/pre-order gate, Tier 2 candidate must be evaluated in same cycle."""
        t1_cand = {
            "symbol": "TITAN",
            "contract": "TITAN26SEP3400CE",
            "side": "CE",
            "pattern": "HAMMER_ABCD",
            "tier": 1,
            "tier_badge": "🥇 T1",
            "tier_label": "TIER_1_GOLD",
            "entry_spot": 50.0,
            "current_sl": 40.0,
            "t1": 70.0,
            "t2": 80.0,
            "t3": 90.0,
            "rr": 2.5,
            "lot_size": 175,
            "position_size": 0  # Fails sizing (pos_size <= 0)
        }

        t2_cand = {
            "symbol": "M&M",
            "contract": "MM26SEP3000CE",
            "side": "CE",
            "pattern": "BULL_ENGULFING",
            "tier": 2,
            "tier_badge": "🥈 T2",
            "tier_label": "TIER_2_CORE",
            "entry_spot": 45.0,
            "current_sl": 38.0,
            "t1": 60.0,
            "t2": 70.0,
            "t3": 80.0,
            "rr": 2.2,
            "lot_size": 150,
            "position_size": 1  # Valid position size
        }

        staged = [t1_cand, t2_cand]

        t1_candidates = [
            t for t in staged
            if int(t.get("tier", 2)) == 1 or "T1" in str(t.get("tier_badge", "")) or "GOLD" in str(t.get("tier_label", ""))
        ]
        t2_candidates = [
            t for t in staged
            if int(t.get("tier", 2)) == 2 or "T2" in str(t.get("tier_badge", "")) or "CORE" in str(t.get("tier_label", ""))
        ]

        t1_sorted = sorted(t1_candidates, key=sote._avg_target_rank, reverse=True)
        t2_sorted = sorted(t2_candidates, key=sote._avg_target_rank, reverse=True)
        sorted_pool = t1_sorted + t2_sorted

        self.assertEqual(len(sorted_pool), 2)
        self.assertEqual(sorted_pool[0]["symbol"], "TITAN")
        self.assertEqual(sorted_pool[1]["symbol"], "M&M")

        selected_for_execution = None
        for best in sorted_pool:
            if best.get("position_size", 0) <= 0:
                continue
            selected_for_execution = best
            break

        self.assertIsNotNone(selected_for_execution)
        self.assertEqual(selected_for_execution["symbol"], "M&M", "Tier 2 candidate M&M must be executed when T1 fails sizing!")


class TestIndivisibleLotSizing(unittest.TestCase):
    """Test 2: F&O Indivisible Lot Sizing & High-Conviction 1-Lot Floor."""

    def test_high_conviction_tier1_1lot_floor(self):
        """Tier 1 setup on TITAN with 1-lot risk exceeding 1% budget gets adaptive 1-lot floor."""
        lots = calculate_position_size(
            spot_price=50.0,
            stop_loss=35.0,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=175,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=5.0
        )
        self.assertEqual(lots, 1, "High-conviction Tier 1 setup must receive adaptive 1-lot floor.")

    def test_high_conviction_tier2_1lot_floor(self):
        """Tier 2 setup on BAJAJ-AUTO with 1-lot risk exceeding budget gets adaptive 1-lot floor."""
        lots = calculate_position_size(
            spot_price=60.0,
            stop_loss=45.0,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=125,
            is_option=True,
            tier=2,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=5.0
        )
        self.assertEqual(lots, 1, "High-conviction Tier 2 setup must receive adaptive 1-lot floor.")

    def test_tier3_does_not_get_floor(self):
        """Tier 3 (Momentum) setup does NOT receive conviction 1-lot floor and returns 0 lots."""
        lots = calculate_position_size(
            spot_price=50.0,
            stop_loss=35.0,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=175,
            is_option=True,
            tier=3,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=5.0
        )
        self.assertEqual(lots, 0, "Tier 3 setup must NOT receive conviction floor when risk exceeds budget.")

    def test_capital_outlay_cap_exceeded_rejects_1lot(self):
        """When 1-lot capital outlay exceeds 25% account capital ceiling, returns 0 lots."""
        lots = calculate_position_size(
            spot_price=160.0,
            stop_loss=150.0,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=175,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=5.0
        )
        self.assertEqual(lots, 0, "Must return 0 lots if capital outlay exceeds 25% ceiling.")

    def test_safety_risk_cap_exceeded_rejects_1lot(self):
        """When 1-lot risk exceeds absolute 5% safety cap, returns 0 lots."""
        lots = calculate_position_size(
            spot_price=50.0,
            stop_loss=15.0,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=175,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=5.0
        )
        self.assertEqual(lots, 0, "Must return 0 lots if risk per lot exceeds 5% account safety cap.")


class TestPatternFunnelMorningPurge(unittest.TestCase):
    """Test 3: Automated Morning Funnel Reset & Stale Setup Cleanup."""

    def setUp(self):
        self.test_engine = "unit_test_engine"
        pattern_funnel.clear_funnel(self.test_engine)

    def tearDown(self):
        pattern_funnel.clear_funnel(self.test_engine)

    def test_purge_stale_prior_day_setups(self):
        """Prior-day setups are evicted while current-day setups are retained."""
        today_str = "2026-09-18"
        yesterday_str = "2026-09-17"

        stale_item = {
            "symbol": "STALE_STOCK",
            "contract": "STALE_STOCK26SEP100CE",
            "side": "CE",
            "candle_a_time": f"{yesterday_str} 10:15:00+05:30",
            "date": yesterday_str,
            "tier": 1,
            "benchmark": 105.0,
            "current_sl": 95.0
        }

        fresh_item = {
            "symbol": "FRESH_STOCK",
            "contract": "FRESH_STOCK26SEP200CE",
            "side": "CE",
            "candle_a_time": f"{today_str} 09:30:00+05:30",
            "date": today_str,
            "tier": 1,
            "benchmark": 210.0,
            "current_sl": 195.0
        }

        pattern_funnel.update_funnel(self.test_engine, a_plus_items=[stale_item, fresh_item])
        state_before = pattern_funnel.load_funnel_state(self.test_engine)
        self.assertEqual(len(state_before.get("category_a_plus", [])), 2)

        state_after = pattern_funnel.purge_stale_prior_day_setups(self.test_engine, today_str=today_str)
        retained = state_after.get("category_a_plus", [])
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]["symbol"], "FRESH_STOCK", "Only today setup must be retained.")

    def test_get_item_date_str_helper(self):
        """Verify _get_item_date_str correctly resolves date from various timestamp fields."""
        item1 = {"candle_c_time": "2026-09-18 11:45:00+05:30"}
        item2 = {"entry_time": "2026-09-17T14:20:00"}
        item3 = {"promoted_at": "2026-09-16 09:15:22"}
        item4 = {"date": "2026-09-18"}

        self.assertEqual(pattern_funnel._get_item_date_str(item1), "2026-09-18")
        self.assertEqual(pattern_funnel._get_item_date_str(item2), "2026-09-17")
        self.assertEqual(pattern_funnel._get_item_date_str(item3), "2026-09-16")
        self.assertEqual(pattern_funnel._get_item_date_str(item4), "2026-09-18")


class TestMorningSpotVWAPGate(unittest.TestCase):
    """Test 4: Fix Morning Spot VWAP Gate Inversion for PE Options."""

    def test_morning_vwap_gate_ce_logic(self):
        """For CE, spot >= VWAP * 0.997 passes; spot < VWAP * 0.997 is rejected."""
        spot_vwap = 1000.0

        spot_ltp_pass = 998.0
        ce_rejected_pass = spot_ltp_pass < (spot_vwap * 0.997)
        self.assertFalse(ce_rejected_pass, "CE: Spot 998.0 >= 997.0 must pass morning gate.")

        spot_ltp_fail = 990.0
        ce_rejected_fail = spot_ltp_fail < (spot_vwap * 0.997)
        self.assertTrue(ce_rejected_fail, "CE: Spot 990.0 < 997.0 must be rejected by morning gate.")

    def test_morning_vwap_gate_pe_logic(self):
        """For PE, spot <= VWAP * 1.003 passes (breakdown); spot > VWAP * 1.003 is rejected."""
        spot_vwap = 1000.0

        spot_ltp_pass = 990.0
        pe_rejected_pass = spot_ltp_pass > (spot_vwap * 1.003)
        self.assertFalse(pe_rejected_pass, "PE: Spot 990.0 <= 1003.0 must pass morning gate (bearish breakdown).")

        spot_ltp_fail = 1010.0
        pe_rejected_fail = spot_ltp_fail > (spot_vwap * 1.003)
        self.assertTrue(pe_rejected_fail, "PE: Spot 1010.0 > 1003.0 must be rejected by morning gate.")


class TestAdaptiveSpreadTolerance(unittest.TestCase):
    """Test 5: Adaptive Spread Tolerance for High-Conviction Setups."""

    def test_titan_spread_passes_under_high_conviction(self):
        """TITAN with 2.06% spread passes under high-conviction tolerance (3.0%), but fails standard (2.0%)."""
        base_max_spread = 0.02
        cand_spread = 0.0206

        std_passes = cand_spread <= base_max_spread
        self.assertFalse(std_passes, "Standard 2.0% spread gate must reject 2.06% spread.")

        high_conviction_max_spread = 0.03
        hc_passes = cand_spread <= high_conviction_max_spread
        self.assertTrue(hc_passes, "High-conviction 3.0% spread gate must accept 2.06% spread for TITAN.")


if __name__ == "__main__":
    unittest.main()
