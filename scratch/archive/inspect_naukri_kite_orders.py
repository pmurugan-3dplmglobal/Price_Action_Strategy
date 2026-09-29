import sys, os, json
sys.path.insert(0, 'common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect
from datetime import datetime as dt

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

orders = kite.orders()
today_str = dt.now().strftime("%Y-%m-%d")
print("=== NAUKRI ORDERS ON KITE TODAY ===")
for o in orders:
    if "NAUKRI" in o.get("tradingsymbol", "") and str(o.get("order_timestamp", "")).startswith(today_str):
        print(f"Order #{o.get('order_id')} | {o.get('order_timestamp')} | {o.get('transaction_type')} {o.get('tradingsymbol')} Qty: {o.get('quantity')} @ Avg: {o.get('average_price')} (Status: {o.get('status')})")
        print(f"  Tag: {o.get('tag')} | GUID: {o.get('guid')} | Status Msg: {o.get('status_message')}")
