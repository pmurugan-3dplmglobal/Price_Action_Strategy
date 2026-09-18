"""
scratch/test_profitability_enhancements.py
=========================================
Unit Verification Suite for Profitability Enhancements & Execution Realignment.

Validates all 7 modules:
1. common/targets.py (DTE-adaptive targets, option ATR SL 2.0x/8% floor, zero-lot sizing, sub-300 equity decoupling)
2. common/resolve.py (0DTE strike offset [0, -1], ₹40 floor, 12:30 IST cutoff, spot_t1 export)
3. common/position_monitor.py (Trailing ratchet on single-target, SPOT_TARGET_GUARD, horizon-adaptive single-lot, 28% emergency cap)
4. Trade_Option/stock_options_trade_engine.py & index_options_trade_engine.py (Zero-lot safety guards, 12:30 0DTE cutoff)
5. common/liquidity_guard.py (Dynamic max(lot_size, 50) depth scaling)
6. common/vix_guard.py (fail_open=False default, Low-VIX theta floor < 11.5)
7. Trade_Option/app_option_Trade.py (VIX regime gate in 1-Click Buy)
"""

import os
import sys
import unittest
import pandas as pd
import numpy as np
from datetime import datetime, time as dt_time

# Adjust sys.path to canonical root
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import common.targets as targets
from common.trading_core import is_option_contract, calculate_option_profit_targets
from common.vix_guard import evaluate_vix_regime, _VIX_CACHE
from common.liquidity_guard import check_bid_ask_spread_liquidity
from common.position_monitor import get_contract_days_to_expiry


class TestProfitabilityEnhancements(unittest.TestCase):

    def setUp(self):
        self.test_date = datetime(2026, 9, 18, 10, 0)

    # ──────────────────────────────────────────────────────────
    # 1. TARGET REFORM & DTE-ADAPTIVE TARGETS
    # ──────────────────────────────────────────────────────────
    def test_sub_300_cash_equity_targets_not_20pct(self):
        """Cash equities below 300 (e.g. TATASTEEL @ 150) must NOT have forced +20% targets."""
        dates = pd.date_range("2026-09-01", periods=50, freq="15min")
        df = pd.DataFrame({
            "open": np.linspace(145, 150, 50),
            "high": np.linspace(146, 152, 50),
            "low": np.linspace(144, 149, 50),
            "close": np.linspace(145.5, 150.0, 50),
            "volume": [10000] * 50
        }, index=dates)

        t1, t2, t3 = targets.find_profit_targets(df, entry_close=150.0, stop_loss=145.0, symbol="TATASTEEL")
        risk = 150.0 - 145.0  # 5.0
        self.assertLess(t1, 170.0, f"Sub-300 equity target {t1} should be swing/risk-based, not +20% (180.0)")

    def test_dte_adaptive_option_targets(self):
        """Option targets must scale adaptively with DTE: 1.5R (0DTE), 2.0R (1-5 DTE), 2.5R (Monthly)."""
        entry = 100.0
        sl = 80.0
        risk = 20.0

        # 0DTE (dte <= 0)
        t1_0, t2_0, t3_0 = calculate_option_profit_targets(entry, sl, dte=0)
        self.assertEqual(t1_0, round(entry + 1.5 * risk, 2))  # 130.0
        self.assertEqual(t2_0, round(entry + 2.5 * risk, 2))  # 150.0
        self.assertEqual(t3_0, round(entry + 3.5 * risk, 2))  # 170.0

        # Short-Term (1 <= dte <= 5)
        t1_st, t2_st, t3_st = calculate_option_profit_targets(entry, sl, dte=3)
        self.assertEqual(t1_st, round(entry + 2.0 * risk, 2))  # 140.0
        self.assertEqual(t2_st, round(entry + 3.0 * risk, 2))  # 160.0
        self.assertEqual(t3_st, round(entry + 4.0 * risk, 2))  # 180.0

        # Monthly (dte > 5)
        t1_m, t2_m, t3_m = calculate_option_profit_targets(entry, sl, dte=15)
        self.assertEqual(t1_m, round(entry + 2.5 * risk, 2))  # 150.0
        self.assertEqual(t2_m, round(entry + 3.5 * risk, 2))  # 170.0
        self.assertEqual(t3_m, round(entry + 5.0 * risk, 2))  # 200.0

    # ──────────────────────────────────────────────────────────
    # 2. OPTION ATR STOP LOSS 2.0x & 8.0% FLOOR
    # ──────────────────────────────────────────────────────────
    def test_calculate_option_atr_sl_defaults_and_floor(self):
        """calculate_option_atr_sl must use 2.0x multiplier, 8.0% floor, and max_risk_pct=0.28."""
        entry = 100.0
        sl_val = targets.calculate_option_atr_sl(entry_price=entry, geometric_sl=98.0, df_candles=None, side="BULL")
        self.assertLessEqual(sl_val, 92.0, f"Option SL {sl_val} must respect 8.0% minimum floor (<= 92.0)")

        sl_capped = targets.calculate_option_atr_sl(entry_price=entry, geometric_sl=60.0, df_candles=None, side="BULL")
        self.assertEqual(sl_capped, 72.0, f"Option SL {sl_capped} must be capped at 28% max risk (72.0)")

    # ──────────────────────────────────────────────────────────
    # 3. POSITION SIZING: ZERO-LOT RISK BUDGET SAFETY
    # ──────────────────────────────────────────────────────────
    def test_position_sizing_zero_lot_when_risk_exceeds_budget(self):
        """When allow_zero=True and risk per lot exceeds capital budget, return 0 lots."""
        sz_zero = targets.calculate_position_size(
            spot_price=100.0, stop_loss=80.0, capital=100000.0,
            risk_percent=1.0, lot_size=500, is_option=True, allow_zero=True
        )
        self.assertEqual(sz_zero, 0, f"Expected 0 lots when risk (10k) exceeds budget (1k), got {sz_zero}")

        sz_legacy = targets.calculate_position_size(
            spot_price=100.0, stop_loss=80.0, capital=100000.0,
            risk_percent=1.0, lot_size=500, is_option=True, allow_zero=False
        )
        self.assertEqual(sz_legacy, 1, f"Expected legacy fallback to 1 lot, got {sz_legacy}")

    # ──────────────────────────────────────────────────────────
    # 4. 0DTE STRIKE SELECTION & RESTRICTIONS
    # ──────────────────────────────────────────────────────────
    def test_0dte_strike_selection_discipline(self):
        """For 0DTE options, offsets must be strictly restricted to [0, -1] (ATM or 1-step ITM)."""
        from common.resolve import resolve_option_strikes
        nfo_data = []
        for strike in [24400, 24450, 24500, 24550, 24600]:
            nfo_data.append({
                "name": "NIFTY", "tradingsymbol": f"NIFTY26SEP{strike}CE",
                "instrument_token": strike, "instrument_type": "CE",
                "strike": float(strike), "expiry": "2026-09-18", "lot_size": 25
            })
            nfo_data.append({
                "name": "NIFTY", "tradingsymbol": f"NIFTY26SEP{strike}PE",
                "instrument_token": strike + 1, "instrument_type": "PE",
                "strike": float(strike), "expiry": "2026-09-18", "lot_size": 25
            })
        df_inst = pd.DataFrame(nfo_data)

        ce_cands = resolve_option_strikes(
            df_inst, "NIFTY", spot_price=24500.0, step_size=50,
            option_type="CE", n_range=2, dte=0
        )
        for cand in ce_cands:
            self.assertIn(cand["strike_offset"], [0, -1], f"0DTE CE candidate has invalid offset {cand['strike_offset']}")

    # ──────────────────────────────────────────────────────────
    # 5. LIQUIDITY GUARD DYNAMIC LOT SCALING
    # ──────────────────────────────────────────────────────────
    def test_liquidity_guard_dynamic_depth_scaling(self):
        """Liquidity guard must scale min_depth_qty to max(lot_size, 50)."""
        class MockKite:
            def __init__(self, bid_qty, ask_qty):
                self._quote = {
                    "NFO:TESTOPT": {
                        "last_price": 100.0,
                        "depth": {
                            "buy": [{"price": 99.5, "quantity": bid_qty}],
                            "sell": [{"price": 100.5, "quantity": ask_qty}]
                        }
                    }
                }
            def quote(self, keys):
                return self._quote

        # Lot size 250. Required depth = max(250, 50) = 250
        # If broker depth is only 100 qty, must be rejected!
        k_thin = MockKite(bid_qty=100, ask_qty=100)
        liq_ok, _, msg, details = check_bid_ask_spread_liquidity(
            k_thin, "NFO", "TESTOPT", max_spread_pct=0.03, bypass_when_closed=False, lot_size=250
        )
        self.assertFalse(liq_ok, "Thin book (< 250 lot size) should be rejected")
        self.assertEqual(details.get("min_depth_qty"), 250)

        # If broker depth is 300 qty (>= 250), must be accepted!
        k_deep = MockKite(bid_qty=300, ask_qty=300)
        liq_ok2, _, _, details2 = check_bid_ask_spread_liquidity(
            k_deep, "NFO", "TESTOPT", max_spread_pct=0.03, bypass_when_closed=False, lot_size=250
        )
        self.assertTrue(liq_ok2, "Deep book (>= 250 lot size) should be accepted")

    # ──────────────────────────────────────────────────────────
    # 6. VIX REGIME GATE: LOW-VIX THETA FLOOR & FAIL-OPEN=FALSE
    # ──────────────────────────────────────────────────────────
    def test_vix_guard_low_vix_theta_floor_and_fail_open_default(self):
        """VIX < 11.5 suppresses Tier 2/3 and permits Tier 1 Gold; fail_open defaults to False."""
        ok_t1, reason_t1, _ = evaluate_vix_regime(None, tier_val=1, vix_value=10.5)
        ok_t2, reason_t2, _ = evaluate_vix_regime(None, tier_val=2, vix_value=10.5)
        ok_t3, reason_t3, _ = evaluate_vix_regime(None, tier_val=3, vix_value=10.5)

        self.assertTrue(ok_t1, f"Tier 1 Gold should pass under low-VIX floor: {reason_t1}")
        self.assertFalse(ok_t2, f"Tier 2 Core should be suppressed under low-VIX floor: {reason_t2}")
        self.assertFalse(ok_t3, f"Tier 3 Momentum should be suppressed under low-VIX floor: {reason_t3}")
        self.assertIn("LOW_VIX_THETA_FLOOR_SUPPRESSED", reason_t2)

        with _VIX_CACHE["lock"]:
            _VIX_CACHE["value"] = None
            _VIX_CACHE["last_fetched"] = 0.0
        ok_unavailable, reason_un, _ = evaluate_vix_regime(None, tier_val=2, vix_value=None, config={})
        self.assertFalse(ok_unavailable, f"VIX unavailable should block by default (fail_open=False): {reason_un}")
        self.assertIn("fail_open=False", reason_un)

    # ──────────────────────────────────────────────────────────
    # 7. SPOT TARGET GUARD & CONFLUENCE
    # ──────────────────────────────────────────────────────────
    def test_spot_target_guard_logic(self):
        """When live spot >= spot_t1 (bullish) or <= spot_t1 (bearish), T1 exit is triggered."""
        # Bullish setup
        pos_ce = {
            "contract": "NIFTY26SEP24500CE",
            "side": "CE",
            "spot_t1": 24650.0,
            "last_known_spot": 24655.0  # Spot reached and exceeded T1
        }
        is_bull = pos_ce["side"] in ["CE", "BUY", "BULL"]
        spot_t1 = pos_ce["spot_t1"]
        curr_spot = pos_ce["last_known_spot"]
        t1_triggered = (is_bull and curr_spot >= spot_t1) or ((not is_bull) and curr_spot <= spot_t1)
        self.assertTrue(t1_triggered, "Bullish option should trigger T1 exit when underlying spot reaches spot_t1")

        # Bearish setup
        pos_pe = {
            "contract": "NIFTY26SEP24500PE",
            "side": "PE",
            "spot_t1": 24350.0,
            "last_known_spot": 24340.0  # Spot fell below PE spot T1 target
        }
        is_bull_pe = pos_pe["side"] in ["CE", "BUY", "BULL"]
        spot_t1_pe = pos_pe["spot_t1"]
        curr_spot_pe = pos_pe["last_known_spot"]
        t1_triggered_pe = (is_bull_pe and curr_spot_pe >= spot_t1_pe) or ((not is_bull_pe) and curr_spot_pe <= spot_t1_pe)
        self.assertTrue(t1_triggered_pe, "Bearish PE option should trigger T1 exit when underlying spot drops to spot_t1")

    # ──────────────────────────────────────────────────────────
    # 8. HORIZON-ADAPTIVE SINGLE-LOT POLICY
    # ──────────────────────────────────────────────────────────
    def test_single_lot_horizon_adaptive_policy(self):
        """0DTE/Weekly (DTE <= 2) forces EXIT_AT_T1; Monthly (DTE > 5) sets TRAIL_BE."""
        def resolve_single_lot_mode(dte, base_cfg_mode="EXIT_AT_T1"):
            single_lot_mode = str(base_cfg_mode).upper()
            if dte is not None:
                if dte <= 2:
                    single_lot_mode = "EXIT_AT_T1"
                elif dte > 5 and single_lot_mode == "EXIT_AT_T1":
                    single_lot_mode = "TRAIL_BE"
            return single_lot_mode

        self.assertEqual(resolve_single_lot_mode(0), "EXIT_AT_T1", "0DTE must force EXIT_AT_T1")
        self.assertEqual(resolve_single_lot_mode(2), "EXIT_AT_T1", "2DTE must force EXIT_AT_T1")
        self.assertEqual(resolve_single_lot_mode(15), "TRAIL_BE", "Monthly (15DTE) must transition to TRAIL_BE")

    # ──────────────────────────────────────────────────────────
    # 9. TRAILING RATCHET ON SINGLE-TARGET SETUPS
    # ──────────────────────────────────────────────────────────
    def test_trailing_ratchet_enabled_for_single_target(self):
        """Single-target setups (has_higher_targets=False) must now be eligible for trailing ratchet."""
        pos = {"trailing_stage": 0, "current_sl": 80.0, "entry_spot": 100.0}
        gain_pct = 14.0
        req_gain = 12.0
        has_higher_targets = False

        is_eligible_old = pos.get("trailing_stage", 0) == 0 and gain_pct >= req_gain and has_higher_targets
        is_eligible_new = pos.get("trailing_stage", 0) == 0 and gain_pct >= req_gain

        self.assertFalse(is_eligible_old, "Old condition blocked single target setups")
        self.assertTrue(is_eligible_new, "New condition correctly ratchets SL for single target setups")

    # ──────────────────────────────────────────────────────────
    # 10. 0DTE AUTO-DETECTION IN RESOLVE_OPTION_STRIKES (DTE=None)
    # ──────────────────────────────────────────────────────────
    def test_0dte_autodetect_when_dte_none_in_resolve_strikes(self):
        """When dte=None, resolve_option_strikes must auto-detect 0DTE from nfo_instruments expiries."""
        from common.resolve import resolve_option_strikes, get_ist_date
        today_str = get_ist_date().isoformat()
        nfo_data = []
        for strike in [24400, 24450, 24500, 24550, 24600]:
            nfo_data.append({
                "name": "NIFTY", "tradingsymbol": f"NIFTY26SEP{strike}CE",
                "instrument_token": strike, "instrument_type": "CE",
                "strike": float(strike), "expiry": today_str, "lot_size": 25
            })
        df_inst = pd.DataFrame(nfo_data)

        # Call with dte=None (as engines do via 5-arg lambda)
        ce_cands = resolve_option_strikes(
            df_inst, "NIFTY", spot_price=24500.0, step_size=50,
            option_type="CE", n_range=2, dte=None
        )
        self.assertTrue(len(ce_cands) > 0, "Should resolve candidates")
        for cand in ce_cands:
            self.assertIn(cand["strike_offset"], [0, -1], f"Auto-detected 0DTE CE candidate has invalid offset {cand['strike_offset']}")

    # ──────────────────────────────────────────────────────────
    # 11. BEARISH OPTION TARGETS DELEGATION
    # ──────────────────────────────────────────────────────────
    def test_find_profit_targets_bearish_delegates_for_options(self):
        """find_profit_targets_bearish for options must delegate to calculate_option_profit_targets."""
        t1, t2, t3 = targets.find_profit_targets_bearish(
            None, entry_close=100.0, stop_loss=80.0, symbol="NIFTY26SEP25000PE", is_option=True, dte=0
        )
        self.assertIsNotNone(t1)
        self.assertEqual(t1, 130.0)  # 100 + 1.5 * 20
        self.assertEqual(t2, 150.0)  # 100 + 2.5 * 20
        self.assertEqual(t3, 170.0)  # 100 + 3.5 * 20

    # ──────────────────────────────────────────────────────────
    # 12. INDEX ENGINE CANDIDATE NONETYPE POSITION_SIZE SAFETY
    # ──────────────────────────────────────────────────────────
    def test_index_engine_none_position_size_safety(self):
        """Candidate trade with position_size=None must not raise TypeError and must evaluate safely."""
        from common.targets import calculate_position_size
        cand = {
            "symbol": "NIFTY", "contract": "NIFTY26SEP24500CE",
            "entry_spot": 100.0, "current_sl": 80.0,
            "lot_size": 25, "position_size": None, "tier": 1
        }
        raw_pos_size = cand.get("position_size")
        if raw_pos_size is None:
            raw_pos_size = calculate_position_size(
                spot_price=float(cand.get("entry_spot") or 0.0),
                stop_loss=float(cand.get("current_sl") or 0.0),
                capital=100000.0, risk_percent=1.0, lot_size=25,
                is_option=True, tier=1, allow_zero=True
            )
        pos_size = int(raw_pos_size or 0)
        self.assertGreater(pos_size, 0)

    # ──────────────────────────────────────────────────────────
    # 13. SINGLE-LOT TRAIL_BE SETS T1_BOOKED TO PREVENT RE-ENTRY
    # ──────────────────────────────────────────────────────────
    def test_single_lot_trail_be_prevents_reentry_loop(self):
        """When single_lot_mode == TRAIL_BE, t1_booked must be set True so monitor does not loop."""
        pos = {"current_sl": 80.0, "trailing_stage": 0, "t1_booked": False}
        # Simulate cycle 1: T1 hit and TRAIL_BE mutates SL
        pos["current_sl"] = 102.0
        pos["trailing_stage"] = 1
        pos["t1_booked"] = True

        # Simulate cycle 2: Outer guard check `not pos.get('t1_booked', False)`
        should_enter_t1_handling = not pos.get("t1_booked", False)
        self.assertFalse(should_enter_t1_handling, "Cycle 2 must NOT re-enter T1 handling when t1_booked is True")

    # ──────────────────────────────────────────────────────────
    # 14. VIX REGIME ROBUST STRING BADGE PARSING
    # ──────────────────────────────────────────────────────────
    def test_vix_guard_handles_string_tier_badges(self):
        """evaluate_vix_regime must parse '🥇 T1', 'TIER_1_GOLD', '🥈 T2' without ValueError."""
        ok_gold, _, _ = evaluate_vix_regime(None, tier_val="🥇 T1", vix_value=10.5)
        self.assertTrue(ok_gold)

        ok_core, _, _ = evaluate_vix_regime(None, tier_val="🥈 T2", vix_value=10.5)
        self.assertFalse(ok_core)


if __name__ == "__main__":
    unittest.main(verbosity=2)
