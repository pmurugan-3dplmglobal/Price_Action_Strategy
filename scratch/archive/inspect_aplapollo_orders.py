import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiteconnect import KiteConnect
from common.session import load_kite_session, optimize_kite_session
from datetime import datetime
import json
import sqlite3

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

orders = kite.orders()
apla_orders = [o for o in orders if "APLAPOLLO" in o.get("tradingsymbol", "") and str(o.get("order_timestamp", "")).startswith("2026-09-22")]

print("=== APLAPOLLO KITE ORDER DETAILS ===")
for o in apla_orders:
    print(f"Order ID: {o.get('order_id')}")
    print(f"  Symbol: {o.get('tradingsymbol')}")
    print(f"  Type: {o.get('transaction_type')} | Qty: {o.get('quantity')} | Price: {o.get('price')} | AvgPrice: {o.get('average_price')}")
    print(f"  Timestamp: {o.get('order_timestamp')}")
    print(f"  Status: {o.get('status')}")
    print(f"  Tag: {o.get('tag')}")
    print(f"  Placed By: {o.get('placed_by')}")
    print(f"  Variety: {o.get('variety')}")
    print(f"  Product: {o.get('product')}")
    print("-" * 50)

# Calculate exact time difference
if len(apla_orders) >= 2:
    t1_str = str(apla_orders[0].get("order_timestamp"))
    t2_str = str(apla_orders[1].get("order_timestamp"))
    fmt = "%Y-%m-%d %H:%M:%S"
    dt1 = datetime.strptime(t1_str, fmt)
    dt2 = datetime.strptime(t2_str, fmt)
    diff = dt2 - dt1
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60
    seconds = diff.seconds % 60
    print(f"\nExact Time Difference: {diff.total_seconds()} seconds ({hours}h {minutes}m {seconds}s)")

# Database Records
conn = sqlite3.connect("output/monitor/trades.sqlite3")
rows = conn.execute("SELECT id, symbol, contract, status, created_at, data_json FROM trades WHERE id IN (793, 807)").fetchall()
print("\n=== DATABASE RECORDS IN TRADES.SQLITE3 ===")
for r in rows:
    tid, sym, cnt, st, cat, dj = r
    d = json.loads(dj) if dj else {}
    print(f"Trade ID: {tid} | Contract: {cnt} | CreatedAt: {cat}")
    print(f"  Pattern: {d.get('pattern')}")
    print(f"  User Edited / Manual Flag: {d.get('user_edited')}")
    print(f"  Execution Type: {d.get('execution_type')}")
    print(f"  Order ID: {d.get('order_id')}")
    print(f"  Strategy: {d.get('strategy')}")
    print("-" * 50)
