import sys
import os
import unittest
from datetime import datetime as dt
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from common.position_monitor import is_new_entry_allowed

class TestIndexSpreadAndCutoff(unittest.TestCase):

    def test_cutoff_timing_invariants(self):
        # Case 1: 11:00 AM on a weekday -> Both index and stock option allowed
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 10, 11, 0, 0)):
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True), "Index should be allowed at 11:00")
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=False), "Stock option should be allowed at 11:00")

        # Case 2: 13:31 PM on a weekday -> Index BLOCKED, stock option STILL ALLOWED
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 10, 13, 31, 0)):
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True), "Index MUST be blocked after 13:30")
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=False), "Stock option should still be allowed at 13:31")

        # Case 3: 15:00 PM on a weekday -> Index BLOCKED, stock option STILL ALLOWED
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 10, 15, 0, 0)):
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True), "Index MUST be blocked at 15:00")
            self.assertTrue(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=False), "Stock option should still be allowed at 15:00")

        # Case 4: 15:25 PM on a weekday -> Both BLOCKED (past 15:20)
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 10, 15, 25, 0)):
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True), "Index MUST be blocked at 15:25")
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=False), "Stock option MUST be blocked at 15:25")

        # Case 5: Weekend (Saturday) -> Blocked
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 12, 11, 0, 0)):
            self.assertFalse(is_new_entry_allowed(live_execution_active=True, is_option=True, is_index=True), "Weekend must be blocked")

        # Case 6: Offline / scan-only mode -> Always allowed anytime
        with patch("common.position_monitor.get_ist_now", return_value=dt(2026, 9, 10, 20, 0, 0)):
            self.assertTrue(is_new_entry_allowed(live_execution_active=False, is_option=True, is_index=True), "Offline mode should allow scanning anytime")

    def test_spread_resolution_mock(self):
        import pandas as pd
        from common.resolve import resolve_option_spread

        sample_nfo = pd.DataFrame([
            {"tradingsymbol": "NIFTY26SEP24000CE", "name": "NIFTY", "instrument_type": "CE", "strike": 24000.0, "expiry": "2026-09-24", "instrument_token": 1001},
            {"tradingsymbol": "NIFTY26SEP24100CE", "name": "NIFTY", "instrument_type": "CE", "strike": 24100.0, "expiry": "2026-09-24", "instrument_token": 1002},
            {"tradingsymbol": "NIFTY26SEP24200CE", "name": "NIFTY", "instrument_type": "CE", "strike": 24200.0, "expiry": "2026-09-24", "instrument_token": 1003},
            {"tradingsymbol": "NIFTY26SEP24000PE", "name": "NIFTY", "instrument_type": "PE", "strike": 24000.0, "expiry": "2026-09-24", "instrument_token": 1004},
            {"tradingsymbol": "NIFTY26SEP23800PE", "name": "NIFTY", "instrument_type": "PE", "strike": 23800.0, "expiry": "2026-09-24", "instrument_token": 1005},
        ])

        # Test Bull Call Spread (Target price 24200 -> Short leg 24200)
        spread_bull = resolve_option_spread(
            nfo_instruments=sample_nfo,
            base_symbol="NIFTY",
            spot_price=24020.0,
            step_size=50,
            direction="BULL",
            target_price=24200.0
        )
        self.assertIsNotNone(spread_bull)
        self.assertEqual(spread_bull["spread_type"], "BULL_CALL_SPREAD")
        self.assertEqual(spread_bull["leg1"]["strike"], 24000.0)
        self.assertEqual(spread_bull["leg2"]["strike"], 24200.0)

        # Test Bear Put Spread (Target price 23800 -> Short leg 23800)
        spread_bear = resolve_option_spread(
            nfo_instruments=sample_nfo,
            base_symbol="NIFTY",
            spot_price=23980.0,
            step_size=50,
            direction="BEAR",
            target_price=23800.0
        )
        self.assertIsNotNone(spread_bear)
        self.assertEqual(spread_bear["spread_type"], "BEAR_PUT_SPREAD")
        self.assertEqual(spread_bear["leg1"]["strike"], 24000.0)
        self.assertEqual(spread_bear["leg2"]["strike"], 23800.0)

if __name__ == "__main__":
    unittest.main()
