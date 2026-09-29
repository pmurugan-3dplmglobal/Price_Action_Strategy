import sys, os
sys.path.insert(0, os.path.abspath('.'))
from common.session import load_kite_session
from kiteconnect import KiteConnect
from common.trading_core import fetch_and_resample_candles

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

opt_token = 14593538
df_entry = fetch_and_resample_candles(kite, opt_token, '2026-09-21', '2026-09-21', '3minute')

print("Index | Date | Open | High | Low | Close | Color")
for idx, c in df_entry.iterrows():
    d = str(c['date'])
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    col = "GREEN" if cl >= o else "RED"
    print(f"{idx:2d} | {d} | {o:6.2f} | {h:6.2f} | {l:6.2f} | {cl:6.2f} | {col}")
