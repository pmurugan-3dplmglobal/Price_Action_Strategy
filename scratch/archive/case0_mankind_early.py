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

token = 3937281 # MANKIND
from_d = dt.date(2026, 9, 25)
to_d = dt.date(2026, 9, 29)

print("=== MANKIND 15-MIN SPOT CANDLES (28-SEP & 29-SEP) ===")
candles_15m = fetch_and_resample_candles(kite, token, from_d, to_d, "15minute")
c_recent = candles_15m[candles_15m["date"].astype(str) >= "2026-09-28"]
for idx, r in c_recent.iterrows():
    print(f"{r['date']} | O: {r['open']} | H: {r['high']} | L: {r['low']} | C: {r['close']} | V: {r['volume']}")

print("\n=== MANKIND LOGS ON 28-SEP AND EARLY 29-SEP ===")
with open("output/logs/bull_nifty50_scanner.log", "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if "MANKIND" in line and ("2026-09-28" in line or ("2026-09-29" in line and " 12:" not in line and " 13:" not in line and " 14:" not in line and " 15:" not in line and " 16:" not in line and " 17:" not in line and " 18:" not in line and " 19:" not in line and " 20:" not in line and " 21:" not in line)):
            if any(k in line for k in ["ANCHOR", "PROMOT", "Category", "DISPATCH", "ORDER", "STALE", "REJECT", "SWAP", "STAGE", "80% T1", "Harami", "Engulfing", "Hammer", "Sweep", "DEATH CROSS", "VWAP"]):
                print(line.strip())
