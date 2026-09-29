import json
import os
import sys
import pandas as pd
from datetime import datetime as dt

sys.path.insert(0, ".")
from common.trading_core import load_kite_session
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

with open('output/monitor/scan_display.json', 'r') as f:
    d = json.load(f)

staged = d.get('all_staged_today', [])
gold_setups = [s for s in staged if 'T1' in str(s.get('tier_badge', '')) or 'GOLD' in str(s.get('tier_label', '')).upper()]

print(f"Total T1 Gold setups to evaluate: {len(gold_setups)}")

results = []
instruments = kite.instruments("NFO")
inst_map = {i['tradingsymbol']: i['instrument_token'] for i in instruments}

for g in gold_setups:
    sym = g.get('symbol')
    contract = g.get('contract')
    side = g.get('side')
    pat = g.get('pattern')
    bm = float(g.get('benchmark') or 0.0)
    sl = float(g.get('sl') or 0.0)
    t1 = float(g.get('t1') or 0.0)
    rr = float(g.get('rr') or 0.0)
    etime = g.get('entry_time') or g.get('created_at') or ''
    
    token = inst_map.get(contract)
    if not token:
        continue
        
    try:
        # Fetch 5m candles for contract today
        candles = kite.historical_data(token, "2026-09-22 09:15:00", "2026-09-22 15:30:00", "5minute")
        if not candles:
            continue
        df = pd.DataFrame(candles)
        day_open = df['open'].iloc[0]
        day_high = df['high'].max()
        day_low = df['low'].min()
        day_close = df['close'].iloc[-1]
        
        # Calculate performance relative to Benchmark (Trigger price)
        # Did it trigger?
        triggered = day_high >= bm if bm > 0 else False
        
        # Max gain from BM to Day High
        max_gain_pct = ((day_high - bm) / bm * 100.0) if bm > 0 else 0.0
        
        # Did it hit T1?
        hit_t1 = day_high >= t1 if t1 > 0 else False
        
        # Max drawdown below BM
        # Look at candles after triggering
        trig_candles = df[df['high'] >= bm]
        if not trig_candles.empty:
            first_idx = trig_candles.index[0]
            after_trig = df.iloc[first_idx:]
            post_high = after_trig['high'].max()
            post_low = after_trig['low'].min()
            post_gain = ((post_high - bm) / bm * 100.0) if bm > 0 else 0.0
            post_loss = ((post_low - bm) / bm * 100.0) if bm > 0 else 0.0
        else:
            post_gain = 0.0
            post_loss = 0.0
            
        results.append({
            "symbol": sym,
            "contract": contract,
            "side": side,
            "pattern": pat,
            "bm": bm,
            "sl": sl,
            "t1": t1,
            "rr": rr,
            "day_high": day_high,
            "day_close": day_close,
            "max_gain_pct": max_gain_pct,
            "post_gain_pct": post_gain,
            "post_loss_pct": post_loss,
            "hit_t1": hit_t1,
            "triggered": triggered,
            "entry_time": etime
        })
    except Exception as e:
        print(f"Error fetching {contract}: {e}")

df_res = pd.DataFrame(results)
print("\n" + "=" * 110)
print(f"{'SYMBOL':12} | {'SIDE':4} | {'BM':<6} | {'T1':<6} | {'RR':<4} | {'HIGH':<6} | {'CLOSE':<6} | {'PEAK GAIN %':<11} | {'POST LOSS %':<11} | {'HIT T1':<6} | {'OUTCOME'}")
print("=" * 110)

winners = []
losers = []

for idx, r in df_res.iterrows():
    outcome = "T1 HIT" if r['hit_t1'] else ("GAIN > 20%" if r['post_gain_pct'] >= 20.0 else ("LOSS" if r['post_loss_pct'] <= -15.0 or r['day_close'] < r['bm'] else "FLAT"))
    if r['hit_t1'] or r['post_gain_pct'] >= 20.0:
        winners.append(r)
    else:
        losers.append(r)
    print(f"{r['symbol']:12} | {r['side']:4} | {r['bm']:<6.2f} | {r['t1']:<6.2f} | {r['rr']:<4.2f} | {r['day_high']:<6.2f} | {r['day_close']:<6.2f} | {r['post_gain_pct']:<+10.1f}% | {r['post_loss_pct']:<+10.1f}% | {str(r['hit_t1']):<6} | {outcome}")

print("\n" + "=" * 50)
print(f"SUMMARY: Total Evaluated: {len(df_res)} | Winners: {len(winners)} | Losers/Flat: {len(losers)}")
print("=" * 50)

with open("scratch/gold_tier_outcomes_audit.json", "w") as out_f:
    json.dump(results, out_f, indent=2)
