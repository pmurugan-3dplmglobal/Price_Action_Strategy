import sys
import os
import datetime as dt
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE
from common.trading_core import fetch_and_resample_candles
from common.patterns_bull import (
    find_anchor_bullish_engulfing, find_anchor_ll_sweep,
    find_anchor_hammer_baby, find_anchor_bullish_harami, find_anchor_two_higher_highs,
    scan_anchor_bcd_breakout, scan_pattern_lifecycle_stage
)
from kiteconnect import KiteConnect

ak, at = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
ensure_kite_session(kite)

# Spot GLENMARK
tok_spot = 1895937
from_d = dt.date(2026, 9, 25)
to_d = dt.date(2026, 9, 29)

df_spot_15m = fetch_and_resample_candles(kite, tok_spot, from_d, to_d, "15minute")
df_spot_75m = fetch_and_resample_candles(kite, tok_spot, from_d, to_d, "75minute")

print("=== GLENMARK SPOT 15M CANDLES TODAY ===")
today_15m = df_spot_15m[df_spot_15m["date"].astype(str) >= "2026-09-29"]
for idx, r in today_15m.iterrows():
    print(f"{r['date']} | O: {r['open']} | H: {r['high']} | L: {r['low']} | C: {r['close']} | V: {r['volume']}")

print("\n=== GLENMARK SPOT 75M CANDLES ===")
for idx, r in df_spot_75m.tail(10).iterrows():
    print(f"{r['date']} | O: {r['open']} | H: {r['high']} | L: {r['low']} | C: {r['close']} | V: {r['volume']}")

# Options for GLENMARK: GLENMARK26OCT2440CE, GLENMARK26OCT2400CE, GLENMARK26OCT2360CE, GLENMARK26OCT2340CE
nfo = kite.instruments("NFO")
glen_opts = [i for i in nfo if "GLENMARK26OCT" in i["tradingsymbol"] and "CE" in i["tradingsymbol"]]
for o in glen_opts:
    if o["strike"] in [2360, 2380, 2400, 2420, 2440]:
        print(f"Option: {o['tradingsymbol']}, Token: {o['instrument_token']}")
        df_opt_15 = fetch_and_resample_candles(kite, o['instrument_token'], from_d, to_d, "15minute")
        df_opt_75 = fetch_and_resample_candles(kite, o['instrument_token'], from_d, to_d, "75minute")
        st_15_75 = scan_pattern_lifecycle_stage(df_opt_15, df_opt_75, anchor_tf="75minute", entry_tf="15minute", is_option=True)
        st_15_15 = scan_pattern_lifecycle_stage(df_opt_15, df_opt_15, anchor_tf="15minute", entry_tf="15minute", is_option=True)
        print(f"  Stage (Anchor 75m): {st_15_75.get('stage') if st_15_75 else None}, A_time: {st_15_75.get('candle_a_time') if st_15_75 else None}, BM: {st_15_75.get('benchmark') if st_15_75 else None}, Close: {st_15_75.get('close') if st_15_75 else None}, T1: {st_15_75.get('t1') if st_15_75 else None}")
        print(f"  Stage (Anchor 15m): {st_15_15.get('stage') if st_15_15 else None}, A_time: {st_15_15.get('candle_a_time') if st_15_15 else None}, BM: {st_15_15.get('benchmark') if st_15_15 else None}, Close: {st_15_15.get('close') if st_15_15 else None}, T1: {st_15_15.get('t1') if st_15_15 else None}")

# Check logs for GLENMARK
print("\n=== GLENMARK LOGS TODAY ===")
with open("output/logs/bull_nifty50_scanner.log", "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if "GLENMARK" in line and "2026-09-29" in line:
            if any(k in line for k in ["2440CE", "2400CE", "2380CE", "80% T1", "ANCHOR", "EVICT"]):
                print(line.strip())
