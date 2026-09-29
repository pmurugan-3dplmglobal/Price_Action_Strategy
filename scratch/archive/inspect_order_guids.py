import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from kiteconnect import KiteConnect
from common.session import load_kite_session, ensure_kite_session
from common.paths import TOKEN_FILE

api_key, access_token = load_kite_session(TOKEN_FILE)
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
ensure_kite_session(kite)

orders = kite.orders()
target_ids = ["260929191160303", "260929191187141"]
for o in orders:
    if o.get("order_id") in target_ids:
        print("=" * 60)
        print("ORDER DETAILS:", o.get("order_id"), o.get("tradingsymbol"))
        print(f"  variety: {o.get('variety')}")
        print(f"  order_type: {o.get('order_type')}")
        print(f"  price: {o.get('price')}")
        print(f"  status: {o.get('status')}")
        print(f"  tag: {o.get('tag')}")
        print(f"  guid: {o.get('guid')}")
        print(f"  order_timestamp: {o.get('order_timestamp')}")
        print(f"  exchange_order_id: {o.get('exchange_order_id')}")
        print(f"  status_message: {o.get('status_message')}")
