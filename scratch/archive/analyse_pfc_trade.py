import os, sys, json, sqlite3
from datetime import datetime as dt, timedelta
import pandas as pd
import numpy as np

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from session import load_kite_session
from kiteconnect import KiteConnect

api_k, acc_t = load_kite_session(paths.TOKEN_FILE)
kite = KiteConnect(api_key=api_k)
kite.set_access_token(acc_t)

print("=== CHECKING PFC ORDERS IN KITE ===", flush=True)
orders = kite.orders()
pfc_orders = [o for o in orders if "PFC" in o.get("tradingsymbol", "")]
for o in pfc_orders:
    print(f"{o.get('order_timestamp')} | {o.get('tradingsymbol')} | {o.get('transaction_type')} | Qty: {o.get('filled_quantity')}/{o.get('quantity')} | Avg: {o.get('average_price')} | Status: {o.get('status')} | Tag: {o.get('tag')} | Msg: {o.get('status_message')}", flush=True)

# Lookup instruments
inst_nse = kite.instruments("NSE")
pfc_spot = [i for i in inst_nse if i["tradingsymbol"] == "PFC"][0]

inst_nfo = kite.instruments("NFO")
pfc_pe = [i for i in inst_nfo if "PFC" in i["tradingsymbol"] and "350PE" in i["tradingsymbol"]]
if not pfc_pe:
    print("Could not find PFC 350 PE in NFO instruments", flush=True)
    sys.exit(1)
pfc_pe_tok = pfc_pe[0]["instrument_token"]
pfc_pe_sym = pfc_pe[0]["tradingsymbol"]
print(f"\nFound Option Contract: {pfc_pe_sym} (Token: {pfc_pe_tok})", flush=True)

today_str = dt.now().strftime("%Y-%m-%d")
# Fetch minute candles for spot and option
c_spot = kite.historical_data(pfc_spot["instrument_token"], f"{today_str} 09:15:00", f"{today_str} 10:35:00", "minute")
c_pe = kite.historical_data(pfc_pe_tok, f"{today_str} 09:15:00", f"{today_str} 10:35:00", "minute")

df_spot = pd.DataFrame(c_spot)
df_pe = pd.DataFrame(c_pe)

print(f"\n=== SPOT PFC LTP: {kite.quote('NSE:PFC')['NSE:PFC']['last_price']} ===", flush=True)
print(f"=== PFC 350 PE LTP: {kite.quote(f'NFO:{pfc_pe_sym}')[f'NFO:{pfc_pe_sym}']['last_price']} ===", flush=True)

# Merge candles around the trade window (09:50 to 10:20)
print("\n=== MINUTE-BY-MINUTE CANDLES DURING PFC 350 PE TRADE (09:52 - 10:15) ===", flush=True)
df_pe_trade = df_pe[(df_pe['date'].dt.hour == 9) & (df_pe['date'].dt.minute >= 52) | (df_pe['date'].dt.hour == 10) & (df_pe['date'].dt.minute <= 15)].copy()
df_spot_trade = df_spot[(df_spot['date'].dt.hour == 9) & (df_spot['date'].dt.minute >= 52) | (df_spot['date'].dt.hour == 10) & (df_spot['date'].dt.minute <= 15)].copy()

merged = pd.merge(df_pe_trade, df_spot_trade, on='date', suffixes=('_pe', '_spot'))
print(merged[['date', 'open_pe', 'high_pe', 'low_pe', 'close_pe', 'volume_pe', 'open_spot', 'high_spot', 'low_spot', 'close_spot', 'volume_spot']].to_string(index=False), flush=True)

# High and Low of PE contract today
print(f"\nPE Contract Today High: {df_pe['high'].max()} at {df_pe.loc[df_pe['high'].idxmax()]['date']}", flush=True)
print(f"PE Contract Today Low : {df_pe['low'].min()} at {df_pe.loc[df_pe['low'].idxmin()]['date']}", flush=True)
print(f"PE Contract Current   : {df_pe.iloc[-1]['close']} at {df_pe.iloc[-1]['date']}", flush=True)

# Check Multi-timeframe trend for PFC spot
from timeframe_utils import fetch_and_resample_candles
print("\n=== PFC MULTI-TIMEFRAME SPOT EMAS & TREND ===", flush=True)
for tf in ["day", "60minute", "15minute", "5minute"]:
    days = 180 if tf == "day" else 10
    dft = fetch_and_resample_candles(kite, pfc_spot["instrument_token"], (dt.now() - timedelta(days=days)).strftime("%Y-%m-%d"), today_str, tf)
    if dft is not None and not dft.empty:
        dft["ema13"] = dft["close"].ewm(span=13, adjust=False).mean()
        dft["ema44"] = dft["close"].ewm(span=44, adjust=False).mean()
        last = dft.iloc[-1]
        align = "BULLISH (13 > 44)" if last["ema13"] > last["ema44"] else "BEARISH (13 < 44)"
        print(f"  {tf.upper():<10}: Close={last['close']} | EMA13={last['ema13']:.2f} | EMA44={last['ema44']:.2f} | Trend={align}", flush=True)
