"""
scratch/test_spread_exit_and_index_cap.py

Unit test suite verifying:
1. Fix 1 (P0): Invert Spread Exit in position_monitor.py
   - Leg 2 (Short Leg Cover) executes BUY FIRST.
   - Leg 1 (Long Leg Sell) executes SELL SECOND.
2. Fix 3 (P1): Index Concurrency Cap
   - Default max_concurrent_index_positions = 1 blocks second directional index trade
     when 1 index trade (NIFTY, BANKNIFTY, SENSEX, etc.) is active.
   - Non-index stock options trades remain unblocked.
   - Configurable override (e.g. 2) allows up to configured cap.
3. Fix 4 (P1): 8:00 AM Auto-Purge & Manual Purge Radar API
   - Purge API /api/radar/purge-stale evicts prior-day incubation setups.
   - Retains current-day fresh setups.
"""

import sys
import os
import json
import unittest
from datetime import datetime as dt, timedelta

# Path alignment
COMMON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common"))
TRADE_OPTION_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Trade_Option"))
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for p in [COMMON_DIR, TRADE_OPTION_DIR, ROOT_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
import pattern_funnel
from position_monitor import close_position, clear_executed_exit, EXECUTED_EXITS
from portfolio_risk import check_portfolio_risk_caps, INDEX_SYMBOLS
import trade_db
import app_option_Trade


class MockKiteSession:
    """Mock KiteConnect session capturing order sequencing and position state."""
    def __init__(self, net_positions=None):
        self.placed_orders = []
        self._net_positions = net_positions or []
        self.VARIETY_REGULAR = "regular"
        self.ORDER_TYPE_LIMIT = "LIMIT"
        self.ORDER_TYPE_MARKET = "MARKET"
        self.TRANSACTION_TYPE_BUY = "BUY"
        self.TRANSACTION_TYPE_SELL = "SELL"
        self.PRODUCT_NRML = "NRML"
        self.PRODUCT_MIS = "MIS"

    def positions(self):
        return {"net": self._net_positions, "day": []}

    def orders(self):
        return []

    def cancel_order(self, variety, order_id):
        return True

    def quote(self, keys):
        res = {}
        for k in keys:
            res[k] = {
                "last_price": 50.0,
                "depth": {
                    "buy": [{"price": 49.5, "quantity": 100}],
                    "sell": [{"price": 50.5, "quantity": 100}]
                }
            }
        return res

    def place_order(self, variety=None, tradingsymbol=None, exchange=None,
                    transaction_type=None, quantity=None, order_type=None,
                    price=None, product=None):
        oid = f"OID_{len(self.placed_orders) + 1}_{tradingsymbol}"
        order_record = {
            "order_id": oid,
            "variety": variety,
            "tradingsymbol": tradingsymbol,
            "exchange": exchange,
            "transaction_type": transaction_type,
            "quantity": quantity,
            "order_type": order_type,
            "price": price,
            "product": product,
            "timestamp": dt.now().isoformat()
        }
        self.placed_orders.append(order_record)
        return oid


class TestSpreadExitAndIndexCap(unittest.TestCase):

    def setUp(self):
        # Clear executed exits cache
        EXECUTED_EXITS.clear()

    def tearDown(self):
        EXECUTED_EXITS.clear()

    # -------------------------------------------------------------------------
    # 1. TEST SPREAD EXIT INVERSION (P0)
    # -------------------------------------------------------------------------
    from unittest.mock import patch

    @patch("position_monitor.is_market_open", return_value=True)
    def test_spread_exit_inversion_leg2_buy_first_leg1_sell_second(self, mock_market_open):
        """
        Verify that close_position() on an option_spread executes:
        1. BUY order for Leg 2 (Short Leg Cover) FIRST.
        2. SELL order for Leg 1 (Long Leg) SECOND.
        Prevents Zerodha RMS margin rejection caused by unhedged naked short writing.
        """
        leg1_sym = "NIFTY2691523400CE"
        leg2_sym = "NIFTY2691523600CE"
        clear_executed_exit(leg1_sym)
        clear_executed_exit(leg2_sym)

        mock_positions = [
            {"tradingsymbol": leg1_sym, "quantity": 50, "product": "NRML"},
            {"tradingsymbol": leg2_sym, "quantity": -50, "product": "NRML"}
        ]
        mock_kite = MockKiteSession(net_positions=mock_positions)

        pos_spread = {
            "contract": leg1_sym,
            "position_type": "option_spread",
            "spread_type": "BULL_CALL_SPREAD",
            "leg2_contract": leg2_sym,
            "quantity": 50,
            "leg2_qty": 50,
            "product": "NRML",
            "entry_spot": 50.0
        }

        res = close_position(mock_kite, pos_spread, live_market=True)
        self.assertTrue(res.get("success"), f"Spread exit failed: {res}")

        orders = mock_kite.placed_orders
        self.assertGreaterEqual(len(orders), 2, f"Expected at least 2 orders placed, got: {orders}")

        first_order = orders[0]
        second_order = orders[1]

        # Order 1 MUST be Leg 2 Short Leg Cover (BUY)
        self.assertEqual(first_order["tradingsymbol"], leg2_sym,
                         f"Order 1 must be Leg 2 short leg ({leg2_sym}), got: {first_order['tradingsymbol']}")
        self.assertEqual(first_order["transaction_type"], "BUY",
                         f"Order 1 must be BUY to cover short leg, got: {first_order['transaction_type']}")
        self.assertEqual(first_order["order_type"], "MARKET",
                         f"Order 1 short cover must be MARKET order, got: {first_order['order_type']}")

        # Order 2 MUST be Leg 1 Long Leg Exit (SELL)
        self.assertEqual(second_order["tradingsymbol"], leg1_sym,
                         f"Order 2 must be Leg 1 long leg ({leg1_sym}), got: {second_order['tradingsymbol']}")
        self.assertEqual(second_order["transaction_type"], "SELL",
                         f"Order 2 must be SELL to close long leg, got: {second_order['transaction_type']}")

    @patch("position_monitor.is_market_open", return_value=True)
    def test_spread_exit_skips_leg2_if_already_covered(self, mock_market_open):
        """
        If Leg 2 short leg has already been covered (net quantity >= 0 on broker),
        close_position() should NOT place duplicate BUY order for Leg 2.
        """
        leg1_sym = "BANKNIFTY26SEP56000CE"
        leg2_sym = "BANKNIFTY26SEP56500CE"
        clear_executed_exit(leg1_sym)
        clear_executed_exit(leg2_sym)

        # Net quantity for leg 2 is 0 (already closed on broker)
        mock_positions = [
            {"tradingsymbol": leg1_sym, "quantity": 30, "product": "NRML"},
            {"tradingsymbol": leg2_sym, "quantity": 0, "product": "NRML"}
        ]
        mock_kite = MockKiteSession(net_positions=mock_positions)

        pos_spread = {
            "contract": leg1_sym,
            "position_type": "option_spread",
            "leg2_contract": leg2_sym,
            "quantity": 30,
            "leg2_qty": 30,
            "product": "NRML",
            "entry_spot": 100.0
        }

        res = close_position(mock_kite, pos_spread, live_market=True)
        self.assertTrue(res.get("success"), f"Exit failed: {res}")

        orders = mock_kite.placed_orders
        self.assertEqual(len(orders), 1, f"Expected exactly 1 order since leg2 is already closed, got: {orders}")
        self.assertEqual(orders[0]["tradingsymbol"], leg1_sym)
        self.assertEqual(orders[0]["transaction_type"], "SELL")

    # -------------------------------------------------------------------------
    # 2. TEST INDEX CONCURRENCY CAP (Fix 3)
    # -------------------------------------------------------------------------
    def test_index_concurrency_cap_blocks_correlated_index_entries(self):
        """
        Verify that portfolio_risk enforces max_concurrent_index_positions = 1:
        - When NIFTY is active, candidate BANKNIFTY is BLOCKED.
        - Non-index equities (e.g. RELIANCE) remain ALLOWED.
        """
        # Active trade on NIFTY
        active_positions = {
            "NIFTY": {
                "symbol": "NIFTY",
                "contract": "NIFTY2691523400CE",
                "quantity": 50
            }
        }

        cfg_cap_1 = {
            "portfolio_risk": {
                "enable": True,
                "max_concurrent_positions": 6,
                "max_concurrent_index_positions": 1
            }
        }

        # 1. Attempt candidate BANKNIFTY -> should be REJECTED by index concurrency cap
        ok_bn, reason_bn, details_bn = check_portfolio_risk_caps(
            engine="index",
            symbol="BANKNIFTY",
            candidate_tier=1,
            capital=100000.0,
            live_positions=active_positions,
            config=cfg_cap_1,
            include_db_trades=False
        )
        self.assertFalse(ok_bn, "Candidate BANKNIFTY should be blocked when NIFTY is active")
        self.assertIn("MAX_INDEX_POSITIONS_REACHED", reason_bn)
        self.assertEqual(details_bn.get("rule"), "max_concurrent_index_positions")

        # 2. Attempt candidate SENSEX -> should also be REJECTED
        ok_sx, reason_sx, _ = check_portfolio_risk_caps(
            engine="index",
            symbol="SENSEX",
            candidate_tier=1,
            capital=100000.0,
            live_positions=active_positions,
            config=cfg_cap_1,
            include_db_trades=False
        )
        self.assertFalse(ok_sx, "Candidate SENSEX should be blocked when NIFTY is active")
        self.assertIn("MAX_INDEX_POSITIONS_REACHED", reason_sx)

        # 3. Non-index stock candidate (RELIANCE) -> should be APPROVED
        ok_rel, reason_rel, _ = check_portfolio_risk_caps(
            engine="nifty50",
            symbol="RELIANCE",
            candidate_tier=1,
            capital=100000.0,
            live_positions=active_positions,
            config=cfg_cap_1,
            include_db_trades=False
        )
        self.assertTrue(ok_rel, f"RELIANCE stock option should not be blocked by index cap: {reason_rel}")

    def test_index_concurrency_cap_configurable_override(self):
        """
        Verify that setting index.max_concurrent_positions = 2 permits 2 concurrent index trades.
        """
        active_positions = {
            "NIFTY": {
                "symbol": "NIFTY",
                "contract": "NIFTY2691523400CE",
                "quantity": 50
            }
        }

        cfg_cap_2 = {
            "index": {
                "max_concurrent_positions": 2
            },
            "portfolio_risk": {
                "enable": True,
                "max_concurrent_positions": 6,
                "max_concurrent_index_positions": 2
            }
        }

        ok_bn, reason_bn, _ = check_portfolio_risk_caps(
            engine="index",
            symbol="BANKNIFTY",
            candidate_tier=1,
            capital=100000.0,
            live_positions=active_positions,
            config=cfg_cap_2,
            include_db_trades=False
        )
        self.assertTrue(ok_bn, f"BANKNIFTY should be allowed when limit is 2: {reason_bn}")

    # -------------------------------------------------------------------------
    # 3. TEST 8:00 AM AUTO-PURGE & PURGE RADAR API (Fix 4)
    # -------------------------------------------------------------------------
    def test_purge_stale_prior_day_setups(self):
        """
        Verify that pattern_funnel.purge_stale_prior_day_setups() evicts prior-day setups
        while preserving current-day fresh setups.
        """
        test_engine = "nifty50_test_purge"
        today_str = dt.now().strftime("%Y-%m-%d")
        yesterday_str = (dt.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        stale_item = {
            "symbol": "TCS",
            "contract": "TCS26SEP3800CE",
            "date": yesterday_str,
            "entry_time": f"{yesterday_str} 14:15:00",
            "benchmark": 3810.0,
            "rr": 2.5
        }
        fresh_item = {
            "symbol": "INFY",
            "contract": "INFY26SEP1800CE",
            "date": today_str,
            "entry_time": f"{today_str} 09:20:00",
            "benchmark": 1815.0,
            "rr": 3.0
        }

        # Populate test engine state
        pattern_funnel.save_funnel_state(test_engine, {
            "category_a_plus": [fresh_item],
            "category_a": [stale_item],
            "category_b": [stale_item]
        })

        # Run purge for today
        pattern_funnel.purge_stale_prior_day_setups(test_engine, today_str=today_str, purge_scan_display=False)

        state_after = pattern_funnel.load_funnel_state(test_engine)
        a_plus_after = state_after.get("category_a_plus", [])
        a_after = state_after.get("category_a", [])
        b_after = state_after.get("category_b", [])

        # Fresh item in A+ should be retained
        self.assertEqual(len(a_plus_after), 1)
        self.assertEqual(a_plus_after[0]["symbol"], "INFY")

        # Stale items in A and B should be completely evicted
        self.assertEqual(len(a_after), 0, f"Stale setup in category_a was not evicted: {a_after}")
        self.assertEqual(len(b_after), 0, f"Stale setup in category_b was not evicted: {b_after}")

    def test_purge_radar_api_endpoint(self):
        """
        Verify that Flask route /api/radar/purge-stale responds with 200 OK and JSON success.
        """
        with app_option_Trade.app.test_client() as client:
            with client.session_transaction() as sess:
                sess["user"] = "admin"
                sess["role"] = "admin"

            res = client.post("/api/radar/purge-stale")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("ok"))
            self.assertIn("Successfully purged prior-day stale setups", data.get("message", ""))


if __name__ == "__main__":
    print("=" * 80)
    print("RUNNING UNIT TESTS: SPREAD EXIT INVERSION, INDEX CAP, & RADAR PURGE")
    print("=" * 80)
    suite = unittest.TestLoader().loadTestsFromTestCase(TestSpreadExitAndIndexCap)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    if result.wasSuccessful():
        print("\n>>> ALL 6 UNIT TESTS PASSED WITH 100% SUCCESS! <<<")
        sys.exit(0)
    else:
        print(f"\n>>> TEST FAILURES DETECTED: {len(result.failures)} failures, {len(result.errors)} errors <<<")
        sys.exit(1)
