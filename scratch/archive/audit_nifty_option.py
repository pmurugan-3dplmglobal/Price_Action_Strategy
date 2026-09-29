import sys, os
sys.path.insert(0, os.path.abspath('.'))
from common.session import load_kite_session
from kiteconnect import KiteConnect
import pandas as pd

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

opt_token = 14593538 # NIFTY2692223450PE
spot_token = 256265  # NIFTY 50

# Fetch 3-minute candles for the option
candles_opt_3m = kite.historical_data(opt_token, '2026-09-21', '2026-09-21', '3minute')
print("=== NIFTY2692223450PE (3-MINUTE CANDLES) ===")
for c in candles_opt_3m:
    d = c['date'].strftime('%H:%M')
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    v = c['volume']
    body = abs(cl - o)
    upper_wick = h - max(o, cl)
    lower_wick = min(o, cl) - l
    color = "GREEN" if cl >= o else "RED"
    print(f"{d} | {color:5} | O: {o:6.2f} | H: {h:6.2f} | L: {l:6.2f} | C: {cl:6.2f} | Vol: {v:7} | Body: {body:5.2f} | Upper: {upper_wick:5.2f} | Lower: {lower_wick:5.2f}")

# Also fetch previous day 3-minute candles if any
print("\n=== NIFTY2692223450PE (PREVIOUS SESSIONS / 18-SEP) ===")
try:
    candles_opt_prev = kite.historical_data(opt_token, '2026-09-18', '2026-09-18', '3minute')
    print(f"Prev day candles count: {len(candles_opt_prev)}")
    if len(candles_opt_prev) > 0:
        print("Last 5 candles of 18-Sep:")
        for c in candles_opt_prev[-5:]:
            print(c['date'].strftime('%Y-%m-%d %H:%M'), "O:", c['open'], "H:", c['high'], "L:", c['low'], "C:", c['close'])
except Exception as e:
    print("Prev day fetch error:", e)

# Fetch 15-minute candles for the option
candles_opt_15m = kite.historical_data(opt_token, '2026-09-21', '2026-09-21', '15minute')
print("\n=== NIFTY2692223450PE (15-MINUTE CANDLES) ===")
for c in candles_opt_15m:
    d = c['date'].strftime('%H:%M')
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    v = c['volume']
    print(f"{d} | O: {o:6.2f} | H: {h:6.2f} | L: {l:6.2f} | C: {cl:6.2f} | Vol: {v:7}")

# Fetch NIFTY 50 spot 3m candles
print("\n=== NIFTY 50 SPOT (3-MINUTE CANDLES) ===")
candles_spot = kite.historical_data(spot_token, '2026-09-21', '2026-09-21', '3minute')
for c in candles_spot:
    d = c['date'].strftime('%H:%M')
    o, h, l, cl = c['open'], c['high'], c['low'], c['close']
    v = c['volume']
    color = "GREEN" if cl >= o else "RED"
    print(f"{d} | {color:5} | O: {o:8.2f} | H: {h:8.2f} | L: {l:8.2f} | C: {cl:8.2f} | Vol: {v:7}")
