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

symbols = ["VMM", "VBL", "BSE"]
print("=== INVESTIGATING VMM, VBL, BSE ===")

# Check spot price change today
from_d = dt.date(2026, 9, 28)
to_d = dt.date(2026, 9, 29)

for sym in symbols:
    insts = [i for i in kite.instruments("NSE") if i["tradingsymbol"] == sym]
    if not insts:
        print(f"Symbol {sym} not found in NSE instruments")
        continue
    tok = insts[0]["instrument_token"]
    c_day = fetch_and_resample_candles(kite, tok, from_d, to_d, "day")
    print(f"\n{sym} DAY CANDLES:")
    print(c_day[["date", "open", "high", "low", "close", "volume"]])

print("\n=== LOGS FOR VMM, VBL, BSE ON 2026-09-29 ===")
with open("output/logs/bull_nifty50_scanner.log", "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if any(s in line for s in symbols) and "2026-09-29" in line:
            if any(k in line for k in ["ANCHOR", "PROMOT", "Category", "DISPATCH", "ORDER", "STALE", "REJECT", "SWAP", "STAGE", "80% T1", "Harami", "Engulfing", "Hammer", "Sweep", "DEATH CROSS", "VWAP", "HOLD", "illusion", "CATEGORY"]):
                print(line.strip())
