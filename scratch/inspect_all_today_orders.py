import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiteconnect import KiteConnect
from common.session import load_kite_session

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

orders = kite.orders()
print("=== ALL KITE ORDERS TODAY ===")
for o in orders:
    ts = str(o.get('order_timestamp', ''))
    if ts.startswith('2026-09-22'):
        sym = o.get('tradingsymbol')
        tt = o.get('transaction_type')
        var = o.get('variety')
        tag = o.get('tag')
        stat = o.get('status')
        price = o.get('average_price') or o.get('price')
        qty = o.get('filled_quantity') or o.get('quantity')
        print(f"{ts} | {sym} | {tt} {qty} @ {price} | Variety: {var} | Tag: {tag} | Status: {stat}")
