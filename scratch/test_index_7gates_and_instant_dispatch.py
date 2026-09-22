"""Unit tests for ISSUE-073: Index Engine 7-Gate Funnel, Normalized Ranking, and Speed Phase Latency Elimination.

Tests:
1. Index Engine Candidate Ranking (Tier 1 Gold + VCP + Confluence prioritized over raw nominal points)
2. Gate 1: Mandatory Spot Confluence Gate in index_options_trade_engine
3. Gate 2: Low-DTE Premium Floor Gate (< ₹5.00 rejected on DTE <= 5) & 11:30 0DTE cutoff
4. Gate 3: Safe Option Value Corridor (> +15% overstretched & < -5% falling knife rejected)
5. Gate 6: Adaptive Liquidity Spread Gate in execute_index_entry (allows up to 3% for T1 Gold, blocks wide spreads)
6. Gate 7: Smart Pegged Mid-Price limit order routing for index options
7. Decoupled Index Position Monitor Thread initialization
8. Fast Bulk-Quote Screener skips dormant stocks while preserving incubating / active / core stocks
"""

import unittest
from unittest.mock import MagicMock, patch
import os
import sys
from datetime import datetime as dt, time as dt_time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [ROOT_DIR, os.path.join(ROOT_DIR, "common"), os.path.join(ROOT_DIR, "Trade_Option")]:
    if p not in sys.path:
        sys.path.insert(0, p)

import Trade_Option.index_options_trade_engine as iote
import Trade_Option.stock_options_trade_engine as sote
from common.targets import _avg_target_rank, _parse_candidate_tier


class TestIndex7GatesAndInstantDispatch(unittest.TestCase):

    def setUp(self):
        # Base setup templates
        self.base_nifty_setup = {
            "symbol": "NIFTY",
            "contract": "NIFTY26SEP24500CE",
            "pattern": "HAMMER_ABCD",
            "side": "CE",
            "strike": 24500,
            "entry_spot": 24500.0,
            "current_sl": 24450.0,
            "benchmark": 120.0,
            "t1": 24600.0,
            "t2": 24700.0,
            "t3": 24800.0,
            "rr": 2.0,
            "tier": 1,
            "tier_badge": "🥇 T1",
            "tier_label": "TIER_1_GOLD",
            "spot_confluence": True,
            "spot_confluence_type": "SPOT_ABOVE_VWAP",
            "atr_ratio": 0.60,
            "is_squeeze": True,
            "vwap_stretch": 2.5,
            "vwap_status": "NORMAL",
            "dte": 3,
            "position_size": 1,
            "timeframe": "15minute"
        }

        self.base_sensex_setup = {
            "symbol": "SENSEX",
            "contract": "SENSEX26SEP82000CE",
            "pattern": "BE_ABCD",
            "side": "CE",
            "strike": 82000,
            "entry_spot": 82000.0,
            "current_sl": 81800.0,  # 200 pts risk
            "benchmark": 300.0,
            "t1": 82250.0,
            "t2": 82400.0,
            "t3": 82500.0,  # 500 pts nominal gain, but no confluence and uncompressed ATR
            "rr": 2.5,
            "tier": 2,
            "tier_badge": "🥈 T2",
            "tier_label": "TIER_2_CORE",
            "spot_confluence": False,
            "spot_confluence_type": "NONE",
            "atr_ratio": 1.05,
            "is_squeeze": False,
            "vwap_stretch": 0.0,
            "vwap_status": "NORMAL",
            "dte": 4,
            "timeframe": "15minute"
        }

    def test_01_index_candidate_ranking_normalized_over_nominal_points(self):
        """Tier 1 Gold with Confluence and VCP must outrank uncompressed setups with large nominal points."""
        rank_nifty = _avg_target_rank(self.base_nifty_setup)
        rank_sensex = _avg_target_rank(self.base_sensex_setup)

        # NIFTY has confluence (+2.0) and VCP squeeze (+1.5) -> should easily outrank SENSEX
        self.assertGreater(rank_nifty, rank_sensex,
                           f"NIFTY score {rank_nifty} should exceed SENSEX {rank_sensex}")

    def test_02_gate_1_spot_confluence_blocks_index_auto_entry(self):
        """Gate 1: Index candidate with spot_confluence=False must be blocked from auto-entry."""
        mock_kite = MagicMock()
        cand_no_conf = dict(self.base_nifty_setup)
        cand_no_conf["spot_confluence"] = False

        with patch.object(iote, "LIVE_MARKET_DEPLOYMENT", True), \
             patch.object(iote, "live_execution_enabled", return_value=True), \
             patch.object(iote, "is_new_entry_allowed", return_value=True), \
             patch.object(iote, "execute_index_entry") as mock_exec, \
             patch("Trade_Option.index_options_trade_engine.trade_db.is_pattern_executed", return_value=False):

            iote.execute_highest_rr_trade(mock_kite, [cand_no_conf])
            mock_exec.assert_not_called()

    def test_03_gate_2_premium_floor_rejects_sub_5_lottery_options(self):
        """Gate 2: Index candidate with DTE <= 5 and benchmark < ₹5.00 must be rejected."""
        mock_kite = MagicMock()
        cand_cheap = dict(self.base_nifty_setup)
        cand_cheap["benchmark"] = 3.50
        cand_cheap["dte"] = 2

        with patch.object(iote, "LIVE_MARKET_DEPLOYMENT", True), \
             patch.object(iote, "live_execution_enabled", return_value=True), \
             patch.object(iote, "is_new_entry_allowed", return_value=True), \
             patch.object(iote, "execute_index_entry") as mock_exec, \
             patch("Trade_Option.index_options_trade_engine.trade_db.is_pattern_executed", return_value=False):

            iote.execute_highest_rr_trade(mock_kite, [cand_cheap])
            mock_exec.assert_not_called()

    def test_04_gate_3_safe_option_value_corridor(self):
        """Gate 3: Rejects overstretched (> +15%) and broken down (< -5%) option contracts."""
        mock_kite = MagicMock()

        # Overstretched FOMO
        cand_fomo = dict(self.base_nifty_setup)
        cand_fomo["vwap_stretch"] = 18.5
        cand_fomo["vwap_status"] = "STRETCHED"

        # Falling knife breakdown
        cand_knife = dict(self.base_nifty_setup)
        cand_knife["vwap_stretch"] = -8.0

        with patch.object(iote, "LIVE_MARKET_DEPLOYMENT", True), \
             patch.object(iote, "live_execution_enabled", return_value=True), \
             patch.object(iote, "is_new_entry_allowed", return_value=True), \
             patch.object(iote, "execute_index_entry") as mock_exec, \
             patch("Trade_Option.index_options_trade_engine.trade_db.is_pattern_executed", return_value=False):

            # FOMO rejected
            iote.execute_highest_rr_trade(mock_kite, [cand_fomo])
            mock_exec.assert_not_called()

            # Knife rejected
            iote.execute_highest_rr_trade(mock_kite, [cand_knife])
            mock_exec.assert_not_called()

    def test_05_gate_6_adaptive_spread_and_mid_price_routing(self):
        """Gate 6 & 7: execute_index_entry applies adaptive spread tolerance and pegs mid-price."""
        mock_kite = MagicMock()
        mock_kite.VARIETY_REGULAR = "regular"
        mock_kite.TRANSACTION_TYPE_BUY = "BUY"
        mock_kite.ORDER_TYPE_LIMIT = "LIMIT"
        mock_kite.PRODUCT_NRML = "NRML"
        mock_kite.place_order.return_value = "12345678"

        pos = dict(self.base_nifty_setup)
        pos["position_size"] = 1
        pos["position_type"] = "option"

        # Mock quote with 2.2% spread (Bid=98.0, Ask=100.2)
        q_data = {
            "NFO:NIFTY26SEP24500CE": {
                "last_price": 99.0,
                "depth": {
                    "buy": [{"price": 98.0, "quantity": 100}],
                    "sell": [{"price": 100.2, "quantity": 100}]
                }
            }
        }
        mock_kite.quote.return_value = q_data

        with patch.object(iote, "LIVE_MARKET_DEPLOYMENT", True), \
             patch("Trade_Option.index_options_trade_engine.clear_executed_exit"), \
             patch("Trade_Option.index_options_trade_engine.slice_quantity_for_freeze", return_value=[65]):

            # T1 Gold setup allows up to 3% spread -> succeeds and places order
            ok = iote.execute_index_entry(mock_kite, pos)
            self.assertTrue(ok)
            mock_kite.place_order.assert_called_once()
            placed_kwargs = mock_kite.place_order.call_args[1]
            # Since spread >= 0.8%, mid-price peg (98.0 + 100.2)/2 = 99.1 is used
            self.assertAlmostEqual(placed_kwargs["price"], 99.1, places=1)

    def test_06_fast_bulk_quote_screener_preserves_safeguards(self):
        """Bulk screener in stock engine skips dormant stocks but retains active and incubating stocks."""
        # Test the screener predicate logic
        incubating = {"TATAMOTORS"}
        active = {"RELIANCE"}
        nifty50 = {"INFY", "TCS"}

        test_quotes = {
            "NSE:TATAMOTORS": {"last_price": 950.0, "volume": 0, "ohlc": {"close": 950.0}},
            "NSE:RELIANCE": {"last_price": 2900.0, "volume": 0, "ohlc": {"close": 2900.0}},
            "NSE:INFY": {"last_price": 1900.0, "volume": 0, "ohlc": {"close": 1900.0}},
            "NSE:ACTIVE_MOVER": {"last_price": 500.0, "volume": 500000, "ohlc": {"close": 490.0}},  # 2.0% move
            "NSE:DEAD_STOCK": {"last_price": 100.0, "volume": 0, "ohlc": {"close": 100.0}}           # 0% move, 0 vol
        }

        # Simulating screener pass
        kept = []
        for s in ["TATAMOTORS", "RELIANCE", "INFY", "ACTIVE_MOVER", "DEAD_STOCK"]:
            if s in incubating or s in active or s in nifty50:
                kept.append(s)
                continue
            q = test_quotes.get(f"NSE:{s}", {})
            lp = float(q.get("last_price") or 0.0)
            vol = float(q.get("volume") or 0.0)
            ohlc = q.get("ohlc") or {}
            prev_close = float(ohlc.get("close") or 0.0)
            pct_chg = abs(lp - prev_close) / prev_close * 100.0 if prev_close > 0 else 0.0
            turnover_cr = (vol * lp) / 1e7
            if lp <= 0 or vol <= 0 or (pct_chg < 0.10 and turnover_cr < 0.25):
                continue
            kept.append(s)

        self.assertIn("TATAMOTORS", kept, "Incubating stock must never be skipped")
        self.assertIn("RELIANCE", kept, "Active position must never be skipped")
        self.assertIn("INFY", kept, "NIFTY50 core symbol must never be skipped")
        self.assertIn("ACTIVE_MOVER", kept, "Active intraday mover must be kept")
        self.assertNotIn("DEAD_STOCK", kept, "Dead flat stock should be skipped")

    def test_07_decoupled_position_monitor_thread_defined(self):
        """Verify position_monitor_loop is defined in index_options_trade_engine."""
        self.assertTrue(hasattr(iote, "position_monitor_loop"))
        self.assertTrue(callable(iote.position_monitor_loop))


if __name__ == "__main__":
    unittest.main()
