import sys
sys.path.insert(0, 'common')
sys.path.insert(0, 'Trade_Option')
import trade_db, json
from trading_core import load_kite_session, safe_kite_call
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

# 1. Orders on Kite
orders = safe_kite_call(kite.orders) or []
for o in orders:
    ts = str(o.get('tradingsymbol'))
    if 'JIOFIN' in ts:
        print(f"ORDER: {o.get('order_id')} | {ts} | {o.get('transaction_type')} | Qty: {o.get('quantity')} | Price: {o.get('price')} | Status: {o.get('status')} | Reason: {o.get('status_message')}")

# 2. Trade DB
trades = trade_db.get_all_trades('nifty50')
for t in trades:
    if 'JIOFIN' in str(t.get('symbol')) or 'JIOFIN' in str(t.get('contract')):
        print("TRADE_DB:", json.dumps(t, indent=2, default=str))
