"""Unit test verifying Opening Spread Safeguards & Fresh Fill Protections."""
import unittest
from datetime import datetime
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common")))
from position_monitor import (
    is_option_contract,
    is_new_entry_allowed,
    get_seconds_since_entry
)

class TestOpeningSpreadSafeguards(unittest.TestCase):
    def test_01_is_option_contract(self):
        """Test option contract detection vs cash equities."""
        # Valid options
        self.assertTrue(is_option_contract("PERSISTENT26SEP5600CE"))
        self.assertTrue(is_option_contract("NIFTY2690823900PE"))
        self.assertTrue(is_option_contract("NFO:BANKNIFTY26SEP57400CE"))
        self.assertTrue(is_option_contract("SENSEX2691076500PE"))
        
        # Cash equities (must return False)
        self.assertFalse(is_option_contract("PERSISTENT"))
        self.assertFalse(is_option_contract("PETRONET"))
        self.assertFalse(is_option_contract("PEL"))
        self.assertFalse(is_option_contract("CENTRALBK"))
        self.assertFalse(is_option_contract("INFY"))
        self.assertFalse(is_option_contract("TCS"))

    def test_02_is_new_entry_allowed_option_buffer(self):
        """Test is_new_entry_allowed option buffer."""
        # Offline mode allows anytime
        self.assertTrue(is_new_entry_allowed(live_execution_active=False, is_option=True))
        self.assertTrue(is_new_entry_allowed(live_execution_active=False, is_option=False))

    def test_03_get_seconds_since_entry(self):
        """Test get_seconds_since_entry calculation."""
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        pos_fresh = {"entry_time": now_str}
        elapsed = get_seconds_since_entry(pos_fresh)
        self.assertLess(elapsed, 10.0)

        # Position entered 10 minutes ago
        old_str = datetime.fromtimestamp(datetime.now().timestamp() - 600).strftime("%Y-%m-%dT%H:%M:%S")
        pos_old = {"entry_time": old_str}
        elapsed_old = get_seconds_since_entry(pos_old)
        self.assertGreater(elapsed_old, 590.0)

if __name__ == "__main__":
    unittest.main()
