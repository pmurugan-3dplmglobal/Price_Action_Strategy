import sys
import os
import datetime as dt
import pandas as pd

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE
from common.trading_core import fetch_and_resample_candles
from common.patterns_bull import find_anchor_bullish_harami
from kiteconnect import KiteConnect

ak, at = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
ensure_kite_session(kite)

# Check KFINTECH spot and CE on 28-Sep and 29-Sep morning
tok_spot = 1270529 # KFINTECH
tok_ce = 22600450  # KFINTECH26OCT880CE

from_d = dt.date(2026, 9, 25)
to_d = dt.date(2026, 9, 29)

df_spot = fetch_and_resample_candles(kite, tok_spot, from_d, to_d, "15minute")
df_ce = fetch_and_resample_candles(kite, tok_ce, from_d, to_d, "15minute")
df_ce_75 = fetch_and_resample_candles(kite, tok_ce, from_d, to_d, "75minute")

print("=== CE 75M CANDLES ===")
print(df_ce_75.tail(10)[["date", "open", "high", "low", "close", "volume"]])

print("find_anchor_bullish_harami on 75m CE:")
print(find_anchor_bullish_harami(df_ce_75))

print("\n=== CE 15M CANDLES ===")
print(df_ce.tail(15)[["date", "open", "high", "low", "close", "volume"]])

print("find_anchor_bullish_harami on 15m CE:")
print(find_anchor_bullish_harami(df_ce))

print("\n=== SPOT 15M CANDLES (28th & 29th) ===")
print(df_spot[df_spot['date'].astype(str) >= '2026-09-28'][["date", "open", "high", "low", "close", "volume"]])
