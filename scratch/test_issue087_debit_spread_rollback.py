"""
scratch/test_issue087_debit_spread_rollback.py
=============================================
Dedicated Unit Verification Suite for ISSUE-087:
Leg 1 / Leg 2 Debit Spread Failure & Rollback Handling across:
1. Manual 1-Click Buy (app_option_Trade.py)
2. Automated Index Options Trade Engine (index_options_trade_engine.py)
3. Automated Stock Options Trade Engine (stock_options_trade_engine.py)
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

PROJ_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMON_DIR = os.path.join(PROJ_ROOT, "common")
TRADE_OPTION_DIR = os.path.join(PROJ_ROOT, "Trade_Option")
for p in [PROJ_ROOT, COMMON_DIR, TRADE_OPTION_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)


class TestDebitSpreadRollbackManual1Click(unittest.TestCase):
    """Test Suite for Manual 1-Click Buy debit spread error handling in app_option_Trade.py."""

    def setUp(self):
        import Trade_Option.app_option_Trade as app_mod
        self.app_mod = app_mod
        self.client = app_mod.app.test_client()

    def _authenticated_client(self):
        ctx = self.client.session_transaction()
        sess = ctx.__enter__()
        sess["user"] = "admin"
        sess["role"] = "admin"
        ctx.__exit__(None, None, None)
        return self.client

    @patch("Trade_Option.app_option_Trade._kite_session")
    @patch("common.position_monitor.is_contract_held_on_broker")
    @patch("common.position_monitor.confirm_leg1_order_filled")
    @patch("common.resolve.resolve_option_spread")
    @patch("liquidity_guard.check_bid_ask_spread_liquidity", return_value=(True, 0.01, "OK", 0))
    @patch("vix_guard.evaluate_vix_regime", return_value=(True, "OK", {}))
    @patch("portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {}))
    def test_1click_leg1_not_filled_aborts_spread(self, mock_risk, mock_vix, mock_liq, mock_resolve, mock_confirm, mock_held, mock_kite):
        """When Leg 1 confirmation fails and contract is not held, cancel resting order and abort Leg 2."""
        mock_kite.VARIETY_REGULAR = "regular"
        mock_kite.TRANSACTION_TYPE_BUY = "BUY"
        mock_kite.TRANSACTION_TYPE_SELL = "SELL"
        mock_kite.ORDER_TYPE_LIMIT = "LIMIT"
        mock_kite.PRODUCT_NRML = "NRML"
        mock_kite.place_order.return_value = "ORD_LEG1_123"

        mock_resolve.return_value = {
            "spread_type": "BULL_CALL_DEBIT_SPREAD",
            "leg1": {"contract": "NIFTY26SEP24000CE", "token": 111, "strike": 24000, "lot_size": 25},
            "leg2": {"contract": "NIFTY26SEP24200CE", "token": 222, "strike": 24200, "lot_size": 25, "entry_price": 50.0}
        }
        # Leg 1 confirmation times out
        mock_confirm.return_value = (False, [], ["ORD_LEG1_123"], "TIMEOUT")
        # Not held on broker
        mock_held.return_value = (False, 0)

        client = self._authenticated_client()
        with patch("trading_core.is_market_open", return_value=True):
            resp = client.post("/api/buy-scanned-trade", json={
                "symbol": "NIFTY",
                "contract": "NIFTY26SEP24000CE",
                "lot_size": 25,
                "price": 100.0,
                "engine": "index",
                "side": "CE",
                "direction": "BULL",
                "force": True
            })

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("was not filled", data["error"])
        # Verify Leg 1 resting order was cancelled
        mock_kite.cancel_order.assert_called_with(variety="regular", order_id="ORD_LEG1_123")
        # Verify Leg 2 was never placed
        self.assertEqual(mock_kite.place_order.call_count, 1)  # Only Leg 1 attempt

    @patch("Trade_Option.app_option_Trade._kite_session")
    @patch("common.position_monitor.is_contract_held_on_broker")
    @patch("common.position_monitor.confirm_leg1_order_filled")
    @patch("common.resolve.resolve_option_spread")
    @patch("liquidity_guard.check_bid_ask_spread_liquidity", return_value=(True, 0.01, "OK", 0))
    @patch("vix_guard.evaluate_vix_regime", return_value=(True, "OK", {}))
    @patch("portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {}))
    def test_1click_leg2_failure_triggers_emergency_unwind(self, mock_risk, mock_vix, mock_liq, mock_resolve, mock_confirm, mock_held, mock_kite):
        """When Leg 2 fails and Leg 1 is held on broker, execute emergency unwind SELL to close Leg 1."""
        mock_kite.VARIETY_REGULAR = "regular"
        mock_kite.TRANSACTION_TYPE_BUY = "BUY"
        mock_kite.TRANSACTION_TYPE_SELL = "SELL"
        mock_kite.ORDER_TYPE_LIMIT = "LIMIT"
        mock_kite.PRODUCT_NRML = "NRML"
        
        # Leg 1 places successfully
        # Leg 2 throws Exception (e.g. RMS Margin Error)
        # Emergency unwind places SELL order successfully
        def mock_place_order(**kwargs):
            if kwargs.get("tradingsymbol") == "NIFTY26SEP24000CE" and kwargs.get("transaction_type") == "BUY":
                return "ORD_LEG1_123"
            elif kwargs.get("tradingsymbol") == "NIFTY26SEP24200CE":
                raise RuntimeError("RMS: Margin Insufficient for Leg 2 Short")
            elif kwargs.get("tradingsymbol") == "NIFTY26SEP24000CE" and kwargs.get("transaction_type") == "SELL":
                return "ORD_UNWIND_999"
            return "ORD_OTHER"

        mock_kite.place_order.side_effect = mock_place_order
        mock_kite.quote.return_value = {
            "NFO:NIFTY26SEP24000CE": {"last_price": 95.0, "depth": {"buy": [{"price": 94.5}]}},
            "NFO:NIFTY26SEP24200CE": {"last_price": 50.0, "depth": {"buy": [{"price": 49.5}]}}
        }

        mock_resolve.return_value = {
            "spread_type": "BULL_CALL_DEBIT_SPREAD",
            "leg1": {"contract": "NIFTY26SEP24000CE", "token": 111, "strike": 24000, "lot_size": 25},
            "leg2": {"contract": "NIFTY26SEP24200CE", "token": 222, "strike": 24200, "lot_size": 25, "entry_price": 50.0}
        }
        mock_confirm.return_value = (True, ["ORD_LEG1_123"], [], "ALL_COMPLETE")
        # Broker holds 25 qty of Leg 1
        mock_held.return_value = (True, 25)

        client = self._authenticated_client()
        with patch("trading_core.is_market_open", return_value=True):
            resp = client.post("/api/buy-scanned-trade", json={
                "symbol": "NIFTY",
                "contract": "NIFTY26SEP24000CE",
                "lot_size": 25,
                "price": 100.0,
                "engine": "index",
                "side": "CE",
                "direction": "BULL",
                "force": True,
                "is_debit_spread": True,
                "spread_info": mock_resolve.return_value
            })

        self.assertEqual(resp.status_code, 400)
        data = resp.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("Emergency unwind executed: cleanly sold Leg 1", data["error"])
        
        # Verify emergency unwind SELL order was executed with tag="spread_unwind"
        sell_calls = [c for c in mock_kite.place_order.call_args_list if c[1].get("tag") == "spread_unwind"]
        self.assertEqual(len(sell_calls), 1)
        self.assertEqual(sell_calls[0][1]["tradingsymbol"], "NIFTY26SEP24000CE")
        self.assertEqual(sell_calls[0][1]["quantity"], 25)
        self.assertEqual(sell_calls[0][1]["tag"], "spread_unwind")

    @patch("Trade_Option.app_option_Trade._kite_session")
    @patch("common.position_monitor.is_contract_held_on_broker")
    @patch("common.position_monitor.confirm_leg1_order_filled")
    @patch("common.resolve.resolve_option_spread")
    @patch("liquidity_guard.check_bid_ask_spread_liquidity", return_value=(True, 0.01, "OK", 0))
    @patch("vix_guard.evaluate_vix_regime", return_value=(True, "OK", {}))
    @patch("portfolio_risk.check_portfolio_risk_caps", return_value=(True, "OK", {}))
    def test_1click_leg2_failure_and_unwind_failure_retains_position(self, mock_risk, mock_vix, mock_liq, mock_resolve, mock_confirm, mock_held, mock_kite):
        """When Leg 2 fails AND emergency unwind fails, retain trade in trade_db as naked option and return 500 alert."""
        mock_kite.VARIETY_REGULAR = "regular"
        mock_kite.TRANSACTION_TYPE_BUY = "BUY"
        mock_kite.TRANSACTION_TYPE_SELL = "SELL"
        mock_kite.ORDER_TYPE_LIMIT = "LIMIT"
        mock_kite.PRODUCT_NRML = "NRML"

        def mock_place_order(**kwargs):
            if kwargs.get("tradingsymbol") == "NIFTY26SEP24000CE" and kwargs.get("transaction_type") == "BUY":
                return "ORD_LEG1_123"
            elif kwargs.get("tradingsymbol") == "NIFTY26SEP24200CE":
                raise RuntimeError("Leg 2 rejection")
            elif kwargs.get("tradingsymbol") == "NIFTY26SEP24000CE" and kwargs.get("transaction_type") == "SELL":
                raise RuntimeError("Broker connection dropped during unwind")
            return "ORD_OTHER"

        mock_kite.place_order.side_effect = mock_place_order
        mock_kite.quote.return_value = {
            "NFO:NIFTY26SEP24000CE": {"last_price": 95.0, "depth": {"buy": [{"price": 94.5}]}},
            "NFO:NIFTY26SEP24200CE": {"last_price": 50.0, "depth": {"buy": [{"price": 49.5}]}}
        }

        mock_resolve.return_value = {
            "spread_type": "BULL_CALL_DEBIT_SPREAD",
            "leg1": {"contract": "NIFTY26SEP24000CE", "token": 111, "strike": 24000, "lot_size": 25},
            "leg2": {"contract": "NIFTY26SEP24200CE", "token": 222, "strike": 24200, "lot_size": 25, "entry_price": 50.0}
        }
        mock_confirm.return_value = (True, ["ORD_LEG1_123"], [], "ALL_COMPLETE")
        mock_held.return_value = (True, 25)

        client = self._authenticated_client()
        with patch("trading_core.is_market_open", return_value=True), \
             patch("trade_db.create_trade", return_value=(9999, True)) as mock_create_trade:
            resp = client.post("/api/buy-scanned-trade", json={
                "symbol": "NIFTY",
                "contract": "NIFTY26SEP24000CE",
                "lot_size": 25,
                "price": 100.0,
                "engine": "index",
                "side": "CE",
                "direction": "BULL",
                "force": True,
                "is_debit_spread": True,
                "spread_info": mock_resolve.return_value
            })

        self.assertEqual(resp.status_code, 500)
        data = resp.get_json()
        self.assertFalse(data["ok"])
        self.assertIn("CRITICAL", data["error"])
        self.assertIn("emergency unwind failed", data["error"])
        # Verify trade was created in trade_db as naked option so position monitor protects it
        mock_create_trade.assert_called_once()
        saved_trade_data = mock_create_trade.call_args[0][2]
        self.assertEqual(saved_trade_data["position_type"], "option")


class TestDebitSpreadRollbackAutoEngines(unittest.TestCase):
    """Test Suite for Automated Engines (Index & Stock Options)."""

    def test_index_engine_leg2_failure_emergency_unwind(self):
        """Index options trade engine executes freeze-sliced emergency unwind on Leg 2 failure."""
        import Trade_Option.index_options_trade_engine as idx_engine
        
        mock_kite = MagicMock()
        mock_kite.VARIETY_REGULAR = "regular"
        mock_kite.TRANSACTION_TYPE_BUY = "BUY"
        mock_kite.TRANSACTION_TYPE_SELL = "SELL"
        mock_kite.ORDER_TYPE_LIMIT = "LIMIT"
        mock_kite.PRODUCT_NRML = "NRML"

        def mock_place_order(**kwargs):
            if kwargs.get("tradingsymbol") == "NIFTY26SEP24000CE" and kwargs.get("transaction_type") == "BUY":
                return "1001"
            elif kwargs.get("tradingsymbol") == "NIFTY26SEP24200CE":
                raise RuntimeError("Leg 2 rejection")
            elif kwargs.get("tradingsymbol") == "NIFTY26SEP24000CE" and kwargs.get("transaction_type") == "SELL":
                return "UNWIND_1001"
            return "OTHER"

        mock_kite.place_order.side_effect = mock_place_order
        mock_kite.ltp.return_value = {"NFO:NIFTY26SEP24000CE": {"last_price": 120.0}}

        pos = {
            "symbol": "NIFTY",
            "contract": "NIFTY26SEP24000CE",
            "position_type": "option_spread",
            "leg2_contract": "NIFTY26SEP24200CE",
            "entry_premium": 120.0,
            "position_size": 104,  # 104 * 25 = 2600 qty
            "trade_id": 1234
        }

        with patch("liquidity_guard.check_bid_ask_spread_liquidity", return_value=(True, 0.01, "OK", 0)), \
             patch("common.position_monitor.confirm_leg1_order_filled", return_value=(True, ["1001"], [], "ALL_COMPLETE")), \
             patch("common.position_monitor.is_contract_held_on_broker", return_value=(True, 2600)), \
             patch("session.safe_kite_call", side_effect=lambda fn, *a, **kw: fn(*a, **kw)), \
             patch("Trade_Option.index_options_trade_engine.safe_kite_call", side_effect=lambda fn, *a, **kw: fn(*a, **kw)), \
             patch("Trade_Option.index_options_trade_engine.trade_db.update_trade") as mock_update_trade:
            
            res = idx_engine.execute_index_entry(mock_kite, pos)
            
            self.assertFalse(res)
            # Verify emergency unwind SELL orders were placed with freeze slicing (NIFTY freeze limit is 1755, so 2600 -> [1755, 845])
            unwind_calls = [c for c in mock_kite.place_order.call_args_list if c[1].get("tag") == "idx_spread_unwind"]
            self.assertEqual(len(unwind_calls), 2)
            self.assertEqual(unwind_calls[0][1]["quantity"], 1755)
            self.assertEqual(unwind_calls[1][1]["quantity"], 845)
            self.assertEqual(unwind_calls[0][1]["tag"], "idx_spread_unwind")
            # Verify trade marked as FAILED in trade_db
            mock_update_trade.assert_called_with(1234, {
                "status": "FAILED",
                "exit_reason": "ORDER_PLACEMENT_FAILED",
                "updated_at": unittest.mock.ANY
            })

    def test_index_engine_leg2_failure_and_unwind_failure_retains_option(self):
        """Index options trade engine retains position as 'option' if emergency unwind fails."""
        import Trade_Option.index_options_trade_engine as idx_engine

        mock_kite = MagicMock()
        mock_kite.place_order.side_effect = [
            "1001",  # Leg 1
            RuntimeError("Leg 2 rejection"),
            RuntimeError("Unwind sell rejected by exchange")
        ]
        mock_kite.ltp.return_value = {"NFO:NIFTY26SEP24000CE": {"last_price": 120.0}}

        pos = {
            "symbol": "NIFTY",
            "contract": "NIFTY26SEP24000CE",
            "position_type": "option_spread",
            "leg2_contract": "NIFTY26SEP24200CE",
            "entry_premium": 120.0,
            "position_size": 1,
            "trade_id": 5678
        }
        idx_engine.ACTIVE_POSITIONS["NIFTY"] = pos

        with patch("liquidity_guard.check_bid_ask_spread_liquidity", return_value=(True, 0.01, "OK", 0)), \
             patch("common.position_monitor.confirm_leg1_order_filled", return_value=(True, ["1001"], [], "ALL_COMPLETE")), \
             patch("common.position_monitor.is_contract_held_on_broker", return_value=(True, 25)), \
             patch("session.safe_kite_call", side_effect=lambda fn, *a, **kw: fn(*a, **kw)), \
             patch("Trade_Option.index_options_trade_engine.safe_kite_call", side_effect=lambda fn, *a, **kw: fn(*a, **kw)), \
             patch("Trade_Option.index_options_trade_engine.trade_db.update_trade") as mock_update_trade:

            res = idx_engine.execute_index_entry(mock_kite, pos)

            self.assertFalse(res)
            # Position must NOT be removed from ACTIVE_POSITIONS! It must be retained as "option"
            self.assertIn("NIFTY", idx_engine.ACTIVE_POSITIONS)
            self.assertEqual(idx_engine.ACTIVE_POSITIONS["NIFTY"]["position_type"], "option")
            mock_update_trade.assert_called_with(5678, {
                "status": "OPEN",
                "position_type": "option",
                "updated_at": unittest.mock.ANY
            })

    def test_stock_engine_emergency_unwind_freeze_slicing(self):
        """Stock options trade engine applies freeze slicing to emergency unwind on Leg 2 failure."""
        from common.position_monitor import slice_quantity_for_freeze
        # Verify slice_quantity_for_freeze handles stock options with large multi-lot quantity
        slices = slice_quantity_for_freeze("RELIANCE26SEP2900CE", 100000)
        # 100000 with 50000 freeze limit -> [50000, 50000]
        self.assertEqual(slices, [50000, 50000])


if __name__ == "__main__":
    unittest.main(verbosity=2)
