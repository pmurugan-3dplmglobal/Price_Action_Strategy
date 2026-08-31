import os
import sys
import json
import sqlite3
import pandas as pd
from datetime import datetime as dt, timedelta

_COMMON_DIR = os.path.join(os.getcwd(), "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

import paths
from kiteconnect import KiteConnect
from session import load_kite_session
from position_monitor import _get_nfo_cache

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

print("==================================================")
print(" NIFTY ARBITRAGE DEEP DIVE: 23950 CE vs 24050 PE")
print("==================================================")

# 1. Check live quotes
quotes = kite.quote(["NSE:NIFTY 50", "NFO:NIFTY2690123950CE", "NFO:NIFTY2690124050PE"])
for k, q in quotes.items():
    print(f"\n[{k}]")
    print(f"  LTP: {q.get('last_price')} | Open: {q.get('ohlc',{}).get('open')} | High: {q.get('ohlc',{}).get('high')} | Low: {q.get('ohlc',{}).get('low')} | Close: {q.get('ohlc',{}).get('close')}")

# 2. Check trades in SQLite for NIFTY
db_path = os.path.join("output", "monitor", "trades.sqlite3")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, engine, symbol, contract, status, data_json, created_at, updated_at FROM trades WHERE contract LIKE '%23950CE%' OR contract LIKE '%24050PE%' ORDER BY id DESC LIMIT 5")
    rows = cur.fetchall()
    print(f"\n[SQLite Matches: {len(rows)}]")
    for r in rows:
        print(f"  ID {r[0]} | {r[3]} | Status: {r[4]} | Created: {r[6]}")
        try:
            dj = json.loads(r[5])
            print(f"    Entry: {dj.get('entry_spot')} | SL: {dj.get('current_sl')} | T1: {dj.get('t1')} | T2: {dj.get('t2')} | T3: {dj.get('t3')}")
        except:
            pass
    conn.close()

# 3. Check scan_display_index.json
disp_p = paths.SCAN_DISPLAY_INDEX_FILE
if os.path.exists(disp_p):
    with open(disp_p) as f:
        d = json.load(f)
    print(f"\n[scan_display_index.json]")
    print(f"  Staged: {json.dumps(d.get('staged_trades', []), indent=2)}")
    print(f"  Active: {json.dumps(d.get('active_positions', []), indent=2)}")
    print(f"  Carry: {json.dumps(d.get('carry_forward', []), indent=2)}")

# 4. Check candle history for NIFTY2690123950CE today
ce_tok = quotes.get("NFO:NIFTY2690123950CE", {}).get("instrument_token")
if ce_tok:
    from_d = (dt.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    to_d = dt.now().strftime("%Y-%m-%d")
    candles = kite.historical_data(ce_tok, from_d, to_d, "15minute")
    df_c = pd.DataFrame(candles)
    if not df_c.empty:
        df_c['date'] = pd.to_datetime(df_c['date'])
        print(f"\n[NIFTY 23950 CE 15m Candles Today]")
        today_c = df_c[df_c['date'].dt.date == dt.now().date()]
        for idx, row in today_c.iterrows():
            print(f"  {row['date'].strftime('%H:%M')} | O: {row['open']:.2f} | H: {row['high']:.2f} | L: {row['low']:.2f} | C: {row['close']:.2f} | V: {row['volume']}")
