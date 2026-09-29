import sys
import os
import datetime as dt
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE
from common.trading_core import fetch_and_resample_candles
from kiteconnect import KiteConnect

ak, at = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
ensure_kite_session(kite)

# 1. Spot Instrument
inst_list = kite.instruments("NSE")
mankind_inst = [i for i in inst_list if i["tradingsymbol"] == "MANKIND"]
print("MANKIND NSE Instrument:", mankind_inst)
token = mankind_inst[0]["instrument_token"]

from_d = dt.date(2026, 9, 25)
to_d = dt.date(2026, 9, 29)

print("\n--- MANKIND SPOT 15-MINUTE CANDLES ---")
candles_15m = fetch_and_resample_candles(kite, token, from_d, to_d, "15minute")
print(candles_15m.tail(25)[["date", "open", "high", "low", "close", "volume"]])

print("\n--- MANKIND SPOT DAY CANDLES ---")
candles_day = fetch_and_resample_candles(kite, token, from_d, to_d, "day")
print(candles_day[["date", "open", "high", "low", "close", "volume"]])

# 2. Search logs for all occurrences of MANKIND on 2026-09-28 and 2026-09-29
print("\n--- MANKIND SCANNER LOG ANALYSIS ---")
with open("output/logs/bull_nifty50_scanner.log", "r", encoding="utf-8", errors="ignore") as f:
    mankind_logs = [l.strip() for l in f if "MANKIND" in l and ("2026-09-28" in l or "2026-09-29" in l)]

print(f"Total log lines for MANKIND (28th & 29th): {len(mankind_logs)}")
for l in mankind_logs:
    if any(k in l for k in ["ANCHOR", "PROMOT", "Category", "DISPATCH", "ORDER", "STALE", "REJECT", "SWAP", "STAGE", "80% T1", "Harami", "Engulfing", "Hammer", "Sweep", "DEATH CROSS", "VWAP"]):
        print("  ", l)
