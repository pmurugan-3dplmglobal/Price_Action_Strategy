import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))

from common.trading_core import load_kite_session, fetch_and_resample_candles
from kiteconnect import KiteConnect
import pandas as pd

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

print("=== LIVE QUOTE CIPLA & CIPLA26OCT1400CE ===")
q = kite.quote(["NSE:CIPLA", "NFO:CIPLA26OCT1400CE"])
for k, v in q.items():
    print(f"{k}:")
    print(f"  LTP: {v.get('last_price')}")
    print(f"  OHLC: {v.get('ohlc')}")
    print(f"  Volume: {v.get('volume')}")

# Get all broker orders today
print("\n=== BROKER ORDERS TODAY FOR CIPLA ===")
orders = kite.orders()
for o in orders:
    tsym = o.get("tradingsymbol", "")
    if "CIPLA" in tsym:
        print(f"Time: {o.get('order_timestamp')} | ID: {o.get('order_id')} | Sym: {tsym} | Tx: {o.get('transaction_type')} | Status: {o.get('status')} | Price: {o.get('price')} | AvgPrice: {o.get('average_price')} | Qty: {o.get('quantity')} | Tag: {o.get('tag')} | StatusMsg: {o.get('status_message')}")

# 15m candles for option
token_opt = q["NFO:CIPLA26OCT1400CE"]["instrument_token"]
df_opt = fetch_and_resample_candles(kite, token_opt, "2026-09-24", "2026-09-24", "15minute")
print(f"\n=== CIPLA26OCT1400CE 15m Candles Today (Total {len(df_opt)}) ===")
for idx, r in df_opt.iterrows():
    print(f"  {r['date']}: O={r['open']:.2f} H={r['high']:.2f} L={r['low']:.2f} C={r['close']:.2f} V={r['volume']}")

# 15m candles for spot
token_spot = q["NSE:CIPLA"]["instrument_token"]
df_spot = fetch_and_resample_candles(kite, token_spot, "2026-09-24", "2026-09-24", "15minute")
print(f"\n=== CIPLA Spot 15m Candles Today (Total {len(df_spot)}) ===")
for idx, r in df_spot.iterrows():
    print(f"  {r['date']}: O={r['open']:.2f} H={r['high']:.2f} L={r['low']:.2f} C={r['close']:.2f} V={r['volume']}")
