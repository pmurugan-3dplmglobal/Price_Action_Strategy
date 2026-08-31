import os
import sys
_COMMON_DIR = os.path.join(os.getcwd(), "common")
if _COMMON_DIR not in sys.path:
    sys.path.insert(0, _COMMON_DIR)
from kiteconnect import KiteConnect
from session import load_kite_session

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

orders = kite.orders()
print("=== TODAY'S ORDERS ===")
for o in orders:
    tsym = o.get("tradingsymbol", "")
    print(f"{o.get('order_timestamp')} | {tsym} | {o.get('transaction_type')} | Qty: {o.get('filled_quantity')}/{o.get('quantity')} | Price: {o.get('price')} | Avg: {o.get('average_price')} | Status: {o.get('status')}")
