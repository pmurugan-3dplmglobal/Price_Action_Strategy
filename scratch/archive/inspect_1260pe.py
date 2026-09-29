import sys, os
sys.path.insert(0, 'common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

orders = kite.orders()
for o in orders:
    if '1260PE' in o.get('tradingsymbol', ''):
        print(f"{o.get('order_timestamp')} | {o.get('transaction_type')} {o.get('tradingsymbol')} Qty: {o.get('quantity')} @ {o.get('average_price')} | tag: {o.get('tag')} | guid: {o.get('guid')}")
