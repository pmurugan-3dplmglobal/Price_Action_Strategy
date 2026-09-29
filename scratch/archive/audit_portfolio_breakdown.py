import sys
sys.path.insert(0, 'common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

contracts_to_check = [
    'BAJAJFINSV26SEP1860PE',
    'APLAPOLLO26SEP2200PE',
    'WIPRO26SEP160CE',
    'NIFTY2692223450PE',
    'APLAPOLLO26SEP2180PE',
    'GODREJPROP26SEP1700CE',
    'NAUKRI26SEP1300PE',
    'NAUKRI26SEP1260PE',
    'INFY26SEP1020CE',
    'ASIANPAINT26SEP2460CE',
    'JSWENERGY26SEP520CE',
    'CANBK26SEP125CE',
    'ICICIGI26SEP1500PE'
]

net_pos = {p['tradingsymbol']: p for p in kite.positions().get('net', [])}
orders = kite.orders()

print("=" * 140)
print(f"{'CONTRACT':<24} | {'STATUS':<15} | {'QTY':<5} | {'BUY':<7} | {'SELL':<7} | {'LTP':<7} | {'PNL (Rs)':<10} | {'LAST ORDER DETAILS'}")
print("=" * 140)

for c in contracts_to_check:
    pos_info = net_pos.get(c)
    related_orders = [o for o in orders if o.get('tradingsymbol') == c]
    last_o = related_orders[-1] if related_orders else None
    
    qty = pos_info.get('quantity', 0) if pos_info else 0
    pnl = pos_info.get('pnl', 0.0) if pos_info else 0.0
    ltp = pos_info.get('last_price', 0.0) if pos_info else (last_o.get('price', 0.0) if last_o else 0.0)
    buy_p = pos_info.get('buy_price', 0.0) if pos_info else 0.0
    sell_p = pos_info.get('sell_price', 0.0) if pos_info else 0.0
    
    status_str = 'ACTIVE (HELD)' if qty != 0 else ('CLOSED' if pos_info else 'NEVER_FILLED')
    
    if last_o:
        otype = last_o.get('transaction_type')
        oqty = last_o.get('quantity')
        oprice = last_o.get('average_price') or last_o.get('price')
        ostat = last_o.get('status')
        omsg = last_o.get('status_message') or ''
        last_o_summary = f"{otype} {oqty} @ {oprice} [{ostat}] {omsg}"
    else:
        last_o_summary = "No orders found today"
    
    print(f"{c:<24} | {status_str:<15} | {qty:<5} | {buy_p:<7.2f} | {sell_p:<7.2f} | {ltp:<7.2f} | {pnl:<10.2f} | {last_o_summary}")

print("=" * 140)
