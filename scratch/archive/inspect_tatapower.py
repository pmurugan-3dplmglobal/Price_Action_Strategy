import sqlite3, json, sys, os
sys.path.insert(0, 'common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect

conn = sqlite3.connect('output/monitor/trades.sqlite3')
c = conn.cursor()
c.execute("SELECT id, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE symbol LIKE '%TATAPOWER%' OR contract LIKE '%TATAPOWER%' ORDER BY id DESC LIMIT 3")
rows = c.fetchall()
print(f"=== TATAPOWER TRADES IN DB ({len(rows)}) ===")
for r in rows:
    tid, sym, cnt, st, cat, uat, dj = r
    print(f"ID: {tid} | {sym} | {cnt} | {st} | Created: {cat}")
    d = json.loads(dj) if dj else {}
    print("  Pattern:", d.get("pattern"), "TF:", d.get("timeframe"), "Entry:", d.get("entry_price") or d.get("entry_spot"), "SL:", d.get("current_sl"), "T1:", d.get("t1"))

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
orders = kite.orders()
print("\n=== KITE ORDERS FOR TATAPOWER TODAY ===")
for o in orders:
    if "TATAPOWER" in o.get("tradingsymbol", ""):
        print(f"Order #{o.get('order_id')} | {o.get('order_timestamp')} | {o.get('transaction_type')} {o.get('tradingsymbol')} Qty: {o.get('quantity')} @ Avg: {o.get('average_price')} Status: {o.get('status')}")
        print(f"  Order Type: {o.get('order_type')} | Tag: {o.get('tag')} | GUID: {o.get('guid')}")
