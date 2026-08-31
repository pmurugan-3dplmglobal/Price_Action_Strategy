import os
import sys
import json
import sqlite3
import pandas as pd

_COMMON_DIR = os.path.join(os.getcwd(), "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

import paths
from kiteconnect import KiteConnect
from session import load_kite_session

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

print("==================================================")
print(" AUDIT: ALL ACTIVE POSITIONS & ASSIGNED SL/TARGETS")
print("==================================================")

pos = kite.positions().get("net", [])
active_kite = [p for p in pos if int(p.get("quantity", 0)) > 0]

db_path = os.path.join("output", "monitor", "trades.sqlite3")
conn = sqlite3.connect(db_path)
cur = conn.cursor()

for p in active_kite:
    tsym = p.get("tradingsymbol")
    qty = p.get("quantity")
    buy_avg = p.get("average_price") or p.get("buy_price")
    ltp = p.get("last_price")
    
    cur.execute("SELECT id, engine, symbol, contract, status, data_json FROM trades WHERE contract = ? AND status = 'ACTIVE' ORDER BY id DESC LIMIT 1", (tsym,))
    row = cur.fetchone()
    if row:
        dj = json.loads(row[5])
        sl = dj.get("current_sl")
        t1 = dj.get("t1")
        t2 = dj.get("t2")
        t3 = dj.get("t3")
        spot_sl = dj.get("spot_sl")
        pattern = dj.get("pattern")
        print(f"\n[{tsym}] (Qty: {qty})")
        print(f"  Live LTP: {ltp} | Buy Price: {buy_avg}")
        print(f"  Assigned SL: {sl} | T1: {t1} | T2: {t2} | T3: {t3}")
        print(f"  Spot SL: {spot_sl} | Pattern: {pattern}")
    else:
        print(f"\n[{tsym}] (Qty: {qty})")
        print(f"  Live LTP: {ltp} | Buy Price: {buy_avg}")
        print(f"  [WARNING] No active SQLite record found!")

conn.close()
