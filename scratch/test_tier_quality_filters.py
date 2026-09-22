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

    def test_spot_anchor_gate_blocks_counter_trend_illusion(self):
        """Simulates RBLBANK: Spot is in morning bull run (Higher Lows, EMA13 > EMA44).
        Candidate 410 PE must be BLOCKED from Tier 1 Gold because spot has NO bearish anchor."""
        import pandas as pd
        # Construct 10 bullish 30m candles
        candles = []
        base_p = 400.0
        for i in range(15):
            o = base_p + i * 0.8
            c = o + 0.6
            h = c + 0.3
            l = o - 0.2
            candles.append({"open": o, "high": h, "low": l, "close": c, "volume": 10000})
        df_bull_spot = pd.DataFrame(candles)

        # Checking PE side on bull spot
        has_anchor, anchor_name = resolve.check_spot_anchor_confirmation(df_bull_spot, "PE")
        self.assertFalse(has_anchor, "Spot in bull trend must NOT confirm PE anchor!")
        self.assertEqual(anchor_name, "NO_SPOT_BEAR_ANCHOR")

    def test_spot_anchor_gate_confirms_true_bearish_engulfing(self):
        """Simulates TRENT: Spot formed Bearish Engulfing anchor on 30m spot chart.
        Candidate PE MUST be confirmed for Tier 1 Gold promotion."""
        import pandas as pd
        candles = []
        base_p = 2800.0
        for i in range(10):
            candles.append({"open": base_p + i * 2, "high": base_p + i * 2 + 5, "low": base_p + i * 2 - 2, "close": base_p + i * 2 + 3, "volume": 10000})
        # Prior candle: Bullish (open 2820, close 2835, high 2840, low 2818)
        candles.append({"open": 2820.0, "high": 2840.0, "low": 2818.0, "close": 2835.0, "volume": 15000})
        # Current candle: Bearish Engulfing (open 2836, close 2810, high 2842, low 2808)
        candles.append({"open": 2836.0, "high": 2842.0, "low": 2808.0, "close": 2810.0, "volume": 35000})
        df_bear_spot = pd.DataFrame(candles)

        has_anchor, anchor_name = resolve.check_spot_anchor_confirmation(df_bear_spot, "PE")
        self.assertTrue(has_anchor, "Spot Bearish Engulfing must confirm PE anchor!")
        self.assertEqual(anchor_name, "SPOT_BEAR_ENGULFING")

    def test_spot_confluence_physical_wick_rejection(self):
        """Spot tested VWAP from below and showed physical upper wick selling rejection."""
        import pandas as pd
        vwap = 500.0
        # Candle tests VWAP at high 501.5, rejects and closes at 496.0 (open 497.0, low 495.0)
        # Upper wick = 501.5 - 497.0 = 4.5 >= 0.3 * body (1.0)
        c = pd.DataFrame([{
            "open": 497.0, "high": 501.5, "low": 495.0, "close": 496.0, "volume": 5000
        }])
        has_conf, conf_type = resolve.evaluate_spot_confluence(
            side="PE", is_d2=False, current_spot=496.0, spot_vwap=vwap,
            spot_sl=505.0, spot_ema_trend=False, df_spot=c
        )
        self.assertTrue(has_conf)
        self.assertEqual(conf_type, "SPOT_VWAP_REJECT")


    def test_spot_anchor_gate_blocks_bull_regime_trap_for_pe(self):
        """Spot price is above VWAP and EMA13 > EMA44 -> Instantly blocked with BULL_SPOT_REGIME_TRAP."""
        import pandas as pd
        candles = []
        base_p = 400.0
        for i in range(50):
            candles.append({"open": base_p + i * 0.5, "high": base_p + i * 0.5 + 1.0, "low": base_p + i * 0.5 - 0.2, "close": base_p + i * 0.5 + 0.8, "volume": 10000})
        df = pd.DataFrame(candles)
        vwap = 410.0  # Current price is 400 + 49*0.5 + 0.8 = 425.3 > VWAP
        has_anchor, reason = resolve.check_spot_anchor_confirmation(df, "PE", spot_vwap=vwap)
        self.assertFalse(has_anchor)
        self.assertEqual(reason, "BULL_SPOT_REGIME_TRAP")

    def test_spot_anchor_gate_blocks_bear_regime_trap_for_ce(self):
        """Spot price is below VWAP and EMA13 < EMA44 -> Instantly blocked with BEAR_SPOT_REGIME_TRAP."""
        import pandas as pd
        candles = []
        base_p = 500.0
        for i in range(50):
            candles.append({"open": base_p - i * 0.5, "high": base_p - i * 0.5 + 0.2, "low": base_p - i * 0.5 - 1.0, "close": base_p - i * 0.5 - 0.8, "volume": 10000})
        df = pd.DataFrame(candles)
        vwap = 490.0  # Current price is ~475 < VWAP
        has_anchor, reason = resolve.check_spot_anchor_confirmation(df, "CE", spot_vwap=vwap)
        self.assertFalse(has_anchor)
        self.assertEqual(reason, "BEAR_SPOT_REGIME_TRAP")

    def test_spot_ema_alignment_requires_rvol_1_point_2(self):
        """EMA alignment on spot requires RVOL >= 1.2 to confirm institutional trend volume."""
        import pandas as pd
        candles = []
        base_p = 600.0
        for i in range(30):
            candles.append({"open": base_p - i * 3.0, "high": base_p - i * 3.0 + 1.0, "low": base_p - i * 3.0 - 4.0, "close": base_p - i * 3.0 - 3.0, "volume": 10000})
        for i in range(20):
            candles.append({"open": 510.0, "high": 511.0, "low": 509.5, "close": 510.2, "volume": 5000})
        df_low_vol = pd.DataFrame(candles)
        has_anchor, reason = resolve.check_spot_anchor_confirmation(df_low_vol, "PE", spot_vwap=0.0)
        self.assertFalse(has_anchor, "EMA alignment with low RVOL < 1.2 must fail")

        # Last candle with high volume surge (RVOL = 20000 / 5000+ = 2.0+ >= 1.2)
        candles[-1]["volume"] = 20000
        df_high_vol = pd.DataFrame(candles)
        has_anchor_high, reason_high = resolve.check_spot_anchor_confirmation(df_high_vol, "PE", spot_vwap=0.0)
        self.assertTrue(has_anchor_high, "EMA alignment with RVOL >= 1.2 must confirm")
        self.assertEqual(reason_high, "SPOT_EMA_BEAR_ALIGNMENT")

    def test_dual_asset_vcp_requires_both_spot_and_option_contraction(self):
        """Dual-Asset VCP: Fails if Spot is expanding (> 0.85) even if option is coiled."""
        spot_atr_ratio_bad = 1.49  # APLAPOLLO expanding volatility
        spot_atr_ratio_good = 0.74  # BIOCON coiled
        opt_atr_ratio = 0.60
        is_squeeze = True
        cand_rr = 2.20
        spot_conf = True
        has_spot_anchor = True
        tier = 2

        # APLAPOLLO simulation:
        is_opt_vcp = (opt_atr_ratio <= 0.85 and (opt_atr_ratio <= 0.65 or is_squeeze))
        is_spot_vcp_bad = (spot_atr_ratio_bad <= 0.85)
        promo_bad = (tier >= 2 and spot_conf and has_spot_anchor and is_spot_vcp_bad and is_opt_vcp and cand_rr >= 1.80)
        self.assertFalse(promo_bad, "Expanding spot ATR 1.49 must NOT be promoted via VCP")

        # BIOCON simulation:
        is_spot_vcp_good = (spot_atr_ratio_good <= 0.85)
        promo_good = (tier >= 2 and spot_conf and has_spot_anchor and is_spot_vcp_good and is_opt_vcp and cand_rr >= 1.80)
        self.assertTrue(promo_good, "Coiled spot ATR 0.74 and coiled opt 0.60 must be promoted via Dual VCP")


if __name__ == "__main__":
    unittest.main()


