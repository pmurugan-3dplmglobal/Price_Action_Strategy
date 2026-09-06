"""
scratch/test_tier_gap_expiry_enhancements.py
=============================================
Genuine Integration Verification Suite for:
1. Conviction-Weighted Tier Sizing (T1 100%, T2 70%, T3 50%, Option 25% cap)
2. Morning 09:16 AM Pre-Flight Reconciler (Put Option PE, Call Option CE, Long Stock, Short Stock)
3. 0DTE Weekly Index Rollover at >= 13:30 IST in common/resolve.py
4. Stock Options Monthly Expiry Rollover Standardization (STOCK_EXPIRY_ROLLOVER_DAYS = 6)
"""

import sys
import os
from datetime import datetime, date, timedelta, time as datetime_time
from unittest.mock import MagicMock, patch
import pandas as pd

# Add common to sys.path
COMMON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common"))
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from targets import calculate_position_size
from registries import STOCK_EXPIRY_ROLLOVER_DAYS
from trading_core import STOCK_EXPIRY_ROLLOVER_DAYS as CORE_STOCK_ROLLOVER_DAYS
import morning_reconciler
import resolve

passed = 0
failed = 0

def check(name, cond):
    global passed, failed
    if cond:
        print(f'  [PASS] {name}')
        passed += 1
    else:
        print(f'  [FAIL] {name}')
        failed += 1


class MockKiteSession:
    """Mock KiteConnect session for offline testing."""
    def __init__(self, quotes=None, positions_net=None):
        self._quotes = quotes or {}
        self._positions_net = positions_net or []
        self.closed_positions = []

    def quote(self, keys):
        res = {}
        for k in keys:
            if k in self._quotes:
                res[k] = self._quotes[k]
        return res

    def positions(self):
        return {"net": self._positions_net, "day": []}

    def margins(self, segment="equity"):
        return {"net": 100000.0, "available": {"cash": 100000.0, "collateral": 0.0}}


# ──────────────────────────────────────────────────────────────────────────────
# TEST 1: Tier-based Capital Sizing & Capital Ceilings
# ──────────────────────────────────────────────────────────────────────────────
print('[TEST 1] Conviction-Weighted Tier Sizing & Capital Ceilings:')
s1 = calculate_position_size(2800, 2750, capital=100000.0, risk_percent=1.0, is_option=False, tier=1)
check('Tier 1 = 100% capital (20 shares)', s1 == 20)

s2 = calculate_position_size(2800, 2750, capital=100000.0, risk_percent=1.0, is_option=False, tier=2)
check('Tier 2 = 70% capital (14 shares)', s2 == 14)

s3 = calculate_position_size(2800, 2750, capital=100000.0, risk_percent=1.0, is_option=False, tier=3)
check('Tier 3 = 50% capital (10 shares)', s3 == 10)

s_def = calculate_position_size(2800, 2750, capital=100000.0, risk_percent=1.0, is_option=False)
check('Default tier = 1 (20 shares)', s_def == 20)

# Option 25% single-strike capital ceiling
lots_t1 = calculate_position_size(100.0, 99.8, capital=100000.0, risk_percent=1.0, lot_size=25, is_option=True, tier=1)
check('Option T1 25% cap enforces 10 lots (Rs 25,000 max)', lots_t1 == 10)

lots_t2 = calculate_position_size(100.0, 99.8, capital=100000.0, risk_percent=1.0, lot_size=25, is_option=True, tier=2)
check('Option T2 25% cap on 70k capital enforces 7 lots (Rs 17,500 max)', lots_t2 == 7)

lots_t3 = calculate_position_size(100.0, 99.8, capital=100000.0, risk_percent=1.0, lot_size=25, is_option=True, tier=3)
check('Option T3 25% cap on 50k capital enforces 5 lots (Rs 12,500 max)', lots_t3 == 5)


# ──────────────────────────────────────────────────────────────────────────────
# TEST 2: Genuine Morning Reconciler Gap Audit (PE, CE, Long Stock, Short Stock)
# ──────────────────────────────────────────────────────────────────────────────
print('\n[TEST 2] Genuine Morning Reconciler Gap Audit:')

# 2.1 Put Option (PE) Normal Open — CRITICAL BUG FIX PROOF: Must NOT False-Breach!
pe_trade_normal = {
    "id": 501,
    "symbol": "NIFTY",
    "contract": "NIFTY24SEP25000PE",
    "position_type": "option",
    "side": "PE",
    "entry_spot": 100.0,
    "current_sl": 80.0,
    "t1": 140.0,
    "trailing_stage": 0
}
mock_kite_pe_normal = MockKiteSession(
    quotes={"NFO:NIFTY24SEP25000PE": {"last_price": 100.0, "ohlc": {"open": 100.0}}},
    positions_net=[{"tradingsymbol": "NIFTY24SEP25000PE", "quantity": 50, "product": "NRML", "pnl": 0.0}]
)
with patch("trade_db.get_active_trades", return_value=[pe_trade_normal]), \
     patch("trade_db.update_trade_status") as mock_update_status, \
     patch.object(morning_reconciler, "close_position") as mock_close_opt:
    rep_pe_norm = morning_reconciler.run_preflight_reconciliation(kite=mock_kite_pe_normal, engines=["index"])
    check('Put Option (PE) Normal Open does NOT trigger false breach', len(rep_pe_norm["gap_events"]) == 0)
    check('Put Option (PE) Normal Open does NOT execute market close', not mock_close_opt.called)
    check('Put Option (PE) Normal Open does NOT update status to SL_HIT', not mock_update_status.called)

# 2.2 Put Option (PE) Gap-Down Breach (open <= SL)
pe_trade_breach = dict(pe_trade_normal, id=502)
mock_kite_pe_breach = MockKiteSession(
    quotes={"NFO:NIFTY24SEP25000PE": {"last_price": 75.0, "ohlc": {"open": 75.0}}},
    positions_net=[{"tradingsymbol": "NIFTY24SEP25000PE", "quantity": 50, "product": "NRML", "pnl": -1250.0}]
)
with patch("trade_db.get_active_trades", return_value=[pe_trade_breach]), \
     patch("trade_db.update_trade_status") as mock_update_status, \
     patch.object(morning_reconciler, "close_position") as mock_close_opt:
    rep_pe_breach = morning_reconciler.run_preflight_reconciliation(kite=mock_kite_pe_breach, engines=["index"])
    check('Put Option (PE) Gap-Down correctly triggers breach', any("GAP DOWN BREACH" in str(e) for e in rep_pe_breach["gap_events"]))
    check('Put Option (PE) Gap-Down calls close_position', mock_close_opt.called)
    mock_update_status.assert_called_with(502, "SL_HIT", exit_price=75.0, exit_reason="OPENING_GAP_DOWN_BREACH")
    check('Put Option (PE) Gap-Down records SL_HIT', True)

# 2.3 Put Option (PE) Gap-Up Windfall (open >= T1)
pe_trade_windfall = dict(pe_trade_normal, id=503)
mock_kite_pe_windfall = MockKiteSession(
    quotes={"NFO:NIFTY24SEP25000PE": {"last_price": 150.0, "ohlc": {"open": 150.0}}},
    positions_net=[{"tradingsymbol": "NIFTY24SEP25000PE", "quantity": 50, "product": "NRML", "pnl": 2500.0}]
)
with patch("trade_db.get_active_trades", return_value=[pe_trade_windfall]), \
     patch("trade_db.update_trade") as mock_update_trade:
    rep_pe_wind = morning_reconciler.run_preflight_reconciliation(kite=mock_kite_pe_windfall, engines=["index"])
    check('Put Option (PE) Gap-Up correctly detects windfall', any("GAP UP WINDFALL" in str(e) for e in rep_pe_wind["gap_events"]))
    mock_update_trade.assert_called_once()
    args, kwargs = mock_update_trade.call_args
    check('Put Option (PE) Gap-Up ratchets SL to Break-Even (entry 100.0)', args[1]["current_sl"] == 100.0 and args[1]["trailing_stage"] == 1)

# 2.4 Bearish Short Stock Gap-Up Breach & Gap-Down Windfall
stock_short = {
    "id": 601,
    "symbol": "SBIN",
    "contract": "SBIN",
    "position_type": "stock",
    "side": "SELL",
    "direction": "BEAR",
    "entry_spot": 800.0,
    "current_sl": 820.0,
    "t1": 760.0,
    "trailing_stage": 0
}
mock_kite_short_breach = MockKiteSession(
    quotes={"NSE:SBIN": {"last_price": 825.0, "ohlc": {"open": 825.0}}},
    positions_net=[{"tradingsymbol": "SBIN", "quantity": -100, "product": "MIS", "pnl": -2500.0}]
)
with patch("trade_db.get_active_trades", return_value=[stock_short]), \
     patch("trade_db.update_trade_status") as mock_update_status, \
     patch.object(morning_reconciler, "close_stock_position") as mock_close_stock:
    rep_short_br = morning_reconciler.run_preflight_reconciliation(kite=mock_kite_short_breach, engines=["daily"])
    check('Bearish short stock detects Gap-Up breach (open 825 >= SL 820)', any("GAP UP BREACH" in str(e) for e in rep_short_br["gap_events"]))
    check('Bearish short stock calls close_stock_position', mock_close_stock.called)
    mock_update_status.assert_called_with(601, "SL_HIT", exit_price=825.0, exit_reason="OPENING_GAP_UP_BREACH")
    check('Bearish short stock status marked SL_HIT', True)

mock_kite_short_windfall = MockKiteSession(
    quotes={"NSE:SBIN": {"last_price": 750.0, "ohlc": {"open": 750.0}}},
    positions_net=[{"tradingsymbol": "SBIN", "quantity": -100, "product": "MIS", "pnl": 5000.0}]
)
with patch("trade_db.get_active_trades", return_value=[stock_short]), \
     patch("trade_db.update_trade") as mock_update_trade:
    rep_short_wd = morning_reconciler.run_preflight_reconciliation(kite=mock_kite_short_windfall, engines=["daily"])
    check('Bearish short stock detects Gap-Down windfall (open 750 <= T1 760)', any("GAP DOWN WINDFALL" in str(e) for e in rep_short_wd["gap_events"]))
    args, _ = mock_update_trade.call_args
    check('Bearish short stock ratchets SL down to Break-Even (entry 800.0)', args[1]["current_sl"] == 800.0 and args[1]["trailing_stage"] == 1)


# ──────────────────────────────────────────────────────────────────────────────
# TEST 3: Genuine 0DTE Weekly Index Rollover at >= 13:30 IST in resolve.py
# ──────────────────────────────────────────────────────────────────────────────
print('\n[TEST 3] Genuine 0DTE Weekly Index Rollover in resolve.py:')

today_d = date(2026, 9, 10)
next_week_d = today_d + timedelta(days=7)

mock_instruments = pd.DataFrame([
    {"name": "NIFTY", "tradingsymbol": "NIFTY2691024500CE", "instrument_token": 101, "instrument_type": "CE", "strike": 24500.0, "expiry": today_d.strftime("%Y-%m-%d"), "lot_size": 25},
    {"name": "NIFTY", "tradingsymbol": "NIFTY2691724500CE", "instrument_token": 102, "instrument_type": "CE", "strike": 24500.0, "expiry": next_week_d.strftime("%Y-%m-%d"), "lot_size": 25},
])

# 3.1 0DTE morning (10:00 IST) -> Today's expiry
t_1000 = datetime.combine(today_d, datetime_time(10, 0, 0))
with patch.object(resolve, "get_ist_date", return_value=today_d), \
     patch.object(resolve, "get_ist_now", return_value=t_1000):
    res_1000 = resolve.resolve_option_strikes(mock_instruments.copy(), "NIFTY", 24500.0, 50, "CE", n_range=0)
    check('0DTE morning (10:00 IST) selects today expiry (NIFTY2691024500CE)', res_1000[0]["tradingsymbol"] == "NIFTY2691024500CE")

# 3.2 0DTE afternoon before threshold (13:29:59 IST) -> Today's expiry
t_1329 = datetime.combine(today_d, datetime_time(13, 29, 59))
with patch.object(resolve, "get_ist_date", return_value=today_d), \
     patch.object(resolve, "get_ist_now", return_value=t_1329):
    res_1329 = resolve.resolve_option_strikes(mock_instruments.copy(), "NIFTY", 24500.0, 50, "CE", n_range=0)
    check('0DTE afternoon (13:29:59 IST) stays on today expiry', res_1329[0]["tradingsymbol"] == "NIFTY2691024500CE")

# 3.3 0DTE afternoon at threshold (13:30:00 IST) -> MUST ROLL OVER TO NEXT WEEK!
t_1330 = datetime.combine(today_d, datetime_time(13, 30, 0))
with patch.object(resolve, "get_ist_date", return_value=today_d), \
     patch.object(resolve, "get_ist_now", return_value=t_1330):
    res_1330 = resolve.resolve_option_strikes(mock_instruments.copy(), "NIFTY", 24500.0, 50, "CE", n_range=0)
    check('0DTE afternoon (13:30:00 IST) rolls over to next week (NIFTY2691724500CE)', res_1330[0]["tradingsymbol"] == "NIFTY2691724500CE")

# 3.4 0DTE afternoon at 13:35:00 IST -> MUST ROLL OVER TO NEXT WEEK!
t_1335 = datetime.combine(today_d, datetime_time(13, 35, 0))
with patch.object(resolve, "get_ist_date", return_value=today_d), \
     patch.object(resolve, "get_ist_now", return_value=t_1335):
    res_1335 = resolve.resolve_option_strikes(mock_instruments.copy(), "NIFTY", 24500.0, 50, "CE", n_range=0)
    check('0DTE afternoon (13:35:00 IST) rolls over to next week (NIFTY2691724500CE)', res_1335[0]["tradingsymbol"] == "NIFTY2691724500CE")

# 3.5 Non-expiry day (1 day remaining) at 14:15 IST -> STAYS ON CURRENT EXPIRY
d_wed = today_d - timedelta(days=1)
t_wed_1415 = datetime.combine(d_wed, datetime_time(14, 15, 0))
with patch.object(resolve, "get_ist_date", return_value=d_wed), \
     patch.object(resolve, "get_ist_now", return_value=t_wed_1415):
    res_wed = resolve.resolve_option_strikes(mock_instruments.copy(), "NIFTY", 24500.0, 50, "CE", n_range=0)
    check('Non-expiry day (1d rem) at 14:15 IST stays on current expiry', res_wed[0]["tradingsymbol"] == "NIFTY2691024500CE")


# ──────────────────────────────────────────────────────────────────────────────
# TEST 4: Stock Option Monthly Expiry Rollover Standardization
# ──────────────────────────────────────────────────────────────────────────────
print('\n[TEST 4] Stock Option Monthly Expiry Rollover Standardization:')

check('STOCK_EXPIRY_ROLLOVER_DAYS == 6 in common/registries.py', STOCK_EXPIRY_ROLLOVER_DAYS == 6)
check('STOCK_EXPIRY_ROLLOVER_DAYS == 6 exported by common/trading_core.py', CORE_STOCK_ROLLOVER_DAYS == 6)

curr_month_exp = date(2026, 9, 24)
next_month_exp = date(2026, 10, 29)
mock_stock_inst = pd.DataFrame([
    {"name": "RELIANCE", "tradingsymbol": "RELIANCE26SEP3000CE", "instrument_token": 201, "instrument_type": "CE", "strike": 3000.0, "expiry": curr_month_exp.strftime("%Y-%m-%d"), "lot_size": 250},
    {"name": "RELIANCE", "tradingsymbol": "RELIANCE26OCT3000CE", "instrument_token": 202, "instrument_type": "CE", "strike": 3000.0, "expiry": next_month_exp.strftime("%Y-%m-%d"), "lot_size": 250},
])

# 7 days remaining -> Current Month
d_rem_7 = curr_month_exp - timedelta(days=7)
with patch.object(resolve, "get_ist_date", return_value=d_rem_7):
    res_stock_7 = resolve.resolve_option_strikes(mock_stock_inst.copy(), "RELIANCE", 3000.0, 20, "CE", n_range=0)
    check('Stock option with 7 days to expiry stays on current month', res_stock_7[0]["tradingsymbol"] == "RELIANCE26SEP3000CE")

# 6 days remaining (<= STOCK_EXPIRY_ROLLOVER_DAYS) -> ROLLS TO NEXT MONTH
d_rem_6 = curr_month_exp - timedelta(days=6)
with patch.object(resolve, "get_ist_date", return_value=d_rem_6):
    res_stock_6 = resolve.resolve_option_strikes(mock_stock_inst.copy(), "RELIANCE", 3000.0, 20, "CE", n_range=0)
    check('Stock option with 6 days to expiry rolls to next month (RELIANCE26OCT3000CE)', res_stock_6[0]["tradingsymbol"] == "RELIANCE26OCT3000CE")

# 4 days remaining -> ROLLS TO NEXT MONTH
d_rem_4 = curr_month_exp - timedelta(days=4)
with patch.object(resolve, "get_ist_date", return_value=d_rem_4):
    res_stock_4 = resolve.resolve_option_strikes(mock_stock_inst.copy(), "RELIANCE", 3000.0, 20, "CE", n_range=0)
    check('Stock option with 4 days to expiry rolls to next month (RELIANCE26OCT3000CE)', res_stock_4[0]["tradingsymbol"] == "RELIANCE26OCT3000CE")


print(f'\n======================================================================')
print(f'TOTAL: {passed} passed, {failed} failed')
print(f'======================================================================')
assert failed == 0, f"{failed} unit test assertions failed!"
