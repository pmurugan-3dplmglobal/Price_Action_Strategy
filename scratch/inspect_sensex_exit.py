import os
import sys
import json
import sqlite3
import pandas as pd
from datetime import datetime as dt, timedelta

_COMMON_DIR = os.path.join(os.getcwd(), "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)

from kiteconnect import KiteConnect
from session import load_kite_session, safe_kite_call

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

print("==================================================")
print(" SENSEX 03SEP 77200 CE EXIT AUDIT")
print("==================================================")

# 1. Orders for SENSEX
orders = safe_kite_call(kite.orders) or []
print("\n[Kite Orders for SENSEX]:")
for o in orders:
    tsym = o.get("tradingsymbol", "")
    if "SENSEX" in tsym:
        print(f"  {o.get('order_timestamp')} | {tsym} | {o.get('transaction_type')} | Qty: {o.get('filled_quantity')}/{o.get('quantity')} | Price: {o.get('price')} | AvgPrice: {o.get('average_price')} | Status: {o.get('status')} | Tag: {o.get('tag')} | StatusMsg: {o.get('status_message')}")

# 2. Net positions for SENSEX
positions = safe_kite_call(kite.positions) or {}
print("\n[Kite Positions for SENSEX]:")
for p in positions.get("net", []):
    if "SENSEX" in p.get("tradingsymbol", ""):
        print(f"  {p.get('tradingsymbol')}: Qty={p.get('quantity')} | BuyQty={p.get('buy_quantity')} | SellQty={p.get('sell_quantity')} | BuyAvg={p.get('average_price')} | SellAvg={p.get('sell_price')} | PnL={p.get('pnl')}")

# 3. SQLite trades for SENSEX
db_path = os.path.join("output", "monitor", "trades.sqlite3")
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT id, engine, symbol, contract, status, data_json, created_at, updated_at FROM trades WHERE contract LIKE '%SENSEX%' OR symbol = 'SENSEX' ORDER BY id DESC LIMIT 5")
    rows = cur.fetchall()
    print(f"\n[SQLite SENSEX Trades: {len(rows)}]:")
    for r in rows:
        print(f"  ID {r[0]} | {r[3]} | Status: {r[4]} | Created: {r[6]} | Updated: {r[7]}")
        try:
            dj = json.loads(r[5])
            print(f"    Entry: {dj.get('entry_spot')} | SL: {dj.get('current_sl')} | T1: {dj.get('t1')} | ExitPrice: {dj.get('exit_price')} | ExitReason: {dj.get('exit_reason')} | Details: {dj.get('details')}")
        except:
            pass
    conn.close()

# 4. executed_exit_orders.json
ex_path = os.path.join("output", "monitor", "executed_exit_orders.json")
if os.path.exists(ex_path):
    with open(ex_path) as f:
        ex = json.load(f)
    print(f"\n[executed_exit_orders.json for SENSEX]:")
    for k, v in ex.items():
        if "SENSEX" in k:
            print(f"  {k}: {v}")

# 5. Logs for SENSEX
print(f"\n[Logs for SENSEX]:")
log_f = os.path.join("output", "logs", "bull_index_trade_engine.log")
if os.path.exists(log_f):
    with open(log_f, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if "SENSEX" in line:
                print(f"  {line.strip()}")
