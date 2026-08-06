import sys
import os
import json
import pandas as pd

sys.path.append('common')
sys.path.append('Trade_Option')
sys.path.append('Trade_Stock')

print("=" * 100)
print("             STARTING COMPREHENSIVE STRATEGY REGRESSION TEST SUITE")
print("=" * 100 + "\n")

errors = []

# Test 1: Module Imports
print("[TEST 1] Testing Core Module & Engine Imports...", end="", flush=True)
try:
    import trading_core
    import trade_db
    import index_options_trade_engine
    import stock_options_trade_engine
    import stock_bullish_reversal_scanner
    import stock_bearish_reversal_scanner
    import app_option_Trade
    import app_Sock_Trade
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Import Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 2: Kite Session Load
print("[TEST 2] Testing Kite Session Authentication...", end="", flush=True)
try:
    from trading_core import load_kite_session
    from kiteconnect import KiteConnect
    ak, at = load_kite_session()
    kite = KiteConnect(api_key=ak)
    kite.set_access_token(at)
    profile = kite.profile()
    print(f" PASSED [OK] (User: {profile.get('user_name', 'OK')})", flush=True)
except Exception as e:
    errors.append(f"Kite Auth Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 3: Bullish & Bearish Pattern Scanners (Option A Strict Invalidation)
print("[TEST 3] Testing Bullish & Bearish Scanners (Option A Strict Invalidation)...", end="", flush=True)
try:
    from trading_core import scan_anchor_bcd_breakout, scan_anchor_bcd_breakout_bearish, fetch_and_resample_candles
    token = 22471938 # BAJAJFINSV26AUG2100PE
    df_30 = fetch_and_resample_candles(kite, token, '2026-08-01', '2026-08-04', '30minute')
    res_bull = scan_anchor_bcd_breakout(df_30, df_30)
    res_bear = scan_anchor_bcd_breakout_bearish(df_30, df_30)
    print(f" PASSED [OK] (Bullish: {res_bull is not None}, Bearish: {res_bear is not None})", flush=True)
except Exception as e:
    errors.append(f"Scanner Test Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 4: Display Data Serializers (write_scan_display_data)
print("[TEST 4] Testing Display Data Serializers (write_scan_display_data)...", end="", flush=True)
try:
    from trading_core import write_scan_display_data
    test_trades = [{
        "symbol": "BAJAJFINSV",
        "contract": "BAJAJFINSV26AUG2100PE",
        "side": "PE",
        "entry_spot": 55.15,
        "current_sl": 47.48,
        "t1": 121.65,
        "t2": 172.00,
        "t3": 180.00,
        "rr": 8.67,
        "pattern": "BASE_ABCD",
        "entry_time": "2026-08-03 14:45:00",
        "candle_a_time": "2026-08-03 14:45:00"
    }]
    disp_path = os.path.join("Trade_Option", "output", "monitor", "scan_display_data.json")
    write_scan_display_data(test_trades, [], disp_path, engine_name="nifty50")
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Display Serializer Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 5: Dashboard Flask Endpoints (/api/get-chart-data)
print("[TEST 5] Testing Dashboard API Endpoint (/api/get-chart-data)...", end="", flush=True)
try:
    with app_option_Trade.app.test_client() as client:
        res1 = client.get('/api/get-chart-data?symbol=BAJAJFINSV26AUG2100PE&type=option&timeframe=30minute')
        res2 = client.get('/api/get-chart-data?symbol=BAJAJFINSV&type=spot&timeframe=30minute')
        assert res1.status_code == 200, f"Option chart status: {res1.status_code}"
        assert res2.status_code == 200, f"Spot chart status: {res2.status_code}"
        d1 = res1.get_json()
        d2 = res2.get_json()
        assert d1.get("ok") == True and len(d1.get("candles", [])) > 0, "No option candles returned"
        assert d2.get("ok") == True and len(d2.get("candles", [])) > 0, "No spot candles returned"
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Chart API Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 6: Database Operations & State
print("[TEST 6] Testing Trade Database (trade_db)...", end="", flush=True)
try:
    active_t = trade_db.get_active_trades()
    completed_t = trade_db.get_completed_trades()
    print(f" PASSED [OK] (Active: {len(active_t)}, Completed: {len(completed_t)})", flush=True)
except Exception as e:
    errors.append(f"Database Test Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

print("\n" + "=" * 100)
if not errors:
    print("      ALL 6 REGRESSION TESTS PASSED WITH 100% SUCCESS -- ZERO REGRESSIONS FOUND!")
else:
    print(f"      REGRESSION ERRORS FOUND ({len(errors)}):")
    for err in errors:
        print(f"        - {err}")
print("=" * 100)
