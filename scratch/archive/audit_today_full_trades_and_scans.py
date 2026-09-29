import os
import json
import sqlite3
import pandas as pd
from datetime import datetime as dt
import sys

sys.path.insert(0, ".")
from common.trading_core import load_kite_session
from kiteconnect import KiteConnect

print("=== 1. KITE LIVE POSITIONS & ORDERS ===")
api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

orders = kite.orders()
today_str = dt.now().strftime("%Y-%m-%d")
today_orders = [o for o in orders if str(o.get("order_timestamp", "")).startswith(today_str)]
print(f"Total orders placed today ({today_str}): {len(today_orders)}")

positions = kite.positions()
net_pos = positions.get("net", [])
day_pos = positions.get("day", [])

print("\n--- Net Positions (Today) ---")
tot_pnl = 0.0
for p in net_pos:
    ts = p.get("tradingsymbol")
    qty = p.get("quantity", 0)
    buy_p = p.get("average_price", 0.0)
    sell_p = p.get("sell_price", 0.0)
    ltp = p.get("last_price", 0.0)
    pnl = p.get("pnl", 0.0)
    tot_pnl += pnl
    status = "OPEN" if qty != 0 else "CLOSED"
    print(f"[{status}] {ts:25s} | Qty: {qty:5d} | Buy: {buy_p:8.2f} | Sell: {sell_p:8.2f} | LTP: {ltp:8.2f} | PnL: {pnl:10.2f}")

print(f"\nTotal Kite Portfolio PnL: Rs {tot_pnl:,.2f}")

print("\n=== 2. TODAY'S TRADES IN TRADES.SQLITE3 ===")
db_path = "output/monitor/trades.sqlite3"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE created_at LIKE ? OR updated_at LIKE ?", (f"{today_str}%", f"{today_str}%"))
    rows = cur.fetchall()
    print(f"Total DB records touched today: {len(rows)}")
    for r in rows:
        d = json.loads(r["data_json"]) if r["data_json"] else {}
        print(f"Trade #{r['id']} | {r['symbol']} ({r['contract']}) | Status: {r['status']} | Entry: {d.get('entry_spot') or d.get('entry_price')} | SL: {d.get('current_sl')} | T1: {d.get('t1')} | PnL: {d.get('pnl')} | Exit Reason: {d.get('exit_reason') or d.get('details')}")

print("\n=== 3. SCANNED DISPLAY SETUPS TODAY ===")
scan_file = "output/monitor/scan_display.json"
if os.path.exists(scan_file):
    with open(scan_file, "r") as f:
        scan_data = json.load(f)
    print(f"Total scanned setups in scan_display: {len(scan_data)}")
    for s in scan_data[:20]:
        print(f"  {s.get('symbol')} | {s.get('pattern')} | {s.get('timeframe')} | Side: {s.get('side')} | Benchmark: {s.get('benchmark')} | SL: {s.get('sl')} | T1: {s.get('t1')} | Tier: {s.get('tier_badge')} | Conf: {s.get('confidence_score')}")

