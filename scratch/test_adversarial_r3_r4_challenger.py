"""
scratch/test_adversarial_r3_r4_challenger.py
=============================================
Adversarial Stress Test Suite for Requirements R3 (Expiry & Rollover) and R4 (Risk Governance).
Empirical challenger harness designed to stress-test boundary conditions and edge cases:

1. Index Options 0DTE Expiry Rollover Boundary (13:29:59 vs 13:30:00) for NFO & BFO.
2. Stock Options Monthly Rollover Boundary (Days <= 4-6).
3. Conviction-Weighted Tier Sizing Multiplier Boundary (1.0 / 0.70 / 0.50), 25% Option Ceiling, Cash Equity 100% Micro-SL Ceiling.
4. Spot-Anchored SL Guard Adversarial Tests (Suppression, 15% Catastrophic Override, Trailed Stop Immunity).
5. Morning Gap Audit Boundary Tests (Bull & Bear Breaches vs Windfalls).
"""

import sys
import os
import unittest
from datetime import datetime as dt, date, time as datetime_time, timedelta
import pandas as pd
from unittest.mock import MagicMock, patch
import threading

# Add canonical paths
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(BASE_DIR, "common")
OPTION_DIR = os.path.join(BASE_DIR, "Trade_Option")
STOCK_DIR = os.path.join(BASE_DIR, "Trade_Stock")

for p in [COMMON_DIR, OPTION_DIR, STOCK_DIR, BASE_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import targets
from targets import calculate_position_size
import resolve
import index_options_trade_engine
import stock_options_trade_engine
import position_monitor
import morning_reconciler


class TestR3Index0DTERolloverBoundary(unittest.TestCase):
    """
    Adversarial Challenge 1: Index 0DTE Rollover Boundary
    Boundary: 13:29:59 (Current Expiry) vs 13:30:00 (Next Weekly Expiry)
    Tested for:
      - NFO (NIFTY)
      - BFO (SENSEX)
      - Non-expiry days (days_rem > 0)
      - Edge case: single expiry available
    """

    def setUp(self):
        self.today = date(2026, 9, 10)  # Thursday
        self.next_week = date(2026, 9, 17)
        self.two_weeks = date(2026, 9, 24)

        # Mock instruments DataFrame for NIFTY (NFO) and SENSEX (BFO)
        self.mock_dump = pd.DataFrame([
            {"name": "NIFTY", "instrument_type": "CE", "strike": 25000.0, "expiry": str(self.today),
             "tradingsymbol": "NIFTY2691025000CE", "instrument_token": 1001, "lot_size": 25},
            {"name": "NIFTY", "instrument_type": "CE", "strike": 25000.0, "expiry": str(self.next_week),
             "tradingsymbol": "NIFTY2691725000CE", "instrument_token": 1002, "lot_size": 25},
            {"name": "NIFTY", "instrument_type": "CE", "strike": 25000.0, "expiry": str(self.two_weeks),
             "tradingsymbol": "NIFTY2692425000CE", "instrument_token": 1003, "lot_size": 25},
            {"name": "SENSEX", "instrument_type": "CE", "strike": 82000.0, "expiry": str(self.today),
             "tradingsymbol": "SENSEX2691082000CE", "instrument_token": 2001, "lot_size": 10},
            {"name": "SENSEX", "instrument_type": "CE", "strike": 82000.0, "expiry": str(self.next_week),
             "tradingsymbol": "SENSEX2691782000CE", "instrument_token": 2002, "lot_size": 10},
        ])

    def test_nifty_rollover_exact_boundary_seconds(self):
        """Test NIFTY 0DTE at 13:29:59 (stay) vs 13:30:00 (roll) vs 13:30:01 (roll)."""
        index_options_trade_engine.instrument_dump = self.mock_dump.copy()

        # 1. Exactly 13:29:59 on expiry day -> MUST STAY ON CURRENT (today)
        mock_now_132959 = dt.combine(self.today, datetime_time(13, 29, 59))
        with patch.object(index_options_trade_engine, "get_ist_date", return_value=self.today), \
             patch.object(index_options_trade_engine, "get_ist_now", return_value=mock_now_132959):
            res_before = index_options_trade_engine.resolve_option_contract("NIFTY", 25000.0, 50, "CE")
            self.assertIsNotNone(res_before)
            self.assertEqual(res_before["tradingsymbol"], "NIFTY2691025000CE")
            self.assertEqual(res_before["expiry"], str(self.today))

        # 2. Exactly 13:30:00 on expiry day -> MUST ROLL TO NEXT WEEK
        mock_now_133000 = dt.combine(self.today, datetime_time(13, 30, 0))
        with patch.object(index_options_trade_engine, "get_ist_date", return_value=self.today), \
             patch.object(index_options_trade_engine, "get_ist_now", return_value=mock_now_133000):
            res_at = index_options_trade_engine.resolve_option_contract("NIFTY", 25000.0, 50, "CE")
            self.assertIsNotNone(res_at)
            self.assertEqual(res_at["tradingsymbol"], "NIFTY2691725000CE")
            self.assertEqual(res_at["expiry"], str(self.next_week))

        # 3. Exactly 13:30:01 on expiry day -> MUST STAY ON NEXT WEEK
        mock_now_133001 = dt.combine(self.today, datetime_time(13, 30, 1))
        with patch.object(index_options_trade_engine, "get_ist_date", return_value=self.today), \
             patch.object(index_options_trade_engine, "get_ist_now", return_value=mock_now_133001):
            res_after = index_options_trade_engine.resolve_option_contract("NIFTY", 25000.0, 50, "CE")
            self.assertIsNotNone(res_after)
            self.assertEqual(res_after["tradingsymbol"], "NIFTY2691725000CE")
            self.assertEqual(res_after["expiry"], str(self.next_week))

    def test_sensex_bfo_rollover_exact_boundary_seconds(self):
        """Test SENSEX (BFO exchange) 0DTE rollover at 13:29:59 vs 13:30:00."""
        index_options_trade_engine.instrument_dump = self.mock_dump.copy()

        # At 13:29:59 -> Stay on today's expiry
        mock_now_132959 = dt.combine(self.today, datetime_time(13, 29, 59))
        with patch.object(index_options_trade_engine, "get_ist_date", return_value=self.today), \
             patch.object(index_options_trade_engine, "get_ist_now", return_value=mock_now_132959):
            res_bfo_before = index_options_trade_engine.resolve_option_contract("SENSEX", 82000.0, 100, "CE")
            self.assertIsNotNone(res_bfo_before)
            self.assertEqual(res_bfo_before["tradingsymbol"], "SENSEX2691082000CE")
            self.assertEqual(res_bfo_before["expiry"], str(self.today))

        # At 13:30:00 -> Roll to next week's expiry
        mock_now_133000 = dt.combine(self.today, datetime_time(13, 30, 0))
        with patch.object(index_options_trade_engine, "get_ist_date", return_value=self.today), \
             patch.object(index_options_trade_engine, "get_ist_now", return_value=mock_now_133000):
            res_bfo_at = index_options_trade_engine.resolve_option_contract("SENSEX", 82000.0, 100, "CE")
            self.assertIsNotNone(res_bfo_at)
            self.assertEqual(res_bfo_at["tradingsymbol"], "SENSEX2691782000CE")
            self.assertEqual(res_bfo_at["expiry"], str(self.next_week))

    def test_off_expiry_day_afternoon_no_premature_roll(self):
        """Verify that on non-expiry days (e.g. Wednesday, days_rem=1), 14:00 does NOT trigger rollover."""
        index_options_trade_engine.instrument_dump = self.mock_dump.copy()
        wednesday = date(2026, 9, 9)
        mock_now_wed = dt.combine(wednesday, datetime_time(14, 30, 0))

        with patch.object(index_options_trade_engine, "get_ist_date", return_value=wednesday), \
             patch.object(index_options_trade_engine, "get_ist_now", return_value=mock_now_wed):
            res = index_options_trade_engine.resolve_option_contract("NIFTY", 25000.0, 50, "CE")
            self.assertIsNotNone(res)
            # Must remain on upcoming Thursday (self.today), NOT roll to next week
            self.assertEqual(res["tradingsymbol"], "NIFTY2691025000CE")
            self.assertEqual(res["expiry"], str(self.today))

    def test_single_expiry_available_graceful_handling(self):
        """Edge Case: On 0DTE afternoon when only 1 expiry exists in dump, must not crash or out-of-bounds."""
        single_dump = self.mock_dump[self.mock_dump["expiry"] == str(self.today)].copy()
        index_options_trade_engine.instrument_dump = single_dump

        mock_now_1330 = dt.combine(self.today, datetime_time(13, 30, 0))
        with patch.object(index_options_trade_engine, "get_ist_date", return_value=self.today), \
             patch.object(index_options_trade_engine, "get_ist_now", return_value=mock_now_1330):
            res = index_options_trade_engine.resolve_option_contract("NIFTY", 25000.0, 50, "CE")
            self.assertIsNotNone(res)
            self.assertEqual(res["tradingsymbol"], "NIFTY2691025000CE")


class TestR3StockOptionsMonthlyRolloverBoundary(unittest.TestCase):
    """
    Adversarial Challenge 2: Stock Options Monthly Rollover Boundary
    Boundary: days to expiry = 7 days vs 6 days vs 4 days vs 3 days
    """

    def setUp(self):
        self.curr_month = date(2026, 9, 24)  # Monthly expiry Thursday
        self.next_month = date(2026, 10, 29) # Next monthly expiry Thursday

        self.mock_nfo = pd.DataFrame([
            {"name": "RELIANCE", "instrument_type": "CE", "strike": 3000.0, "expiry": str(self.curr_month),
             "tradingsymbol": "RELIANCE26SEP3000CE", "instrument_token": 5001, "lot_size": 250},
            {"name": "RELIANCE", "instrument_type": "CE", "strike": 3000.0, "expiry": str(self.next_month),
             "tradingsymbol": "RELIANCE26OCT3000CE", "instrument_token": 5002, "lot_size": 250},
        ])

    def test_stock_engine_rollover_days_thresholds(self):
        """
        Test stock_options_trade_engine.resolve_option_contract:
        Rule: days_rem <= 4 -> Next Month
        """
        stock_options_trade_engine.NFO_INSTRUMENTS = self.mock_nfo.copy()

        # 7 days remaining (2026-09-17) -> Current month
        d_7 = self.curr_month - timedelta(days=7)
        with patch.object(stock_options_trade_engine, "get_ist_date", return_value=d_7):
            res_7 = stock_options_trade_engine.resolve_option_contract("RELIANCE", 3000.0, 20, "CE")
            self.assertEqual(res_7, "RELIANCE26SEP3000CE")

        # 6 days remaining (2026-09-18) -> MUST ROLL TO NEXT MONTH (STOCK_EXPIRY_ROLLOVER_DAYS = 6)
        d_6 = self.curr_month - timedelta(days=6)
        with patch.object(stock_options_trade_engine, "get_ist_date", return_value=d_6):
            res_6 = stock_options_trade_engine.resolve_option_contract("RELIANCE", 3000.0, 20, "CE")
            self.assertEqual(res_6, "RELIANCE26OCT3000CE")

        # 4 days remaining (2026-09-20) -> MUST ROLL TO NEXT MONTH
        d_4 = self.curr_month - timedelta(days=4)
        with patch.object(stock_options_trade_engine, "get_ist_date", return_value=d_4):
            res_4 = stock_options_trade_engine.resolve_option_contract("RELIANCE", 3000.0, 20, "CE")
            self.assertEqual(res_4, "RELIANCE26OCT3000CE")

        # 3 days remaining (2026-09-21) -> MUST ROLL TO NEXT MONTH
        d_3 = self.curr_month - timedelta(days=3)
        with patch.object(stock_options_trade_engine, "get_ist_date", return_value=d_3):
            res_3 = stock_options_trade_engine.resolve_option_contract("RELIANCE", 3000.0, 20, "CE")
            self.assertEqual(res_3, "RELIANCE26OCT3000CE")

    def test_common_resolve_strikes_rollover_threshold(self):
        """
        Test common/resolve.py: resolve_option_strikes
        Rule: days_rem <= 6 -> Next Month
        """
        # 7 days remaining -> Current month
        d_7 = self.curr_month - timedelta(days=7)
        with patch.object(resolve, "get_ist_date", return_value=d_7):
            out_7 = resolve.resolve_option_strikes(self.mock_nfo.copy(), "RELIANCE", 3000.0, 20, "CE", n_range=0)
            self.assertTrue(len(out_7) > 0)
            self.assertEqual(out_7[0]["tradingsymbol"], "RELIANCE26SEP3000CE")

        # 6 days remaining -> MUST ROLL TO NEXT MONTH
        d_6 = self.curr_month - timedelta(days=6)
        with patch.object(resolve, "get_ist_date", return_value=d_6):
            out_6 = resolve.resolve_option_strikes(self.mock_nfo.copy(), "RELIANCE", 3000.0, 20, "CE", n_range=0)
            self.assertTrue(len(out_6) > 0)
            self.assertEqual(out_6[0]["tradingsymbol"], "RELIANCE26OCT3000CE")

        # 4 days remaining -> Next month
        d_4 = self.curr_month - timedelta(days=4)
        with patch.object(resolve, "get_ist_date", return_value=d_4):
            out_4 = resolve.resolve_option_strikes(self.mock_nfo.copy(), "RELIANCE", 3000.0, 20, "CE", n_range=0)
            self.assertTrue(len(out_4) > 0)
            self.assertEqual(out_4[0]["tradingsymbol"], "RELIANCE26OCT3000CE")


class TestR4ConvictionWeightedTierSizingAndCeilings(unittest.TestCase):
    """
    Adversarial Challenge 3: Conviction-Weighted Tier Sizing Multiplier Boundary
    - Tier 1: 100% effective capital
    - Tier 2: 70% effective capital
    - Tier 3: 50% effective capital
    - Option 25% single-strike capital ceiling
    - Cash equity 100% total capital ceiling under micro stop-loss
    """

    def test_tier_capital_multipliers_cash_equity(self):
        """Verify exact effective capital and share sizing for Tier 1, 2, 3."""
        capital = 100000.0
        risk_pct = 1.0  # 1% = 1000 base risk
        spot = 500.0
        sl = 475.0      # risk_per_unit = 25.0

        # Tier 1 (100% cap = 100,000, risk = 1,000): 1000 / 25 = 40 shares
        s1 = calculate_position_size(spot, sl, capital=capital, risk_percent=risk_pct, is_option=False, tier=1)
        self.assertEqual(s1, 40)
        self.assertEqual(s1 * 25.0, 1000.0)

        # Tier 2 (70% cap = 70,000, risk = 700): 700 / 25 = 28 shares
        s2 = calculate_position_size(spot, sl, capital=capital, risk_percent=risk_pct, is_option=False, tier=2)
        self.assertEqual(s2, 28)
        self.assertEqual(s2 * 25.0, 700.0)

        # Tier 3 (50% cap = 50,000, risk = 500): 500 / 25 = 20 shares
        s3 = calculate_position_size(spot, sl, capital=capital, risk_percent=risk_pct, is_option=False, tier=3)
        self.assertEqual(s3, 20)
        self.assertEqual(s3 * 25.0, 500.0)

    def test_out_of_bounds_tier_graceful_fallback(self):
        """Adversarial input: tier=None, tier=0, tier=4, tier='INVALID'."""
        spot = 500.0
        sl = 475.0
        # Default tier (tier=1 when omitted or None) -> 40 shares
        s_none = calculate_position_size(spot, sl, capital=100000.0, tier=None)
        self.assertEqual(s_none, 40)

        # tier=4 -> falls back to 0.50 multiplier (20 shares)
        s_4 = calculate_position_size(spot, sl, capital=100000.0, tier=4)
        self.assertEqual(s_4, 20)

    def test_cash_equity_micro_sl_runaway_leverage_ceiling(self):
        """
        Adversarial Test: Micro Stop-Loss on Cash Equity.
        Without 100% capital ceiling, risk = 0.05 on a 500 Rs stock would request:
        1,000 / 0.05 = 20,000 shares (10,000,000 Rs = 100x account!).
        Ceiling MUST cap shares strictly to capital / price.
        """
        capital = 100000.0
        spot = 500.0
        sl = 499.95  # risk_per_unit = 0.05

        # Tier 1: max_units_capital = int(100,000 / 500) = 200 shares (100,000 Rs max)
        s1 = calculate_position_size(spot, sl, capital=capital, risk_percent=1.0, is_option=False, tier=1)
        self.assertEqual(s1, 200)
        self.assertLessEqual(s1 * spot, capital * 1.0)

        # Tier 2: max_units_capital = int(70,000 / 500) = 140 shares (70,000 Rs max)
        s2 = calculate_position_size(spot, sl, capital=capital, risk_percent=1.0, is_option=False, tier=2)
        self.assertEqual(s2, 140)
        self.assertLessEqual(s2 * spot, capital * 0.70)

        # Tier 3: max_units_capital = int(50,000 / 500) = 100 shares (50,000 Rs max)
        s3 = calculate_position_size(spot, sl, capital=capital, risk_percent=1.0, is_option=False, tier=3)
        self.assertEqual(s3, 100)
        self.assertLessEqual(s3 * spot, capital * 0.50)

        # Extreme Micro-SL: 0.01 on a 1000 Rs stock
        s_extreme = calculate_position_size(1000.0, 999.99, capital=capital, risk_percent=1.0, is_option=False, tier=1)
        self.assertEqual(s_extreme, 100)  # 100 * 1000 = 100,000 Rs max
        self.assertLessEqual(s_extreme * 1000.0, capital)

    def test_option_25pct_single_strike_capital_ceiling(self):
        """
        Adversarial Test: Option 25% single-strike capital ceiling.
        Tight stop-loss on option would allow excessive lots based solely on risk,
        exceeding total portfolio safety. 25% cap MUST hard-limit deployed premium.
        """
        capital = 100000.0
        opt_premium = 100.0
        opt_sl = 99.8
        lot_size = 25

        # Tier 1 (25% of 100k = 25,000 Rs -> 10 lots)
        lots_t1 = calculate_position_size(opt_premium, opt_sl, capital=capital, risk_percent=1.0,
                                          lot_size=lot_size, is_option=True, tier=1)
        self.assertEqual(lots_t1, 10)
        self.assertLessEqual(lots_t1 * lot_size * opt_premium, capital * 0.25)

        # Tier 2 (25% of 70k = 17,500 Rs -> 17,500 / 2500 = 7 lots)
        lots_t2 = calculate_position_size(opt_premium, opt_sl, capital=capital, risk_percent=1.0,
                                          lot_size=lot_size, is_option=True, tier=2)
        self.assertEqual(lots_t2, 7)
        self.assertLessEqual(lots_t2 * lot_size * opt_premium, (capital * 0.70) * 0.25)

        # Tier 3 (25% of 50k = 12,500 Rs -> 12,500 / 2500 = 5 lots)
        lots_t3 = calculate_position_size(opt_premium, opt_sl, capital=capital, risk_percent=1.0,
                                          lot_size=lot_size, is_option=True, tier=3)
        self.assertEqual(lots_t3, 5)
        self.assertLessEqual(lots_t3 * lot_size * opt_premium, (capital * 0.50) * 0.25)


class TestR4SpotAnchoredSLGuardAdversarial(unittest.TestCase):
    """
    Adversarial Challenge 4: Spot-Anchored SL Guard
    - Test option stopout suppression when spot holds support.
    - Test 15% catastrophic loss override (exit even if spot holds).
    - Test immunity when stop is already trailed (trailing_stage >= 1 or current_sl >= entry * 0.99).
    """

    def setUp(self):
        self.mock_kite = MagicMock()
        self.mock_trade_db = MagicMock()
        self.mock_log_fn = MagicMock()
        self.lock = threading.Lock()

    def _make_df(self, candle_closes, base_time="2026-09-10 10:45:00"):
        b_dt = dt.fromisoformat(base_time)
        records = []
        for i, c in enumerate(candle_closes):
            c_time = (b_dt + timedelta(minutes=3 * (i + 1))).strftime("%Y-%m-%d %H:%M:%S")
            records.append({
                "date": c_time,
                "open": c + 1.0,
                "high": c + 2.0,
                "low": c - 1.0,
                "close": float(c),
                "volume": 1000
            })
        return pd.DataFrame(records)

    def test_spot_guard_suppresses_premature_option_whipsaw(self):
        """
        Scenario A: Option premium drops below SL on candle close (e.g. 89.0 vs SL 90.0),
        BUT Underlying Spot is strictly holding above structural support (spot_sl 24,900, live 24,950).
        Stopout MUST be suppressed!
        """
        entry_spot = 100.0
        current_sl = 90.0   # 10% SL
        live_ltp = 89.0     # 11% loss < 15% catastrophic
        spot_support = 24900.0
        live_spot = 24950.0 # Strictly holding above support!

        positions = {
            "NIFTY_CE": {
                "symbol": "NIFTY_CE",
                "contract": "NIFTY2691025000CE",
                "position_type": "option",
                "side": "CE",
                "entry_spot": entry_spot,
                "entry_time": "2026-09-10 10:45:00",
                "sl_set_time": "2026-09-10 10:45:00",
                "current_sl": current_sl,
                "t1": 130.0,
                "trailing_stage": 0,
                "spot_token": 256265,
                "spot_sl": spot_support,
                "option_token": 1001,
            }
        }

        mock_df = self._make_df([95.0, 92.0, 89.0])

        self.mock_kite.quote.return_value = {
            "NFO:NIFTY2691025000CE": {
                "last_price": live_ltp,
                "ohlc": {"open": live_ltp, "high": live_ltp, "low": live_ltp, "close": live_ltp}
            }
        }
        self.mock_kite.ltp.return_value = {
            "256265": {"last_price": live_spot}
        }

        with patch.object(position_monitor, "_load_program_config_file", return_value={"enable_spot_sl_guard": True, "max_option_loss_pct": 15}), \
             patch.object(position_monitor, "get_ist_now", return_value=dt(2026, 9, 10, 11, 0, 0)), \
             patch.object(position_monitor, "fetch_and_resample_candles", return_value=mock_df), \
             patch.object(position_monitor, "close_position") as mock_close:
            
            position_monitor.monitor_active_positions(
                kite=self.mock_kite,
                registry={},
                positions_dict=positions,
                lock=self.lock,
                product_type="NRML",
                engine_name="index",
                timeframe_entry="3minute",
                trade_db=self.mock_trade_db,
                log_fn=self.mock_log_fn,
                live=False
            )

            # Verification: close_position should NOT have been called! Trade suppressed by Spot SL Guard!
            mock_close.assert_not_called()
            self.mock_trade_db.update_trade.assert_not_called()

    def test_spot_guard_15pct_catastrophic_loss_override(self):
        """
        Scenario B: 15% Catastrophic Loss Override
        Option premium plunges to 84.0 (16% drop from 100.0).
        Even though Underlying Spot is still holding above support (24,950 > 24,900),
        the 15% emergency catastrophic loss ceiling MUST override spot suppression and exit!
        """
        entry_spot = 100.0
        current_sl = 90.0
        live_ltp = 84.0     # 16% loss >= 15% catastrophic cap!
        spot_support = 24900.0
        live_spot = 24950.0 # Spot holding support

        positions = {
            "NIFTY_CE": {
                "symbol": "NIFTY_CE",
                "contract": "NIFTY2691025000CE",
                "position_type": "option",
                "side": "CE",
                "entry_spot": entry_spot,
                "entry_time": "2026-09-10 10:45:00",
                "sl_set_time": "2026-09-10 10:45:00",
                "current_sl": current_sl,
                "t1": 130.0,
                "trailing_stage": 0,
                "spot_token": 256265,
                "spot_sl": spot_support,
                "option_token": 1001,
            }
        }

        mock_df = self._make_df([95.0, 90.0, 84.0])

        self.mock_kite.quote.return_value = {
            "NFO:NIFTY2691025000CE": {
                "last_price": live_ltp,
                "ohlc": {"open": live_ltp, "high": live_ltp, "low": live_ltp, "close": live_ltp}
            }
        }
        self.mock_kite.ltp.return_value = {
            "256265": {"last_price": live_spot}
        }

        with patch.object(position_monitor, "_load_program_config_file", return_value={"enable_spot_sl_guard": True, "max_option_loss_pct": 15}), \
             patch.object(position_monitor, "get_ist_now", return_value=dt(2026, 9, 10, 11, 0, 0)), \
             patch.object(position_monitor, "fetch_and_resample_candles", return_value=mock_df), \
             patch.object(position_monitor, "close_position", return_value={"success": True}) as mock_close:
            
            position_monitor.monitor_active_positions(
                kite=self.mock_kite,
                registry={},
                positions_dict=positions,
                lock=self.lock,
                product_type="NRML",
                engine_name="index",
                timeframe_entry="3minute",
                trade_db=self.mock_trade_db,
                log_fn=self.mock_log_fn,
                live=False
            )

            # Verification: close_position MUST be called because 15% catastrophic cap overrides spot guard!
            mock_close.assert_called_once()

    def test_spot_guard_trailed_stop_immunity(self):
        """
        Scenario C: Trailed Stop Immunity (trailing_stage >= 1).
        When a position has reached Target T1 and is trailed to Break-Even (current_sl = 100.0, trailing_stage = 1),
        if price falls to 99.0 on candle close, the initial morning spot support must NEVER suppress the exit!
        Profit / BE protection has absolute priority!
        """
        entry_spot = 100.0
        current_sl = 100.0  # Trailed to BE!
        live_ltp = 99.0     # Tripped trailed SL
        spot_support = 24900.0
        live_spot = 25050.0 # Spot is booming above support!

        positions = {
            "NIFTY_CE": {
                "symbol": "NIFTY_CE",
                "contract": "NIFTY2691025000CE",
                "position_type": "option",
                "side": "CE",
                "entry_spot": entry_spot,
                "entry_time": "2026-09-10 10:45:00",
                "sl_set_time": "2026-09-10 10:55:00",
                "current_sl": current_sl,
                "t1": 130.0,
                "trailing_stage": 1,  # Trailed stop active!
                "spot_token": 256265,
                "spot_sl": spot_support,
                "option_token": 1001,
            }
        }

        # Candle 1 at 10:56 (after sl_set_time 10:55) closes at 99.0 <= current_sl (100.0)
        mock_df = self._make_df([99.0], base_time="2026-09-10 10:55:00")

        self.mock_kite.quote.return_value = {
            "NFO:NIFTY2691025000CE": {
                "last_price": live_ltp,
                "ohlc": {"open": live_ltp, "high": live_ltp, "low": live_ltp, "close": live_ltp}
            }
        }
        self.mock_kite.ltp.return_value = {
            "256265": {"last_price": live_spot}
        }

        with patch.object(position_monitor, "_load_program_config_file", return_value={"enable_spot_sl_guard": True, "max_option_loss_pct": 15}), \
             patch.object(position_monitor, "get_ist_now", return_value=dt(2026, 9, 10, 11, 0, 0)), \
             patch.object(position_monitor, "fetch_and_resample_candles", return_value=mock_df), \
             patch.object(position_monitor, "close_position", return_value={"success": True}) as mock_close:
            
            position_monitor.monitor_active_positions(
                kite=self.mock_kite,
                registry={},
                positions_dict=positions,
                lock=self.lock,
                product_type="NRML",
                engine_name="index",
                timeframe_entry="3minute",
                trade_db=self.mock_trade_db,
                log_fn=self.mock_log_fn,
                live=False
            )

            # Verification: Trailed stop MUST NOT be suppressed by spot support!
            mock_close.assert_called_once()

    def test_spot_guard_trailed_stop_immunity_by_sl_level(self):
        """
        Scenario D: Trailed Stop Immunity by current_sl >= entry_s * 0.99.
        Even if trailing_stage is somehow 0, if current_sl has been raised to near entry (e.g. 99.5),
        the spot guard is strictly bypassed!
        """
        entry_spot = 100.0
        current_sl = 99.5   # Trailed near BE
        live_ltp = 99.0
        spot_support = 24900.0
        live_spot = 25050.0

        positions = {
            "NIFTY_CE": {
                "symbol": "NIFTY_CE",
                "contract": "NIFTY2691025000CE",
                "position_type": "option",
                "side": "CE",
                "entry_spot": entry_spot,
                "entry_time": "2026-09-10 10:45:00",
                "sl_set_time": "2026-09-10 10:55:00",
                "current_sl": current_sl,
                "t1": 130.0,
                "trailing_stage": 0,  # Trailing stage 0, but current_sl >= entry * 0.99
                "spot_token": 256265,
                "spot_sl": spot_support,
                "option_token": 1001,
            }
        }

        mock_df = self._make_df([99.0], base_time="2026-09-10 10:55:00")

        self.mock_kite.quote.return_value = {
            "NFO:NIFTY2691025000CE": {
                "last_price": live_ltp,
                "ohlc": {"open": live_ltp, "high": live_ltp, "low": live_ltp, "close": live_ltp}
            }
        }
        self.mock_kite.ltp.return_value = {
            "256265": {"last_price": live_spot}
        }

        with patch.object(position_monitor, "_load_program_config_file", return_value={"enable_spot_sl_guard": True, "max_option_loss_pct": 15}), \
             patch.object(position_monitor, "get_ist_now", return_value=dt(2026, 9, 10, 11, 0, 0)), \
             patch.object(position_monitor, "fetch_and_resample_candles", return_value=mock_df), \
             patch.object(position_monitor, "close_position", return_value={"success": True}) as mock_close:
            
            position_monitor.monitor_active_positions(
                kite=self.mock_kite,
                registry={},
                positions_dict=positions,
                lock=self.lock,
                product_type="NRML",
                engine_name="index",
                timeframe_entry="3minute",
                trade_db=self.mock_trade_db,
                log_fn=self.mock_log_fn,
                live=False
            )

            # Verification: Trailed stop level MUST bypass spot guard!
            mock_close.assert_called_once()


class TestR4MorningGapAuditBoundary(unittest.TestCase):
    """
    Adversarial Challenge 5: Morning Gap Audit Boundary Tests (09:16 AM Pre-Flight)
    - Bullish Long: Gap-down past SL (immediate exit) vs Gap-up past T1 (ratchet to BE).
    - Bearish Short: Gap-up past SL (immediate exit) vs Gap-down past T1 (ratchet to BE).
    """

    def setUp(self):
        self.mock_kite = MagicMock()
        # Mock margins
        self.mock_kite.margins.return_value = {
            "net": 100000.0,
            "available": {"cash": 100000.0, "collateral": 0.0}
        }

    def test_bullish_long_gap_down_breach_immediate_exit(self):
        """Bullish Long opens gap-down below Stop-Loss -> Immediate exit executed and status marked SL_HIT."""
        active_trade = {
            "id": 101,
            "symbol": "INFY",
            "contract": "INFY",
            "position_type": "stock",
            "side": "BUY",
            "entry_spot": 1800.0,
            "current_sl": 1750.0,
            "t1": 1900.0,
            "trailing_stage": 0,
        }

        # Mock broker holding the position
        self.mock_kite.positions.return_value = {
            "net": [{"tradingsymbol": "INFY", "quantity": 50, "product": "CNC", "pnl": -3000.0}]
        }
        # Mock overnight opening quote: opened at 1740 (below SL 1750)
        self.mock_kite.quote.return_value = {
            "NSE:INFY": {
                "last_price": 1742.0,
                "ohlc": {"open": 1740.0, "high": 1748.0, "low": 1738.0, "close": 1742.0}
            }
        }

        with patch("trade_db.get_active_trades", return_value=[active_trade]), \
             patch("trade_db.update_trade_status") as mock_update_status, \
             patch.object(morning_reconciler, "close_stock_position") as mock_close_stock:
            
            report = morning_reconciler.run_preflight_reconciliation(kite=self.mock_kite, engines=["daily"])

            # Verification:
            # 1. close_stock_position must be executed
            mock_close_stock.assert_called_once()
            # 2. trade_db must update status to SL_HIT with OPENING_GAP_DOWN_BREACH
            mock_update_status.assert_called_with(101, "SL_HIT", exit_price=1742.0, exit_reason="OPENING_GAP_DOWN_BREACH")
            # 3. Gap event logged
            self.assertTrue(any("GAP DOWN BREACH" in str(evt) for evt in report["gap_events"]))

    def test_bullish_long_gap_up_windfall_ratchets_to_be(self):
        """Bullish Long opens gap-up above Target T1 -> Ratchets SL to Breakeven (entry_spot) & sets trailing_stage=1."""
        active_trade = {
            "id": 102,
            "symbol": "TCS",
            "contract": "TCS",
            "position_type": "stock",
            "side": "BUY",
            "entry_spot": 4200.0,
            "current_sl": 4120.0,
            "t1": 4350.0,
            "trailing_stage": 0,
        }

        self.mock_kite.positions.return_value = {
            "net": [{"tradingsymbol": "TCS", "quantity": 25, "product": "CNC", "pnl": 4000.0}]
        }
        # Mock gap-up open at 4380 (above T1 4350)
        self.mock_kite.quote.return_value = {
            "NSE:TCS": {
                "last_price": 4385.0,
                "ohlc": {"open": 4380.0, "high": 4400.0, "low": 4375.0, "close": 4385.0}
            }
        }

        with patch("trade_db.get_active_trades", return_value=[active_trade]), \
             patch("trade_db.update_trade") as mock_update_trade, \
             patch.object(morning_reconciler, "close_stock_position") as mock_close_stock:
            
            report = morning_reconciler.run_preflight_reconciliation(kite=self.mock_kite, engines=["daily"])

            # Must NOT close position (it's a profitable windfall!)
            mock_close_stock.assert_not_called()
            # Must ratchet stop-loss to Breakeven (4200.0) and trailing_stage = 1
            mock_update_trade.assert_called_once()
            args, kwargs = mock_update_trade.call_args
            self.assertEqual(args[0], 102)
            self.assertEqual(args[1]["trailing_stage"], 1)
            self.assertEqual(args[1]["current_sl"], 4200.0)
            self.assertTrue(any("GAP UP WINDFALL" in str(evt) for evt in report["gap_events"]))

    def test_bearish_short_gap_up_breach_immediate_exit(self):
        """Bearish Short MIS opens gap-up above Stop-Loss -> Immediate exit executed and status marked SL_HIT."""
        active_trade = {
            "id": 201,
            "symbol": "SBIN",
            "contract": "SBIN",
            "position_type": "stock",
            "side": "BEAR",  # or SELL / SHORT
            "entry_spot": 800.0,
            "current_sl": 820.0,  # Overhead SL
            "t1": 760.0,          # Downward target
            "trailing_stage": 0,
        }

        self.mock_kite.positions.return_value = {
            "net": [{"tradingsymbol": "SBIN", "quantity": -100, "product": "MIS", "pnl": -2500.0}]
        }
        # Opened at 825 (above overhead SL 820)
        self.mock_kite.quote.return_value = {
            "NSE:SBIN": {
                "last_price": 826.0,
                "ohlc": {"open": 825.0, "high": 830.0, "low": 824.0, "close": 826.0}
            }
        }

        with patch("trade_db.get_active_trades", return_value=[active_trade]), \
             patch("trade_db.update_trade_status") as mock_update_status, \
             patch.object(morning_reconciler, "close_stock_position") as mock_close_stock:
            
            report = morning_reconciler.run_preflight_reconciliation(kite=self.mock_kite, engines=["bear_trade"])

            # Must trigger immediate exit to cover short
            mock_close_stock.assert_called_once()
            mock_update_status.assert_called_with(201, "SL_HIT", exit_price=826.0, exit_reason="OPENING_GAP_UP_BREACH")
            self.assertTrue(any("GAP UP BREACH" in str(evt) for evt in report["gap_events"]))

    def test_bearish_short_gap_down_windfall_ratchets_to_be(self):
        """Bearish Short MIS opens gap-down past Target T1 -> Ratchets SL down to Breakeven & sets trailing_stage=1."""
        active_trade = {
            "id": 202,
            "symbol": "HDFCBANK",
            "contract": "HDFCBANK",
            "position_type": "stock",
            "side": "BEAR",
            "entry_spot": 1650.0,
            "current_sl": 1680.0,
            "t1": 1580.0,         # Downward profit target
            "trailing_stage": 0,
        }

        self.mock_kite.positions.return_value = {
            "net": [{"tradingsymbol": "HDFCBANK", "quantity": -50, "product": "MIS", "pnl": 4500.0}]
        }
        # Opened at 1570 (below downward target T1 1580)
        self.mock_kite.quote.return_value = {
            "NSE:HDFCBANK": {
                "last_price": 1568.0,
                "ohlc": {"open": 1570.0, "high": 1575.0, "low": 1565.0, "close": 1568.0}
            }
        }

        with patch("trade_db.get_active_trades", return_value=[active_trade]), \
             patch("trade_db.update_trade") as mock_update_trade, \
             patch.object(morning_reconciler, "close_stock_position") as mock_close_stock:
            
            report = morning_reconciler.run_preflight_reconciliation(kite=self.mock_kite, engines=["bear_trade"])

            mock_close_stock.assert_not_called()
            mock_update_trade.assert_called_once()
            args, kwargs = mock_update_trade.call_args
            self.assertEqual(args[0], 202)
            self.assertEqual(args[1]["trailing_stage"], 1)
            # For bearish short, new_sl = min(sl_val, entry_spot) -> 1650.0
            self.assertEqual(args[1]["current_sl"], 1650.0)
            self.assertTrue(any("GAP DOWN WINDFALL" in str(evt) for evt in report["gap_events"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
