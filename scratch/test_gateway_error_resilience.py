import unittest
from unittest.mock import MagicMock
import pandas as pd
import sys, os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from common.session import safe_kite_call
from common.timeframe_utils import fetch_and_resample_candles

class TestGatewayErrorResilience(unittest.TestCase):

    def test_safe_kite_call_retries_and_succeeds_on_502(self):
        call_count = 0
        def mock_func():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Unknown Content-Type (text/html) with response: (b'<html><head><title>502 Bad Gateway</title></head></html>')")
            return {"status": "success"}

        res = safe_kite_call(mock_func, retries=3, delay=0.01)
        self.assertEqual(res, {"status": "success"})
        self.assertEqual(call_count, 2)

    def test_fetch_and_resample_candles_graceful_on_502(self):
        mock_kite = MagicMock()
        mock_kite.historical_data.side_effect = Exception(
            "Unknown Content-Type (text/html) with response: (b'<html><head><title>502 Bad Gateway</title></head></html>')"
        )
        # Should catch after 4 attempts, log warning, and return empty DataFrame
        df = fetch_and_resample_candles(mock_kite, 12345, "2026-09-20", "2026-09-24", "30minute")
        self.assertTrue(isinstance(df, pd.DataFrame))
        self.assertTrue(df.empty)
        self.assertEqual(mock_kite.historical_data.call_count, 4)

if __name__ == "__main__":
    unittest.main()
