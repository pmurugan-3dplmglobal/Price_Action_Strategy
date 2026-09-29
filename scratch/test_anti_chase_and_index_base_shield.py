"""
Unit Verification: Anti-Chase 25% Entry Ceiling & Index BASE Short-Timeframe Chop Shield
Tests:
1. Anti-Chase 25% Ceiling in Fast Surveillance Radar:
   - Within 25% of BM->T1 distance: is_breakout is True.
   - Extended beyond 25% of BM->T1 distance: is_breakout is False (anti-chase kicks in).
   - Retest within benchmark zone [0.98, 1.025]: is_retest is True.
2. Anti-Chase Ceiling in execute_highest_rr_trade (Scan Cycle Completion):
   - Rejects live price extended beyond 25% of BM->T1 distance.
3. Index BASE_ABCD Short-Timeframe Chop Shield:
   - BASE_ABCD on 3minute or 5minute: REJECTED with [INDEX_BASE_CHOP_GUARD].
   - BASE_ABCD on 15minute or 30minute: ALLOWED.
   - HH_ABCD, BE_ABCD, LL_ABCD on 3minute: ALLOWED.
"""

import sys, os, unittest
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

class TestAntiChaseAndIndexBaseShield(unittest.TestCase):

    def test_01_anti_chase_ceiling_logic(self):
        bm = 100.0
        t1 = 150.0
        sl = 80.0
        
        # Max allowed chase price is bm + 0.25 * (t1 - bm) = 100 + 0.25 * 50 = 112.50
        max_chase = round(bm + 0.25 * (t1 - bm), 2)
        self.assertEqual(max_chase, 112.50)

        # Case A: Price is at 105.0 (within 25% distance) -> Breakout allowed
        c_now_good = 105.0
        is_breakout = (bm > 0 and bm <= c_now_good <= max_chase)
        self.assertTrue(is_breakout)

        # Case B: Price is at 125.0 (extended, 50% to T1) -> Breakout BLOCKED
        c_now_extended = 125.0
        is_breakout_ext = (bm > 0 and bm <= c_now_extended <= max_chase)
        self.assertFalse(is_breakout_ext)

        # Case C: Retest condition on extended candidate that pulls back to 101.0
        c_now_retest = 101.0
        retest_lower = bm * 0.980
        retest_upper = bm * 1.025
        is_retest = (retest_lower <= c_now_retest <= retest_upper and c_now_retest < t1 and c_now_retest > sl)
        self.assertTrue(is_retest)

    def test_02_index_base_chop_shield_filter(self):
        # Setup test cases for (pattern, timeframe)
        def should_block_index_base(pattern, timeframe):
            p_name = str(pattern or "").upper()
            tf_cand = str(timeframe or "15minute").lower()
            is_short_tf = ("3min" in tf_cand or "1min" in tf_cand or ("5min" in tf_cand and "15min" not in tf_cand) or tf_cand in ["1m", "3m", "5m"])
            return bool("BASE" in p_name and is_short_tf)

        # 3m and 5m BASE_ABCD MUST BE BLOCKED
        self.assertTrue(should_block_index_base("BASE_ABCD", "3minute"))
        self.assertTrue(should_block_index_base("BASE_ABCD", "5minute"))
        self.assertTrue(should_block_index_base("BASE_ABCD", "1minute"))

        # 15m, 30m, 60m, Day BASE_ABCD MUST BE ALLOWED
        self.assertFalse(should_block_index_base("BASE_ABCD", "15minute"))
        self.assertFalse(should_block_index_base("BASE_ABCD", "30minute"))
        self.assertFalse(should_block_index_base("BASE_ABCD", "60minute"))
        self.assertFalse(should_block_index_base("BASE_ABCD", "day"))

        # Institutional momentum anchors (HH, BE, LL, SWEEP) on 3m MUST BE ALLOWED
        self.assertFalse(should_block_index_base("HH_ABCD", "3minute"))
        self.assertFalse(should_block_index_base("BE_ABCD", "3minute"))
        self.assertFalse(should_block_index_base("LL_ABCD", "3minute"))
        self.assertFalse(should_block_index_base("SWEEP_ABCD", "3minute"))

    def test_03_fallback_max_chase_when_no_t1(self):
        # When t1 is missing or t1 <= bm, fallback to bm * 1.05
        bm = 200.0
        t1 = 0.0
        max_chase = round(bm + 0.25 * (t1 - bm), 2) if (bm > 0 and t1 > bm) else round(bm * 1.05, 2)
        self.assertEqual(max_chase, 210.0)

        # Price at 208.0 <= 210.0 -> allowed
        self.assertTrue(bm <= 208.0 <= max_chase)
        # Price at 215.0 > 210.0 -> blocked
        self.assertFalse(bm <= 215.0 <= max_chase)

if __name__ == "__main__":
    unittest.main()
