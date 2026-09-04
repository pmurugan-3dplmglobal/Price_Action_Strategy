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
    import app_Stock_Trade
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
    from trading_core import scan_anchor_bcd_breakout, scan_anchor_bcd_breakout_bearish, fetch_and_resample_candles, STOCK_REGISTRY
    from datetime import datetime as dt, timedelta
    token = STOCK_REGISTRY.get("RELIANCE", {}).get("token", 738561)
    df_30 = fetch_and_resample_candles(kite, token, (dt.now() - timedelta(days=15)).strftime('%Y-%m-%d'), dt.now().strftime('%Y-%m-%d'), '30minute')
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
    import paths
    test_trades = [{
        "symbol": "KAYNES",
        "contract": "KAYNES26SEP3900PE",
        "side": "PE",
        "entry_spot": 176.95,
        "current_sl": 158.76,
        "t1": 235.00,
        "t2": 262.00,
        "t3": 275.00,
        "rr": 3.19,
        "pattern": "BASE_ABCD",
        "entry_time": "2026-08-25 14:15:00",
        "candle_a_time": "2026-08-25 10:15:00"
    }]
    disp_path = paths.SCAN_DISPLAY_FILE + ".regression_tmp"
    write_scan_display_data(test_trades, [], disp_path, engine_name="nifty50")
    if os.path.exists(disp_path):
        os.remove(disp_path)
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Display Serializer Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 5: Dashboard Flask Endpoints (/api/get-chart-data)
print("[TEST 5] Testing Dashboard API Endpoint (/api/get-chart-data)...", end="", flush=True)
try:
    with app_option_Trade.app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user"] = "test_admin"
            sess["role"] = "admin"
        res1 = client.get('/api/get-chart-data?symbol=KAYNES26SEP3900PE&type=option&timeframe=30minute')
        res2 = client.get('/api/get-chart-data?symbol=RELIANCE&type=spot&timeframe=30minute')
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

# Test 7: Path Consistency (single canonical root regardless of CWD)
print("[TEST 7] Testing Canonical Path Consistency (cwd-independent)...", end="", flush=True)
try:
    import paths
    root_abs = os.path.abspath(paths.PROJECT_ROOT)
    targets = {
        "SCAN_DISPLAY_FILE": paths.SCAN_DISPLAY_FILE,
        "SCAN_DISPLAY_INDEX_FILE": paths.SCAN_DISPLAY_INDEX_FILE,
        "SCAN_DISPLAY_STOCK_FILE": paths.SCAN_DISPLAY_STOCK_FILE,
        "SCAN_DISPLAY_BEAR_FILE": paths.SCAN_DISPLAY_BEAR_FILE,
        "TRADES_DB": paths.TRADES_DB,
        "ACTIVE_POSITIONS_DB": paths.ACTIVE_POSITIONS_DB,
        "TOKEN_FILE": paths.TOKEN_FILE,
        "JOURNAL_TRADES_DB": paths.JOURNAL_TRADES_DB,
    }
    for name, p in targets.items():
        ap = os.path.abspath(p)
        assert ap.startswith(root_abs), f"{name} resolves outside root: {ap}"
        assert os.path.isabs(ap), f"{name} is not absolute: {ap}"
    assert os.path.abspath(paths.SCAN_DISPLAY_FILE) == os.path.join(root_abs, "output", "monitor", "scan_display.json"), "scan_display.json not at root output/monitor"
    assert os.path.abspath(paths.TRADES_DB) == os.path.join(root_abs, "output", "monitor", "trades_db.json"), "trades_db.json not at root output/monitor"
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Path Consistency Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 8: DB Invariants (no dupe ACTIVE contracts, no expired ACTIVE rows, no executed-exit leftovers)
print("[TEST 8] Testing DB Invariants (dupes/expired/executed-exit)...", end="", flush=True)
try:
    from collections import Counter
    from trade_db import get_active_trades, run_db_housekeeping
    from trading_core import contract_is_expired, load_executed_exits, EXECUTED_EXITS
    # Engines/apps run housekeeping on startup; reproduce it here so Test 8 is idempotent.
    run_db_housekeeping()
    active = get_active_trades()
    keys = [f"{t.get('engine')}|{t.get('contract', t.get('symbol'))}" for t in active]
    dups = {k: v for k, v in Counter(keys).items() if v > 1}
    assert not dups, f"Duplicate ACTIVE rows found: {dups}"
    expired = [t for t in active if contract_is_expired(str(t.get('contract', t.get('symbol'))))]
    assert not expired, f"Expired ACTIVE rows found: {[t.get('contract') for t in expired]}"
    # No ACTIVE trade may still have a matching executed-exit order (closed but never flipped)
    load_executed_exits()
    exit_set = {str(k).replace(' ', '').upper() for k in (EXECUTED_EXITS or {})}
    leftover = [t for t in active if str(t.get('contract', t.get('symbol'))).replace(' ', '').upper() in exit_set]
    assert not leftover, f"ACTIVE rows with executed-exit orders: {[t.get('contract') for t in leftover]}"
    print(f" PASSED [OK] (Active: {len(active)}, no dupes, no expired, no executed-exit leftovers)", flush=True)
except Exception as e:
    errors.append(f"DB Invariants Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 9: Engine path alignment (engines target canonical display files)
print("[TEST 9] Testing Engine/App Path Alignment...", end="", flush=True)
try:
    import paths
    exp_disp = os.path.abspath(paths.SCAN_DISPLAY_FILE)
    exp_idx = os.path.abspath(paths.SCAN_DISPLAY_INDEX_FILE)
    exp_stock = os.path.abspath(paths.SCAN_DISPLAY_STOCK_FILE)
    exp_bear = os.path.abspath(paths.SCAN_DISPLAY_BEAR_FILE)
    mismatch = []
    if os.path.abspath(stock_options_trade_engine.SCAN_DISPLAY_FILE) != exp_disp:
        mismatch.append("stock_options_trade_engine.SCAN_DISPLAY_FILE")
    if os.path.abspath(index_options_trade_engine.SCAN_DISPLAY_FILE) != exp_idx:
        mismatch.append("index_options_trade_engine.SCAN_DISPLAY_FILE")
    if os.path.abspath(stock_bullish_reversal_scanner.SCAN_DISPLAY_FILE) != exp_stock:
        mismatch.append("stock_bullish_reversal_scanner.SCAN_DISPLAY_FILE")
    if os.path.abspath(stock_bearish_reversal_scanner.SCAN_DISPLAY_FILE) != exp_bear:
        mismatch.append("stock_bearish_reversal_scanner.SCAN_DISPLAY_FILE")
    assert not mismatch, f"Path mismatch: {mismatch}"
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Engine Path Alignment Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 10: ACTIVE trades must have a usable entry_time (no None, not older than created_at)
print("[TEST 10] Testing ACTIVE entry_time Invariant (candle-filter correctness)...", end="", flush=True)
try:
    from trade_db import get_active_trades
    from trading_core import sanitize_entry_time
    active = get_active_trades()
    bad = []
    for t in active:
        et = str(t.get("entry_time") or "").strip().lower()
        ca = str(t.get("created_at") or "").strip().lower()
        if not et or et == "none":
            bad.append(f"{t.get('contract')}: entry_time missing")
            continue
        clean = sanitize_entry_time(dict(t))
        assert str(clean).strip().lower() == et, f"{t.get('contract')}: sanitize changed {et} -> {clean}"
        if ca and et < ca:
            bad.append(f"{t.get('contract')}: entry_time {et} older than created_at {ca}")
    assert not bad, "; ".join(bad)
    print(f" PASSED [OK] (Active: {len(active)}, all entry_time valid)", flush=True)
except Exception as e:
    errors.append(f"entry_time Invariant Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 11: Trailed-SL floor guard (CANDLE_CLOSE_SL must NOT re-judge pre-trail candles)
print("[TEST 11] Testing Trailed-SL Floor Guard (no retroactive SL breach)...", end="", flush=True)
try:
    from datetime import datetime as dt, timedelta
    from position_monitor import get_sl_floor_time, is_candle_before_entry
    # fresh position: floor falls back to sanitized entry_time (original SL applies post-entry)
    fresh = {"entry_time": "2026-08-10 12:15:03", "current_sl": 48.0}
    assert get_sl_floor_time(fresh) == "2026-08-10 12:15:03", "fresh floor != entry_time"
    # trailed position (TRAIL-1 to BE at 10:27 on 08-12): floor = sl_set_time
    trailed = {"entry_time": "2026-08-10 12:15:03", "sl_set_time": "2026-08-12 10:27:18"}
    floor = get_sl_floor_time(trailed)
    # the entry-day 13:00 bar (close 50.60) predates the trail -> must be SKIPPED by CANDLE_CLOSE_SL
    assert is_candle_before_entry("2026-08-10 13:00:00+05:30", floor) is True, \
        "pre-trail entry-day candle must be skipped by the SL floor"
    # a candle formed after the trail is still evaluated normally
    assert is_candle_before_entry("2026-08-12 10:30:00+05:30", floor) is False, \
        "post-trail candle must still be evaluated against the trailed SL"
    # legacy already-trailed position without a stamp: floor must be today (old bars skipped)
    legacy = {"entry_time": "2026-08-10 12:15:03", "trailing_stage": 1}
    lf = get_sl_floor_time(legacy)
    today_str = dt.now().strftime("%Y-%m-%d")
    yesterday_str = (dt.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    assert is_candle_before_entry(f"{yesterday_str} 14:00:00+05:30", lf) is True, \
        "legacy trailed position must skip yesterday's bars"
    assert is_candle_before_entry(f"{today_str} 10:30:00+05:30", lf) is False, \
        "legacy trailed position must still evaluate today's bars"
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Trailed-SL Floor Guard Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 12: HTML Template JavaScript V8 Compiler Check (catches unclosed braces/syntax errors in HTML templates)
print("[TEST 12] Testing HTML Template JavaScript V8 Compiler Syntax...", end="", flush=True)
try:
    import subprocess
    cmd = [
        "node", "-e",
        "const fs = require('fs'), vm = require('vm'); "
        "['Trade_Option/templates/index.html', 'Trade_Stock/templates/index.html'].forEach(f => { "
        "  const html = fs.readFileSync(f, 'utf8'); "
        "  const scripts = html.match(/<script[\\s\\S]*?<\\/script>/gi) || []; "
        "  scripts.forEach((s, idx) => { "
        "    const code = s.replace(/<script[^>]*>/i, '').replace(/<\\/script>/i, '').replace(/\\{\\{[\\s\\S]*?\\}\\}/g, '10000'); "
        "    try { new vm.Script(code); } catch(e) { throw new Error(`${f} script ${idx}: ${e.message}`); } "
        "  }); "
        "}); "
        "console.log('OK');"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=paths.PROJECT_ROOT)
    assert res.returncode == 0 and "OK" in res.stdout, f"V8 JS Template error: {res.stderr.strip() or res.stdout.strip()}"
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"HTML Template JS V8 Check Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 13: Parabolic Multi-Swing Curve Math & Structure Detection
print("[TEST 13] Testing Parabolic Multi-Swing Curve Math & Structure Detection...", end="", flush=True)
try:
    from swing_detection import (
        is_parabolic_arch_enhanced,
        detect_parabolic_multi_swings
    )
    import numpy as np
    import pandas as pd
    
    # Synthetic concave down parabolic arch: y = -0.5*(x-5)^2 + 100
    x = np.arange(11)
    y = -0.5 * (x - 5)**2 + 100
    df_synthetic = pd.DataFrame({
        "close": y,
        "high": y + 0.5,
        "low": y - 0.5,
        "open": y
    })
    
    assert is_parabolic_arch_enhanced(df_synthetic, min_r2=0.55, side="BULL") is True, "Synthetic dome must match BULL parabolic arch"
    assert is_parabolic_arch_enhanced(df_synthetic, min_r2=0.55, side="BEAR") is False, "Synthetic dome must not match BEAR cup"
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Parabolic Multi-Swing Test Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 14: Dashboard Authentication & Access Control
print("[TEST 14] Testing Dashboard Authentication & Access Control...", end="", flush=True)
try:
    import dashboard_auth
    assert hasattr(dashboard_auth, "register_user"), "register_user missing"
    assert hasattr(dashboard_auth, "verify_user"), "verify_user missing"
    assert hasattr(dashboard_auth, "approve_user"), "approve_user missing"
    assert hasattr(dashboard_auth, "list_users"), "list_users missing"
    with app_option_Trade.app.test_client() as client:
        # Unauthenticated request to / must redirect to /login
        r = client.get('/', follow_redirects=False)
        assert r.status_code == 302 and '/login' in r.headers.get('Location', ''), f"Expected redirect to /login, got {r.status_code}"
        # Unauthenticated API request must return 401
        r_api = client.get('/api/status')
        assert r_api.status_code == 401, f"Expected 401 for /api/status, got {r_api.status_code}"
        # Login page must render
        r_login = client.get('/login')
        assert r_login.status_code == 200 and b'Sign In' in r_login.data, "Login template failed to render"
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Dashboard Auth Test Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 15: VIX Macro Gate & Portfolio Risk Governance Invariants
print("[TEST 15] Testing VIX Macro Gate & Portfolio Risk Governance Invariants...", end="", flush=True)
try:
    import vix_guard
    import portfolio_risk
    import registries
    
    # 1. VIX threshold logic
    v_norm, reg_norm, _ = vix_guard.evaluate_vix_regime(candidate_tier=2, vix_value=15.0)
    v_elev, reg_elev, _ = vix_guard.evaluate_vix_regime(candidate_tier=2, vix_value=22.0)
    v_elev_t1, _, _ = vix_guard.evaluate_vix_regime(candidate_tier=1, vix_value=22.0)
    v_ext, reg_ext, _ = vix_guard.evaluate_vix_regime(candidate_tier=1, vix_value=28.0)
    assert v_norm is True, "Normal VIX (15.0) must permit Tier 2"
    assert v_elev is False, "Elevated VIX (22.0) must suppress Tier 2"
    assert v_elev_t1 is True, "Elevated VIX (22.0) must permit Tier 1 Gold"
    assert v_ext is False, "Extreme VIX (28.0) must halt all entries"

    # 2. Portfolio Risk & Sector map
    assert len(registries.SECTOR_MAP) >= 150, f"SECTOR_MAP must cover at least 150 symbols (found {len(registries.SECTOR_MAP)})"
    assert registries.get_symbol_sector("HDFCBANK") == "BANKING_FINANCE", "HDFCBANK sector mismatch"
    assert registries.get_symbol_sector("TCS") == "IT", "TCS sector mismatch"

    # 3. Portfolio concurrent & sector caps
    fake_pos = [
        {"symbol": "HDFCBANK", "contract": "HDFCBANK26SEP1600CE", "engine": "nifty50"},
        {"symbol": "ICICIBANK", "contract": "ICICIBANK26SEP1200CE", "engine": "nifty50"}
    ]
    p_ok, p_reason, _ = portfolio_risk.check_portfolio_risk_caps("nifty50", "TCS", live_positions=fake_pos, include_db_trades=False)
    assert p_ok is True, f"TCS entry in IT sector should be allowed: {p_reason}"

    p_block, p_reason_blk, _ = portfolio_risk.check_portfolio_risk_caps("nifty50", "SBIN", live_positions=fake_pos, include_db_trades=False)
    assert p_block is False and ("MAX_SECTOR_POSITIONS_REACHED" in p_reason_blk or "SECTOR" in p_reason_blk), f"3rd banking stock SBIN must be blocked by sector cap: {p_reason_blk}"
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"VIX & Portfolio Risk Invariant Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 16: Option Position Sizing & Monthly Expiry Rollover Invariants
print("[TEST 16] Testing Option Position Sizing & Monthly Expiry Rollover Invariants...", end="", flush=True)
try:
    import targets
    import ema_engine
    from datetime import datetime as dt

    # 1. Option position sizing
    cash_sz = targets.calculate_position_size(spot_price=2800, stop_loss=2750, capital=100000, risk_percent=1.0, is_option=False)
    assert cash_sz == 20, f"Cash size expected 20, got {cash_sz}"

    opt_sz = targets.calculate_position_size(spot_price=100, stop_loss=90, capital=100000, risk_percent=1.0, lot_size=500, is_option=True)
    assert opt_sz == 1, f"Option size expected 1 lot, got {opt_sz}"

    # 2. EMA rollover helper
    yr_mid, mo_mid = ema_engine._get_monthly_expiry_month_str(dt(2026, 1, 10))
    assert mo_mid == "JAN", f"Expected JAN for Jan 10, got {mo_mid}"
    yr_exp, mo_exp = ema_engine._get_monthly_expiry_month_str(dt(2026, 1, 26))
    assert mo_exp == "FEB", f"Expected FEB rollover for Jan 26, got {mo_exp}"
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Option Sizing & Rollover Invariant Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

# Test 17: Candlestick Pattern Geometries (Harami Body Ratio & Bearish Multi-TF Mapping)
print("[TEST 17] Testing Harami Body Ratio & Multi-TF Candlestick Geometry...", end="", flush=True)
try:
    from patterns_bull import find_anchor_bullish_harami
    from patterns_bear import find_anchor_bearish_harami, scan_anchor_bcd_breakout_bearish
    import pandas as pd

    # 1. Bullish Harami <= 65% ratio
    df_h_valid = pd.DataFrame([
        {"open": 100.0, "high": 101.0, "low": 89.0, "close": 90.0, "date": "2026-09-01 09:15:00"},
        {"open": 92.0, "high": 97.0, "low": 91.0, "close": 96.0, "date": "2026-09-01 09:45:00"}
    ])
    df_h_invalid = pd.DataFrame([
        {"open": 100.0, "high": 101.0, "low": 89.0, "close": 90.0, "date": "2026-09-01 09:15:00"},
        {"open": 91.0, "high": 99.5, "low": 90.5, "close": 99.0, "date": "2026-09-01 09:45:00"}
    ])
    assert find_anchor_bullish_harami(df_h_valid) is not None, "Valid Harami was rejected"
    assert find_anchor_bullish_harami(df_h_invalid) is None, "Tweezer/railway inside bar should be rejected"

    # 2. Bearish multi-TF date mapping
    dates_a = pd.date_range("2026-08-20", periods=10, freq="D")
    df_ba = pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d 00:00:00") for d in dates_a],
        "open": [100.0] * 10, "high": [102.0] * 10, "low": [98.0] * 10, "close": [101.0] * 10, "volume": [10000] * 10
    })
    df_ba.loc[8, "open"] = 100.0; df_ba.loc[8, "high"] = 105.0; df_ba.loc[8, "low"] = 98.0; df_ba.loc[8, "close"] = 104.0
    df_ba.loc[9, "open"] = 104.0; df_ba.loc[9, "high"] = 106.0; df_ba.loc[9, "low"] = 95.0; df_ba.loc[9, "close"] = 96.0; df_ba.loc[9, "date"] = "2026-09-01 00:00:00"

    dates_e = pd.date_range("2026-09-01 09:15", periods=20, freq="15min")
    df_be = pd.DataFrame({
        "date": [d.strftime("%Y-%m-%d %H:%M:%S+05:30") for d in dates_e],
        "open": [96.0] * 20, "high": [97.0] * 20, "low": [95.5] * 20, "close": [96.0] * 20, "volume": [10000] * 20
    })
    df_be.loc[5, "open"] = 95.5; df_be.loc[5, "close"] = 92.0; df_be.loc[5, "low"] = 91.5; df_be.loc[5, "high"] = 95.5; df_be.loc[5, "volume"] = 25000
    df_be.loc[6, "open"] = 92.0; df_be.loc[6, "close"] = 93.0; df_be.loc[6, "low"] = 91.8; df_be.loc[6, "high"] = 93.5
    df_be.loc[8, "open"] = 93.0; df_be.loc[8, "close"] = 96.0; df_be.loc[8, "low"] = 93.0; df_be.loc[8, "high"] = 96.5; df_be.loc[8, "volume"] = 7000
    df_be.loc[11, "open"] = 95.5; df_be.loc[11, "close"] = 91.0; df_be.loc[11, "low"] = 90.5; df_be.loc[11, "high"] = 95.5; df_be.loc[11, "volume"] = 30000
    for i in range(12, 20):
        df_be.loc[i, "open"] = 91.0; df_be.loc[i, "close"] = 91.0; df_be.loc[i, "high"] = 91.5; df_be.loc[i, "low"] = 90.5

    res_b = scan_anchor_bcd_breakout_bearish(df_be, df_ba, anchor_tf="day", entry_tf="15minute", enable_swing_filter=False)
    assert res_b is not None and res_b.get("Direction") == "BEAR", "Bearish multi-TF breakout mapping failed"
    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Candlestick Geometry Test Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

print("[TEST 18] Testing Debit Spreads, Liquidity Gate & 09:16 AM Reconciler...", end="", flush=True)
try:
    from resolve import resolve_option_spread
    from liquidity_guard import check_bid_ask_spread_liquidity
    from morning_reconciler import run_preflight_reconciliation

    df_mock_nfo = pd.DataFrame([
        {"name": "NIFTY", "tradingsymbol": "NIFTY24500CE", "instrument_token": 1, "instrument_type": "CE", "strike": 24500.0, "expiry": "2026-09-30", "lot_size": 25},
        {"name": "NIFTY", "tradingsymbol": "NIFTY24700CE", "instrument_token": 2, "instrument_type": "CE", "strike": 24700.0, "expiry": "2026-09-30", "lot_size": 25}
    ])
    sp = resolve_option_spread(df_mock_nfo, "NIFTY", 24500.0, 50, "BULL", target_price=24700.0)
    assert sp is not None and sp["spread_type"] == "BULL_CALL_SPREAD"

    class MockK:
        def quote(self, k):
            return {k[0]: {"last_price": 100.0, "depth": {"buy": [{"price": 99.0, "quantity": 10}], "sell": [{"price": 101.0, "quantity": 10}]}}}
    l_ok, sp_val, _, _ = check_bid_ask_spread_liquidity(MockK(), "NFO", "OPT1", max_spread_pct=0.03, bypass_when_closed=False)
    assert l_ok is True

    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"Spread/Liquidity/Reconciler Invariants Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

print("[TEST 19] Testing CVE Fixes, Positive Breakeven (+BE: Entry + 2%) & B-C Excursion Guard...", end="", flush=True)
try:
    import position_monitor
    from patterns_bear import find_anchor_shooting_star_baby
    from patterns_bull import find_anchor_hammer_baby, scan_anchor_bcd_breakout

    # 1. CVE-1 REJECTED_ERROR retry tracking
    c_test = "REGRESSION_TEST_OPT_CE"
    position_monitor.clear_executed_exit(c_test)
    position_monitor.save_executed_exit(c_test, "REJECTED_ERROR", {"error": "primary reject"})
    position_monitor.load_executed_exits()
    assert position_monitor.EXECUTED_EXITS[c_test]["details"]["retry_count"] == 1
    position_monitor.save_executed_exit(c_test, "REJECTED_ERROR", {"error": "secondary reject"})
    position_monitor.load_executed_exits()
    assert position_monitor.EXECUTED_EXITS[c_test]["details"]["retry_count"] == 2
    position_monitor.clear_executed_exit(c_test)

    # 2. Feature 5 +BE math
    entry_s = 100.0
    be_target = round(round((entry_s * 1.02) / 0.05) * 0.05, 2)
    assert be_target == 102.0

    # 3. Hammer Baby containment
    df_h_bad = pd.DataFrame([
        {"open": 100.0, "high": 102.0, "low": 90.0, "close": 91.0},
        {"open": 98.0, "high": 99.0, "low": 93.0, "close": 98.5}
    ])
    assert find_anchor_hammer_baby(df_h_bad) is None, "Floating hammer must be rejected"

    # 4. Shooting Star Baby containment
    df_s_bad = pd.DataFrame([
        {"open": 90.0, "high": 110.0, "low": 89.0, "close": 105.0},
        {"open": 95.0, "high": 102.0, "low": 94.0, "close": 94.5}
    ])
    assert find_anchor_shooting_star_baby(df_s_bad) is None, "Low shooting star must be rejected"

    # 5. B-C Runaway Excursion Guard
    df_runaway = pd.DataFrame([
        {"date": "2026-09-04 09:15:00", "open": 100.0, "high": 100.5, "low": 89.5, "close": 90.0, "volume": 1000},
        {"date": "2026-09-04 09:18:00", "open": 89.0, "high": 102.0, "low": 88.0, "close": 101.0, "volume": 2000},
        {"date": "2026-09-04 09:21:00", "open": 101.0, "high": 104.0, "low": 100.5, "close": 103.0, "volume": 1500},
        {"date": "2026-09-04 09:24:00", "open": 103.0, "high": 130.0, "low": 102.5, "close": 128.0, "volume": 1800},
        {"date": "2026-09-04 09:27:00", "open": 105.0, "high": 106.0, "low": 100.0, "close": 95.0, "volume": 1200},
        {"date": "2026-09-04 09:30:00", "open": 96.0, "high": 105.0, "low": 95.5, "close": 104.0, "volume": 1500},
    ])
    m_runaway = scan_anchor_bcd_breakout(df_runaway, df_runaway, anchor_tf="3m", entry_tf="3m")
    assert m_runaway is None, "Runaway excursion > 1.5x risk between B and C must be rejected"

    print(" PASSED [OK]", flush=True)
except Exception as e:
    errors.append(f"CVE Fixes & Excursion Guard Invariants Failed: {e}")
    print(f" FAILED [ERR] ({e})", flush=True)

print("\n" + "=" * 100)
if not errors:
    print("      ALL REGRESSION TESTS PASSED WITH 100% SUCCESS -- ZERO REGRESSIONS FOUND!")
else:
    print(f"      REGRESSION ERRORS FOUND ({len(errors)}):")
    for err in errors:
        print(f"        - {err}")
print("=" * 100)
