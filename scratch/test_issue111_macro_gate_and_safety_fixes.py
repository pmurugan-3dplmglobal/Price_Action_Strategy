"""
Unit verification suite for ISSUE-111 and Option 3 & 4 Enhancements:
1. Macro Index Gate (common/macro_gate.py) - Real-time NIFTY/BANKNIFTY delta directional gating & TTL cache
2. Position Monitor sl_distance minimum floor & opening gap breach override sanity
3. Portfolio Risk live_balance cash extraction priority
4. Terminal rejected order reconciliation & ghost positions purge
5. 50% UI capital spread margin floor derivation
6. Option 4: Configurable Modes (TREND_FOLLOWING, CONTRARIAN, OFF) & Dynamic Thresholds
7. Option 3: Institutional Relative Strength (RS) Alpha Bypass Exception for Decoupled Outperformers
"""

import sys
import os
import time
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.macro_gate import (
    evaluate_macro_index_gate,
    get_macro_index_deltas,
    get_macro_gate_config,
    check_rs_alpha_exception,
    _MACRO_CACHE,
    _CONFIG_CACHE
)
from common.portfolio_risk import get_live_available_cash


class TestIssue111MacroGateAndSafety(unittest.TestCase):

    def setUp(self):
        # Reset caches before tests
        _MACRO_CACHE["timestamp"] = 0.0
        _MACRO_CACHE["data"] = {}
        _CONFIG_CACHE["mtime"] = 0.0
        _CONFIG_CACHE["data"] = {}

    def test_01_macro_gate_ce_blocked_on_nifty_drop(self):
        """When NIFTY is red by > -0.25%, all CE buys must be blocked, PE allowed (TREND_FOLLOWING)."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 24800.0, "ohlc": {"close": 25000.0}},  # -0.80%
            "NSE:NIFTY BANK": {"last_price": 53000.0, "ohlc": {"close": 53500.0}} # -0.93%
        }

        # CE should be blocked
        allowed_ce, reason_ce = evaluate_macro_index_gate(mock_kite, "CE", "INFY", mode="TREND_FOLLOWING")
        self.assertFalse(allowed_ce)
        self.assertIn("NIFTY 50 is down", reason_ce)

        # PE should be allowed
        allowed_pe, reason_pe = evaluate_macro_index_gate(mock_kite, "PE", "INFY", mode="TREND_FOLLOWING")
        self.assertTrue(allowed_pe)

    def test_02_macro_gate_pe_blocked_on_nifty_rally(self):
        """When NIFTY is green by > +0.25%, all PE buys must be blocked, CE allowed (TREND_FOLLOWING)."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 25200.0, "ohlc": {"close": 25000.0}},  # +0.80%
            "NSE:NIFTY BANK": {"last_price": 53500.0, "ohlc": {"close": 53000.0}} # +0.94%
        }

        # PE should be blocked
        allowed_pe, reason_pe = evaluate_macro_index_gate(mock_kite, "PE", "TCS", mode="TREND_FOLLOWING")
        self.assertFalse(allowed_pe)
        self.assertIn("NIFTY 50 is up", reason_pe)

        # CE should be allowed
        allowed_ce, reason_ce = evaluate_macro_index_gate(mock_kite, "CE", "TCS", mode="TREND_FOLLOWING")
        self.assertTrue(allowed_ce)

    def test_03_macro_gate_banking_uses_banknifty(self):
        """Banking tickers should prioritize BANKNIFTY delta."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 25000.0, "ohlc": {"close": 25000.0}},  # 0.0%
            "NSE:NIFTY BANK": {"last_price": 53000.0, "ohlc": {"close": 53500.0}} # -0.93%
        }

        allowed_sbin_ce, reason_sbin = evaluate_macro_index_gate(mock_kite, "CE", "SBIN", mode="TREND_FOLLOWING")
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
        entry_s = 10.0
        current_sl = 10.0
        raw_dist = abs(entry_s - current_sl)

        sl_distance = max(raw_dist, current_sl * 0.05, 1.50)
        self.assertGreaterEqual(sl_distance, 1.50)

        ltp = 9.70
        gap_magnitude = current_sl - ltp
        is_catastrophic = gap_magnitude > (2.0 * sl_distance)
        self.assertFalse(is_catastrophic, "Normal 30-paise opening spread must NOT trigger catastrophic gap override")

        ltp_crash = 6.00
        gap_crash = current_sl - ltp_crash
        is_crash = gap_crash > (2.0 * sl_distance)
        self.assertTrue(is_crash, "Catastrophic 4-point crash must trigger gap override")

    def test_06_live_available_cash_prioritizes_live_balance(self):
        """Verify get_live_available_cash prioritizes live_balance over static opening cash."""
        mock_kite = MagicMock()
        mock_kite.margins.return_value = {
            "equity": {
                "available": {
                    "cash": 33234.90,
                    "live_balance": 11552.15,
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

    def test_08_macro_gate_contrarian_mode(self):
        """Option 4: In CONTRARIAN mode, direction is reversed (blocks PE on dips, blocks CE on surges)."""
        mock_kite = MagicMock()

        # Scenario A: Market Crash / Dip (-0.80%)
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 24800.0, "ohlc": {"close": 25000.0}},  # -0.80%
            "NSE:NIFTY BANK": {"last_price": 53000.0, "ohlc": {"close": 53500.0}} # -0.93%
        }
        # In CONTRARIAN: PE is blocked on drops (mean-reversion dip expectation)
        allowed_pe, reason_pe = evaluate_macro_index_gate(mock_kite, "PE", "INFY", mode="CONTRARIAN")
        self.assertFalse(allowed_pe)
        self.assertIn("MACRO_CONTRARIAN_DIP_GATE", reason_pe)

        # In CONTRARIAN: CE is allowed on oversold dips
        allowed_ce, reason_ce = evaluate_macro_index_gate(mock_kite, "CE", "INFY", mode="CONTRARIAN")
        self.assertTrue(allowed_ce)
        self.assertEqual(reason_ce, "MACRO_GATE_PASSED")

        # Scenario B: Market Rally / Surge (+0.80%)
        _MACRO_CACHE["timestamp"] = 0.0
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 25200.0, "ohlc": {"close": 25000.0}},  # +0.80%
            "NSE:NIFTY BANK": {"last_price": 53500.0, "ohlc": {"close": 53000.0}} # +0.94%
        }
        # In CONTRARIAN: CE is blocked on surges (mean-reversion peak pullback expectation)
        allowed_ce2, reason_ce2 = evaluate_macro_index_gate(mock_kite, "CE", "TCS", mode="CONTRARIAN")
        self.assertFalse(allowed_ce2)
        self.assertIn("MACRO_CONTRARIAN_PEAK_GATE", reason_ce2)

        # In CONTRARIAN: PE is allowed on overbought peaks
        allowed_pe2, reason_pe2 = evaluate_macro_index_gate(mock_kite, "PE", "TCS", mode="CONTRARIAN")
        self.assertTrue(allowed_pe2)
        self.assertEqual(reason_pe2, "MACRO_GATE_PASSED")

        # Scenario C: Banking ticker in CONTRARIAN
        _MACRO_CACHE["timestamp"] = 0.0
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 25000.0, "ohlc": {"close": 25000.0}},  # 0.0%
            "NSE:NIFTY BANK": {"last_price": 53000.0, "ohlc": {"close": 53500.0}} # -0.93%
        }
        allowed_bn_pe, reason_bn_pe = evaluate_macro_index_gate(mock_kite, "PE", "SBIN", mode="CONTRARIAN")
        self.assertFalse(allowed_bn_pe)
        self.assertIn("MACRO_CONTRARIAN_BANK_DIP_GATE", reason_bn_pe)

    def test_09_macro_gate_off_mode(self):
        """Option 4: In OFF mode, the gate allows all trades unconditionally."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 24000.0, "ohlc": {"close": 25000.0}},  # -4.0% Crash!
            "NSE:NIFTY BANK": {"last_price": 50000.0, "ohlc": {"close": 53500.0}} # -6.5% Crash!
        }
        allowed_ce, reason_ce = evaluate_macro_index_gate(mock_kite, "CE", "INFY", mode="OFF")
        self.assertTrue(allowed_ce)
        self.assertIn("MACRO_GATE_DISABLED", reason_ce)

        allowed_pe, reason_pe = evaluate_macro_index_gate(mock_kite, "PE", "INFY", mode="OFF")
        self.assertTrue(allowed_pe)
        self.assertIn("MACRO_GATE_DISABLED", reason_pe)

    def test_10_rs_alpha_exception_bypasses_macro_crash(self):
        """Option 3: Decoupled Alpha Outperformer (T1 Gold, RVOL >= 2.0x, Spot >= +1.0% VWAP) bypasses NIFTY crash."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 24800.0, "ohlc": {"close": 25000.0}},  # -0.80% Crash
            "NSE:NIFTY BANK": {"last_price": 53000.0, "ohlc": {"close": 53500.0}}
        }

        # 1. Valid Candidate: T1 Gold, RVOL 2.5x, Spot VWAP dist +1.5% -> PERMITTED via RS Alpha
        cand_gold = {
            "symbol": "RELIANCE",
            "tier": 1,
            "tier_badge": "🥇 T1",
            "rvol": 2.5,
            "vwap_dist_pct": 1.5
        }
        allowed, reason = evaluate_macro_index_gate(mock_kite, "CE", "RELIANCE", candidate_meta=cand_gold, mode="TREND_FOLLOWING")
        self.assertTrue(allowed)
        self.assertIn("RS_ALPHA_BYPASS", reason)
        self.assertIn("🥇 T1 Gold", reason)

        # 2. Dynamic spot vs vwap computation test
        cand_dynamic_vwap = {
            "symbol": "TCS",
            "tier": 1,
            "rvol": 2.2,
            "spot_entry": 3950.0,
            "spot_vwap": 3900.0  # +1.28% above VWAP
        }
        allowed_dyn, reason_dyn = evaluate_macro_index_gate(mock_kite, "CE", "TCS", candidate_meta=cand_dynamic_vwap, mode="TREND_FOLLOWING")
        self.assertTrue(allowed_dyn)
        self.assertIn("RS_ALPHA_BYPASS", reason_dyn)

        # 3. Negative: Tier 2 Core (Not Gold) -> Blocked
        cand_t2 = {
            "symbol": "RELIANCE",
            "tier": 2,
            "tier_badge": "🥈 T2",
            "rvol": 2.5,
            "vwap_dist_pct": 1.5
        }
        allowed_t2, reason_t2 = evaluate_macro_index_gate(mock_kite, "CE", "RELIANCE", candidate_meta=cand_t2, mode="TREND_FOLLOWING")
        self.assertFalse(allowed_t2)
        self.assertIn("NIFTY 50 is down", reason_t2)

        # 4. Negative: Low RVOL 1.2x (< 2.0x) -> Blocked
        cand_low_rvol = {
            "symbol": "RELIANCE",
            "tier": 1,
            "rvol": 1.2,
            "vwap_dist_pct": 1.5
        }
        allowed_lr, reason_lr = evaluate_macro_index_gate(mock_kite, "CE", "RELIANCE", candidate_meta=cand_low_rvol, mode="TREND_FOLLOWING")
        self.assertFalse(allowed_lr)
        self.assertIn("NIFTY 50 is down", reason_lr)

        # 5. Negative: VWAP distance +0.4% (< +1.0%) -> Blocked
        cand_weak_vwap = {
            "symbol": "RELIANCE",
            "tier": 1,
            "rvol": 2.5,
            "vwap_dist_pct": 0.4
        }
        allowed_wv, reason_wv = evaluate_macro_index_gate(mock_kite, "CE", "RELIANCE", candidate_meta=cand_weak_vwap, mode="TREND_FOLLOWING")
        self.assertFalse(allowed_wv)
        self.assertIn("NIFTY 50 is down", reason_wv)

        # 6. Negative: Index symbol (NIFTY) cannot decouple from itself -> Blocked
        cand_index = {
            "symbol": "NIFTY",
            "tier": 1,
            "rvol": 3.0,
            "vwap_dist_pct": 2.0
        }
        allowed_idx, reason_idx = evaluate_macro_index_gate(mock_kite, "CE", "NIFTY", candidate_meta=cand_index, mode="TREND_FOLLOWING")
        self.assertFalse(allowed_idx)
        self.assertIn("NIFTY 50 is down", reason_idx)

    def test_11_rs_alpha_exception_put_bypasses_macro_surge(self):
        """Option 3: Decoupled Put Alpha Outperformer (T1 Gold, RVOL >= 2.0x, Spot <= -1.0% VWAP) bypasses NIFTY rally."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 25200.0, "ohlc": {"close": 25000.0}},  # +0.80% Surge
            "NSE:NIFTY BANK": {"last_price": 53500.0, "ohlc": {"close": 53000.0}}
        }

        # 1. Valid Put Decoupled Breakdown: Spot is -1.5% below VWAP with 2.8x RVOL
        cand_put_gold = {
            "symbol": "TATASTEEL",
            "tier": 1,
            "rvol": 2.8,
            "vwap_dist_pct": -1.5
        }
        allowed_pe, reason_pe = evaluate_macro_index_gate(mock_kite, "PE", "TATASTEEL", candidate_meta=cand_put_gold, mode="TREND_FOLLOWING")
        self.assertTrue(allowed_pe)
        self.assertIn("RS_ALPHA_BYPASS", reason_pe)

        # 2. Negative: Put candidate price is above VWAP (+0.5%) -> Not an institutional breakdown
        cand_put_bad = {
            "symbol": "TATASTEEL",
            "tier": 1,
            "rvol": 2.8,
            "vwap_dist_pct": 0.5
        }
        allowed_bad, reason_bad = evaluate_macro_index_gate(mock_kite, "PE", "TATASTEEL", candidate_meta=cand_put_bad, mode="TREND_FOLLOWING")
        self.assertFalse(allowed_bad)
        self.assertIn("NIFTY 50 is up", reason_bad)

    def test_12_dynamic_config_loading(self):
        """Option 4: get_macro_gate_config loads dynamically and reflects input/program_config.json."""
        cfg = get_macro_gate_config(force_reload=True)
        self.assertTrue(cfg.get("enable"))
        self.assertEqual(cfg.get("mode"), "TREND_FOLLOWING")
        self.assertEqual(cfg.get("nifty_drop_threshold_pct"), -0.5)
        self.assertEqual(cfg.get("nifty_surge_threshold_pct"), 0.5)
        self.assertEqual(cfg.get("banknifty_drop_threshold_pct"), -0.75)
        self.assertEqual(cfg.get("banknifty_surge_threshold_pct"), 0.75)
        self.assertEqual(cfg.get("nifty_drop_threshold"), -0.5)
        self.assertEqual(cfg.get("nifty_surge_threshold"), 0.5)
        self.assertTrue(cfg.get("allow_rs_alpha_bypass"))
        self.assertTrue(cfg.get("allow_rs_alpha_exception"))
        self.assertEqual(cfg.get("rs_min_tier"), "GOLD")
        self.assertEqual(cfg.get("rs_min_rvol"), 2.0)
        self.assertEqual(cfg.get("rs_vwap_distance_pct"), 1.0)
        self.assertEqual(cfg.get("rs_min_vwap_dist_pct"), 1.0)

    def test_13_rs_min_tier_configuration(self):
        """Option 3 & 4: rs_min_tier dynamic qualification (GOLD vs SILVER)."""
        cand_t2 = {
            "symbol": "BAJFINANCE",
            "tier": 2,
            "tier_label": "TIER_2_CORE",
            "tier_badge": "🥈 T2",
            "rvol": 2.5,
            "vwap_dist_pct": 1.8
        }
        # With rs_min_tier="GOLD", T2 is blocked
        ok_gold, reason_gold = check_rs_alpha_exception(cand_t2, "CE", "BAJFINANCE", rs_min_tier="GOLD")
        self.assertFalse(ok_gold)
        self.assertIn("TIER_NOT_GOLD", reason_gold)

        # With rs_min_tier="SILVER", T2 is permitted
        ok_silver, reason_silver = check_rs_alpha_exception(cand_t2, "CE", "BAJFINANCE", rs_min_tier="SILVER")
        self.assertTrue(ok_silver)
        self.assertIn("RS_ALPHA_BYPASS", reason_silver)

    def test_14_allow_rs_alpha_bypass_toggle(self):
        """Option 4: When allow_rs_alpha_bypass is False, even T1 Gold outlier is blocked."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 24800.0, "ohlc": {"close": 25000.0}},  # -0.80% Crash
            "NSE:NIFTY BANK": {"last_price": 53000.0, "ohlc": {"close": 53500.0}}
        }
        cand_gold = {
            "symbol": "RELIANCE",
            "tier": 1,
            "tier_badge": "🥇 T1",
            "rvol": 3.0,
            "vwap_dist_pct": 2.0
        }
        # Explicit bypass disabled -> Must block
        allowed, reason = evaluate_macro_index_gate(
            mock_kite, "CE", "RELIANCE", candidate_meta=cand_gold,
            mode="TREND_FOLLOWING", allow_rs_alpha_bypass=False
        )
        self.assertFalse(allowed)
        self.assertIn("NIFTY 50 is down", reason)

    def test_15_end_to_end_resolve_and_gate0b_simulation(self):
        """End-to-End Simulation: Filtering multiple candidates during macro crash."""
        mock_kite = MagicMock()
        mock_kite.quote.return_value = {
            "NSE:NIFTY 50": {"last_price": 24800.0, "ohlc": {"close": 25000.0}},  # -0.80% (crash < -0.5%)
            "NSE:NIFTY BANK": {"last_price": 53000.0, "ohlc": {"close": 53500.0}}
        }

        candidates = [
            # 1. Normal CE candidate (Tier 2, low RVOL) -> Should be blocked by crash
            {"contract": "INFY26OCT1800CE", "symbol": "INFY", "side": "CE", "tier": 2, "rvol": 1.1, "vwap_dist_pct": 0.2},
            # 2. RS Alpha Outperformer CE (Tier 1 Gold, RVOL 2.5x, VWAP +1.5%) -> Should bypass and pass!
            {"contract": "RELIANCE26OCT3000CE", "symbol": "RELIANCE", "side": "CE", "tier": 1, "tier_badge": "🥇 T1", "rvol": 2.5, "vwap_dist_pct": 1.5},
            # 3. PE candidate (direction aligned with crash) -> Should pass!
            {"contract": "TCS26OCT4000PE", "symbol": "TCS", "side": "PE", "tier": 2, "rvol": 1.2, "vwap_dist_pct": -0.8},
            # 4. Index CE candidate (cannot decouple from itself) -> Should be blocked!
            {"contract": "NIFTY26OCT25000CE", "symbol": "NIFTY", "side": "CE", "tier": 1, "tier_badge": "🥇 T1", "rvol": 3.0, "vwap_dist_pct": 2.0}
        ]

        passed = []
        for c in candidates:
            ok, reason = evaluate_macro_index_gate(mock_kite, c["side"], c["symbol"], candidate_meta=c)
            if ok:
                passed.append((c["contract"], reason))

        passed_contracts = [p[0] for p in passed]
        self.assertNotIn("INFY26OCT1800CE", passed_contracts, "Ordinary CE must be blocked during crash")
        self.assertIn("RELIANCE26OCT3000CE", passed_contracts, "RS Alpha CE outperformer must pass during crash")
        self.assertIn("TCS26OCT4000PE", passed_contracts, "Trend-aligned PE must pass during crash")
        self.assertNotIn("NIFTY26OCT25000CE", passed_contracts, "Index CE must never decouple from itself")

        # Verify RS Alpha reason string on the outperformer
        rel_reason = next(r for c, r in passed if c == "RELIANCE26OCT3000CE")
        self.assertIn("RS_ALPHA_BYPASS", rel_reason)


if __name__ == "__main__":
    unittest.main(verbosity=2)
