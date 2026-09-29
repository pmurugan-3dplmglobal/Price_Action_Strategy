import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "common"))

import sqlite3, json, csv
from common import paths, trade_db
from common.trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

print("=== ALL BROKER ORDERS TODAY (2026-09-24) ===")
orders = kite.orders()
today_str = "2026-09-24"
orders_today = [o for o in orders if str(o.get("order_timestamp", "")).startswith(today_str)]
print(f"Total orders placed today: {len(orders_today)}")

completed_orders = [o for o in orders_today if o.get("status") == "COMPLETE"]
print(f"Completed orders today: {len(completed_orders)}")

for o in completed_orders:
    print(f"Time: {str(o.get('order_timestamp'))[11:19]} | Sym: {o.get('tradingsymbol')} | Tx: {o.get('transaction_type')} | Qty: {o.get('quantity')} | AvgP: {o.get('average_price')} | Tag: {o.get('tag')}")

rejected_orders = [o for o in orders_today if o.get("status") == "REJECTED"]
print(f"\nRejected orders today: {len(rejected_orders)}")
for o in rejected_orders:
    print(f"Time: {str(o.get('order_timestamp'))[11:19]} | Sym: {o.get('tradingsymbol')} | Tx: {o.get('transaction_type')} | Qty: {o.get('quantity')} | Msg: {o.get('status_message')}")

print("\n=== KITE NET POSITIONS ===")
pos = kite.positions().get("net", [])
for p in pos:
    print(f"Sym: {p.get('tradingsymbol')} | Qty: {p.get('quantity')} | BuyAvg: {p.get('buy_price')} | SellAvg: {p.get('sell_price')} | M2M: {p.get('m2m')} | PnL: {p.get('pnl')} | LTP: {p.get('last_price')}")
