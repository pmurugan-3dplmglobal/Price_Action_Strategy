import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from kiteconnect import KiteConnect
from common.session import load_kite_session, optimize_kite_session

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
optimize_kite_session(kite)

orders = kite.orders()
canbk_orders = [o for o in orders if 'CANBK' in o.get('tradingsymbol', '')]
print(f'=== CANBK ORDERS ({len(canbk_orders)}) ===')
for o in canbk_orders:
    print(f"{o.get('order_timestamp')} | {o.get('order_id')} | {o.get('tradingsymbol')} | {o.get('transaction_type')} | Qty: {o.get('quantity')} | Price: {o.get('price')} | AvgPrice: {o.get('average_price')} | Status: {o.get('status')} | StatusMsg: {o.get('status_message')}")

positions = kite.positions().get('net', [])
canbk_pos = [p for p in positions if 'CANBK' in p.get('tradingsymbol', '')]
print(f'\n=== CANBK POSITIONS ({len(canbk_pos)}) ===')
for p in canbk_pos:
    print(f"{p.get('tradingsymbol')} | Qty: {p.get('quantity')} | BuyPrice: {p.get('buy_price')} | SellPrice: {p.get('sell_price')} | M2M: {p.get('m2m')} | PnL: {p.get('pnl')} | LTP: {p.get('last_price')}")

# Get quotes for CANBK spot and options
keys = ['NSE:CANBK', 'NFO:CANBK26SEP125CE', 'NFO:CANBK26SEP130CE', 'NFO:CANBK26SEP122.5CE', 'NFO:CANBK26SEP120CE']
quotes = kite.quote(keys)
print('\n=== LIVE QUOTES & DEPTH ===')
for k, q in quotes.items():
    depth = q.get('depth', {})
    buy_top = depth.get('buy', [{}])[0] if depth.get('buy') else {}
    sell_top = depth.get('sell', [{}])[0] if depth.get('sell') else {}
    bid = buy_top.get('price', 0)
    bid_qty = buy_top.get('quantity', 0)
    ask = sell_top.get('price', 0)
    ask_qty = sell_top.get('quantity', 0)
    ltp = q.get('last_price', 0)
    spread = round(ask - bid, 4) if (ask and bid) else 0
    spread_pct = round((spread / ltp * 100), 2) if ltp else 0
import sqlite3
conn = sqlite3.connect('output/monitor/trades.sqlite3')
rows = conn.execute("SELECT id, engine, symbol, contract, status, created_at, updated_at FROM trades WHERE symbol='CANBK' ORDER BY id DESC").fetchall()
print('\n=== CANBK IN TRADES DB ===')
for r in rows:
    print(r)
