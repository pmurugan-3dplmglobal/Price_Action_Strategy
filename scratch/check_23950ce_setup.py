import os
import sys
import json
import pandas as pd
from datetime import datetime as dt, timedelta

_COMMON_DIR = os.path.join(os.getcwd(), "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

from kiteconnect import KiteConnect
from session import load_kite_session
from timeframe_utils import fetch_and_resample_candles
from patterns_bull import (
    scan_anchor_bcd_breakout,
    scan_trend_continuation_reentry,
    find_anchor_bullish_engulfing,
    find_anchor_ll_sweep,
    find_anchor_hammer_baby,
    find_anchor_bullish_harami,
    find_anchor_two_higher_highs
)
from targets import find_profit_targets

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

contract = "NIFTY2690123950CE"
q = kite.quote([f"NFO:{contract}"])
tok = q.get(f"NFO:{contract}", {}).get("instrument_token")
ltp = q.get(f"NFO:{contract}", {}).get("last_price")

print(f"Contract: {contract} | Token: {tok} | Live LTP: {ltp}")

from_d = (dt.now() - timedelta(days=10)).strftime("%Y-%m-%d")
to_d = dt.now().strftime("%Y-%m-%d")

# Fetch candles
for tf in ["3minute", "5minute", "15minute", "30minute"]:
    print(f"\n==================================================")
    print(f" EVALUATING TIMEFRAME: {tf}")
    print(f"==================================================")
    df = fetch_and_resample_candles(kite, tok, from_d, to_d, tf)
    if df is None or df.empty:
        print(f"No candle data for {tf}")
        continue
    
    print(f"Total candles fetched: {len(df)}")
    print(f"Last 5 candles on {tf}:")
    for idx, r in df.iloc[-5:].iterrows():
        print(f"  {r['date']} | O: {r['open']:.2f} | H: {r['high']:.2f} | L: {r['low']:.2f} | C: {r['close']:.2f} | V: {r['volume']}")
    
    # 1. Test 5 Anchor Detectors
    print(f"\n--- Checking 5 Anchor Patterns ---")
    anchors = [
        ("A1_Bullish_Engulfing", find_anchor_bullish_engulfing),
        ("A2_LL_Sweep", find_anchor_ll_sweep),
        ("A3_Hammer_Baby", find_anchor_hammer_baby),
        ("A4_Bullish_Harami", find_anchor_bullish_harami),
        ("A5_Two_Higher_Highs", find_anchor_two_higher_highs)
    ]
    for name, detector in anchors:
        try:
            res = detector(df)
            if res:
                print(f"  [ANCHOR FOUND] {name} | Pattern: {res.get('Pattern')} | Close: {res.get('Close')} | SL: {res.get('SL')} | Date: {res.get('Date') or res.get('CandleTime')}")
        except Exception as e:
            print(f"  Error checking {name}: {e}")

    # 2. Test ABCD Breakout
    print(f"\n--- Checking Full A-B-C-D Breakout Setup ---")
    try:
        res_abcd = scan_anchor_bcd_breakout(df, df)
        if res_abcd:
            print(f"  [ABCD BREAKOUT FOUND]:")
            for k, v in res_abcd.items():
                print(f"    {k}: {v}")
            # Profit targets
            t1, t2, t3 = find_profit_targets(df, res_abcd['Close'], stop_loss=res_abcd['SL'])
            print(f"    Target Formulation: T1={t1}, T2={t2}, T3={t3}")
        else:
            print(f"  [NO ABCD BREAKOUT] on {tf}")
    except Exception as e:
        print(f"  Error checking ABCD: {e}")
