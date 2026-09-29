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

# 1. Search logs for ADANIENT26OCT2950CE or ADANIENT on 2026-09-29
print("=== ADANIENT SCANNER LOGS TODAY (2026-09-29) ===")
with open("output/logs/bull_nifty50_scanner.log", "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if "ADANIENT" in line and "2026-09-29" in line:
            if any(k in line for k in ["2950CE", "2950", "DISPATCH", "PROMO", "CONFIRMED", "STAGE", "ARBITRAGE", "WINNER", "ANCHOR FORMED", "DUAL_VCP"]):
                print(line.strip())

# 2. Check ADANIENT spot and 2950 CE candles
nfo_instruments = kite.instruments("NFO")
match_opt = [i for i in nfo_instruments if i["tradingsymbol"] == "ADANIENT26OCT2950CE"]
print("\nADANIENT26OCT2950CE instrument:", match_opt)
if match_opt:
    tok_opt = match_opt[0]["instrument_token"]
    from_d = dt.date(2026, 9, 28)
    to_d = dt.date(2026, 9, 29)
    df_opt_15m = fetch_and_resample_candles(kite, tok_opt, from_d, to_d, "15minute")
    print("\nADANIENT 2950 CE 15M CANDLES:")
    for idx, r in df_opt_15m.tail(20).iterrows():
        print(f"{r['date']} | O: {r['open']} | H: {r['high']} | L: {r['low']} | C: {r['close']} | V: {r['volume']}")

nse_inst = [i for i in kite.instruments("NSE") if i["tradingsymbol"] == "ADANIENT"]
if nse_inst:
    tok_spot = nse_inst[0]["instrument_token"]
    df_spot_15m = fetch_and_resample_candles(kite, tok_spot, from_d, to_d, "15minute")
    print("\nADANIENT SPOT 15M CANDLES:")
    for idx, r in df_spot_15m.tail(20).iterrows():
        print(f"{r['date']} | O: {r['open']} | H: {r['high']} | L: {r['low']} | C: {r['close']} | V: {r['volume']}")
