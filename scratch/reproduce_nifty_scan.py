import sys, os
sys.path.insert(0, os.path.abspath('.'))
from common.session import load_kite_session
from kiteconnect import KiteConnect
import pandas as pd
from common.patterns_bull import scan_anchor_bcd_breakout, find_anchor_hammer_baby
from common.trading_core import fetch_and_resample_candles

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

opt_token = 14593538

# Fetch candles
df_entry = fetch_and_resample_candles(kite, opt_token, "2026-09-21", "2026-09-21", "3minute")
df_anchor = fetch_and_resample_candles(kite, opt_token, "2026-09-21", "2026-09-21", "15minute")

print(f"df_entry length: {len(df_entry)}, df_anchor length: {len(df_anchor)}")

# Let's run scan_anchor_bcd_breakout
matches = scan_anchor_bcd_breakout(df_entry, df_anchor, entry_tf="3minute", anchor_tf="15minute")
print(f"Total matches found: {len(matches)}")
print("Match keys:", list(matches.keys()))
print("Pattern:", matches.get("Pattern"))
print("CandleATime:", matches.get("CandleATime"))
print("Point B time:", matches.get("CandleBTime"))
print("Point C time:", matches.get("CandleCTime"))
print("Point D time:", matches.get("CandleTime"))
print("Benchmark:", matches.get("Benchmark"))
print("AnchorLow:", matches.get("AnchorLow"))
print("SL:", matches.get("SL"))
print("T1:", matches.get("T1"))
print("T2:", matches.get("T2"))
print("RR:", matches.get("RR"))
print("Close:", matches.get("Close"))
