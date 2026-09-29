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

# Spot POLICYBZR
nfo = kite.instruments("NSE")
tok_spot = [i for i in nfo if i["tradingsymbol"] == "POLICYBZR"][0]["instrument_token"]

from_d = dt.date(2026, 9, 25)
to_d = dt.date(2026, 9, 29)

df_spot_15m = fetch_and_resample_candles(kite, tok_spot, from_d, to_d, "15minute")
df_spot_75m = fetch_and_resample_candles(kite, tok_spot, from_d, to_d, "75minute")

print("=== POLICYBZR SPOT CANDLES (28th & 29th) ===")
spot_recent = df_spot_15m[df_spot_15m["date"].astype(str) >= "2026-09-28"]
for idx, r in spot_recent.iterrows():
    print(f"{r['date']} | O: {r['open']} | H: {r['high']} | L: {r['low']} | C: {r['close']} | V: {r['volume']}")

# Options for POLICYBZR PE: 1200PE, 1180PE, 1160PE, 1140PE, 1120PE, 1100PE
nfo_all = kite.instruments("NFO")
pb_pes = [i for i in nfo_all if "POLICYBZR26OCT" in i["tradingsymbol"] and "PE" in i["tradingsymbol"]]
print(f"\nFound {len(pb_pes)} POLICYBZR PE contracts")

for o in pb_pes:
    if o["strike"] in [1100, 1120, 1140, 1160, 1180, 1200]:
        cnt = o["tradingsymbol"]
        tok = o["instrument_token"]
        df_15 = fetch_and_resample_candles(kite, tok, from_d, to_d, "15minute")
        df_75 = fetch_and_resample_candles(kite, tok, from_d, to_d, "75minute")
        st = scan_pattern_lifecycle_stage(df_15, df_75, anchor_tf="75minute", entry_tf="15minute", is_option=True)
        print(f"\nContract: {cnt} (Strike {o['strike']})")
        print(f"  Stage: {st.get('stage') if st else None} | Pattern: {st.get('pattern') if st else None} | BM: {st.get('benchmark') if st else None} | Close: {st.get('close') if st else None} | T1: {st.get('t1') if st else None} | A_time: {st.get('candle_a_time') if st else None}")
        if df_15 is not None and not df_15.empty:
            print(f"  28-Sep Close: {df_15[df_15['date'].astype(str) < '2026-09-29'].iloc[-1]['close']}, 29-Sep Max High: {df_15[df_15['date'].astype(str) >= '2026-09-29']['high'].max()}, Latest Close: {df_15.iloc[-1]['close']}")

print("\n=== POLICYBZR LOGS (28th & 29th) ===")
with open("output/logs/bull_nifty50_scanner.log", "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if "POLICYBZR" in line and ("2026-09-28" in line or "2026-09-29" in line):
            if any(k in line for k in ["PE", "Category", "DISPATCH", "PROMO", "CONFIRMED", "STAGE", "ARBITRAGE", "WINNER", "ANCHOR FORMED", "DUAL_VCP", "ORDER", "TRIGGER", "REJECT", "HOLD", "EVICT"]):
                print(line.strip())
