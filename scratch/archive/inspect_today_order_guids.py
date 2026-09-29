import os, sys
from pathlib import Path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

from common.session import load_kite_session, safe_kite_call
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

orders = safe_kite_call(kite.orders)
for o in orders:
    print(f"--- Order {o.get('order_id')} ---")
    print(f"Symbol: {o.get('tradingsymbol')} | Side: {o.get('transaction_type')} | Qty: {o.get('quantity')}")
    print(f"Status: {o.get('status')} | Variety: {o.get('variety')} | Product: {o.get('product')} | OrderType: {o.get('order_type')}")
    print(f"Price: {o.get('price')} | Avg: {o.get('average_price')} | TriggerPrice: {o.get('trigger_price')}")
    print(f"Tag: {o.get('tag')} | GUID: {o.get('guid')} | Timestamp: {o.get('order_timestamp')}")
    print(f"Status Msg: {o.get('status_message')}")
