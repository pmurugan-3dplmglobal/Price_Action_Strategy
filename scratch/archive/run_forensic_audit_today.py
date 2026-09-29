import os
import sys
import json
import pandas as pd
from datetime import datetime as dt, timedelta

sys.path.insert(0, os.path.abspath("."))
sys.path.insert(0, os.path.abspath("common"))
from common.trading_core import load_kite_session, safe_kite_call, fetch_and_resample_candles
from kiteconnect import KiteConnect

def get_symbol_instrument_token(kite, symbol, exchange="NSE"):
    try:
        q = safe_kite_call(kite.quote, [f"{exchange}:{symbol}"])
        return q.get(f"{exchange}:{symbol}", {}).get("instrument_token")
    except Exception:
        return None

def main():
    api_key, access_token = load_kite_session()
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)

    today_str = "2026-09-28"
    
    symbols_audit = [
        {"sym": "BAJAJ-AUTO", "cnt": "BAJAJ-AUTO26OCT11100PE", "side": "PE", "entry_p": 219.0, "exit_p": 248.3, "entry_t": "14:00:02", "exit_t": "14:42:37", "lot": 75, "status": "CLOSED"},
        {"sym": "BHARTIARTL", "cnt": "BHARTIARTL26OCT1780CE", "side": "CE", "entry_p": 35.0, "exit_p": None, "entry_t": "12:55:30", "exit_t": None, "lot": 475, "status": "OPEN"},
        {"sym": "COALINDIA", "cnt": "COALINDIA26OCT420PE", "side": "PE", "entry_p": 6.30, "exit_p": None, "entry_t": "14:40:32", "exit_t": None, "lot": 1350, "status": "OPEN"},
        {"sym": "SBIN", "cnt": "SBIN26OCT960CE", "side": "CE", "entry_p": 24.35, "exit_p": None, "entry_t": "14:57:11", "exit_t": None, "lot": 750, "status": "OPEN"},
        {"sym": "ASTRAL", "cnt": "ASTRAL26OCT1400CE", "side": "CE", "entry_p": 42.80, "exit_p": 31.75, "entry_t": "2026-09-25", "exit_t": "09:50:01", "lot": 425, "status": "CLOSED"},
        {"sym": "GMRAIRPORT", "cnt": "GMRAIRPORT26OCT99CE", "side": "CE", "entry_p": 3.20, "exit_p": 2.07, "entry_t": "2026-09-25", "exit_t": "09:50:02", "lot": 6975, "status": "CLOSED"},
        {"sym": "NIFTY", "cnt": "NIFTY26SEP23000CE", "side": "CE", "entry_p": 70.0, "exit_p": 34.0, "entry_t": "09:20:41", "exit_t": "14:15:17", "lot": 65, "status": "CLOSED", "exchange": "NFO", "spot_exchange": "NSE"}
    ]

    forensic_results = []

    for item in symbols_audit:
        sym = item["sym"]
        cnt = item["cnt"]
        side = item["side"]
        
        # Spot token
        spot_sym = "NIFTY 50" if sym == "NIFTY" else sym
        spot_tok = get_symbol_instrument_token(kite, spot_sym, exchange="NSE")
        
        # Option token
        opt_tok = get_symbol_instrument_token(kite, cnt, exchange="NFO")
        
        print(f"\nAnalyzing {sym} ({cnt})... Spot Tok: {spot_tok}, Opt Tok: {opt_tok}")

        # Fetch Spot 15m candles
        spot_day_high, spot_day_low, spot_close, spot_vwap = 0.0, 0.0, 0.0, 0.0
        spot_ema13, spot_ema44 = 0.0, 0.0
        
        if spot_tok:
            try:
                df_spot = fetch_and_resample_candles(kite, spot_tok, today_str, today_str, "15minute")
                if df_spot is not None and not df_spot.empty:
                    spot_day_high = float(df_spot["high"].max())
                    spot_day_low = float(df_spot["low"].min())
                    spot_close = float(df_spot["close"].iloc[-1])
                    if "volume" in df_spot.columns and df_spot["volume"].sum() > 0:
                        typical_price = (df_spot["high"] + df_spot["low"] + df_spot["close"]) / 3.0
                        spot_vwap = round(float((typical_price * df_spot["volume"]).sum() / df_spot["volume"].sum()), 2)
            except Exception as e:
                print(f"Error fetching spot for {sym}: {e}")

        # Fetch Option 5m candles
        opt_day_high, opt_day_low, opt_close, opt_vwap = 0.0, 0.0, 0.0, 0.0
        opt_mfe, opt_mae = 0.0, 0.0

        if opt_tok:
            try:
                df_opt = fetch_and_resample_candles(kite, opt_tok, today_str, today_str, "5minute")
                if df_opt is not None and not df_opt.empty:
                    opt_day_high = float(df_opt["high"].max())
                    opt_day_low = float(df_opt["low"].min())
                    opt_close = float(df_opt["close"].iloc[-1])
                    if "volume" in df_opt.columns and df_opt["volume"].sum() > 0:
                        opt_tp = (df_opt["high"] + df_opt["low"] + df_opt["close"]) / 3.0
                        opt_vwap = round(float((opt_tp * df_opt["volume"]).sum() / df_opt["volume"].sum()), 2)
                    
                    # Filter candles after entry
                    entry_p = item["entry_p"]
                    opt_mfe = opt_day_high
                    opt_mae = opt_day_low
            except Exception as e:
                print(f"Error fetching option for {cnt}: {e}")

        forensic_results.append({
            "symbol": sym,
            "contract": cnt,
            "side": side,
            "status": item["status"],
            "entry_p": item["entry_p"],
            "exit_p": item["exit_p"],
            "entry_t": item["entry_t"],
            "exit_t": item["exit_t"],
            "lot": item["lot"],
            "opt_day_high": opt_day_high,
            "opt_day_low": opt_day_low,
            "opt_close": opt_close,
            "opt_vwap": opt_vwap,
            "spot_day_high": spot_day_high,
            "spot_day_low": spot_day_low,
            "spot_close": spot_close,
            "spot_vwap": spot_vwap
        })

    with open("scratch/today_forensic_results.json", "w", encoding="utf-8") as f:
        json.dump(forensic_results, f, indent=2)
    print("\nSaved scratch/today_forensic_results.json")

if __name__ == "__main__":
    main()
