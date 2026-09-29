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
    scan_pattern_lifecycle_stage
)
from kiteconnect import KiteConnect

ak, at = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
ensure_kite_session(kite)

# Spot KFINTECH
nfo = kite.instruments("NSE")
tok_spot = [i for i in nfo if i["tradingsymbol"] == "KFINTECH"][0]["instrument_token"]
from_d = dt.date(2026, 9, 25)
to_d = dt.date(2026, 9, 29)

df_spot_15m = fetch_and_resample_candles(kite, tok_spot, from_d, to_d, "15minute")
print("=== KFINTECH SPOT 15M CANDLES TODAY ===")
today_spot = df_spot_15m[df_spot_15m["date"].astype(str) >= "2026-09-29"]
for idx, r in today_spot.iterrows():
    print(f"{r['date']} | O: {r['open']} | H: {r['high']} | L: {r['low']} | C: {r['close']} | V: {r['volume']}")

# Check KFINTECH26OCT880CE
nfo_all = kite.instruments("NFO")
match_ce = [i for i in nfo_all if i["tradingsymbol"] == "KFINTECH26OCT880CE"]
if match_ce:
    tok_ce = match_ce[0]["instrument_token"]
    df_ce_15m = fetch_and_resample_candles(kite, tok_ce, from_d, to_d, "15minute")
    df_ce_75m = fetch_and_resample_candles(kite, tok_ce, from_d, to_d, "75minute")
    print("\n=== KFINTECH26OCT880CE 15M CANDLES TODAY ===")
    today_ce = df_ce_15m[df_ce_15m["date"].astype(str) >= "2026-09-29"]
    for idx, r in today_ce.iterrows():
        print(f"{r['date']} | O: {r['open']} | H: {r['high']} | L: {r['low']} | C: {r['close']} | V: {r['volume']}")

    print("\nChecking patterns on KFINTECH26OCT880CE:")
    print("find_anchor_bullish_harami(df_ce_75m):", find_anchor_bullish_harami(df_ce_75m))
    print("find_anchor_bullish_harami(df_ce_15m):", find_anchor_bullish_harami(df_ce_15m))

# Search all log lines for KFINTECH on 2026-09-29
print("\n=== KFINTECH LOGS ON 2026-09-29 ===")
with open("output/logs/bull_nifty50_scanner.log", "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if "KFINTECH" in line and "2026-09-29" in line:
            if "PRIORITY" not in line:
                print(line.strip())
