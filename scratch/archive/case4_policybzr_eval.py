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

# 1. Spot POLICYBZR
nfo = kite.instruments("NSE")
tok_spot = [i for i in nfo if i["tradingsymbol"] == "POLICYBZR"][0]["instrument_token"]
from_d = dt.date(2026, 9, 25)
to_d = dt.date(2026, 9, 29)

# 2. Options for POLICYBZR PE:
nfo_all = kite.instruments("NFO")
pb_pes = [i for i in nfo_all if "POLICYBZR26OCT" in i["tradingsymbol"] and "PE" in i["tradingsymbol"]]

print("=== POLICYBZR PE STRIKE EVALUATION ===")
for o in pb_pes:
    if o["strike"] in [1080, 1100, 1120, 1140, 1160, 1200]:
        cnt = o["tradingsymbol"]
        tok = o["instrument_token"]
        df_15 = fetch_and_resample_candles(kite, tok, from_d, to_d, "15minute")
        df_75 = fetch_and_resample_candles(kite, tok, from_d, to_d, "75minute")
        st_75 = scan_pattern_lifecycle_stage(df_15, df_75, anchor_tf="75minute", entry_tf="15minute", is_option=True)
        st_15 = scan_pattern_lifecycle_stage(df_15, df_15, anchor_tf="15minute", entry_tf="15minute", is_option=True)
        print(f"\nContract: {cnt} (Strike {o['strike']})")
        print(f"  Anchor 75m -> Stage: {st_75.get('stage') if st_75 else None} | Pattern: {st_75.get('pattern') if st_75 else None} | BM: {st_75.get('benchmark') if st_75 else None} | Close: {st_75.get('close') if st_75 else None} | T1: {st_75.get('t1') if st_75 else None} | A_time: {st_75.get('candle_a_time') if st_75 else None}")
        print(f"  Anchor 15m -> Stage: {st_15.get('stage') if st_15 else None} | Pattern: {st_15.get('pattern') if st_15 else None} | BM: {st_15.get('benchmark') if st_15 else None} | Close: {st_15.get('close') if st_15 else None} | T1: {st_15.get('t1') if st_15 else None} | A_time: {st_15.get('candle_a_time') if st_15 else None}")
        if df_15 is not None and not df_15.empty:
            c_28 = df_15[df_15['date'].astype(str) < '2026-09-29']
            c_29 = df_15[df_15['date'].astype(str) >= '2026-09-29']
            p_28 = c_28.iloc[-1]['close'] if not c_28.empty else 0
            h_29 = c_29['high'].max() if not c_29.empty else 0
            l_29 = c_29['close'].iloc[-1] if not c_29.empty else 0
            gain_pct = round(((h_29 - p_28) / p_28) * 100, 1) if p_28 > 0 else 0
            print(f"  28-Sep Close: ₹{p_28} -> 29-Sep High: ₹{h_29} (+{gain_pct}%) | Final Close: ₹{l_29}")

print("\n=== POLICYBZR PROMOTIONS AND REJECTIONS IN LOGS (Market hours 09:15-15:30) ===")
with open("output/logs/bull_nifty50_scanner.log", "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if "POLICYBZR" in line and "2026-09-29" in line:
            if any(k in line for k in ["PROMO", "CONFIRMED", "DISPATCH", "ARBITRAGE", "WINNER", "PORTFOLIO", "CAP", "RADAR"]):
                print(line.strip())
