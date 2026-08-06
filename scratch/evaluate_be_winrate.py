import sys
import json
import os
import pandas as pd

sys.path.append('common')
sys.path.append('Trade_Option')

from trading_core import load_kite_session, fetch_and_resample_candles
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

nfo = pd.read_csv('Trade_Option/output/monitor/nfo_instruments_cache.csv')
data = json.load(open('backtest/master_backtest_results.json'))
trades = data['stock_options_30m']['trades']

pattern_stats = {}

for t in trades:
    contract = t['Asset']
    matches = nfo[nfo['tradingsymbol'] == contract]
    token = int(matches.iloc[0]['instrument_token']) if not matches.empty else None
    
    entry_date = t['BM_Time'][:10]
    entry_p = float(t['Entry'])
    sl_p = float(t['SL'])
    t1_p = float(t['T1'])
    pattern = t['Pattern']
    
    if pattern not in pattern_stats:
        pattern_stats[pattern] = {"total": 0, "wins": 0, "losses": 0, "active": 0}
    pattern_stats[pattern]["total"] += 1

    df = fetch_and_resample_candles(kite, token, entry_date, '2026-08-04', '30minute')
    if df.empty:
        pattern_stats[pattern]["active"] += 1
        continue

    post = df[df['date'] >= t['BM_Time']]
    if post.empty:
        post = df[df['date'] >= entry_date]
        
    outcome = "ACTIVE"
    for idx, row in post.iterrows():
        low = float(row['low'])
        high = float(row['high'])
        
        if low <= sl_p:
            outcome = "SL_HIT"
            break
        if high >= t1_p:
            outcome = "T1_HIT"
            break
            
    if outcome == "T1_HIT":
        pattern_stats[pattern]["wins"] += 1
    elif outcome == "SL_HIT":
        pattern_stats[pattern]["losses"] += 1
    else:
        pattern_stats[pattern]["active"] += 1

print("=" * 100)
print("              PATTERN-BY-PATTERN WIN RATE BREAKDOWN (LAST 4 SESSIONS)")
print("=" * 100)
print(f"{'Pattern':<20} | {'Total':<6} | {'Wins (T1+)':<10} | {'Losses (SL)':<11} | {'Active':<8} | {'Win Rate %'}")
print("-" * 100)

for pat, stats in sorted(pattern_stats.items(), key=lambda x: x[1]["total"], reverse=True):
    completed = stats["wins"] + stats["losses"]
    wr = (stats["wins"] / completed * 100) if completed > 0 else 0.0
    print(f"{pat:<20} | {stats['total']:<6} | {stats['wins']:<10} | {stats['losses']:<11} | {stats['active']:<8} | {wr:.2f}%")

print("=" * 100)
