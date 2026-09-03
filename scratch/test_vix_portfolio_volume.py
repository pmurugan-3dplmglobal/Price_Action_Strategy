"""
scratch/test_vix_portfolio_volume.py — Unit & Integration Test for:
1. India VIX Regime Gate
2. Portfolio Risk & Sector Exposure Caps
3. A-B-C-D Volume Profile Analysis
"""

import os
import sys
import pandas as pd
import numpy as np
from datetime import datetime as dt, timedelta

COMMON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common"))
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

import paths
from vix_guard import evaluate_vix_regime, _VIX_CACHE
from portfolio_risk import check_portfolio_risk_caps
from registries import get_symbol_sector, SECTOR_MAP
from patterns_bull import scan_anchor_bcd_breakout
from patterns_bear import scan_anchor_bcd_breakout_bearish

print("=" * 80)
print("  RUNNING TESTS: VIX GATE, PORTFOLIO RISK CAPS & BCD VOLUME PROFILE")
print("=" * 80)

passed = 0
failed = 0

def test(name, condition, extra=""):
    global passed, failed
    if condition:
        print(f"  [PASS] {name} {extra}")
        passed += 1
    else:
        print(f"  [FAIL] {name} {extra}")
        failed += 1


# ──────────────────────────────────────────────
#  TEST 1: VIX REGIME GATE
# ──────────────────────────────────────────────
print("\n[TEST 1] Testing India VIX Regime Gate...")

# Test 1a: Normal VIX (15.0) -> All tiers allowed
with _VIX_CACHE["lock"]:
    _VIX_CACHE["value"] = 15.0
    _VIX_CACHE["last_fetched"] = 9999999999.0

ok_t1, reason_t1, _ = evaluate_vix_regime(None, tier_val=1)
ok_t2, reason_t2, _ = evaluate_vix_regime(None, tier_val=2)
ok_t3, reason_t3, _ = evaluate_vix_regime(None, tier_val=3)

test("Normal VIX (15.0) permits Tier 1 Gold", ok_t1)
test("Normal VIX (15.0) permits Tier 2 Core", ok_t2)
test("Normal VIX (15.0) permits Tier 3 Momentum", ok_t3)

# Test 1b: Elevated VIX (22.0) -> Only Tier 1 Gold allowed, T2/T3 blocked
with _VIX_CACHE["lock"]:
    _VIX_CACHE["value"] = 22.0
    _VIX_CACHE["last_fetched"] = 9999999999.0

ok_t1_hi, reason_t1_hi, _ = evaluate_vix_regime(None, tier_val=1)
ok_t2_hi, reason_t2_hi, _ = evaluate_vix_regime(None, tier_val=2)
ok_t3_hi, reason_t3_hi, _ = evaluate_vix_regime(None, tier_val=3)

test("Elevated VIX (22.0) permits Tier 1 Gold", ok_t1_hi)
test("Elevated VIX (22.0) suppresses Tier 2 Core", not ok_t2_hi and "HIGH_VIX" in reason_t2_hi)
test("Elevated VIX (22.0) suppresses Tier 3 Momentum", not ok_t3_hi and "HIGH_VIX" in reason_t3_hi)

# Test 1c: Extreme VIX (28.0) -> All entries blocked
with _VIX_CACHE["lock"]:
    _VIX_CACHE["value"] = 28.0
    _VIX_CACHE["last_fetched"] = 9999999999.0

ok_t1_ext, reason_t1_ext, _ = evaluate_vix_regime(None, tier_val=1)
ok_t2_ext, reason_t2_ext, _ = evaluate_vix_regime(None, tier_val=2)

test("Extreme VIX (28.0) blocks Tier 1 Gold", not ok_t1_ext and "EXTREME_VIX" in reason_t1_ext)
test("Extreme VIX (28.0) blocks Tier 2 Core", not ok_t2_ext and "EXTREME_VIX" in reason_t2_ext)

# Reset cache
with _VIX_CACHE["lock"]:
    _VIX_CACHE["value"] = None
    _VIX_CACHE["last_fetched"] = 0.0


# ──────────────────────────────────────────────
#  TEST 2: SECTOR RESOLVER & PORTFOLIO RISK CAPS
# ──────────────────────────────────────────────
print("\n[TEST 2] Testing Sector Resolver & Portfolio Risk Caps...")

test("HDFCBANK sector is BANKING_FINANCE", get_symbol_sector("HDFCBANK") == "BANKING_FINANCE")
test("TCS sector is IT", get_symbol_sector("TCS") == "IT")
test("TATAMOTORS sector is AUTO", get_symbol_sector("TATAMOTORS") == "AUTO")
test("RELIANCE sector is ENERGY_POWER", get_symbol_sector("RELIANCE") == "ENERGY_POWER")
test("TATASTEEL sector is METALS", get_symbol_sector("TATASTEEL") == "METALS")
test("SUNPHARMA sector is PHARMA_HEALTHCARE", get_symbol_sector("SUNPHARMA") == "PHARMA_HEALTHCARE")
test("NIFTY sector is INDICES", get_symbol_sector("NIFTY") == "INDICES")

# Test 2b: Portfolio Concurrent Position Limit Check
mock_positions_full = {
    "P1": {"symbol": "HDFCBANK", "contract": "HDFCBANK26SEP1600CE"},
    "P2": {"symbol": "TCS", "contract": "TCS26SEP4400CE"},
    "P3": {"symbol": "TATAMOTORS", "contract": "TATAMOTORS26SEP1100CE"},
    "P4": {"symbol": "RELIANCE", "contract": "RELIANCE26SEP3000CE"},
    "P5": {"symbol": "TATASTEEL", "contract": "TATASTEEL26SEP150CE"},
    "P6": {"symbol": "SUNPHARMA", "contract": "SUNPHARMA26SEP1800CE"},
}

ok_cap_pass, _, _ = check_portfolio_risk_caps("nifty50", "INFY", candidate_tier=2, capital=100000.0, live_positions={}, config={"portfolio_risk": {"enable": True, "max_concurrent_positions": 6, "max_daily_loss_pct": 3.0, "max_same_sector_positions": 2}}, include_db_trades=False)
ok_cap_fail, reason_cap, _ = check_portfolio_risk_caps("nifty50", "INFY", candidate_tier=2, capital=100000.0, live_positions=mock_positions_full, config={"portfolio_risk": {"enable": True, "max_concurrent_positions": 6, "max_daily_loss_pct": 3.0, "max_same_sector_positions": 2}}, include_db_trades=False)

test("Portfolio allows entry when positions < max_concurrent", ok_cap_pass)
test("Portfolio blocks entry when positions >= max_concurrent (6/6)", not ok_cap_fail and "MAX_CONCURRENT_POSITIONS" in reason_cap)

# Test 2c: Sector Exposure Cap Check
mock_banking_positions = {
    "P1": {"symbol": "HDFCBANK", "contract": "HDFCBANK26SEP1600CE"},
    "P2": {"symbol": "ICICIBANK", "contract": "ICICIBANK26SEP1200CE"},
}

ok_sec_pass, _, _ = check_portfolio_risk_caps("nifty50", "TCS", candidate_tier=2, capital=100000.0, live_positions=mock_banking_positions, config={"portfolio_risk": {"enable": True, "max_concurrent_positions": 6, "max_daily_loss_pct": 3.0, "max_same_sector_positions": 2}}, include_db_trades=False)
ok_sec_fail, reason_sec, _ = check_portfolio_risk_caps("nifty50", "AXISBANK", candidate_tier=2, capital=100000.0, live_positions=mock_banking_positions, config={"portfolio_risk": {"enable": True, "max_concurrent_positions": 6, "max_daily_loss_pct": 3.0, "max_same_sector_positions": 2}}, include_db_trades=False)

test("Sector cap allows non-banking stock (TCS in IT)", ok_sec_pass)
test("Sector cap blocks 3rd banking stock (AXISBANK in BANKING_FINANCE)", not ok_sec_fail and "MAX_SECTOR_POSITIONS" in reason_sec)


# ──────────────────────────────────────────────
#  TEST 3: A-B-C-D VOLUME PROFILE ANALYSIS
# ──────────────────────────────────────────────
print("\n[TEST 3] Testing A-B-C-D Volume Profile Analysis...")

# Create synthetic OHLCV candle sequence with Engulfing + BCD pattern & volume
dates = pd.date_range(end=dt.now(), periods=40, freq="30min")
df_test = pd.DataFrame({
    "date": dates,
    "open": [100.0] * 40,
    "high": [102.0] * 40,
    "low": [98.0] * 40,
    "close": [100.0] * 40,
    "volume": [10000] * 40
})

# Setup Anchor A at idx 15 (Bullish Engulfing)
# Prior bar (idx 14) is red
df_test.loc[14, "open"] = 100.0
df_test.loc[14, "close"] = 96.0
df_test.loc[14, "high"] = 100.5
df_test.loc[14, "low"] = 95.5

# Anchor A (idx 15) is green engulfing
df_test.loc[15, "open"] = 95.0
df_test.loc[15, "close"] = 102.0
df_test.loc[15, "high"] = 103.0  # Benchmark = 103.0
df_test.loc[15, "low"] = 94.0   # A_low = 94.0
df_test.loc[15, "volume"] = 15000

# Point B at idx 18 (Breakout with volume expansion)
df_test.loc[18, "open"] = 102.0
df_test.loc[18, "close"] = 105.0
df_test.loc[18, "high"] = 106.0
df_test.loc[18, "low"] = 101.5
df_test.loc[18, "volume"] = 25000  # High breakout volume

# Point C at idx 20 (Retest with volume dry-up)
df_test.loc[20, "open"] = 104.0
df_test.loc[20, "close"] = 102.5  # red candle dipping towards benchmark 103.0
df_test.loc[20, "high"] = 104.5
df_test.loc[20, "low"] = 102.0
df_test.loc[20, "volume"] = 8000   # Low dry-up volume (8000 < 25000)

# Point D at idx 22 (Trigger candle with volume expansion)
df_test.loc[22, "open"] = 102.5
df_test.loc[22, "close"] = 107.0  # close > benchmark 103.0
df_test.loc[22, "high"] = 108.0
df_test.loc[22, "low"] = 102.0
df_test.loc[22, "volume"] = 28000  # High trigger volume

# Historical targets above
df_anchor = df_test.copy()
df_anchor.loc[5, "high"] = 120.0
df_anchor.loc[5, "close"] = 119.0

res_bull = scan_anchor_bcd_breakout(df_test, df_anchor, anchor_tf="30minute", entry_tf="30minute", enable_swing_filter=False)

test("Bullish BCD scanner detected pattern", res_bull is not None)
if res_bull:
    test("Volume B ratio present in result", "vol_b_ratio" in res_bull and res_bull["vol_b_ratio"] > 0)
    test("Volume C ratio present in result", "vol_c_ratio" in res_bull)
    test("Volume D ratio present in result", "vol_d_ratio" in res_bull and res_bull["vol_d_ratio"] > 0)
    test("Volume confirmed flag is True", res_bull.get("vol_confirmed") is True)
    test("Volume score computed (>=3)", res_bull.get("vol_score", 0) >= 3, f"(Score: {res_bull.get('vol_score')})")

# ──────────────────────────────────────────────
#  TEST 4: EMA ENGINE MONTHLY OPTION EXPIRY ROLLOVER
# ──────────────────────────────────────────────
print("\n[TEST 4] Testing EMA Engine Option Expiry Rollover...")
from ema_engine import _get_monthly_expiry_month_str, get_option_contract_symbol
import datetime

# Mid-month date (e.g. 10th Jan 2026) -> Should select JAN
mid_month = datetime.datetime(2026, 1, 10)
yr, mo = _get_monthly_expiry_month_str(mid_month)
test("EMA selects current month when > 6 days to expiry (Jan 10 -> JAN)", mo == "JAN")

# Expiry week date (e.g. 26th Jan 2026, Thursday is Jan 29 -> 3 days remaining) -> Should roll to FEB
expiry_week = datetime.datetime(2026, 1, 26)
yr_exp, mo_exp = _get_monthly_expiry_month_str(expiry_week)
test("EMA rolls to next month when <= 6 days to expiry (Jan 26 -> FEB)", mo_exp == "FEB")

sym_contract = get_option_contract_symbol("RELIANCE", 2800, side="CE")
test("EMA builds valid option tradingsymbol format", "RELIANCE" in sym_contract and "CE" in sym_contract and "2800" in sym_contract)


# ──────────────────────────────────────────────
#  TEST 5: STANDARDIZED IST IN is_live_candle_near_close
# ──────────────────────────────────────────────
print("\n[TEST 5] Testing IST in is_live_candle_near_close()...")
from timeframe_utils import is_live_candle_near_close, get_ist_now

now_ist = get_ist_now().replace(tzinfo=None)
# Active 15m candle started 13 mins ago (86% complete) -> Should return True
candle_86pct = (now_ist - timedelta(minutes=13)).strftime("%Y-%m-%d %H:%M:%S")
test("is_live_candle_near_close detects >= 80% completion in IST", is_live_candle_near_close(candle_86pct, "15minute", completion_pct=0.80) is True)

# Active 15m candle started 5 mins ago (33% complete) -> Should return False
candle_33pct = (now_ist - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
test("is_live_candle_near_close ignores < 80% completion", is_live_candle_near_close(candle_33pct, "15minute", completion_pct=0.80) is False)


# ──────────────────────────────────────────────
#  TEST 6: OPTION-AWARE POSITION SIZING
# ──────────────────────────────────────────────
print("\n[TEST 6] Testing Option-Aware Position Sizing...")
from targets import calculate_position_size

# Cash equity sizing: 100k capital, 1% risk (Rs 1,000 max risk), Rs 50 risk per share -> 20 shares
cash_size = calculate_position_size(spot_price=2800, stop_loss=2750, capital=100000.0, risk_percent=1.0, is_option=False)
test("Cash equity position sizing allocates correct share count (20 shares)", cash_size == 20)

# Option sizing: Rs 100 entry, Rs 90 SL (Rs 10 risk per share), lot size 500
# Risk per lot = Rs 10 * 500 = Rs 5,000. Max risk = Rs 1,000 -> 1 lot
opt_size = calculate_position_size(spot_price=100, stop_loss=90, capital=100000.0, risk_percent=1.0, lot_size=500, is_option=True)
test("Option position sizing respects lot size and risk per lot (1 lot)", opt_size == 1)

# Option capital allocation ceiling: 25% max capital cap
# Entry = Rs 100, Lot size = 500 -> 1 lot cost = Rs 50,000 (50% of 100k account).
# 25% cap of 100k = Rs 25,000 -> max_lots_capital = 1 (minimum 1 lot allowed)
opt_cap_size = calculate_position_size(spot_price=100, stop_loss=99, capital=100000.0, risk_percent=10.0, lot_size=500, is_option=True)
test("Option position sizing enforces capital ceiling guard", opt_cap_size <= 2)


# ──────────────────────────────────────────────
#  TEST 7: HARAMI BODY SIZE RATIO FILTER (<= 65%)
# ──────────────────────────────────────────────
print("\n[TEST 7] Testing Harami Body Size Ratio Filter...")
from patterns_bull import find_anchor_bullish_harami
from patterns_bear import find_anchor_bearish_harami

# Valid Bullish Harami: Mother Body = 10 pts (open 100, close 90), Inside Body = 4 pts (open 92, close 96)
# Ratio = 4 / 10 = 40% <= 65% -> Match
df_harami_valid = pd.DataFrame([
    {"open": 100.0, "high": 101.0, "low": 89.0, "close": 90.0, "date": "2026-09-01 09:15:00"},
    {"open": 92.0, "high": 97.0, "low": 91.0, "close": 96.0, "date": "2026-09-01 09:45:00"}
])
res_h_valid = find_anchor_bullish_harami(df_harami_valid)
test("Bullish Harami with <= 65% body ratio is accepted", res_h_valid is not None and res_h_valid.get("Pattern") == "BULL_A_Harami")

# Invalid Tweezer/Giant Inside Bar: Mother Body = 10 pts (open 100, close 90), Inside Body = 8 pts (open 91, close 99)
# Ratio = 8 / 10 = 80% > 65% -> Rejected
df_harami_invalid = pd.DataFrame([
    {"open": 100.0, "high": 101.0, "low": 89.0, "close": 90.0, "date": "2026-09-01 09:15:00"},
    {"open": 91.0, "high": 99.5, "low": 90.5, "close": 99.0, "date": "2026-09-01 09:45:00"}
])
res_h_invalid = find_anchor_bullish_harami(df_harami_invalid)
test("Bullish Harami with > 65% body ratio (tweezer/railway) is rejected", res_h_invalid is None)


# ──────────────────────────────────────────────
#  TEST 8: BEAR SCANNER MULTI-TIMEFRAME DATE NORMALIZATION
# ──────────────────────────────────────────────
print("\n[TEST 8] Testing Bearish Scanner Multi-Timeframe Date Mapping...")

# Create daily anchor dataframe with 10 daily candles ending with timestamp "2026-09-01 00:00:00"
dates_a = pd.date_range("2026-08-20", periods=10, freq="D")
df_bear_anchor = pd.DataFrame({
    "date": [d.strftime("%Y-%m-%d 00:00:00") for d in dates_a],
    "open": [100.0] * 10,
    "high": [102.0] * 10,
    "low": [98.0] * 10,
    "close": [101.0] * 10,
    "volume": [10000] * 10
})
df_bear_anchor.loc[8, "open"] = 100.0
df_bear_anchor.loc[8, "high"] = 105.0
df_bear_anchor.loc[8, "low"] = 98.0
df_bear_anchor.loc[8, "close"] = 104.0
df_bear_anchor.loc[9, "open"] = 104.0
df_bear_anchor.loc[9, "high"] = 106.0
df_bear_anchor.loc[9, "low"] = 95.0
df_bear_anchor.loc[9, "close"] = 96.0
df_bear_anchor.loc[9, "date"] = "2026-09-01 00:00:00"

# Create intraday entry dataframe with ISO timestamp "2026-09-01 09:15:00+05:30"
dates_intra = pd.date_range("2026-09-01 09:15", periods=20, freq="15min")
df_bear_entry = pd.DataFrame({
    "date": [d.strftime("%Y-%m-%d %H:%M:%S+05:30") for d in dates_intra],
    "open": [96.0] * 20,
    "high": [97.0] * 20,
    "low": [95.5] * 20,
    "close": [96.0] * 20,
    "volume": [10000] * 20
})
# Point B: Breakdown below 95.0 at idx 5
df_bear_entry.loc[5, "open"] = 95.5
df_bear_entry.loc[5, "close"] = 92.0
df_bear_entry.loc[5, "low"] = 91.5
df_bear_entry.loc[5, "high"] = 95.5
df_bear_entry.loc[5, "volume"] = 25000

# Retest low candles before C
df_bear_entry.loc[6, "open"] = 92.0
df_bear_entry.loc[6, "close"] = 93.0
df_bear_entry.loc[6, "low"] = 91.8
df_bear_entry.loc[6, "high"] = 93.5

# Point C: Retest touching/exceeding benchmark 95.0 at idx 8
df_bear_entry.loc[8, "open"] = 93.0
df_bear_entry.loc[8, "close"] = 96.0
df_bear_entry.loc[8, "low"] = 93.0
df_bear_entry.loc[8, "high"] = 96.5
df_bear_entry.loc[8, "volume"] = 7000

# Point D: Breakdown trigger at idx 11
df_bear_entry.loc[11, "open"] = 95.5
df_bear_entry.loc[11, "close"] = 91.0
df_bear_entry.loc[11, "low"] = 90.5
df_bear_entry.loc[11, "high"] = 95.5
df_bear_entry.loc[11, "volume"] = 30000

# Following candles stay around 91.0 without hitting T1 or SL
for i in range(12, 20):
    df_bear_entry.loc[i, "open"] = 91.0
    df_bear_entry.loc[i, "close"] = 91.0
    df_bear_entry.loc[i, "high"] = 91.5
    df_bear_entry.loc[i, "low"] = 90.5

res_bear_norm = scan_anchor_bcd_breakout_bearish(df_bear_entry, df_bear_anchor, anchor_tf="day", entry_tf="15minute", enable_swing_filter=False)
test("Bearish scanner successfully maps daily anchor date to intraday entry candles", res_bear_norm is not None)
if res_bear_norm:
    test("Bearish scanner output direction is BEAR", res_bear_norm.get("Direction") == "BEAR")
    test("Bearish scanner calculates valid RR (>= 1.5)", res_bear_norm.get("RR", 0) >= 1.5)


# ──────────────────────────────────────────────
#  TEST 9: CASH EQUITY CAPITAL CEILING ON TIGHT SL
# ──────────────────────────────────────────────
print("\n[TEST 9] Testing Cash Equity Capital Ceiling on Micro SL...")
# Spot = Rs 2500, SL = Rs 2499.90 (0.10 pt risk), Capital = Rs 100,000, 1% risk (Rs 1,000 max risk)
# Without cap: 1000 / 0.10 = 10,000 shares (Rs 2.5 Crore exposure)
# With cap: 100,000 / 2500 = 40 shares (Rs 100,000 exposure)
tight_sl_size = calculate_position_size(spot_price=2500, stop_loss=2499.90, capital=100000.0, risk_percent=1.0, is_option=False)
test("Cash equity sizing caps at account capital (40 shares, not 10,000)", tight_sl_size == 40)

# ──────────────────────────────────────────────
#  TEST 10: VIX GUARD CONFIGURABLE FAIL-OPEN POLICY
# ──────────────────────────────────────────────
print("\n[TEST 10] Testing VIX Guard Configurable fail_open Policy...")
# When vix is None and fail_open=True (default): permitted
vix_ok_default, _, _ = evaluate_vix_regime(kite=None, vix_value=None, config={"fail_open": True})
test("VIX guard permits when data unavailable and fail_open=True", vix_ok_default is True)

# When vix is None and fail_open=False: blocked
vix_ok_strict, _, _ = evaluate_vix_regime(kite=None, vix_value=None, config={"fail_open": False})
test("VIX guard blocks when data unavailable and fail_open=False", vix_ok_strict is False)

# ──────────────────────────────────────────────
#  TEST 11: PORTFOLIO RISK REALIZED + UNREALIZED LOSS
# ──────────────────────────────────────────────
print("\n[TEST 11] Testing Portfolio Risk Realized + Unrealized Drawdown...")
# Verify check_portfolio_risk_caps returns total_pnl including unrealized
p_ok_dd, p_msg_dd, p_details_dd = check_portfolio_risk_caps(
    engine="nifty50",
    symbol="INFY",
    capital=100000.0,
    include_db_trades=False
)
test("Portfolio risk details include unrealized PnL key", "today_unrealized_pnl_inr" in p_details_dd)
test("Portfolio risk details include total PnL key", "today_total_pnl_inr" in p_details_dd)


print("\n" + "=" * 80)
print(f"  FINAL TEST SUMMARY: {passed} PASSED, {failed} FAILED")
print("=" * 80)

if failed > 0:
    sys.exit(1)
else:
    sys.exit(0)

