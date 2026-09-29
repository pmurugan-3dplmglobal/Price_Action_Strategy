import sys
sys.path.insert(0, 'common')
sys.path.insert(0, 'Trade_Option')
from trading_core import load_kite_session, safe_kite_call
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

orders = safe_kite_call(kite.orders) or []
for o in orders:
    ts = str(o.get('tradingsymbol'))
    if 'INDHOTEL' in ts:
        oid = o.get('order_id')
        tt = o.get('transaction_type')
        status = o.get('status')
        msg = o.get('status_message')
        price = o.get('price')
        qty = o.get('quantity')
        print(f"ID: {oid} | Symbol: {ts} | Side: {tt} | Price: {price} | Qty: {qty} | Status: {status} | Reason: {msg}")
