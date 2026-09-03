"""
scratch/test_spread_liquidity_reconciler.py
===========================================
Comprehensive Test Suite for:
1. Phase 1: 2-Leg Debit Spread Execution (Bull Call Spread & Bear Put Spread).
2. Phase 2: Bid-Ask Spread & Market Depth Liquidity Gate.
3. Phase 3: Automated 09:16 AM Pre-Flight Market Open Reconciler.
"""

import os
import sys
import json
import pandas as pd
from datetime import datetime, date

# Add paths
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(ROOT_DIR, "common")
for p in [ROOT_DIR, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

from resolve import resolve_option_spread, resolve_option_strikes
from liquidity_guard import check_bid_ask_spread_liquidity
from morning_reconciler import run_preflight_reconciliation, is_preflight_window
import paths
import trade_db


class MockKite:
    """Mock KiteConnect session for unit testing."""
    def __init__(self, quotes=None, positions_net=None, margins_data=None):
        self._quotes = quotes or {}
        self._positions_net = positions_net or []
        self._margins = margins_data or {
            "net": 150000.0,
            "available": {"cash": 120000.0, "collateral": 30000.0}
        }
        self.orders_placed = []

    def quote(self, keys):
        res = {}
        for k in keys:
            if k in self._quotes:
                res[k] = self._quotes[k]
        return res

    def positions(self):
        return {"net": self._positions_net, "day": []}

    def margins(self, segment="equity"):
        return self._margins

    def place_order(self, **kwargs):
        self.orders_placed.append(kwargs)
        return f"MOCK_OID_{len(self.orders_placed)}"


def build_mock_nfo_instruments():
    """Construct mock NFO instruments DataFrame."""
    records = []
    base_symbol = "NIFTY"
    today = date.today()
    expiry = today.strftime("%Y-%m-%d")

    # Strikes from 24000 to 25000 in steps of 50
    for strike in range(24000, 25050, 50):
        # CE
        records.append({
            "name": base_symbol,
            "tradingsymbol": f"NIFTY{strike}CE",
            "instrument_token": 100000 + strike,
            "instrument_type": "CE",
            "strike": float(strike),
            "expiry": expiry,
            "lot_size": 25
        })
        # PE
        records.append({
            "name": base_symbol,
            "tradingsymbol": f"NIFTY{strike}PE",
            "instrument_token": 200000 + strike,
            "instrument_type": "PE",
            "strike": float(strike),
            "expiry": expiry,
            "lot_size": 25
        })
    return pd.DataFrame(records)


def run_all_tests():
    passed = 0
    failed = 0

    print("=" * 80)
    print("  RUNNING UNIT TESTS: SPREADS, LIQUIDITY GATE & MORNING RECONCILER")
    print("=" * 80)

    # ──────────────────────────────────────────────────────────────────────────
    # TEST 1: Phase 1 — 2-Leg Debit Spread Resolution
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[TEST 1] Testing 2-Leg Debit Spread Resolution...")
    nfo_df = build_mock_nfo_instruments()

    # 1.1 Bull Call Spread
    spread_bull = resolve_option_spread(
        nfo_instruments=nfo_df,
        base_symbol="NIFTY",
        spot_price=24510.0,
        step_size=50,
        direction="BULL",
        target_price=24650.0
    )
    assert spread_bull is not None, "Failed to resolve Bull Call Spread"
    assert spread_bull["spread_type"] == "BULL_CALL_SPREAD"
    assert spread_bull["leg1"]["strike"] == 24500  # ATM
    assert spread_bull["leg2"]["strike"] == 24650  # OTM at Target T1
    assert spread_bull["leg1"]["action"] == "BUY"
    assert spread_bull["leg2"]["action"] == "SELL"
    assert spread_bull["strike_diff"] == 150
    print("  [PASS] Bull Call Spread correctly resolved ATM 24500 Long + OTM 24650 Short")
    passed += 1

    # 1.2 Bear Put Spread
    spread_bear = resolve_option_spread(
        nfo_instruments=nfo_df,
        base_symbol="NIFTY",
        spot_price=24510.0,
        step_size=50,
        direction="BEAR",
        target_price=24350.0
    )
    assert spread_bear is not None, "Failed to resolve Bear Put Spread"
    assert spread_bear["spread_type"] == "BEAR_PUT_SPREAD"
    assert spread_bear["leg1"]["strike"] == 24500  # ATM
    assert spread_bear["leg2"]["strike"] == 24350  # OTM at Target T1
    assert spread_bear["leg1"]["action"] == "BUY"
    assert spread_bear["leg2"]["action"] == "SELL"
    assert spread_bear["strike_diff"] == 150
    print("  [PASS] Bear Put Spread correctly resolved ATM 24500 Long + OTM 24350 Short")
    passed += 1

    # 1.3 Default width fallback when target_price is None
    spread_default = resolve_option_spread(
        nfo_instruments=nfo_df,
        base_symbol="NIFTY",
        spot_price=24500.0,
        step_size=50,
        direction="BULL",
        target_price=None,
        spread_width_steps=2
    )
    assert spread_default is not None
    assert spread_default["leg2"]["strike"] == 24600  # ATM + 2 steps (100 pts)
    print("  [PASS] Debit spread correctly applies spread_width_steps default fallback")
    passed += 1

    # ──────────────────────────────────────────────────────────────────────────
    # TEST 2: Phase 2 — Bid-Ask Spread & Order Book Depth Liquidity Gate
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[TEST 2] Testing Bid-Ask Spread Liquidity Gate...")

    # 2.1 Tight Liquid Spread (0.8% spread)
    mock_liquid_quote = {
        "NFO:NIFTY24500CE": {
            "last_price": 100.0,
            "depth": {
                "buy": [{"price": 99.6, "quantity": 500}, {"price": 99.5, "quantity": 1000}],
                "sell": [{"price": 100.4, "quantity": 600}, {"price": 100.5, "quantity": 800}]
            }
        }
    }
    kite_liquid = MockKite(quotes=mock_liquid_quote)
    liq_ok, spread_val, msg, _ = check_bid_ask_spread_liquidity(
        kite=kite_liquid, exchange="NFO", contract="NIFTY24500CE", max_spread_pct=0.02, bypass_when_closed=False
    )
    assert liq_ok is True
    assert spread_val == 0.008  # 0.8%
    print(f"  [PASS] Tight spread (0.8%) correctly accepted (msg: {msg})")
    passed += 1

    # 2.2 Illiquid Wide Spread (4.5% spread > 2.0% limit)
    mock_wide_quote = {
        "NFO:MIDCAP24500CE": {
            "last_price": 100.0,
            "depth": {
                "buy": [{"price": 97.5, "quantity": 100}],
                "sell": [{"price": 102.0, "quantity": 100}]
            }
        }
    }
    kite_wide = MockKite(quotes=mock_wide_quote)
    liq_ok_w, spread_val_w, msg_w, _ = check_bid_ask_spread_liquidity(
        kite=kite_wide, exchange="NFO", contract="MIDCAP24500CE", max_spread_pct=0.02, bypass_when_closed=False
    )
    assert liq_ok_w is False
    assert spread_val_w == 0.045
    assert "Wide bid-ask spread" in msg_w
    print(f"  [PASS] Wide spread (4.5%) correctly rejected by liquidity gate (msg: {msg_w})")
    passed += 1

    # 2.3 Empty Book Depth
    mock_empty_quote = {
        "NFO:ILLIQUID_OPT": {
            "last_price": 50.0,
            "depth": {
                "buy": [],
                "sell": [{"price": 55.0, "quantity": 10}]
            }
        }
    }
    kite_empty = MockKite(quotes=mock_empty_quote)
    liq_ok_e, _, msg_e, _ = check_bid_ask_spread_liquidity(
        kite=kite_empty, exchange="NFO", contract="ILLIQUID_OPT", bypass_when_closed=False
    )
    assert liq_ok_e is False
    assert "Empty order book" in msg_e
    print("  [PASS] Empty order book correctly rejected by depth validation")
    passed += 1

    # ──────────────────────────────────────────────────────────────────────────
    # TEST 3: Phase 3 — 09:16 AM Pre-Flight Market Open Reconciler
    # ──────────────────────────────────────────────────────────────────────────
    print("\n[TEST 3] Testing 09:16 AM Morning Pre-Flight Reconciler...")

    # Mock Kite with 1 active position on broker and quotes
    mock_reconcile_quote = {
        "NSE:RELIANCE": {
            "last_price": 1400.0,
            "ohlc": {"open": 1405.0}
        }
    }
    mock_positions_net = [
        {"tradingsymbol": "RELIANCE", "quantity": 20, "product": "CNC", "pnl": 100.0, "exchange": "NSE"}
    ]
    kite_reconcile = MockKite(quotes=mock_reconcile_quote, positions_net=mock_positions_net)

    report = run_preflight_reconciliation(kite=kite_reconcile, engines=["daily"])
    assert report is not None
    assert "timestamp" in report
    assert "margin_summary" in report
    assert report["margin_summary"]["available_cash"] == 120000.0
    assert os.path.exists(paths.MONITOR_DIR)
    print("  [PASS] 09:16 AM pre-flight reconciliation ran and generated structured audit report")
    passed += 1

    print("\n" + "=" * 80)
    print(f"  FINAL SUMMARY: {passed} PASSED, {failed} FAILED (100% SUCCESS)")
    print("=" * 80)
    return passed, failed


if __name__ == "__main__":
    p, f = run_all_tests()
    if f > 0:
        sys.exit(1)
    sys.exit(0)
