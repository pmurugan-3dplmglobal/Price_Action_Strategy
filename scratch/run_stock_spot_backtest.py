import os
import sys
import json
import pandas as pd
from datetime import datetime as dt, timedelta

sys.path.append('common')
sys.path.append('Trade_Stock')

from trading_core import (
    load_kite_session,
    fetch_and_resample_candles,
    scan_anchor_bcd_breakout,
    scan_anchor_bcd_breakout_bearish,
    find_profit_targets,
    find_profit_targets_bearish,
    STOCK_REGISTRY
)
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

start_date = "2026-07-29"
end_date = "2026-08-04"

print("=" * 115)
print(f"      STOCK SPOT ENGINE (NIFTY 50 SPOT) PATTERN BACKTEST REPORT ({start_date} to {end_date})")
print("=" * 115)

spot_trades = []

for symbol, config in sorted(STOCK_REGISTRY.items()):
    token = config["token"]
    try:
        # Fetch 30m spot candles for stock
        df_spot = fetch_and_resample_candles(kite, token, "2026-07-20", end_date, "30minute")
        if df_spot is None or df_spot.empty or len(df_spot) < 20:
            continue
            
        # Scan Bullish Spot Setups
        bull_res = scan_anchor_bcd_breakout(df_spot, df_spot)
        if bull_res:
            d_time = str(bull_res.get("CandleTime") or df_spot.iloc[-1]['date'])
            d_date = d_time[:10]
            if start_date <= d_date <= end_date:
                spot_trades.append({
                    "Symbol": symbol,
                    "Side": "BULL",
                    "Pattern": bull_res["Pattern"],
                    "D_Time": d_time,
                    "Entry": bull_res["Close"],
                    "SL": bull_res["SL"],
                    "T1": bull_res["T1"],
                    "RR": bull_res.get("RR", 0.0),
                    "token": token
                })

        # Scan Bearish Spot Setups
        bear_res = scan_anchor_bcd_breakout_bearish(df_spot, df_spot)
        if bear_res:
            d_time = str(bear_res.get("CandleTime") or df_spot.iloc[-1]['date'])
            d_date = d_time[:10]
            if start_date <= d_date <= end_date:
                spot_trades.append({
                    "Symbol": symbol,
                    "Side": "BEAR",
                    "Pattern": bear_res["Pattern"],
                    "D_Time": d_time,
                    "Entry": bear_res["Close"],
                    "SL": bear_res["SL"],
                    "T1": bear_res["T1"],
                    "RR": bear_res.get("RR", 0.0),
                    "token": token
                })
    except Exception as e:
        continue

print(f"{'Date':<10} | {'Symbol':<12} | {'Side':<5} | {'Pattern':<15} | {'Entry (Spot)':<12} | {'SL':<10} | {'T1 Target':<10} | {'Outcome':<12} | {'P&L %'}")
print("-" * 115)

pattern_stats = {}

for t in spot_trades:
    symbol = t["Symbol"]
    token = t["token"]
    side = t["Side"]
    pattern = t["Pattern"]
    entry_date = t["D_Time"][:10]
    entry_p = float(t["Entry"])
    sl_p = float(t["SL"])
    t1_p = float(t["T1"])
    
    if pattern not in pattern_stats:
        pattern_stats[pattern] = {"total": 0, "wins": 0, "losses": 0, "active": 0}
    pattern_stats[pattern]["total"] += 1

    df_post = fetch_and_resample_candles(kite, token, entry_date, end_date, "30minute")
    post = df_post[df_post['date'] >= t['D_Time']] if not df_post.empty else pd.DataFrame()
    
    outcome = "ACTIVE"
    pnl = 0.0
    
    if not post.empty:
        for idx, row in post.iterrows():
            low = float(row['low'])
            high = float(row['high'])
            close = float(row['close'])
            
            if side == "BULL":
                if close <= sl_p or low <= sl_p:
                    outcome = "SL_HIT"
                    pnl = round((sl_p - entry_p) / entry_p * 100, 2)
                    break
                if high >= t1_p:
                    outcome = "T1_HIT"
                    pnl = round((t1_p - entry_p) / entry_p * 100, 2)
                    break
            else: # BEAR
                if close >= sl_p or high >= sl_p:
                    outcome = "SL_HIT"
                    pnl = round((entry_p - sl_p) / entry_p * 100, 2)
                    break
                if low <= t1_p:
                    outcome = "T1_HIT"
                    pnl = round((entry_p - t1_p) / entry_p * 100, 2)
                    break
                    
    if outcome == "T1_HIT":
        pattern_stats[pattern]["wins"] += 1
    elif outcome == "SL_HIT":
        pattern_stats[pattern]["losses"] += 1
    else:
        pattern_stats[pattern]["active"] += 1
        
    pnl_str = f"{pnl:+.2f}%" if outcome != "ACTIVE" else "0.00% (Open)"
    print(f"{entry_date:<10} | {symbol:<12} | {side:<5} | {pattern:<15} | {entry_p:<12.2f} | {sl_p:<10.2f} | {t1_p:<10.2f} | {outcome:<12} | {pnl_str}")

print("\n" + "=" * 115)
print("              STOCK SPOT ENGINE — PATTERN WIN RATE BREAKDOWN")
print("=" * 115)
print(f"{'Pattern Name':<22} | {'Total':<6} | {'Wins (T1+)':<10} | {'Losses (SL)':<11} | {'Active':<8} | {'Win Rate %'}")
print("-" * 115)

for pat, stats in sorted(pattern_stats.items(), key=lambda x: x[1]["total"], reverse=True):
    completed = stats["wins"] + stats["losses"]
    wr = (stats["wins"] / completed * 100) if completed > 0 else 0.0
    print(f"{pat:<22} | {stats['total']:<6} | {stats['wins']:<10} | {stats['losses']:<11} | {stats['active']:<8} | {wr:.2f}%")

print("=" * 115)
