"""
scratch/test_tier2_architectural_upgrades.py
============================================
Unit test verification suite for Tier 2 Strategic Architectural Upgrades:
1. Point D Climax Excursion Throttle (patterns_bull.py & patterns_bear.py)
2. Consolidated Pre-Flight Batch Quote Query (liquidity_guard.py & stock_options_trade_engine.py)
3. Event-Driven WebSocket Triggers for Category A+ Setups (websocket_monitor.py)
"""

import sys
import os
import time
import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime as dt, timedelta

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from patterns_bull import scan_anchor_bcd_breakout
from patterns_bear import scan_anchor_bcd_breakout_bearish
from liquidity_guard import check_bid_ask_spread_liquidity
from websocket_monitor import ActivePositionWebSocketMonitor


class TestTier2ArchitecturalUpgrades(unittest.TestCase):

    def test_01_climax_excursion_throttle_bullish_blocks_overextended_d(self):
        """
        Verify that if Candle D closes >50% toward Target 1, market breakout is blocked,
        and permitted ONLY if price pulls back to Benchmark corridor as POST_D_RETEST.
        """
        # Create synthetic OHLCV dataframe:
        # Candle 3: Structural 5-bar swing high (High=120.0)
        # Candle 10: Anchor A (Bullish Engulfing, High=100.0, Low=96.0)
        # Candle 12: Point B (Close=100.8 > BM 100.0, High=101.2)
        # Candle 13: Point C (Retest Low=100.2, Close=100.4)
        # Candle 14: Point D Breakout
        dates = [dt(2026, 9, 1, 9, 15) + timedelta(minutes=15 * i) for i in range(25)]
        data = {
            "date": dates,
            "open": [98.0] * 25,
            "high": [99.0] * 25,
            "low": [97.0] * 25,
            "close": [98.0] * 25,
            "volume": [1000] * 25
        }
        df = pd.DataFrame(data)

        # Structural 5-bar swing high at Candle 3
        df.loc[3, "open"] = 118.0
        df.loc[3, "high"] = 120.0
        df.loc[3, "low"] = 115.0
        df.loc[3, "close"] = 119.0

        # Anchor Candle 10: Bullish Engulfing
        df.loc[9, "open"] = 98.5
        df.loc[9, "close"] = 96.5
        df.loc[9, "high"] = 98.5
        df.loc[9, "low"] = 96.0

        df.loc[10, "open"] = 96.2
        df.loc[10, "close"] = 99.0
        df.loc[10, "high"] = 100.0  # Benchmark = 100.0
        df.loc[10, "low"] = 96.0   # Anchor Low = 96.0 -> SL = 94.08

        df.loc[11, "open"] = 99.0
        df.loc[11, "close"] = 99.5
        df.loc[11, "high"] = 99.8
        df.loc[11, "low"] = 98.0

        # Point B (Candle 12)
        df.loc[12, "open"] = 99.5
        df.loc[12, "close"] = 100.8
        df.loc[12, "high"] = 101.2
        df.loc[12, "low"] = 99.0

        # Point C (Candle 13)
        df.loc[13, "open"] = 100.8
        df.loc[13, "close"] = 100.4
        df.loc[13, "high"] = 100.8
        df.loc[13, "low"] = 100.2

        # CASE A: Candle 14 is a Climax Point D closing at 115.0 (>50% toward Target 120.0)
        df_climax = df.copy().iloc[:16]
        df_climax.loc[14, "open"] = 100.5
        df_climax.loc[14, "close"] = 115.0
        df_climax.loc[14, "high"] = 115.5
        df_climax.loc[14, "low"] = 100.4
        df_climax.loc[14, "volume"] = 2500
        df_climax.loc[15, "open"] = 115.0
        df_climax.loc[15, "close"] = 115.2
        df_climax.loc[15, "high"] = 115.5
        df_climax.loc[15, "low"] = 114.5
        df_climax.loc[15, "volume"] = 1000

        res_climax = scan_anchor_bcd_breakout(df_climax, df_climax, entry_tf="15minute", enable_swing_filter=False)
        # Should be None because market entry was throttled (consumed > 50% toward T1)
        self.assertIsNone(
            res_climax,
            f"Expected Climax D bar to be throttled, but got: {res_climax}"
        )

        # CASE B: Candle 14 is normal Point D (Close = 102.0, <=50% toward Target 120.0)
        df_normal = df.copy().iloc[:16]
        df_normal.loc[14, "open"] = 100.5
        df_normal.loc[14, "close"] = 102.0
        df_normal.loc[14, "high"] = 102.5
        df_normal.loc[14, "low"] = 100.4
        df_normal.loc[14, "volume"] = 2500
        df_normal.loc[15, "open"] = 102.0
        df_normal.loc[15, "close"] = 104.0
        df_normal.loc[15, "high"] = 104.5
        df_normal.loc[15, "low"] = 101.8
        df_normal.loc[15, "volume"] = 1000

        res_normal = scan_anchor_bcd_breakout(df_normal, df_normal, entry_tf="15minute", enable_swing_filter=False)
        self.assertIsNotNone(res_normal, "Normal Point D breakout should not be throttled")
        self.assertIn(res_normal.get("Stage_Status"), ["FRESH_ENTRY", "EARLY_D_ENTRY"])

        # CASE C: Climax Candle 14 followed by subsequent pullback to Benchmark corridor (POST_D_RETEST)
        df_retest = df.copy().iloc[:17]
        df_retest.loc[14, "open"] = 100.5
        df_retest.loc[14, "close"] = 115.0
        df_retest.loc[14, "high"] = 115.5
        df_retest.loc[14, "low"] = 100.4
        df_retest.loc[14, "volume"] = 2500

        # Candle 15 pulls back
        df_retest.loc[15, "open"] = 115.0
        df_retest.loc[15, "close"] = 106.0
        df_retest.loc[15, "high"] = 115.0
        df_retest.loc[15, "low"] = 105.0

        # Candle 16 hovers at Benchmark corridor (100.8)
        df_retest.loc[16, "open"] = 106.0
        df_retest.loc[16, "close"] = 100.8
        df_retest.loc[16, "high"] = 106.0
        df_retest.loc[16, "low"] = 100.3

        res_retest = scan_anchor_bcd_breakout(df_retest, df_retest, entry_tf="15minute", enable_swing_filter=False)
        self.assertIsNotNone(res_retest, "Post-D retest near benchmark should be accepted")
        self.assertEqual(res_retest.get("Stage_Status"), "POST_D_RETEST")
        self.assertAlmostEqual(res_retest.get("Close"), 100.8, places=1)

    def test_02_consolidated_preflight_quote_bypasses_extra_network_calls(self):
        """
        Verify check_bid_ask_spread_liquidity uses passed quote_dict without calling kite.quote().
        """
        mock_kite = MagicMock()
        mock_kite.is_market_open = MagicMock(return_value=True)

        contract = "TITAN26OCT3500CE"
        q_key = f"NFO:{contract}"
        cached_quote = {
            q_key: {
                "last_price": 45.0,
                "depth": {
                    "buy": [{"price": 44.80, "quantity": 375}],
                    "sell": [{"price": 45.20, "quantity": 375}]
                }
            },
            "NSE:TITAN": {
                "last_price": 3490.0
            }
        }

        with patch("liquidity_guard.is_market_open", return_value=True):
            liq_ok, spread_pct, reason, details = check_bid_ask_spread_liquidity(
                kite=mock_kite,
                exchange="NFO",
                contract=contract,
                max_spread_pct=0.03,
                quote_dict=cached_quote
            )

        self.assertTrue(liq_ok)
        self.assertAlmostEqual(details.get("best_bid"), 44.80)
        self.assertAlmostEqual(details.get("best_ask"), 45.20)
        # Crucial: kite.quote must NOT have been called because quote_dict had the key
        mock_kite.quote.assert_not_called()

    def test_03_websocket_radar_registration_and_tick_trigger(self):
        """
        Verify ActivePositionWebSocketMonitor registers Category A+ candidates,
        subscribes tokens, and fires the trigger callback upon sub-second tick breach.
        """
        mon = ActivePositionWebSocketMonitor(api_key="mock_key", access_token="mock_token")
        mock_kws = MagicMock()
        mock_kws.ws = MagicMock()
        mock_kws.is_connected.return_value = True
        mon.kws = mock_kws
        mon.is_running = True
        mon.kws.on_ticks = mon.on_ticks

        # Register callback
        triggered_events = []
        def mock_callback(cand, live_p, tick_data):
            triggered_events.append((cand["contract"], live_p))

        mon.register_radar_callback(mock_callback)

        # Feed Category A+ candidates
        a_plus_candidates = [
            {
                "contract": "RELIANCE26OCT3000CE",
                "symbol": "RELIANCE",
                "option_token": 111111,
                "benchmark": 50.0,
                "current_sl": 42.0,
                "t1": 65.0,
                "stage": "STAGE_A_PLUS_READY"
            },
            {
                "contract": "TCS26OCT4500CE",
                "symbol": "TCS",
                "option_token": 222222,
                "benchmark": 80.0,
                "current_sl": 70.0,
                "t1": 100.0,
                "stage": "STAGE_A_PLUS_READY"
            }
        ]

        mon.update_radar_candidates(a_plus_candidates)

        # Tokens should be in radar_tokens and radar_candidates
        self.assertIn(111111, mon.radar_tokens)
        self.assertIn(222222, mon.radar_tokens)
        self.assertEqual(set(mock_kws.subscribe.call_args[0][0]), {111111, 222222})

        # Simulate ticks arriving:
        # Tick 1: RELIANCE at 48.0 (< BM 50.0) -> No trigger
        # Tick 2: RELIANCE at 50.5 (>= BM 50.0) -> Trigger!
        ticks = [
            {"instrument_token": 111111, "last_price": 48.0},
            {"instrument_token": 222222, "last_price": 75.0}
        ]
        mon.kws.on_ticks(mon.kws, ticks)
        time.sleep(0.05)
        self.assertEqual(len(triggered_events), 0, "No trigger expected below benchmark")

        # Now tick crosses benchmark
        trigger_ticks = [
            {"instrument_token": 111111, "last_price": 50.5}
        ]
        mon.kws.on_ticks(mon.kws, trigger_ticks)
        time.sleep(0.1)  # Allow async thread to execute

        self.assertEqual(len(triggered_events), 1)
        self.assertEqual(triggered_events[0][0], "RELIANCE26OCT3000CE")
        self.assertEqual(triggered_events[0][1], 50.5)

        # Duplicate tick should NOT trigger again due to debounce
        mon.kws.on_ticks(mon.kws, trigger_ticks)
        time.sleep(0.05)
        self.assertEqual(len(triggered_events), 1, "Duplicate tick should be debounced")

        # Test clear triggered token
        mon.clear_triggered_radar_token(111111)
        self.assertNotIn(111111, mon.radar_triggered_tokens)

    def test_04_websocket_subscriptions_isolation_between_active_and_radar(self):
        """
        Verify that active position updates and radar updates do not inadvertently
        unsubscribe tokens needed by the other.
        """
        mon = ActivePositionWebSocketMonitor(api_key="mock_key", access_token="mock_token")
        mock_kws = MagicMock()
        mock_kws.ws = MagicMock()
        mock_kws.is_connected.return_value = True
        mon.kws = mock_kws
        mon.is_running = True

        # Active position has Token 101
        mon.update_subscriptions({"INFY": {"option_token": 101}})
        self.assertEqual(mon.subscribed_tokens, {101})

        # Radar adds Token 202
        mon.update_radar_candidates([{"option_token": 202, "benchmark": 30.0}])
        self.assertEqual(mon.radar_tokens, {202})

        # Reset mock calls
        mock_kws.unsubscribe.reset_mock()

        # Update active positions without 202 -> must NOT unsubscribe 202 because it's in radar
        mon.update_subscriptions({"INFY": {"option_token": 101}})
        mock_kws.unsubscribe.assert_not_called()

        # Update radar candidates without 101 -> must NOT unsubscribe 101 because it's in active positions
        mon.update_radar_candidates([{"option_token": 202, "benchmark": 30.0}])
        mock_kws.unsubscribe.assert_not_called()


if __name__ == "__main__":
    unittest.main()
