import sys
sys.path.insert(0, 'common')
import unittest
from unittest.mock import MagicMock, patch
from position_monitor import close_position, clear_executed_exit

class TestPhantomExitGuard(unittest.TestCase):
    def setUp(self):
        clear_executed_exit("ICICIGI26SEP1500PE")
        self.mock_kite = MagicMock()
        self.mock_kite.PRODUCT_NRML = "NRML"
        self.mock_kite.VARIETY_REGULAR = "regular"
        self.mock_kite.EXCHANGE_NFO = "NFO"
        self.mock_kite.TRANSACTION_TYPE_SELL = "SELL"
        self.mock_kite.TRANSACTION_TYPE_BUY = "BUY"
        self.mock_kite.ORDER_TYPE_LIMIT = "LIMIT"

    def test_phantom_exit_not_found_on_broker(self):
        """Verify that an option not present in net positions is skipped from SELL execution."""
        self.mock_kite.positions.return_value = {
            "net": [
                {"tradingsymbol": "RELIANCE26SEP2800CE", "quantity": 250, "product": "NRML"}
            ]
        }
        self.mock_kite.orders.return_value = []
        pos = {
            "contract": "ICICIGI26SEP1500PE",
            "symbol": "ICICIGI",
            "quantity": 325,
            "direction": "BULL",
            "side": "PE"
        }
        res = close_position(self.mock_kite, pos, live_market=True)
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("status"), "NOT_FOUND_ON_BROKER")
        self.mock_kite.place_order.assert_not_called()

    def test_phantom_exit_zero_qty_on_broker(self):
        """Verify that an option present in net positions with quantity 0 is skipped from SELL execution."""
        self.mock_kite.positions.return_value = {
            "net": [
                {"tradingsymbol": "ICICIGI26SEP1500PE", "quantity": 0, "product": "NRML"}
            ]
        }
        self.mock_kite.orders.return_value = []
        pos = {
            "contract": "ICICIGI26SEP1500PE",
            "symbol": "ICICIGI",
            "quantity": 325,
            "direction": "BULL",
            "side": "PE"
        }
        res = close_position(self.mock_kite, pos, live_market=True)
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("status"), "ZERO_QTY")
        self.mock_kite.place_order.assert_not_called()

    @patch("position_monitor.is_market_open", return_value=True)
    def test_real_position_calls_sell(self, mock_market_open):
        """Verify that a genuine held option executes SELL exit with clamped quantity."""
        self.mock_kite.positions.return_value = {
            "net": [
                {"tradingsymbol": "ICICIGI26SEP1500PE", "quantity": 325, "product": "NRML"}
            ]
        }
        self.mock_kite.orders.return_value = []
        self.mock_kite.quote.return_value = {
            "NFO:ICICIGI26SEP1500PE": {
                "last_price": 20.0,
                "depth": {"buy": [{"price": 19.8, "quantity": 325}]}
            }
        }
        self.mock_kite.place_order.return_value = "ORDER_99999"
        pos = {
            "contract": "ICICIGI26SEP1500PE",
            "symbol": "ICICIGI",
            "quantity": 325,
            "direction": "BULL",
            "side": "PE"
        }
        res = close_position(self.mock_kite, pos, live_market=True)
        self.assertTrue(res.get("success"))
        self.mock_kite.place_order.assert_called_once()
        call_kwargs = self.mock_kite.place_order.call_args[1]
        self.assertEqual(call_kwargs["tradingsymbol"], "ICICIGI26SEP1500PE")
        self.assertEqual(call_kwargs["transaction_type"], "SELL")
        self.assertEqual(call_kwargs["quantity"], 325)

if __name__ == '__main__':
    unittest.main()
