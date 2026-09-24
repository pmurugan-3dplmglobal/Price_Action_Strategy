"""
Unit tests verifying fixes for:
1. WebSocket monitor 'NoneType' object has no attribute 'sendMessage' during connecting/reconnecting states.
2. trade_db.reconcile_broker_live_positions rate-limiting, caching, and safe_kite_call integration.
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))

from websocket_monitor import ActivePositionWebSocketMonitor
import trade_db


class TestWebSocketAndReconcileFixes(unittest.TestCase):

    def test_websocket_no_ws_attribute_error_suppression(self):
        """ActivePositionWebSocketMonitor.update_subscriptions must not raise AttributeError when ws is None."""
        mon = ActivePositionWebSocketMonitor(api_key="mock_key", access_token="mock_token")
        
        # Simulate kws object created but ws is None (pre-handshake)
        mock_kws = MagicMock()
        mock_kws.ws = None
        mock_kws.is_connected.return_value = False
        mon.kws = mock_kws
        mon.is_running = True

        # Calling update_subscriptions with active positions
        active_pos = {
            "NIFTY26SEP24000CE": {"option_token": 123456},
            "GMRAIRPORT": {"token": 78910}
        }

        # This should NOT call mock_kws.subscribe or raise AttributeError
        mon.update_subscriptions(active_pos)
        self.assertEqual(mon.subscribed_tokens, {123456, 78910})
        mock_kws.subscribe.assert_not_called()

        # Now simulate socket connected
        mock_kws.ws = MagicMock()
        mock_kws.is_connected.return_value = True

        # Add another token
        active_pos["VOLTAS"] = {"token": 99999}
        mon.update_subscriptions(active_pos)
        self.assertIn(99999, mon.subscribed_tokens)
        mock_kws.subscribe.assert_called_with([99999])

    def test_reconcile_broker_positions_caching_and_pos_data_injection(self):
        """trade_db.reconcile_broker_live_positions must respect cache and passed pos_data."""
        mock_kite = MagicMock()
        mock_kite.positions.return_value = {
            "net": [{"tradingsymbol": "INFY", "quantity": 10}],
            "day": []
        }
        mock_kite.orders.return_value = []

        # Reset module-level cache
        trade_db._LAST_RECONCILE_TIME = 0.0
        trade_db._LAST_RECONCILE_POS_DATA = None
        trade_db._LAST_RECONCILE_ORDERS_DATA = None

        # Call with explicit pos_data -> should NOT call mock_kite.positions()
        pos_data = {"net": [], "day": []}
        trade_db.reconcile_broker_live_positions(mock_kite, pos_data=pos_data)
        mock_kite.positions.assert_not_called()

        # Call without pos_data -> calls mock_kite.positions()
        trade_db.reconcile_broker_live_positions(mock_kite)
        self.assertEqual(mock_kite.positions.call_count, 1)

        # Immediate second call -> should hit the 2.5s cache, NOT calling mock_kite.positions again
        trade_db.reconcile_broker_live_positions(mock_kite)
        self.assertEqual(mock_kite.positions.call_count, 1, "Expected cached positions to be reused")


if __name__ == "__main__":
    unittest.main()
