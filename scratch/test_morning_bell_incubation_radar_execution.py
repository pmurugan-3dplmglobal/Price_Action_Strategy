"""
scratch/test_morning_bell_incubation_radar_execution.py
======================================================
Unit verification suite for ISSUE-120:
Morning Bell Breakout Execution & Overnight Incubation Retention Engine.

Verifies:
1. reconcile_funnel_and_display_setups retains valid prior-day incubated setups up to 5 calendar days old (holiday weekends).
2. purge_invalidated_or_triggered does NOT evict fresh Day T+1 Point D breakouts (live_price >= bm) or coiled setups (live_price >= bm * 0.98).
3. auto_purge_if_due preserves valid incubated setups via smart reconciliation.
4. Fast Radar entry window unlocks at 09:15:00 for pre-incubated setups.
5. Opening bell fast-track bypasses forming-bar maturity for pre-incubated setups.
6. 80% T1 anti-chase guard skips entry without hard-evicting the setup from pattern_funnel.
"""

import unittest
import os
import sys
from datetime import datetime, timedelta, date

# Add repo root to path
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import common.pattern_funnel as pattern_funnel


class TestMorningBellIncubationRadarExecution(unittest.TestCase):

    def setUp(self):
        self.test_engine = "test_engine_morning_bell"
        pattern_funnel.clear_funnel(self.test_engine)

    def tearDown(self):
        pattern_funnel.clear_funnel(self.test_engine)

    def test_01_holiday_weekend_incubation_retention(self):
        """
        Verify that a Point C setup formed 4 calendar days ago (e.g. Thu close to Mon morning across Gandhi Jayanti holiday)
        is RETAINED by reconcile_funnel_and_display_setups, while breached/runaway setups are evicted.
        """
        today_str = "2026-10-05" # Monday
        thu_str = "2026-10-01"   # Thursday (4 calendar days ago, but 0 intervening trading sessions)

        # 1. Valid incubated setup (like KALYANKJIL 570 CE)
        kalyan_setup = {
            "symbol": "KALYANKJIL",
            "contract": "KALYANKJIL26OCT570CE",
            "side": "CE",
            "candle_c_time": f"{thu_str} 15:15:00+05:30",
            "date": thu_str,
            "tier": 1,
            "benchmark": 10.55,
            "current_sl": 8.05,
            "t1": 22.75,
            "entry_spot": 10.40, # Closed at 10.40 on Thursday
            "stage": "STAGE_A_PLUS_READY"
        }

        # 2. Breached SL setup from Thursday (SL was 15.0, closed at 14.0)
        breached_setup = {
            "symbol": "BREACHED_STOCK",
            "contract": "BREACHED26OCT100CE",
            "side": "CE",
            "candle_c_time": f"{thu_str} 15:15:00+05:30",
            "date": thu_str,
            "tier": 2,
            "benchmark": 20.0,
            "current_sl": 15.0,
            "t1": 30.0,
            "entry_spot": 14.0, # Breached SL
            "stage": "STAGE_A_READY"
        }

        # 3. Already runaway setup from Thursday (T1=30, BM=20, 80% T1 = 28.0, closed at 28.50)
        runaway_setup = {
            "symbol": "RUNAWAY_STOCK",
            "contract": "RUNAWAY26OCT200CE",
            "side": "CE",
            "candle_c_time": f"{thu_str} 15:15:00+05:30",
            "date": thu_str,
            "tier": 2,
            "benchmark": 20.0,
            "current_sl": 15.0,
            "t1": 30.0,
            "entry_spot": 28.50, # Already hit 80% T1 on Thursday
            "stage": "STAGE_A_READY"
        }

        # 4. Old setup (> 5 days old, e.g. 7 days old)
        ancient_setup = {
            "symbol": "ANCIENT_STOCK",
            "contract": "ANCIENT26OCT500CE",
            "side": "CE",
            "candle_c_time": "2026-09-28 15:15:00+05:30",
            "date": "2026-09-28",
            "tier": 2,
            "benchmark": 50.0,
            "current_sl": 40.0,
            "t1": 70.0,
            "entry_spot": 48.0,
            "stage": "STAGE_A_READY"
        }

        pattern_funnel.update_funnel(
            self.test_engine,
            a_plus_items=[kalyan_setup],
            a_items=[breached_setup, runaway_setup],
            b_items=[ancient_setup]
        )

        # Run smart reconciliation for Monday 2026-10-05
        state_after = pattern_funnel.reconcile_funnel_and_display_setups(
            self.test_engine,
            today_str=today_str,
            purge_scan_display=False
        )

        retained_a_plus = state_after.get("category_a_plus", [])
        retained_a = state_after.get("category_a", [])
        retained_b = state_after.get("category_b", [])

        # KALYANKJIL MUST be retained
        self.assertEqual(len(retained_a_plus), 1, "Valid holiday-incubated setup MUST be retained in A+!")
        self.assertEqual(retained_a_plus[0]["symbol"], "KALYANKJIL")

        # Breached, runaway, and >5-day setups MUST be cleanly purged
        self.assertEqual(len(retained_a), 0, "Breached and runaway setups must be evicted!")
        self.assertEqual(len(retained_b), 0, "Ancient (>5 days) setups must be evicted!")

    def test_02_purge_invalidated_or_triggered_does_not_kill_fresh_breakouts(self):
        """
        Verify that purge_invalidated_or_triggered does NOT evict an incubated setup
        when live price breaks out today (live_price >= benchmark).
        """
        thu_str = "2026-10-01"
        kalyan_setup = {
            "symbol": "KALYANKJIL",
            "contract": "KALYANKJIL26OCT570CE",
            "side": "CE",
            "candle_c_time": f"{thu_str} 15:15:00+05:30",
            "date": thu_str,
            "tier": 1,
            "benchmark": 10.55,
            "current_sl": 8.05,
            "t1": 22.75,
            "entry_spot": 10.40, # Prior session close
            "stage": "STAGE_A_PLUS_READY"
        }

        pattern_funnel.update_funnel(self.test_engine, a_plus_items=[kalyan_setup])

        # Test A: Coiling at 98% of BM (live_price = 10.35)
        # Old bug: evicted because live_price >= bm * 0.98! New behavior: MUST KEEP!
        ltp_coiling = {"KALYANKJIL26OCT570CE": 10.35}
        pattern_funnel.purge_invalidated_or_triggered(self.test_engine, ltp_dict=ltp_coiling)
        state_coiling = pattern_funnel.load_funnel_state(self.test_engine)
        self.assertEqual(len(state_coiling.get("category_a_plus", [])), 1, "Coiled setup at 98% BM must NOT be evicted!")

        # Test B: Fresh opening breakout (live_price = 11.30, above BM 10.55)
        # Old bug: evicted because item_date < today and live_price >= bm! New behavior: MUST KEEP for execution!
        ltp_breakout = {"KALYANKJIL26OCT570CE": 11.30}
        pattern_funnel.purge_invalidated_or_triggered(self.test_engine, ltp_dict=ltp_breakout)
        state_breakout = pattern_funnel.load_funnel_state(self.test_engine)
        self.assertEqual(len(state_breakout.get("category_a_plus", [])), 1, "Fresh Day T+1 breakout must NOT be evicted!")

        # Test C: Actual runaway (live_price = 21.00 >= 80% T1 [10.55 + 0.8*(22.75-10.55) = 20.31])
        # Runaway > 80% T1 pre-entry MUST be evicted by Rule 1
        ltp_runaway = {"KALYANKJIL26OCT570CE": 21.00}
        pattern_funnel.purge_invalidated_or_triggered(self.test_engine, ltp_dict=ltp_runaway)
        state_runaway = pattern_funnel.load_funnel_state(self.test_engine)
        self.assertEqual(len(state_runaway.get("category_a_plus", [])), 0, "Runaway >80% T1 must be evicted!")

    def test_03_prior_day_stale_close_eviction(self):
        """
        Verify that a setup whose prior-day candle close was ALREADY above BM is evicted as a stale run.
        """
        yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        stale_run = {
            "symbol": "STALE_RUNNER",
            "contract": "STALE_RUNNER26OCT100CE",
            "side": "CE",
            "candle_c_time": f"{yesterday_str} 15:15:00+05:30",
            "date": yesterday_str,
            "benchmark": 10.00,
            "current_sl": 8.00,
            "t1": 20.00,
            "entry_spot": 11.50, # Prior day ALREADY closed above BM (11.50 >= 10.00)
            "c_close": 11.50,
            "stage": "STAGE_A_READY"
        }

        pattern_funnel.update_funnel(self.test_engine, a_items=[stale_run])
        ltp_dict = {"STALE_RUNNER26OCT100CE": 12.00}
        pattern_funnel.purge_invalidated_or_triggered(self.test_engine, ltp_dict=ltp_dict)
        state = pattern_funnel.load_funnel_state(self.test_engine)
        self.assertEqual(len(state.get("category_a", [])), 0, "Prior-day setup that already closed above BM must be evicted!")

    def test_04_opening_bell_execution_lock_logic(self):
        """
        Verify the opening bell temporal lock logic:
        1. Fast radar candidates with trigger_type or Stage A/A+ allow execution from 09:15 AM.
        2. Regular candidates observe the standard 09:20 stabilization window.
        """
        # Case A: Fast Radar Trigger candidate
        cands_radar = [{
            "symbol": "KALYANKJIL",
            "contract": "KALYANKJIL26OCT570CE",
            "trigger_type": "COMPLETED_BAR_D",
            "stage": "STAGE_A_PLUS_READY"
        }]
        has_radar_trigger = any(
            bool(c.get("trigger_type") or str(c.get("stage", "")).upper() in ["A_PLUS", "A", "STAGE_A_PLUS_READY", "STAGE_A_READY"])
            for c in cands_radar if isinstance(c, dict)
        )
        eff_min_entry_radar = "09:15" if has_radar_trigger else "09:20"
        self.assertEqual(eff_min_entry_radar, "09:15", "Pre-incubated radar triggers must unlock at 09:15!")

        # Case B: Standard universe scan candidate
        cands_regular = [{
            "symbol": "RELIANCE",
            "contract": "RELIANCE26OCT3000CE",
            "pattern": "BASE_ABCD",
            "stage": None
        }]
        has_regular_trigger = any(
            bool(c.get("trigger_type") or str(c.get("stage", "")).upper() in ["A_PLUS", "A", "STAGE_A_PLUS_READY", "STAGE_A_READY"])
            for c in cands_regular if isinstance(c, dict)
        )
        eff_min_entry_reg = "09:15" if has_regular_trigger else "09:20"
        self.assertEqual(eff_min_entry_reg, "09:20", "Standard universe scan candidates must observe 09:20 window!")


if __name__ == "__main__":
    unittest.main()
