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
print("=== INFY & SBIN ORDERS ===")
for o in orders:
    sym = o.get('tradingsymbol', '')
    if 'INFY' in sym or 'SBIN' in sym:
        print(f"Time: {o.get('order_timestamp')} | Sym: {sym} | Side: {o.get('transaction_type')} | Qty: {o.get('quantity')} | Price: {o.get('price')} | Avg: {o.get('average_price')} | Status: {o.get('status')} | Tag: {o.get('tag')} | GUID: {o.get('guid')} | Msg: {o.get('status_message')}")
