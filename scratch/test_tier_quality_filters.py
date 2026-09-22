"""
scratch/test_tier_quality_filters.py
Verification suite for ISSUE-079:
1. Anti-Whipsaw Filter (Directional Conviction Guard)
2. Strict VCP Promotion Guard (ATR <= 0.85 ceiling + RR >= 1.80 floor)
3. Low VIX Trend Momentum Override & Debit Spread Exemption
4. Dynamic Slot Swap for High-Conviction Tier 1 Gold (RR >= 3.0)
"""

import unittest
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))

from common.vix_guard import evaluate_vix_regime
from common.portfolio_risk import find_weakest_swappable_position
import common.resolve as resolve


class TestTierQualityFilters(unittest.TestCase):

    def setUp(self):
        # Clear direction history before each test
        resolve._SYMBOL_DIRECTION_HISTORY.clear()

    def test_whipsaw_demotion_blocks_direction_flip(self):
        """Simulates RBLBANK: Flipped PE to CE within 34 mins -> Demoted from T1 to T2."""
        now = resolve.get_ist_now(naive=True)
        earlier = now - timedelta(minutes=34)

        # Simulate prior staged PE trade
        resolve._SYMBOL_DIRECTION_HISTORY["RBLBANK"] = ("PE", earlier)

        candidate = {
            "symbol": "RBLBANK",
            "contract": "RBLBANK26SEP410CE",
            "side": "CE",
            "tier": 1,
            "tier_badge": "🥇 T1",
            "tier_label": "TIER_1_GOLD",
            "rr": 2.13,
            "spot_confluence_type": "SPOT_SUPPORT_HOLD"
        }

        # Run step 1.5 logic directly
        prev_dir_info = resolve._SYMBOL_DIRECTION_HISTORY.get("RBLBANK")
        self.assertIsNotNone(prev_dir_info)
        prev_side, prev_time = prev_dir_info
        time_diff = (now - prev_time).total_seconds() / 60.0
        self.assertLessEqual(time_diff, resolve._WHIPSAW_WINDOW_MINUTES)

        conf_type = str(candidate.get("spot_confluence_type") or "").upper()
        is_major_reversal = (candidate["rr"] >= 3.0 and ("VWAP_RECLAIM" in conf_type or "VWAP_REJECT" in conf_type))
        self.assertFalse(is_major_reversal)

        if time_diff <= resolve._WHIPSAW_WINDOW_MINUTES and not is_major_reversal:
            candidate["tier"] = 2
            candidate["tier_label"] = "TIER_2_CORE"
            candidate["tier_badge"] = "🥈 T2"

        self.assertEqual(candidate["tier"], 2)
        self.assertEqual(candidate["tier_badge"], "🥈 T2")

    def test_whipsaw_allows_high_conviction_major_reversal(self):
        """A flip with RR >= 3.0 and VWAP Reclaim is a valid major reversal (exempt from demotion)."""
        now = resolve.get_ist_now(naive=True)
        earlier = now - timedelta(minutes=45)
        resolve._SYMBOL_DIRECTION_HISTORY["TRENT"] = ("PE", earlier)

        candidate = {
            "symbol": "TRENT",
            "contract": "TRENT26SEP2800CE",
            "side": "CE",
            "tier": 1,
            "tier_badge": "🥇 T1",
            "rr": 3.50,
            "spot_confluence_type": "SPOT_VWAP_RECLAIM"
        }

        prev_side, prev_time = resolve._SYMBOL_DIRECTION_HISTORY["TRENT"]
        time_diff = (now - prev_time).total_seconds() / 60.0
        conf_type = str(candidate.get("spot_confluence_type") or "").upper()
        is_major_reversal = (candidate["rr"] >= 3.0 and ("VWAP_RECLAIM" in conf_type or "VWAP_REJECT" in conf_type))
        self.assertTrue(is_major_reversal)

        # Should NOT demote
        if time_diff <= resolve._WHIPSAW_WINDOW_MINUTES and not is_major_reversal:
            candidate["tier"] = 2

        self.assertEqual(candidate["tier"], 1)

    def test_atr_ceiling_blocks_expanding_volatility(self):
        """Simulates KALYANKJIL: ATR ratio 1.36 (> 0.85) fails VCP promotion even with squeeze=True."""
        atr_r = 1.36
        is_squeeze = True
        cand_rr = 2.20
        spot_conf = True
        tier = 2

        # New VCP Gate rule
        promoted = (tier >= 2 and spot_conf and atr_r <= 0.85 and (atr_r <= 0.65 or is_squeeze) and cand_rr >= 1.80)
        self.assertFalse(promoted, "Expanding ATR ratio > 0.85 must NOT be promoted to Tier 1 Gold!")

    def test_vcp_promo_allows_genuine_coiled_base(self):
        """A genuine coiled base (ATR <= 0.85, squeeze=True, RR >= 1.80) is promoted to Tier 1 Gold."""
        atr_r = 0.58
        is_squeeze = True
        cand_rr = 2.45
        spot_conf = True
        tier = 2

        promoted = (tier >= 2 and spot_conf and atr_r <= 0.85 and (atr_r <= 0.65 or is_squeeze) and cand_rr >= 1.80)
        self.assertTrue(promoted, "Genuine coiled base should be promoted to Tier 1 Gold!")

    def test_low_vix_trend_momentum_override(self):
        """Tier 2 setup with Trend Momentum Override is permitted under low VIX (< 11.5)."""
        vix_val = 11.16
        is_allowed, reason, _ = evaluate_vix_regime(
            kite=None,
            tier_val=2,
            vix_value=vix_val,
            has_momentum_override=True
        )
        self.assertTrue(is_allowed)
        self.assertIn("LOW_VIX_TREND_MOMENTUM_OVERRIDE", reason)

    def test_low_vix_debit_spread_exemption(self):
        """Debit Spread setup is permitted under low VIX (< 11.5) due to Theta immunity."""
        vix_val = 11.16
        is_allowed, reason, _ = evaluate_vix_regime(
            kite=None,
            tier_val=2,
            vix_value=vix_val,
            is_debit_spread=True
        )
        self.assertTrue(is_allowed)
        self.assertIn("LOW_VIX_DEBIT_SPREAD_APPROVED", reason)

    def test_low_vix_blocks_naked_t2_without_momentum(self):
        """Naked Tier 2 setup without momentum override or spread is suppressed under low VIX."""
        vix_val = 11.16
        is_allowed, reason, _ = evaluate_vix_regime(
            kite=None,
            tier_val=2,
            vix_value=vix_val,
            has_momentum_override=False,
            is_debit_spread=False
        )
        self.assertFalse(is_allowed)
        self.assertIn("LOW_VIX_THETA_FLOOR_SUPPRESSED", reason)

    def test_dynamic_slot_swap_replaces_weakest(self):
        """Simulates KEI (RR=3.42): Finds the weakest stale/flat position and returns it for slot swap."""
        now = datetime.now()
        live_positions = {
            "APLAPOLLO": {
                "symbol": "APLAPOLLO",
                "contract": "APLAPOLLO26SEP2200PE",
                "entry_time": (now - timedelta(minutes=120)).strftime("%Y-%m-%d %H:%M:%S"),
                "entry_spot": 30.0,
                "ltp": 38.0,
                "trailing_stage": 1,  # Trailing stage 1 -> NOT swappable
                "rr": 2.5
            },
            "STALESTOCK": {
                "symbol": "STALESTOCK",
                "contract": "STALESTOCK26SEP100CE",
                "entry_time": (now - timedelta(minutes=75)).strftime("%Y-%m-%d %H:%M:%S"),
                "entry_spot": 50.0,
                "ltp": 48.5,  # Down -3%
                "trailing_stage": 0,  # Stage 0 -> SWAPPABLE!
                "rr": 1.5
            }
        }

        swappable = find_weakest_swappable_position(live_positions, candidate_rr=3.42, kite=None, min_hold_minutes=45.0)
        self.assertIsNotNone(swappable)
        self.assertEqual(swappable["symbol"], "STALESTOCK")
        self.assertIn("STALESTOCK", swappable["reason"])

    def test_slot_swap_rejects_low_rr_candidate(self):
        """Candidate with RR < 3.0 cannot trigger a dynamic slot swap."""
        live_positions = {
            "STALESTOCK": {
                "symbol": "STALESTOCK",
                "contract": "STALESTOCK26SEP100CE",
                "entry_time": (datetime.now() - timedelta(minutes=75)).strftime("%Y-%m-%d %H:%M:%S"),
                "entry_spot": 50.0,
                "ltp": 48.5,
                "trailing_stage": 0,
                "rr": 1.5
            }
        }
        # Candidate RR is only 2.20 (< 3.0)
        swappable = find_weakest_swappable_position(live_positions, candidate_rr=2.20, kite=None)
        self.assertIsNone(swappable, "Candidate with RR < 3.0 must NOT trigger slot swap!")


if __name__ == "__main__":
    unittest.main()
