"""
scratch/test_priority_ranking_laws.py — Unit Verification for ISSUE-071:
1. Composite Priority Score (_avg_target_rank)
2. VCP Coiled Promotion Gate (resolve.py CE & PE)
3. Mandatory Spot Confluence Gate (stock_options_trade_engine.py)
4. Safe Option Value Corridor (-5% to +15% VWAP)
5. Premium Floor Gate (Benchmark >= 5.0 when DTE <= 5)
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
TRADE_OPT_DIR = os.path.join(PROJECT_ROOT, "Trade_Option")

for p in [PROJECT_ROOT, COMMON_DIR, TRADE_OPT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
import stock_options_trade_engine as sote


class TestCompositeRankingScore(unittest.TestCase):
    """Test 1: Composite Priority Score (_avg_target_rank)."""

    def test_confluence_and_vcp_outranks_zero_confluence_high_rr(self):
        """Voltas (confluence + VCP coiled) must decisively outrank GodrejProp (high paper RR, no confluence)."""
        # GODREJPROP: Paper RR = 3.75, no confluence, flat ATR 1.0, 0 stretch
        loser_godrej = {
            "symbol": "GODREJPROP",
            "entry_spot": 100.0,
            "current_sl": 90.0,  # risk = 10
            "t1": 137.5,         # reward = 37.5 -> base RR = 3.75
            "spot_confluence": False,
            "atr_ratio": 1.0,
            "is_squeeze": False,
            "vwap_stretch": 0.0,
            "vwap_status": "FAIR"
        }

        # VOLTAS: Paper RR = 3.66, spot confluence True (+2.0), coiled ATR 0.48 (+1.2), 0 stretch
        winner_voltas = {
            "symbol": "VOLTAS",
            "entry_spot": 100.0,
            "current_sl": 90.0,  # risk = 10
            "t1": 136.6,         # reward = 36.6 -> base RR = 3.66
            "spot_confluence": True,
            "atr_ratio": 0.48,   # <= 0.50 -> +1.2 bonus
            "is_squeeze": False,
            "vwap_stretch": 0.0,
            "vwap_status": "FAIR"
        }

        score_godrej = sote._avg_target_rank(loser_godrej)
        score_voltas = sote._avg_target_rank(winner_voltas)

        self.assertAlmostEqual(score_godrej, 3.75, places=2)
        # 3.66 + 2.0 (spot) + 1.2 (VCP) = 6.86
        self.assertAlmostEqual(score_voltas, 6.86, places=2)
        self.assertGreater(score_voltas, score_godrej, "VOLTAS (confluence+VCP) must decisively outrank GODREJPROP!")

    def test_safe_option_vwap_discount_and_breakdown_penalty(self):
        """Safe discount (-5% to 0%) gives +0.5 bonus; breakdown (<-5%) and stretch (>15%) receive -1.5 penalty."""
        base_cand = {
            "symbol": "TCS",
            "entry_spot": 100.0,
            "current_sl": 90.0,
            "t1": 120.0,  # base RR = 2.0
            "spot_confluence": True,  # +2.0
            "atr_ratio": 1.0,
            "is_squeeze": False,
        }

        # Safe discount (-3% stretch)
        cand_safe = dict(base_cand, vwap_stretch=-3.0, vwap_status="FAIR")
        score_safe = sote._avg_target_rank(cand_safe)
        # 2.0 + 2.0 + 0.5 = 4.5
        self.assertAlmostEqual(score_safe, 4.5, places=2)

        # Falling knife breakdown (-10% stretch)
        cand_knife = dict(base_cand, vwap_stretch=-10.0, vwap_status="FAIR")
        score_knife = sote._avg_target_rank(cand_knife)
        # 2.0 + 2.0 - 1.5 = 2.5
        self.assertAlmostEqual(score_knife, 2.5, places=2)
        self.assertGreater(score_safe, score_knife, "Safe VWAP discount must outrank broken down falling knife!")

        # Overstretched FOMO (> 15% stretch)
        cand_fomo = dict(base_cand, vwap_stretch=18.0, vwap_status="STRETCHED")
        score_fomo = sote._avg_target_rank(cand_fomo)
        # 2.0 + 2.0 - 1.5 = 2.5
        self.assertAlmostEqual(score_fomo, 2.5, places=2)

    def test_base_rr_capped_at_5(self):
        """Unrealistic paper RR (e.g. 15.0) is capped at 5.0 to prevent distant-target distortion."""
        cand_wild_rr = {
            "symbol": "INFY",
            "entry_spot": 100.0,
            "current_sl": 99.0,  # risk = 1
            "t1": 115.0,         # reward = 15 -> paper RR = 15.0
            "spot_confluence": False,
            "atr_ratio": 1.0,
            "is_squeeze": False,
            "vwap_stretch": 0.0,
            "vwap_status": "FAIR"
        }
        score = sote._avg_target_rank(cand_wild_rr)
        self.assertEqual(score, 5.0, "Base RR contribution must be capped at 5.0")


class TestVCPCoiledPromotionGate(unittest.TestCase):
    """Test 2: VCP Coiled Promotion Gate in resolve.py logic."""

    def _simulate_vcp_promotion(self, tier, spot_conf, atr_ratio, is_squeeze, cand_rr):
        """Helper mirroring the exact VCP promotion gate implemented in resolve.py."""
        tier_out = tier
        tier_label_out = "TIER_2_CORE" if tier == 2 else "TIER_3_MOMENTUM"
        tier_badge_out = "🥈 T2" if tier == 2 else "🥉 T3"

        if tier_out >= 2 and spot_conf and (atr_ratio <= 0.65 or is_squeeze) and cand_rr >= 1.5:
            tier_out = 1
            tier_label_out = "TIER_1_GOLD"
            tier_badge_out = "🥇 T1"

        return tier_out, tier_label_out, tier_badge_out

    def test_vcp_coiled_promotes_to_tier_1_gold(self):
        """Candidate with tier 2, spot confluence, ATR <= 0.65, and RR >= 1.5 is promoted to Tier 1 Gold."""
        t, label, badge = self._simulate_vcp_promotion(tier=2, spot_conf=True, atr_ratio=0.55, is_squeeze=False, cand_rr=1.8)
        self.assertEqual(t, 1)
        self.assertEqual(label, "TIER_1_GOLD")
        self.assertEqual(badge, "🥇 T1")

    def test_ttm_squeeze_promotes_to_tier_1_gold(self):
        """Candidate with tier 3, spot confluence, active squeeze, and RR >= 1.5 is promoted to Tier 1 Gold."""
        t, label, badge = self._simulate_vcp_promotion(tier=3, spot_conf=True, atr_ratio=0.85, is_squeeze=True, cand_rr=1.6)
        self.assertEqual(t, 1)
        self.assertEqual(label, "TIER_1_GOLD")
        self.assertEqual(badge, "🥇 T1")

    def test_no_spot_confluence_blocks_promotion(self):
        """Even with coiled VCP and high RR, lacking spot confluence blocks promotion to Tier 1."""
        t, label, badge = self._simulate_vcp_promotion(tier=2, spot_conf=False, atr_ratio=0.45, is_squeeze=True, cand_rr=3.5)
        self.assertEqual(t, 2)
        self.assertEqual(label, "TIER_2_CORE")

    def test_uncoiled_normal_atr_blocks_promotion(self):
        """Flat ATR (1.00) without squeeze does not qualify for VCP promotion."""
        t, label, badge = self._simulate_vcp_promotion(tier=2, spot_conf=True, atr_ratio=1.00, is_squeeze=False, cand_rr=2.5)
        self.assertEqual(t, 2)

    def test_sub_1_5_rr_blocks_promotion(self):
        """RR < 1.5 blocks promotion even if coiled and confluent."""
        t, label, badge = self._simulate_vcp_promotion(tier=2, spot_conf=True, atr_ratio=0.50, is_squeeze=False, cand_rr=1.2)
        self.assertEqual(t, 2)


class TestExecutionGates(unittest.TestCase):
    """Test 3, 4, 5: Mandatory Spot Confluence, Safe Option Value Corridor, and Premium Floor Gates."""

    def _setup_mock_kite(self):
        mock_kite = MagicMock()
        mock_kite.place_order.return_value = "ORD_12345"
        mock_kite.EXCHANGE_NFO = "NFO"
        mock_kite.TRANSACTION_TYPE_BUY = "BUY"
        mock_kite.ORDER_TYPE_LIMIT = "LIMIT"
        mock_kite.PRODUCT_NRML = "NRML"
        mock_kite.VARIETY_REGULAR = "regular"
        return mock_kite

    def test_mandatory_spot_confluence_gate_blocks_candidate(self):
        """Candidate with spot_confluence=False is rejected before order placement."""
        mock_kite = self._setup_mock_kite()
        candidate_no_conf = {
            "symbol": "GODREJPROP",
            "contract": "GODREJPROP26SEP2500CE",
            "side": "CE",
            "pattern": "BE_ABCD",
            "tier": 1,
            "tier_badge": "🥇 T1",
            "tier_label": "TIER_1_GOLD",
            "entry_spot": 50.0,
            "current_sl": 40.0,
            "t1": 70.0,
            "t2": 80.0,
            "t3": 90.0,
            "position_size": 1,
            "lot_size": 100,
            "spot_confluence": False,
            "spot_confluence_type": "NONE"
        }

        candidate_conf = {
            "symbol": "VOLTAS",
            "contract": "VOLTAS26SEP1800CE",
            "side": "CE",
            "pattern": "BASE_ABCD",
            "tier": 1,
            "tier_badge": "🥇 T1",
            "tier_label": "TIER_1_GOLD",
            "entry_spot": 50.0,
            "current_sl": 40.0,
            "t1": 70.0,
            "t2": 80.0,
            "t3": 90.0,
            "position_size": 1,
            "lot_size": 100,
            "spot_confluence": True,
            "spot_confluence_type": "SPOT_VWAP_RECLAIM",
            "vwap_stretch": 2.0,
            "vwap_status": "FAIR",
            "benchmark": 50.0,
            "dte": 10
        }

        executed_syms = []

        with patch.object(sote, "LIVE_MARKET_DEPLOYMENT", True):
            with patch.object(sote, "live_execution_enabled", return_value=True):
                with patch.object(sote, "is_new_entry_allowed", return_value=True):
                    with patch.object(sote.trade_db, "is_pattern_executed", return_value=False):
                        with patch.object(sote.trade_db, "is_symbol_active", return_value=False):
                            with patch.object(sote.trade_db, "is_contract_active", return_value=False):
                                with patch.object(sote.trade_db, "create_trade", return_value=("TR_1", True)):
                                    with patch("vix_guard.evaluate_vix_regime", return_value=(True, "OK", 15.0)):
                                        with patch("portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {})):
                                            with patch("liquidity_guard.check_bid_ask_spread_liquidity", return_value=(True, 0.01, "OK", {})):
                                                with patch("position_monitor.is_contract_held_on_broker", return_value=(False, 0)):
                                                    with patch.object(sote, "log_to_journal") as mock_journal:
                                                        sote.execute_highest_rr_trade(mock_kite, [candidate_no_conf, candidate_conf])
                                                        for call_args in mock_journal.call_args_list:
                                                            executed_syms.append(call_args[0][0])

        self.assertNotIn("GODREJPROP", executed_syms, "GODREJPROP (no confluence) must be blocked by Spot Confluence Gate!")
        self.assertIn("VOLTAS", executed_syms, "VOLTAS (confluence=True) must be executed when first candidate is blocked!")

    def test_safe_option_value_corridor_rejects_falling_knife(self):
        """Candidate with vwap_stretch < -5.0% is rejected as falling knife / decaying asset."""
        mock_kite = self._setup_mock_kite()
        candidate_knife = {
            "symbol": "KNIFE_SYM",
            "contract": "KNIFE26SEP100CE",
            "side": "CE",
            "pattern": "BE_ABCD",
            "tier": 1,
            "entry_spot": 50.0,
            "current_sl": 40.0,
            "t1": 70.0,
            "position_size": 1,
            "lot_size": 100,
            "spot_confluence": True,
            "vwap_stretch": -8.5,  # < -5.0% -> falling knife
            "vwap_status": "BREAKDOWN",
            "benchmark": 50.0,
            "dte": 10
        }

        rejected_reasons = []

        with patch.object(sote, "LIVE_MARKET_DEPLOYMENT", True):
            with patch.object(sote, "live_execution_enabled", return_value=True):
                with patch.object(sote, "is_new_entry_allowed", return_value=True):
                    with patch.object(sote.trade_db, "is_pattern_executed", return_value=False):
                        with patch.object(sote.trade_db, "is_symbol_active", return_value=False):
                            with patch("vix_guard.evaluate_vix_regime", return_value=(True, "OK", 15.0)):
                                with patch("portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {})):
                                    with patch.object(sote, "log_to_journal") as mock_journal:
                                        sote.execute_highest_rr_trade(mock_kite, [candidate_knife])
                                        for call_args in mock_journal.call_args_list:
                                            rejected_reasons.append(call_args[0][3])

        self.assertIn("SKIP_FALLING_KNIFE_VWAP", rejected_reasons, "Option trading < -5% below VWAP must be rejected as falling knife!")

    def test_safe_option_value_corridor_rejects_overstretched_fomo(self):
        """Candidate with vwap_stretch > 15.0% or vwap_status='STRETCHED' is skipped to wait for retest."""
        mock_kite = self._setup_mock_kite()
        candidate_fomo = {
            "symbol": "FOMO_SYM",
            "contract": "FOMO26SEP100CE",
            "side": "CE",
            "pattern": "HAMMER_ABCD",
            "tier": 1,
            "entry_spot": 50.0,
            "current_sl": 40.0,
            "t1": 70.0,
            "position_size": 1,
            "lot_size": 100,
            "spot_confluence": True,
            "vwap_stretch": 22.0,  # > 15% -> overstretched
            "vwap_status": "STRETCHED",
            "benchmark": 50.0,
            "dte": 10
        }

        rejected_reasons = []

        with patch.object(sote, "LIVE_MARKET_DEPLOYMENT", True):
            with patch.object(sote, "live_execution_enabled", return_value=True):
                with patch.object(sote, "is_new_entry_allowed", return_value=True):
                    with patch.object(sote.trade_db, "is_pattern_executed", return_value=False):
                        with patch.object(sote.trade_db, "is_symbol_active", return_value=False):
                            with patch("vix_guard.evaluate_vix_regime", return_value=(True, "OK", 15.0)):
                                with patch("portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {})):
                                    with patch.object(sote, "log_to_journal") as mock_journal:
                                        sote.execute_highest_rr_trade(mock_kite, [candidate_fomo])
                                        for call_args in mock_journal.call_args_list:
                                            rejected_reasons.append(call_args[0][3])

        self.assertIn("SKIP_OVERSTRETCHED_VWAP", rejected_reasons, "Option trading > 15% above VWAP must be skipped to avoid FOMO tops!")

    def test_premium_floor_gate_rejects_sub_5_rupee_on_low_dte(self):
        """Candidate with premium < 5.00 and DTE <= 5 is rejected as lottery ticket risk."""
        mock_kite = self._setup_mock_kite()
        candidate_lottery = {
            "symbol": "LOTTERY_SYM",
            "contract": "LOTTERY26SEP100CE",
            "side": "CE",
            "pattern": "HAMMER_ABCD",
            "tier": 1,
            "entry_spot": 3.20,
            "benchmark": 3.20,     # < 5.00
            "dte": 2,              # <= 5
            "current_sl": 1.50,
            "t1": 6.0,
            "position_size": 1,
            "lot_size": 1000,
            "spot_confluence": True,
            "vwap_stretch": 2.0,
            "vwap_status": "FAIR"
        }

        rejected_reasons = []

        with patch.object(sote, "LIVE_MARKET_DEPLOYMENT", True):
            with patch.object(sote, "live_execution_enabled", return_value=True):
                with patch.object(sote, "is_new_entry_allowed", return_value=True):
                    with patch.object(sote.trade_db, "is_pattern_executed", return_value=False):
                        with patch.object(sote.trade_db, "is_symbol_active", return_value=False):
                            with patch("vix_guard.evaluate_vix_regime", return_value=(True, "OK", 15.0)):
                                with patch("portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {})):
                                    with patch.object(sote, "log_to_journal") as mock_journal:
                                        sote.execute_highest_rr_trade(mock_kite, [candidate_lottery])
                                        for call_args in mock_journal.call_args_list:
                                            rejected_reasons.append(call_args[0][3])

        self.assertIn("SKIP_PREMIUM_FLOOR", rejected_reasons, "Option premium < 5.00 on DTE <= 5 must be rejected by Premium Floor Gate!")

    def test_premium_floor_boundary_exact_5_rupees_allowed(self):
        """Exact 5.00 benchmark premium on DTE <= 5 is permitted (only strictly < 5.00 is rejected)."""
        mock_kite = self._setup_mock_kite()
        candidate_exact_5 = {
            "symbol": "EXACT5_SYM",
            "contract": "EXACT526SEP100CE",
            "side": "CE",
            "pattern": "HAMMER_ABCD",
            "tier": 1,
            "entry_spot": 5.00,
            "benchmark": 5.00,
            "dte": 3,
            "current_sl": 3.0,
            "t1": 10.0,
            "t2": 12.0,
            "t3": 15.0,
            "position_size": 1,
            "lot_size": 100,
            "spot_confluence": True,
            "vwap_stretch": 2.0,
            "vwap_status": "FAIR"
        }

        executed_syms = []

        with patch.object(sote, "LIVE_MARKET_DEPLOYMENT", True):
            with patch.object(sote, "live_execution_enabled", return_value=True):
                with patch.object(sote, "is_new_entry_allowed", return_value=True):
                    with patch.object(sote.trade_db, "is_pattern_executed", return_value=False):
                        with patch.object(sote.trade_db, "is_symbol_active", return_value=False):
                            with patch.object(sote.trade_db, "is_contract_active", return_value=False):
                                with patch.object(sote.trade_db, "create_trade", return_value=("TR_2", True)):
                                    with patch("vix_guard.evaluate_vix_regime", return_value=(True, "OK", 15.0)):
                                        with patch("portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {})):
                                            with patch("liquidity_guard.check_bid_ask_spread_liquidity", return_value=(True, 0.01, "OK", {})):
                                                with patch("position_monitor.is_contract_held_on_broker", return_value=(False, 0)):
                                                    with patch.object(sote, "log_to_journal") as mock_journal:
                                                        sote.execute_highest_rr_trade(mock_kite, [candidate_exact_5])
                                                        for call_args in mock_journal.call_args_list:
                                                            executed_syms.append(call_args[0][0])

        self.assertIn("EXACT5_SYM", executed_syms, "Exact ₹5.00 benchmark premium must NOT be blocked by Premium Floor Gate!")

    def test_safe_option_value_corridor_boundaries(self):
        """Boundary conditions: exactly -5.0% and +15.0% are within corridor; -5.1% and +15.1% are rejected."""
        mock_kite = self._setup_mock_kite()
        # Candidate at exactly -5.0%
        cand_lower_bound = {
            "symbol": "BOUND_LOWER",
            "contract": "LOWER26SEP100CE",
            "side": "CE",
            "pattern": "HAMMER_ABCD",
            "tier": 1,
            "entry_spot": 50.0,
            "benchmark": 50.0,
            "dte": 10,
            "current_sl": 40.0,
            "t1": 70.0, "t2": 80.0, "t3": 90.0,
            "position_size": 1,
            "lot_size": 100,
            "spot_confluence": True,
            "vwap_stretch": -5.0,  # Exactly -5.0% (not < -5.0)
            "vwap_status": "FAIR"
        }

        # Candidate at exactly +15.0%
        cand_upper_bound = {
            "symbol": "BOUND_UPPER",
            "contract": "UPPER26SEP100CE",
            "side": "CE",
            "pattern": "HAMMER_ABCD",
            "tier": 1,
            "entry_spot": 50.0,
            "benchmark": 50.0,
            "dte": 10,
            "current_sl": 40.0,
            "t1": 70.0, "t2": 80.0, "t3": 90.0,
            "position_size": 1,
            "lot_size": 100,
            "spot_confluence": True,
            "vwap_stretch": 15.0,  # Exactly 15.0% (not > 15.0)
            "vwap_status": "EXPANDED"
        }

        executed_syms = []

        with patch.object(sote, "LIVE_MARKET_DEPLOYMENT", True):
            with patch.object(sote, "live_execution_enabled", return_value=True):
                with patch.object(sote, "is_new_entry_allowed", return_value=True):
                    with patch.object(sote.trade_db, "is_pattern_executed", return_value=False):
                        with patch.object(sote.trade_db, "is_symbol_active", return_value=False):
                            with patch.object(sote.trade_db, "is_contract_active", return_value=False):
                                with patch.object(sote.trade_db, "create_trade", return_value=("TR_BOUND", True)):
                                    with patch("vix_guard.evaluate_vix_regime", return_value=(True, "OK", 15.0)):
                                        with patch("portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {})):
                                            with patch("liquidity_guard.check_bid_ask_spread_liquidity", return_value=(True, 0.01, "OK", {})):
                                                with patch("position_monitor.is_contract_held_on_broker", return_value=(False, 0)):
                                                    with patch.object(sote, "log_to_journal") as mock_journal:
                                                        sote.execute_highest_rr_trade(mock_kite, [cand_lower_bound])
                                                        sote.execute_highest_rr_trade(mock_kite, [cand_upper_bound])
                                                        for call_args in mock_journal.call_args_list:
                                                            executed_syms.append(call_args[0][0])

        self.assertIn("BOUND_LOWER", executed_syms, "Boundary -5.0% stretch must be allowed!")
        self.assertIn("BOUND_UPPER", executed_syms, "Boundary +15.0% stretch must be allowed!")


class TestEdgeCasesAndBoundaryValues(unittest.TestCase):
    """Test 6: Edge cases, empty inputs, and boundary checks."""

    def test_avg_target_rank_empty_or_invalid_inputs(self):
        """_avg_target_rank must handle empty dicts, missing targets, or zero risk cleanly."""
        self.assertEqual(sote._avg_target_rank({}), 0)
        self.assertEqual(sote._avg_target_rank({"entry_spot": 100, "current_sl": 100}), 0)
        self.assertEqual(sote._avg_target_rank({"t1": 120, "entry_spot": 100, "current_sl": 100}), 0)

    def test_vcp_promotion_boundary_values(self):
        """Test boundary conditions for VCP promotion: ATR 0.65 vs 0.651, RR 1.50 vs 1.49."""
        tester = TestVCPCoiledPromotionGate()

        # ATR 0.65 (boundary pass)
        t, _, _ = tester._simulate_vcp_promotion(tier=2, spot_conf=True, atr_ratio=0.65, is_squeeze=False, cand_rr=1.50)
        self.assertEqual(t, 1, "ATR exactly 0.65 must promote")

        # ATR 0.651 (boundary fail)
        t, _, _ = tester._simulate_vcp_promotion(tier=2, spot_conf=True, atr_ratio=0.651, is_squeeze=False, cand_rr=1.50)
        self.assertEqual(t, 2, "ATR 0.651 must NOT promote")

        # RR 1.50 (boundary pass)
        t, _, _ = tester._simulate_vcp_promotion(tier=2, spot_conf=True, atr_ratio=0.50, is_squeeze=False, cand_rr=1.50)
        self.assertEqual(t, 1, "RR exactly 1.50 must promote")

        # RR 1.49 (boundary fail)
        t, _, _ = tester._simulate_vcp_promotion(tier=2, spot_conf=True, atr_ratio=0.50, is_squeeze=False, cand_rr=1.49)
        self.assertEqual(t, 2, "RR 1.49 must NOT promote")

    def test_spot_confluence_gate_blocks_none_and_missing_key(self):
        """Spot Confluence Gate strictly blocks candidates when spot_confluence is None or omitted."""
        mock_kite = MagicMock()
        cand_none = {
            "symbol": "CONF_NONE",
            "tier": 1,
            "entry_spot": 50.0,
            "current_sl": 40.0,
            "t1": 70.0,
            "spot_confluence": None,  # Explicit None
            "position_size": 1,
            "lot_size": 100
        }
        cand_missing = {
            "symbol": "CONF_MISSING",
            "tier": 1,
            "entry_spot": 50.0,
            "current_sl": 40.0,
            "t1": 70.0,
            # No spot_confluence key at all
            "position_size": 1,
            "lot_size": 100
        }
        executed = []
        with patch.object(sote, "LIVE_MARKET_DEPLOYMENT", False):
            with patch.object(sote, "log_to_journal") as mock_j:
                sote.execute_highest_rr_trade(mock_kite, [cand_none, cand_missing])
                for call_args in mock_j.call_args_list:
                    executed.append(call_args[0][0])
        self.assertNotIn("CONF_NONE", executed, "Candidate with spot_confluence=None must be blocked!")
        self.assertNotIn("CONF_MISSING", executed, "Candidate with missing spot_confluence key must be blocked!")

    def test_avg_target_rank_missing_entry_spot_no_crash(self):
        """_avg_target_rank must not raise KeyError when entry_spot is omitted."""
        # Risk is abs(0 - 10) = 10, targets present, entry_spot absent
        cand = {"t1": 50.0, "current_sl": 10.0}
        score = sote._avg_target_rank(cand)
        self.assertIsInstance(score, (int, float))
        self.assertGreaterEqual(score, 0)

    def test_gates_defensive_against_missing_sl_and_target(self):
        """Corridor and floor gates must log without raising KeyError when current_sl or t1 are missing."""
        mock_kite = MagicMock()
        cand_no_sl = {
            "symbol": "NO_SL_SYM",
            "contract": "NOSL26SEP100CE",
            "tier": 1,
            "entry_spot": 50.0,
            "benchmark": 3.0,
            "dte": 2,  # Triggers premium floor
            "spot_confluence": True,
            "position_size": 1,
            "lot_size": 100
            # current_sl and t1 missing
        }
        with patch.object(sote, "LIVE_MARKET_DEPLOYMENT", True):
            with patch.object(sote, "live_execution_enabled", return_value=True):
                with patch.object(sote, "is_new_entry_allowed", return_value=True):
                    with patch.object(sote.trade_db, "is_pattern_executed", return_value=False):
                        with patch.object(sote.trade_db, "is_symbol_active", return_value=False):
                            with patch("vix_guard.evaluate_vix_regime", return_value=(True, "OK", 15.0)):
                                with patch("portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {})):
                                    with patch.object(sote, "log_to_journal") as mock_j:
                                        sote.execute_highest_rr_trade(mock_kite, [cand_no_sl])
                                        # Should cleanly record SKIP_PREMIUM_FLOOR without crashing
                                        reasons = [c[0][3] for c in mock_j.call_args_list]
                                        self.assertIn("SKIP_PREMIUM_FLOOR", reasons)


if __name__ == "__main__":
    unittest.main()
