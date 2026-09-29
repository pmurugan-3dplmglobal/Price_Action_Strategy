import sys
import os
import pandas as pd
from datetime import datetime, date

sys.path.insert(0, ".")
sys.path.insert(0, "common")

from common.trading_core import load_kite_session
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

symbols = ["RBLBANK", "KALYANKJIL"]
quotes = kite.quote([f"NSE:{s}" for s in symbols])
today = date.today()

for s in symbols:
    q = quotes.get(f"NSE:{s}", {})
    token = q.get("instrument_token")
    ohlc = q.get("ohlc", {})
    ltp = q.get("last_price", 0.0)
    print(f"\n==========================================")
    print(f"=== {s} (Spot Token: {token}) ===")
    print(f"==========================================")
    print(f"Open: {ohlc.get('open')}, High: {ohlc.get('high')}, Low: {ohlc.get('low')}, Close: {ohlc.get('close')}, LTP: {ltp}")
    
    candles_15m = kite.historical_data(token, from_date=f"{today} 09:15:00", to_date=f"{today} 15:30:00", interval="15minute")
    df15 = pd.DataFrame(candles_15m)
    if not df15.empty:
        df15["vwap"] = (df15["volume"] * (df15["high"] + df15["low"] + df15["close"]) / 3).cumsum() / df15["volume"].cumsum()
        df15["ema13"] = df15["close"].ewm(span=13, adjust=False).mean()
        df15["ema44"] = df15["close"].ewm(span=44, adjust=False).mean()
        
        print(f"15m Candles count: {len(df15)}")
        for idx, row in df15.iterrows():
            t_str = str(row['date'])[-14:-6] if 'date' in row else str(idx)
            c_dir = "GREEN" if row['close'] >= row['open'] else "RED"
            ema_align = "BULL(13>44)" if row['ema13'] > row['ema44'] else "BEAR(13<44)"
            vwap_rel = "ABOVE_VWAP" if row['close'] > row['vwap'] else "BELOW_VWAP"
            body = abs(row['close'] - row['open'])
            rng = row['high'] - row['low']
            print(f"  {t_str} | O:{row['open']:<6.2f} H:{row['high']:<6.2f} L:{row['low']:<6.2f} C:{row['close']:<6.2f} (R:{rng:<4.2f} B:{body:<4.2f}) | Vol:{row['volume']:<8} | {c_dir:<5} | VWAP:{row['vwap']:<6.2f} ({vwap_rel:<10}) | {ema_align}")
