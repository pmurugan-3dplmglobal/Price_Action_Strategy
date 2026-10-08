"""
test_issue126_risk_and_spread_sizing.py

Unit verification suite for ISSUE-126:
1. Naked Option Risk Cap: 7.0% (Risk is ₹6,694 = 6.69% of ₹100k, approved).
2. Debit Spread Risk Cap: 11.0% (Net debit risk is ₹10,763 = 10.76% of ₹100k, approved).
3. Portfolio Risk Circuit Breaker: max_daily_loss_pct updated to 10.0% across all engines.
4. Auto-spread conversion and radar sizing parameter precedence.
"""

import unittest
import json
import os
import sys

# Ensure canonical paths
common_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common")
trade_opt_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Trade_Option")
if common_dir not in sys.path:
    sys.path.insert(0, common_dir)
if trade_opt_dir not in sys.path:
    sys.path.insert(0, trade_opt_dir)

from targets import calculate_position_size
from portfolio_risk import _load_portfolio_risk_config, check_portfolio_risk_caps
import paths


class TestIssue126RiskAndSpreadSizing(unittest.TestCase):

    def test_01_naked_430_pe_sizing(self):
        """
        Naked 430 PE setup:
        Risk is ₹6,694 = 6.694% of ₹100k.
        Under old 5.0% cap: Rejected (returns 0 lots).
        Under new 7.0% cap / default: Approved (returns 1 lot).
        """
        # Contract parameters simulating 430 PE setup
        lot_size = 1338
        entry = 15.0
        # Risk per unit = 6694 / 1338 = 5.00298...
        sl = entry - (6694.0 / lot_size)
        risk_per_lot = abs(entry - sl) * lot_size
        self.assertAlmostEqual(risk_per_lot, 6694.0, places=1)

        # 1. Blocked under 5.0% cap
        lots_5pct = calculate_position_size(
            spot_price=entry,
            stop_loss=sl,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=lot_size,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=5.0,
            is_spread=False
        )
        self.assertEqual(lots_5pct, 0, "Naked 430 PE risk of 6.69% must be rejected under 5.0% cap")

        # 2. Approved under 7.0% cap
        lots_7pct = calculate_position_size(
            spot_price=entry,
            stop_loss=sl,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=lot_size,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=7.0,
            is_spread=False
        )
        self.assertEqual(lots_7pct, 1, "Naked 430 PE risk of 6.69% must be approved under 7.0% cap")

        # 3. Approved under new default (7.0%)
        lots_default = calculate_position_size(
            spot_price=entry,
            stop_loss=sl,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=lot_size,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True
        )
        self.assertEqual(lots_default, 1, "Naked 430 PE must be approved under new default cap")

    def test_02_debit_spread_net_debit_risk_sizing(self):
        """
        Debit Spread setup:
        Net debit risk is ₹10,763 = 10.763% of ₹100k.
        Under 7.0% naked cap: Rejected (returns 0 lots).
        Under 11.0% spread cap: Approved (returns 1 lot).
        """
        lot_size = 1000
        net_debit = 10.763
        l1_p = 25.0
        l2_p = l1_p - net_debit
        risk_per_lot = abs(l1_p - l2_p) * lot_size
        self.assertAlmostEqual(risk_per_lot, 10763.0, places=1)

        # 1. Blocked if treated as naked (7.0% cap)
        lots_naked = calculate_position_size(
            spot_price=l1_p,
            stop_loss=l2_p,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=lot_size,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=7.0,
            is_spread=False
        )
        self.assertEqual(lots_naked, 0, "Debit spread risk of 10.76% must be rejected under 7.0% naked cap")

        # 2. Approved under 11.0% spread cap
        lots_spread = calculate_position_size(
            spot_price=l1_p,
            stop_loss=l2_p,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=lot_size,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True,
            max_single_lot_risk_pct=7.0,
            is_spread=True,
            max_single_lot_spread_risk_pct=11.0
        )
        self.assertEqual(lots_spread, 1, "Debit spread risk of 10.76% must be approved under 11.0% spread cap")

        # 3. Capital outlay correctly evaluates net debit (₹10,763 <= ₹25,000 25% account ceiling)
        # Even if gross leg 1 premium would exceed 25% account cap:
        l1_expensive = 35.0  # 35 * 1000 = 35,000 > 25,000 (would fail if gross premium used)
        l2_expensive = l1_expensive - net_debit
        lots_expensive_l1 = calculate_position_size(
            spot_price=l1_expensive,
            stop_loss=l2_expensive,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=lot_size,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True,
            is_spread=True,
            max_single_lot_spread_risk_pct=11.0
        )
        self.assertEqual(lots_expensive_l1, 1, "Debit spread outlay must use net debit, not gross Leg 1 premium")

    def test_03_spread_risk_cap_overrides(self):
        """Custom spread risk cap overrides are strictly respected."""
        lots_tight = calculate_position_size(
            spot_price=20.0,
            stop_loss=10.0,  # net debit 10.0 * 1000 = 10,000 = 10%
            capital=100000.0,
            risk_percent=1.0,
            lot_size=1000,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True,
            is_spread=True,
            max_single_lot_spread_risk_pct=9.0  # 9% < 10%
        )
        self.assertEqual(lots_tight, 0, "Spread with 10% risk must be rejected under 9% spread cap")

        lots_generous = calculate_position_size(
            spot_price=20.0,
            stop_loss=10.0,
            capital=100000.0,
            risk_percent=1.0,
            lot_size=1000,
            is_option=True,
            tier=1,
            allow_zero=True,
            allow_single_lot_conviction=True,
            is_spread=True,
            max_single_lot_spread_risk_pct=12.0  # 12% > 10%
        )
        self.assertEqual(lots_generous, 1, "Spread with 10% risk must be approved under 12% spread cap")

    def test_04_portfolio_risk_config_10pct_across_engines(self):
        """Verify max_daily_loss_pct is 10.0% across all engines and fallback."""
        # 1. Default fallback
        cfg_default = _load_portfolio_risk_config(config={})
        self.assertEqual(cfg_default["max_daily_loss_pct"], 10.0)

        # 2. nifty50 engine
        cfg_nifty50 = _load_portfolio_risk_config(engine="nifty50")
        self.assertEqual(cfg_nifty50["max_daily_loss_pct"], 10.0)

        # 3. index engine
        cfg_index = _load_portfolio_risk_config(engine="index")
        self.assertEqual(cfg_index["max_daily_loss_pct"], 10.0)

        # 4. daily engine
        cfg_daily = _load_portfolio_risk_config(engine="daily")
        self.assertEqual(cfg_daily["max_daily_loss_pct"], 10.0)

    def test_05_intraday_circuit_breaker_threshold(self):
        """
        Intraday circuit breaker allows up to 10% drawdown before capping new entries.
        On ₹100k capital:
        - Loss of ₹9,500 (-9.5%): Allowed
        - Loss of ₹10,500 (-10.5%): Blocked with DAILY_DRAWDOWN_CAP_EXCEEDED
        """
        # Mock broker Kite returning PnL
        class MockKiteLoss:
            def __init__(self, pnl):
                self._pnl = pnl
            def positions(self):
                return {"net": [{"tradingsymbol": "LOSS_SYM", "pnl": self._pnl, "product": "MIS"}]}
            def holdings(self):
                return []

        kite_9_5pct = MockKiteLoss(-9500.0)
        ok_9_5, reason_9_5, _ = check_portfolio_risk_caps(
            "nifty50", "INFY", capital=100000.0, include_db_trades=False, kite=kite_9_5pct
        )
        self.assertTrue(ok_9_5, f"-9.5% loss should be permitted under 10% limit, got: {reason_9_5}")

        kite_10_5pct = MockKiteLoss(-10500.0)
        ok_10_5, reason_10_5, details_10_5 = check_portfolio_risk_caps(
            "nifty50", "INFY", capital=100000.0, include_db_trades=False, kite=kite_10_5pct
        )
        self.assertFalse(ok_10_5, "-10.5% loss must be blocked under 10% limit")
        self.assertIn("DAILY_DRAWDOWN_CAP_EXCEEDED", reason_10_5)
        self.assertEqual(details_10_5.get("rule"), "max_daily_loss_pct")

    def test_06_config_files_audited_and_synchronized(self):
        """Verify program_config.json files contain synchronized 10.0% daily loss and 7%/11% risk caps."""
        config_paths = [
            paths.PROGRAM_CONFIG_FILE,
            os.path.join(paths.PROJECT_ROOT, "Trade_Option", "input", "program_config.json"),
            os.path.join(paths.PROJECT_ROOT, "Trade_Stock", "input", "program_config.json")
        ]
        for cp in config_paths:
            self.assertTrue(os.path.exists(cp), f"Config file must exist: {cp}")
            with open(cp, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["portfolio_risk"]["max_daily_loss_pct"], 10.0, f"portfolio_risk.max_daily_loss_pct mismatch in {cp}")
            self.assertEqual(data["nifty50"]["max_daily_loss_pct"], 10.0, f"nifty50.max_daily_loss_pct mismatch in {cp}")
            self.assertEqual(data["nifty50"]["max_single_lot_risk_pct"], 7.0, f"nifty50.max_single_lot_risk_pct mismatch in {cp}")
            self.assertEqual(data["nifty50"]["max_single_lot_spread_risk_pct"], 11.0, f"nifty50.max_single_lot_spread_risk_pct mismatch in {cp}")
            self.assertEqual(data["index"]["max_daily_loss_pct"], 10.0, f"index.max_daily_loss_pct mismatch in {cp}")
            self.assertEqual(data["daily"]["max_daily_loss_pct"], 10.0, f"daily.max_daily_loss_pct mismatch in {cp}")
            self.assertEqual(data["bear_trade"]["max_daily_loss_pct"], 10.0, f"bear_trade.max_daily_loss_pct mismatch in {cp}")


if __name__ == "__main__":
    unittest.main()
