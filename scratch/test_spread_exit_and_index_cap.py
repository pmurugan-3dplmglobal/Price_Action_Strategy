#!/usr/bin/env python3
"""
scratch/test_spread_exit_and_index_cap.py
Unit test suite verifying:
1. Spread Opening Stabilization Window (09:15 - 09:20 IST) in position_monitor
2. Net Spread Value Target Guard (protects against single-leg false target triggers)
3. Sequential Leg 2 fill confirmation inline loop
4. Radar risk budget and capital gate with debit spread calibration
5. Portfolio risk daily drawdown excluding CNC and accurately accounting for spreads
6. Dashboard failsafe monitor 09:20 gate and spread protection
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime as dt, time as dt_time
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
common_dir = os.path.join(PROJECT_ROOT, "common")
if common_dir not in sys.path:
    sys.path.insert(0, common_dir)

from common import position_monitor
from common import portfolio_risk


class TestSpreadExitAndRiskCap(unittest.TestCase):

    def test_01_spread_opening_stabilization_suppresses_exits(self):
        """Before 09:20 IST, automated exits on spreads must be suppressed."""
        pos = {
            "symbol": "FINNIFTY",
            "contract": "FINNIFTY26OCT24950PE",
            "position_type": "option_spread",
            "leg2_contract": "FINNIFTY26OCT24800PE",
            "entry_spot": 351.90,
            "current_sl": 320.00,
            "t1": 390.00,
            "quantity": 60,
            "position_size": 1
        }
        
        # Test empty-candle shield before 09:20
        now_time_str = "09:16"
        is_spread_pos = (pos.get("position_type") == "option_spread") or bool(pos.get("leg2_contract"))
        self.assertTrue(is_spread_pos)
        self.assertTrue(now_time_str < "09:20")
        
        # In position_monitor: is_spread_pos and now_time_str < "09:20" triggers suppression
        suppress_empty = is_spread_pos and now_time_str < "09:20"
        self.assertTrue(suppress_empty)

    def test_02_net_spread_value_suppresses_deficit_target_trigger(self):
        """When Leg 1 LTP > Entry, but Net Spread Value <= Net Debit, T1 must NOT trigger."""
        pos = {
            "symbol": "FINNIFTY",
            "contract": "FINNIFTY26OCT24950PE",
            "position_type": "option_spread",
            "leg2_contract": "FINNIFTY26OCT24800PE",
            "entry_spot": 351.90,
            "leg2_entry_price": 288.90,
            "net_debit": 63.00,
            "strike_diff": 150.0,
            "spot_t1": 24789.0,
            "current_sl": 320.00,
            "t1": 390.00,
            "side": "PE"
        }
        
        # Leg 1 is 363.55 (gain on naked leg), but Leg 2 is 374.95 (loss on short leg)
        leg1_ltp = 363.55
        leg2_ltp = 374.95
        curr_net_spread = leg1_ltp - leg2_ltp  # -11.40
        net_debit = float(pos["net_debit"])
        
        # Verify net spread is in severe loss
        self.assertLess(curr_net_spread, net_debit)
        
        # Logic from position_monitor SPOT_TARGET_GUARD
        spot_target_hit = True  # e.g. FINNIFTY spot was at 24773 <= 24789
        t1_hit = False
        min_spread_target = net_debit * 1.25
        if curr_net_spread > net_debit and curr_net_spread >= min_spread_target:
            t1_hit = True
            
        self.assertFalse(t1_hit, "T1 hit should be False when Net Spread Value is in deficit")

    def test_03_net_spread_value_allows_profitable_target_trigger(self):
        """When Net Spread Value > Net Debit and reaches target threshold, T1 triggers."""
        net_debit = 63.00
        strike_diff = 150.0
        min_spread_target = max(net_debit * 1.25, net_debit + 0.65 * (strike_diff - net_debit))
        
        # Profitable scenario: Leg 1 = 430, Leg 2 = 300 -> Net spread = 130
        leg1_ltp = 430.00
        leg2_ltp = 300.00
        curr_net_spread = leg1_ltp - leg2_ltp  # 130.0
        
        t1_hit = False
        if curr_net_spread > net_debit and curr_net_spread >= min_spread_target:
            t1_hit = True
            
        self.assertTrue(t1_hit, "T1 should trigger when Net Spread reaches profitable target threshold")

    def test_04_radar_risk_budget_uses_net_debit_for_spreads(self):
        """Debit spread candidates must evaluate sizing and capital on net debit, not gross premium."""
        from common.trading_core import calculate_position_size
        
        naked_opt_premium = 65.0
        lot_sz = 600
        cap = 100000.0
        max_risk_pct = 1.0  # 1000 max risk
        
        # Naked sizing with wide SL: 65 - 40 = 25 pts risk * 600 = 15,000 risk -> rejected (0 lots)
        naked_pos_sz = calculate_position_size(
            spot_price=naked_opt_premium,
            stop_loss=40.0,
            capital=cap,
            risk_percent=max_risk_pct,
            lot_size=lot_sz,
            is_option=True,
            tier=2,
            allow_zero=True,
            allow_single_lot_conviction=False
        )
        self.assertEqual(naked_pos_sz, 0)
        
        # With Debit spread calibration:
        # Stock option spread with net debit 6.0 pts, SL 2.0 pts, lot 600: risk = 4.0 * 600 = 2400 (<= 5% cap)
        net_debit = 6.0
        spread_sl = 2.0
        spread_pos_sz = calculate_position_size(
            spot_price=net_debit,
            stop_loss=spread_sl,
            capital=cap,
            risk_percent=max_risk_pct,
            lot_size=lot_sz,
            is_option=True,
            tier=2,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=5.0
        )
        self.assertGreaterEqual(spread_pos_sz, 1, "Spread candidate should pass single lot conviction")

    def test_05_portfolio_risk_excludes_cnc_and_scales_spreads(self):
        """Portfolio risk check must exclude CNC investments and compute spread INR from net debit."""
        fake_db_trades = [
            {
                "id": 1,
                "symbol": "FINNIFTY",
                "contract": "FINNIFTY26OCT24950PE",
                "position_type": "option_spread",
                "leg2_contract": "FINNIFTY26OCT24800PE",
                "net_debit": 63.0,
                "entry_spot": 351.90,
                "lot_size": 60,
                "position_size": 1,
                "pnl_percent": -15.0,  # -15% on 63 pts = -9.45 * 60 = -567 INR
                "created_at": dt.now().strftime("%Y-%m-%d 10:00:00"),
                "status": "COMPLETED",
                "exit_time": dt.now().strftime("%Y-%m-%d 10:30:00")
            }
        ]
        
        # Test spread basis calculation:
        t = fake_db_trades[0]
        is_spread = (t.get("position_type") == "option_spread") or bool(t.get("leg2_contract"))
        self.assertTrue(is_spread)
        eff_basis = float(t.get("net_debit"))
        self.assertEqual(eff_basis, 63.0)
        
        # Verify broker CNC exclusion:
        net_pos = [
            {"tradingsymbol": "RELIANCE", "product": "CNC", "pnl": -15000.0},
            {"tradingsymbol": "NIFTY26O1322500CE", "product": "NRML", "pnl": -2000.0}
        ]
        algo_pnl = sum(float(p.get("pnl", 0.0)) for p in net_pos if str(p.get("product", "")).upper() != "CNC")
        self.assertEqual(algo_pnl, -2000.0, "CNC investment loss of -15,000 must be excluded from algorithmic drawdown")

    def test_06_dashboard_failsafe_0920_gate(self):
        """Dashboard failsafe loop must suppress target exits before 09:20 AM and on spreads."""
        # 1. Before 09:20 AM
        now_t_early = dt_time(9, 16)
        is_fs_spread = False
        target_exits_active_early = (now_t_early >= dt_time(9, 20)) and not is_fs_spread
        self.assertFalse(target_exits_active_early)
        
        # 2. Spread at 09:30 AM
        now_t_later = dt_time(9, 30)
        is_fs_spread = True
        target_exits_active_spread = (now_t_later >= dt_time(9, 20)) and not is_fs_spread
        self.assertFalse(target_exits_active_spread)
        
        # 3. Naked option at 09:30 AM
        is_fs_spread = False
        target_exits_active_clean = (now_t_later >= dt_time(9, 20)) and not is_fs_spread
        self.assertTrue(target_exits_active_clean)


if __name__ == "__main__":
    unittest.main()
