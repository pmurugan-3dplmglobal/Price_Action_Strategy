import sqlite3, json, os, sys
sys.path.insert(0, 'common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect

conn = sqlite3.connect('output/monitor/trades.sqlite3')
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE symbol LIKE '%TMPV%' OR contract LIKE '%TMPV%' ORDER BY id DESC")
rows = c.fetchall()
print(f"=== TMPV TRADES IN DATABASE ({len(rows)}) ===")
for r in rows:
    tid, sym, cnt, st, cat, uat, dj = r
    print(f"Trade ID: {tid} | Symbol: {sym} | Contract: {cnt} | Status: {st} | Created: {cat}")
    d = json.loads(dj) if dj else {}
    print(json.dumps(d, indent=2, default=str))

# Kite orders for TMPV today
ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
orders = kite.orders()
print("\n=== KITE ORDERS FOR TMPV TODAY ===")
for o in orders:
    if "TMPV" in o.get("tradingsymbol", ""):
        print(f"Order #{o.get('order_id')} | {o.get('order_timestamp')} | {o.get('transaction_type')} {o.get('tradingsymbol')} Qty: {o.get('quantity')} @ Avg: {o.get('average_price')} (Req: {o.get('price')}) Status: {o.get('status')}")
        print(f"  Order Type: {o.get('order_type')} | Variety: {o.get('variety')} | Tag: {o.get('tag')} | GUID: {o.get('guid')}")
