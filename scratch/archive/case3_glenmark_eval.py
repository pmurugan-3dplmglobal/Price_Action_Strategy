import sys
import os
import datetime as dt
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE
from common.trading_core import fetch_and_resample_candles
from common.patterns_bull import scan_pattern_lifecycle_stage
from kiteconnect import KiteConnect

ak, at = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
ensure_kite_session(kite)

nfo = kite.instruments("NFO")
glen_opts = [i for i in nfo if "GLENMARK26OCT" in i["tradingsymbol"] and "CE" in i["tradingsymbol"]]
from_d = dt.date(2026, 9, 25)
to_d = dt.date(2026, 9, 29)

print("=== GLENMARK STRIKE LIFECYCLE EVALUATION ===")
for o in glen_opts:
    if o["strike"] in [2340, 2360, 2380, 2400, 2420, 2440]:
        cnt = o['tradingsymbol']
        tok = o['instrument_token']
        df_15 = fetch_and_resample_candles(kite, tok, from_d, to_d, "15minute")
        df_75 = fetch_and_resample_candles(kite, tok, from_d, to_d, "75minute")
        
        st_75 = scan_pattern_lifecycle_stage(df_15, df_75, anchor_tf="75minute", entry_tf="15minute", is_option=True)
        st_15 = scan_pattern_lifecycle_stage(df_15, df_15, anchor_tf="15minute", entry_tf="15minute", is_option=True)
        
        print(f"\nContract: {cnt} (Strike {o['strike']})")
        print(f"  Anchor 75m -> Stage: {st_75.get('stage') if st_75 else None} | Pattern: {st_75.get('pattern') if st_75 else None} | Close: {st_75.get('close') if st_75 else None} | BM: {st_75.get('benchmark') if st_75 else None} | T1: {st_75.get('t1') if st_75 else None} | A_time: {st_75.get('candle_a_time') if st_75 else None}")
        print(f"  Anchor 15m -> Stage: {st_15.get('stage') if st_15 else None} | Pattern: {st_15.get('pattern') if st_15 else None} | Close: {st_15.get('close') if st_15 else None} | BM: {st_15.get('benchmark') if st_15 else None} | T1: {st_15.get('t1') if st_15 else None} | A_time: {st_15.get('candle_a_time') if st_15 else None}")

# Check when GLENMARK surged today
tok_spot = 1895937
df_spot_15m = fetch_and_resample_candles(kite, tok_spot, from_d, to_d, "15minute")
today_15m = df_spot_15m[df_spot_15m["date"].astype(str) >= "2026-09-29"]
print("\n=== GLENMARK SPOT 15M CANDLE SUMMARY TODAY ===")
for idx, r in today_15m.iterrows():
    print(f"{r['date']} | O: {r['open']} | H: {r['high']} | L: {r['low']} | C: {r['close']} | V: {r['volume']}")
