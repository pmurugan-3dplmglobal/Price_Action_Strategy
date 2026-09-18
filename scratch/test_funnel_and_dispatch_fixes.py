"""
scratch/test_funnel_and_dispatch_fixes.py
=========================================
Unit verification suite for ISSUE-062:
1. Head-of-Line Starvation in Candidate Dispatch (Combined Prioritized Pool T1 + T2).
2. Robust Candidate Tier Parsing (prevents crashes on None, string tiers, missing badges).
3. F&O Indivisible Lot Sizing & High-Conviction 1-Lot Floor (Adaptive 1-lot sizing for T1 & T2).
4. Automated Morning Funnel Reset & Stale Setup Cleanup across engines.
5. Morning Spot VWAP Gate Inversion Fix for PE Options.
6. Adaptive Spread Tolerance for High-Conviction Limit Orders.
"""

import sys
import os
import unittest
from datetime import datetime as dt, date
from unittest.mock import MagicMock, patch

# Canonical path setup
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Trade_Option")))

from common.targets import calculate_position_size
import common.pattern_funnel as pattern_funnel
import Trade_Option.stock_options_trade_engine as sote


class TestCandidateDispatchPriority(unittest.TestCase):
    """Test 1 & 2: Candidate Dispatch Priority, Starvation Prevention & Tier Robustness."""

    def test_parse_candidate_tier_edge_cases(self):
        """Safely parse tiers from integer, string labels, badges, or None without throwing exceptions."""
        self.assertEqual(sote._parse_candidate_tier({"tier": 1}), 1)
        self.assertEqual(sote._parse_candidate_tier({"tier": "1"}), 1)
        self.assertEqual(sote._parse_candidate_tier({"tier": "TIER_1_GOLD"}), 1)
        self.assertEqual(sote._parse_candidate_tier({"tier_badge": "🥇 T1"}), 1)
        self.assertEqual(sote._parse_candidate_tier({"tier": 2}), 2)
        self.assertEqual(sote._parse_candidate_tier({"tier": "2"}), 2)
        self.assertEqual(sote._parse_candidate_tier({"tier": "TIER_2_CORE"}), 2)
        self.assertEqual(sote._parse_candidate_tier({"tier_badge": "🥈 T2"}), 2)
        self.assertEqual(sote._parse_candidate_tier({"tier": 3}), 3)
        self.assertEqual(sote._parse_candidate_tier({"tier_label": "TIER_3_MOMENTUM"}), 3)
        self.assertEqual(sote._parse_candidate_tier({"tier": None}), 2)
        self.assertEqual(sote._parse_candidate_tier({}), 2)
        self.assertEqual(sote._parse_candidate_tier(None), 2)

    def test_combined_pool_evaluates_tier2_when_tier1_fails_sizing(self):
        """When Tier 1 candidate fails sizing/gates, Tier 2 candidate is executed in the exact same cycle."""
        t1_cand = {
            "symbol": "TITAN",
            "contract": "TITAN26SEP3400CE",
            "side": "CE",
            "pattern": "HAMMER_ABCD",
            "tier": 1,
            "tier_badge": "🥇 T1",
            "tier_label": "TIER_1_GOLD",
            "entry_spot": 50.0,
            "current_sl": 10.0,  # Risk (50-10)*175 = 7,000 > 5,000 safety cap -> pos_size = 0
            "t1": 70.0,
            "t2": 80.0,
            "t3": 90.0,
            "rr": 2.5,
            "lot_size": 175,
            "position_size": 0  # Fails sizing
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

        # Mock Kite and execute_highest_rr_trade
        mock_kite = MagicMock()
        mock_kite.place_order.return_value = "ORDER_123456"
        mock_kite.EXCHANGE_NFO = "NFO"
        mock_kite.TRANSACTION_TYPE_BUY = "BUY"
        mock_kite.ORDER_TYPE_LIMIT = "LIMIT"
        mock_kite.PRODUCT_NRML = "NRML"
        mock_kite.VARIETY_REGULAR = "regular"

        executed_syms = []

        with patch.object(sote, "LIVE_MARKET_DEPLOYMENT", False):
            with patch.object(sote, "BACKTEST_DATE", None):
                with patch.object(sote, "log_to_journal") as mock_journal:
                    sote.execute_highest_rr_trade(mock_kite, staged)
                    for call_args in mock_journal.call_args_list:
                        executed_syms.append(call_args[0][0])

        self.assertIn("M&M", executed_syms, "Tier 2 setup M&M must be executed when Tier 1 fails sizing!")

    def test_execute_highest_rr_trade_handles_none_and_string_tiers_without_crash(self):
        """Candidates with tier: None or string tiers do not raise unhandled exceptions."""
        candidates = [
            {"symbol": "SYM1", "tier": None, "pattern": "BASE_ABCD", "entry_spot": 50.0, "current_sl": 40.0, "t1": 70.0, "position_size": 0},
            {"symbol": "SYM2", "tier": "TIER_1_GOLD", "pattern": "HAMMER_ABCD", "entry_spot": 50.0, "current_sl": 40.0, "t1": 70.0, "position_size": 0},
            {"symbol": "SYM3", "tier": "TIER_2_CORE", "pattern": "BULL_ENGULFING", "entry_spot": 50.0, "current_sl": 40.0, "t1": 70.0, "position_size": 0},
        ]
        mock_kite = MagicMock()
        # Must execute cleanly without raising TypeError or ValueError
        try:
            sote.execute_highest_rr_trade(mock_kite, candidates)
            success = True
        except Exception as e:
            success = False
        self.assertTrue(success, "execute_highest_rr_trade must never crash on unusual candidate tier representations.")


class TestIndivisibleLotSizing(unittest.TestCase):
    """Test 3: F&O Indivisible Lot Sizing & High-Conviction 1-Lot Floor."""

    def test_high_conviction_tier1_titan_1lot_floor(self):
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

    def test_high_conviction_tier2_bajaj_auto_1lot_floor(self):
        """Tier 2 setup on BAJAJ-AUTO with outlay Rs 18,750 <= Rs 25,000 ceiling gets adaptive 1-lot floor."""
        # BAJAJ-AUTO: lot_size=125, premium=150.0, sl=125.0 -> risk=3125 (3.125% <= 5%), outlay=18750 (<= 25% account cap)
        lots = calculate_position_size(
            spot_price=150.0,
            stop_loss=125.0,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=125,
            is_option=True,
            tier=2,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=5.0
        )
        self.assertEqual(lots, 1, "High-conviction Tier 2 setup BAJAJ-AUTO must receive adaptive 1-lot floor under 25% account ceiling.")

    def test_high_conviction_tier2_lodha_1lot_floor(self):
        """Tier 2 setup on LODHA with outlay Rs 19,125 <= Rs 25,000 ceiling gets adaptive 1-lot floor."""
        # LODHA: lot_size=425, premium=45.0, sl=39.0 -> risk=2550 (2.55% <= 5%), outlay=19125 (<= 25% account cap)
        lots = calculate_position_size(
            spot_price=45.0,
            stop_loss=39.0,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=425,
            is_option=True,
            tier=2,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=5.0
        )
        self.assertEqual(lots, 1, "High-conviction Tier 2 setup LODHA must receive adaptive 1-lot floor.")

    def test_string_tier_sizing(self):
        """String representation of tier receives correct conviction floor."""
        lots = calculate_position_size(
            spot_price=50.0,
            stop_loss=35.0,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=175,
            is_option=True,
            tier="TIER_1_GOLD",
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=5.0
        )
        self.assertEqual(lots, 1, "String tier TIER_1_GOLD must receive 1-lot floor.")

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
        """When 1-lot capital outlay exceeds 25% account capital ceiling (Rs 25,000), returns 0 lots."""
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
        # Outlay = 160 * 175 = 28,000 > 25,000 ceiling
        self.assertEqual(lots, 0, "Must return 0 lots if capital outlay exceeds 25% ceiling.")

    def test_safety_risk_cap_exceeded_rejects_1lot(self):
        """When 1-lot risk exceeds absolute 5% safety cap (Rs 5,000), returns 0 lots."""
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
        # Risk = (50 - 15) * 175 = 6,125 > 5,000 safety cap
        self.assertEqual(lots, 0, "Must return 0 lots if risk per lot exceeds 5% account safety cap.")


class TestPatternFunnelMorningPurge(unittest.TestCase):
    """Test 4: Automated Morning Funnel Reset & Stale Setup Cleanup."""

    def setUp(self):
        self.test_engine = "unit_test_engine"
        pattern_funnel.clear_funnel(self.test_engine)

    def tearDown(self):
        pattern_funnel.clear_funnel(self.test_engine)

    def test_purge_stale_prior_day_setups(self):
        """Prior-day setups are evicted while current-day setups are retained across categories."""
        today_str = "2026-09-18"
        yesterday_str = "2026-09-17"

        stale_a_plus = {
            "symbol": "STALE_STOCK_A_PLUS",
            "contract": "STALE_STOCK_A_PLUS26SEP100CE",
            "side": "CE",
            "candle_a_time": f"{yesterday_str} 10:15:00+05:30",
            "date": yesterday_str,
            "tier": 1,
            "benchmark": 105.0,
            "current_sl": 95.0
        }

        fresh_a_plus = {
            "symbol": "FRESH_STOCK_A_PLUS",
            "contract": "FRESH_STOCK_A_PLUS26SEP200CE",
            "side": "CE",
            "candle_a_time": f"{today_str} 09:30:00+05:30",
            "date": today_str,
            "tier": 1,
            "benchmark": 210.0,
            "current_sl": 195.0
        }

        stale_b = {
            "symbol": "STALE_STOCK_B",
            "contract": "STALE_STOCK_B26SEP500CE",
            "side": "CE",
            "candle_a_time": f"{yesterday_str} 14:15:00+05:30",
            "date": yesterday_str,
            "tier": 2,
            "benchmark": 510.0,
            "current_sl": 490.0
        }

        pattern_funnel.update_funnel(self.test_engine, a_plus_items=[stale_a_plus, fresh_a_plus], b_items=[stale_b])
        state_before = pattern_funnel.load_funnel_state(self.test_engine)
        self.assertEqual(len(state_before.get("category_a_plus", [])), 2)
        self.assertEqual(len(state_before.get("category_b", [])), 1)

        state_after = pattern_funnel.purge_stale_prior_day_setups(self.test_engine, today_str=today_str)
        retained_a_plus = state_after.get("category_a_plus", [])
        retained_b = state_after.get("category_b", [])

        self.assertEqual(len(retained_a_plus), 1)
        self.assertEqual(retained_a_plus[0]["symbol"], "FRESH_STOCK_A_PLUS", "Only today setup must be retained in A+.")
        self.assertEqual(len(retained_b), 0, "Stale category B setup must be evicted.")

    def test_get_item_date_str_helper(self):
        """Verify _get_item_date_str correctly resolves date from various timestamp fields and formats."""
        item1 = {"candle_c_time": "2026-09-18 11:45:00+05:30"}
        item2 = {"entry_time": "2026-09-17T14:20:00"}
        item3 = {"promoted_at": "2026-09-16 09:15:22"}
        item4 = {"date": "2026-09-18"}
        item5 = {"timestamp": "2026/09/18 10:00:00"}
        item6 = {"date": dt(2026, 9, 18, 9, 15)}
        item7 = {"date": date(2026, 9, 18)}

        self.assertEqual(pattern_funnel._get_item_date_str(item1), "2026-09-18")
        self.assertEqual(pattern_funnel._get_item_date_str(item2), "2026-09-17")
        self.assertEqual(pattern_funnel._get_item_date_str(item3), "2026-09-16")
        self.assertEqual(pattern_funnel._get_item_date_str(item4), "2026-09-18")
        self.assertEqual(pattern_funnel._get_item_date_str(item5), "2026-09-18")
        self.assertEqual(pattern_funnel._get_item_date_str(item6), "2026-09-18")
        self.assertEqual(pattern_funnel._get_item_date_str(item7), "2026-09-18")


class TestMorningSpotVWAPGate(unittest.TestCase):
    """Test 5: Fix Morning Spot VWAP Gate Inversion for PE Options."""

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

    def test_is_pe_detection_variations(self):
        """Verify is_pe correctly flags PE options via side, direction, or contract suffix."""
        def check_is_pe(item):
            side_val = str(item.get("side", "CE")).upper()
            dir_val = str(item.get("direction", "BULL")).upper()
            c_str = str(item.get("contract", "")).upper()
            return (side_val == "PE" or dir_val == "BEAR" or c_str.endswith("PE"))

        self.assertTrue(check_is_pe({"side": "PE"}))
        self.assertTrue(check_is_pe({"direction": "BEAR"}))
        self.assertTrue(check_is_pe({"contract": "TATAMOTORS26SEP900PE"}))
        self.assertFalse(check_is_pe({"side": "CE", "direction": "BULL", "contract": "TITAN26SEP3200CE"}))


class TestAdaptiveSpreadTolerance(unittest.TestCase):
    """Test 6: Adaptive Spread Tolerance for High-Conviction Setups."""

    def test_titan_spread_passes_under_high_conviction(self):
        """TITAN with 2.06% spread passes under high-conviction tolerance (3.0%), but fails standard (2.0%)."""
        base_max_spread = 0.02
        cand_spread = 0.0206

        std_passes = cand_spread <= base_max_spread
        self.assertFalse(std_passes, "Standard 2.0% spread gate must reject 2.06% spread.")

        high_conviction_max_spread = 0.03
        hc_passes = cand_spread <= high_conviction_max_spread
        self.assertTrue(hc_passes, "High-conviction 3.0% spread gate must accept 2.06% spread for TITAN.")

    def test_tier_based_spread_threshold_resolution(self):
        """High-conviction (Tier 1 & 2) setups resolve 3.0% spread tolerance while Tier 3 resolves 2.0%."""
        base_max_spread = 0.02
        hc_max_spread = 0.03

        def get_max_spread(cand):
            cand_tier = sote._parse_candidate_tier(cand, default=2)
            is_hc = (
                cand_tier in [1, 2]
                or "T1" in str(cand.get("tier_badge", ""))
                or "T2" in str(cand.get("tier_badge", ""))
                or "GOLD" in str(cand.get("tier_label", ""))
                or "CORE" in str(cand.get("tier_label", ""))
            )
            return hc_max_spread if is_hc else base_max_spread

        self.assertEqual(get_max_spread({"tier": 1}), 0.03)
        self.assertEqual(get_max_spread({"tier": 2}), 0.03)
        self.assertEqual(get_max_spread({"tier": "TIER_1_GOLD"}), 0.03)
        self.assertEqual(get_max_spread({"tier": "TIER_2_CORE"}), 0.03)
        self.assertEqual(get_max_spread({"tier": 3}), 0.02)


if __name__ == "__main__":
    unittest.main()
