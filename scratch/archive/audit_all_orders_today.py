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

sym_filter = sys.argv[1].upper() if len(sys.argv) > 1 else ""

print(f"=== ORDERS TODAY FILTER='{sym_filter}' ===")
for o in orders:
    ts = str(o.get('order_timestamp', ''))
    sym = str(o.get('tradingsymbol', ''))
    if ts.startswith(today_str) and (not sym_filter or sym_filter in sym):
        oid = o.get('order_id')
        txn = o.get('transaction_type')
        qty = o.get('quantity')
        p = o.get('price')
        ap = o.get('average_price')
        st = o.get('status')
        msg = o.get('status_message') or ''
        tag = o.get('tag')
        guid = o.get('guid')
        ot = o.get('order_type')
        prod = o.get('product')
        var = o.get('variety')
        time_part = ts[11:19]
        print(f"[{time_part}] #{oid} | {txn} {qty} {sym} ({prod}/{ot}) @ req={p}, avg={ap} -> {st}")
        if msg:
            print(f"    Message: {msg}")
        if tag or guid:
            print(f"    Tag: {tag} | GUID: {guid}")
