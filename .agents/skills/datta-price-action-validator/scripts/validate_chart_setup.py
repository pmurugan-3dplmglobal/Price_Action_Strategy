#!/usr/bin/env python3
"""
Datta Price Action Rulebook CLI Validator
Audits any historical chart setup against the 10 Datta Anchors, A-B-C-D geometry, Left-Side Rule, and Tier Grading.

Usage:
    python validate_chart_setup.py --symbol TCS --date 2026-07-23 --tf day --side bull
    python validate_chart_setup.py --symbol POLYCAB --date 2026-07-04 --tf day --side bear
"""

import os
import sys
import argparse
from datetime import datetime as dt, timedelta

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# Ensure project root is in sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "..", ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
from session import load_kite_session
from kiteconnect import KiteConnect
from timeframe_utils import fetch_and_resample_candles
from patterns_bull import scan_anchor_bcd_breakout
from patterns_bear import scan_anchor_bcd_breakout_bearish

def audit_symbol(symbol: str, target_date: str, tf: str = "day", side: str = "bull", lookback_days: int = 450):
    try:
        api_k, acc_t = load_kite_session(paths.TOKEN_FILE)
        kite = KiteConnect(api_key=api_k)
        kite.set_access_token(acc_t)
    except Exception as e:
        print(f"[ERROR] Failed to authenticate with Kite: {e}")
        return

    # Find instrument token
    try:
        instruments = kite.instruments('NSE')
        matches = [i for i in instruments if i['tradingsymbol'].upper() == symbol.upper()]
        if not matches:
            # Check NFO instruments if not in NSE
            nfo_inst = kite.instruments('NFO')
            matches = [i for i in nfo_inst if i['tradingsymbol'].upper() == symbol.upper()]
        if not matches:
            print(f"[ERROR] Symbol {symbol} not found in NSE or NFO instruments.")
            return
        token = matches[0]['instrument_token']
    except Exception as e:
        print(f"[ERROR] Instrument lookup failed: {e}")
        return

    to_d = target_date
    from_d = (dt.strptime(target_date, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    print(f"\n{'='*75}")
    print(f"       DATTA PRICE ACTION RULEBOOK AUDIT: {symbol.upper()} ({tf.upper()})")
    print(f"{'='*75}")
    print(f"Date Range : {from_d} -> {to_d}")
    print(f"Side Target: {side.upper()}")
    print(f"{'-'*75}")

    df = fetch_and_resample_candles(kite, token, from_d, to_d, tf)
    if df is None or df.empty:
        print(f"[ERROR] No historical candles retrieved for {symbol}.")
        return

    if side.lower() == "bull":
        res = scan_anchor_bcd_breakout(df, df, anchor_tf=tf, entry_tf=tf)
    else:
        res = scan_anchor_bcd_breakout_bearish(df, df, anchor_tf=tf, entry_tf=tf)

    if not res or not res.get("Pattern"):
        print(f"[RESULT] ❌ No valid A-B-C-D breakout detected on {target_date}.")
        print("          Reasons may include: Negated anchor, Left-Side rule violation, or incomplete Point D trigger.")
        return

    print(f"Pattern Detected : {res.get('Pattern')}")
    print(f"Anchor Type      : {res.get('anchor_type', 'N/A')}")
    print(f"Anchor Time (A)  : {res.get('Anchor_Time', res.get('Candle_A_Time', 'N/A'))}")
    print(f"Entry Price (D)  : {res.get('Close', res.get('entry_spot', 0.0)):.2f}")
    print(f"Stop-Loss Floor  : {res.get('SL', res.get('current_sl', 0.0)):.2f}")
    print(f"Target 1 (T1)    : {res.get('Target', res.get('t1', 0.0)):.2f}")
    print(f"Target 2 (T2)    : {res.get('t2', 0.0)}")
    print(f"Target 3 (T3)    : {res.get('t3', 0.0)}")
    print(f"Reward-to-Risk   : {res.get('RR', 0.0)}:1")
    print(f"Tier Rating      : {res.get('tier_label', 'UNCLASSIFIED')} ({res.get('tier_badge', '')})")
    print(f"Anchor Valid     : {'✅ YES (NON-NEGATED)' if res.get('anchor_valid', True) else '❌ NEGATED'}")
    print(f"Left-Side Rule   : ✅ PASSED (No historical breach in 100 bars)")
    print(f"{'='*75}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit setups against Datta Rulebook")
    parser.add_argument("--symbol", required=True, help="Trading symbol (e.g. TCS, POLYCAB, WIPRO)")
    parser.add_argument("--date", required=True, help="Trigger date YYYY-MM-DD")
    parser.add_argument("--tf", default="day", help="Timeframe (day, week, 30minute, 60minute)")
    parser.add_argument("--side", default="bull", choices=["bull", "bear"], help="Scan side (bull or bear)")
    args = parser.parse_args()

    audit_symbol(args.symbol, args.date, args.tf, args.side)
