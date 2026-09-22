import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.position_monitor import _get_nfo_cache
from common.resolve import normalize_strike_step, resolve_option_strikes, resolve_option_spread

class TestDebitSpreadAndStrikeResolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.nfo_df = _get_nfo_cache()

    def test_normalize_strike_step_fractional(self):
        # 2.5 step
        self.assertEqual(normalize_strike_step(123.3, 2.5), 122.5)
        self.assertEqual(normalize_strike_step(123.8, 2.5), 125.0)
        self.assertEqual(normalize_strike_step(121.2, 2.5), 120.0)
        # 1.25 step
        self.assertEqual(normalize_strike_step(134.2, 1.25), 133.75)
        self.assertEqual(normalize_strike_step(134.5, 1.25), 135.0)

    def test_normalize_strike_step_integer(self):
        # 50 step (NIFTY)
        self.assertEqual(normalize_strike_step(24560, 50), 24550)
        self.assertIsInstance(normalize_strike_step(24560, 50), int)
        # 20 step (RELIANCE)
        self.assertEqual(normalize_strike_step(3015, 20), 3020)
        self.assertIsInstance(normalize_strike_step(3015, 20), int)

    def test_canbk_strike_resolution_fractional(self):
        if self.nfo_df.empty:
            self.skipTest("NFO cache unavailable")
        # CANBK spot 123.3, step 2.5
        strikes = resolve_option_strikes(self.nfo_df, "CANBK", 123.3, 2.5, "CE", n_range=2, allow_otm=True)
        self.assertTrue(len(strikes) > 0, "Strikes should not be empty for CANBK at 123.3")
        resolved_strikes = [s["strike"] for s in strikes]
        # ATM 122.5 must be in resolved strikes!
        self.assertIn(122.5, resolved_strikes)
        self.assertIn(125.0, resolved_strikes)
        self.assertIn(120.0, resolved_strikes)

    def test_canbk_debit_spread_resolution(self):
        if self.nfo_df.empty:
            self.skipTest("NFO cache unavailable")
        # Bull Call Spread without target_price
        spread = resolve_option_spread(self.nfo_df, "CANBK", 123.3, 2.5, direction="BULL", side="CE")
        self.assertIsNotNone(spread, "CANBK spread must not be None at spot 123.3")
        self.assertEqual(spread["leg1"]["strike"], 122.5, "Leg 1 must be ATM 122.5 CE")
        self.assertTrue("122.5CE" in spread["leg1"]["contract"])
        self.assertGreater(spread["leg2"]["strike"], 122.5, "Leg 2 must be OTM strike > 122.5")
        self.assertEqual(spread["direction"], "BULL")
        self.assertEqual(spread["spread_type"], "BULL_CALL_SPREAD")

        # Bull Call Spread with target_price = 125.0
        spread_tgt = resolve_option_spread(self.nfo_df, "CANBK", 123.3, 2.5, direction="BULL", target_price=125.0, side="CE")
        self.assertIsNotNone(spread_tgt)
        self.assertEqual(spread_tgt["leg1"]["strike"], 122.5)
        self.assertEqual(spread_tgt["leg2"]["strike"], 125.0)

    def test_bear_put_spread_resolution(self):
        if self.nfo_df.empty:
            self.skipTest("NFO cache unavailable")
        # Bear Put Spread on CANBK at spot 123.3
        spread = resolve_option_spread(self.nfo_df, "CANBK", 123.3, 2.5, direction="BEAR", side="PE")
        self.assertIsNotNone(spread)
        self.assertEqual(spread["leg1"]["strike"], 122.5, "Leg 1 must be ATM 122.5 PE")
        self.assertLess(spread["leg2"]["strike"], 122.5, "Leg 2 must be OTM strike < 122.5")
        self.assertEqual(spread["direction"], "BEAR")
        self.assertEqual(spread["spread_type"], "BEAR_PUT_SPREAD")

    def test_leg2_limit_price_calculation(self):
        # When leg2 bid is 0.20
        bid = 0.20
        limit = round(max(0.05, bid * 0.995), 2)
        self.assertEqual(limit, 0.20)
        
        # When leg2 bid is 0.04 (below 0.05 floor)
        bid_low = 0.04
        limit_low = round(max(0.05, bid_low * 0.995), 2)
        self.assertEqual(limit_low, 0.05)

if __name__ == "__main__":
    unittest.main(verbosity=2)
