import os, sys, json, sqlite3
from datetime import datetime as dt

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
COMMON_DIR = os.path.join(PROJECT_ROOT, "common")
for p in [PROJECT_ROOT, COMMON_DIR]:
    if p not in sys.path:
        sys.path.insert(0, p)

import paths
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from session import load_kite_session
from kiteconnect import KiteConnect

api_k, acc_t = load_kite_session(paths.TOKEN_FILE)
kite = KiteConnect(api_key=api_k)
kite.set_access_token(acc_t)

print("=== KITE ORDERS (POLYCAB) ===", flush=True)
orders = kite.orders()
poly_orders = [o for o in orders if "POLYCAB" in o.get("tradingsymbol", "")]
for o in poly_orders:
    ts = o.get("order_timestamp")
    sym = o.get("tradingsymbol")
    tx = o.get("transaction_type")
    qty = f"{o.get('filled_quantity')}/{o.get('quantity')}"
    price = o.get("average_price")
    stat = o.get("status")
    tag = o.get("tag")
    msg = o.get("status_message")
    print(f"{ts} | {sym} | {tx} | Qty: {qty} | AvgPrice: {price} | Status: {stat} | Tag: {tag} | Msg: {msg}", flush=True)

print("\n=== KITE TRADES (POLYCAB) ===", flush=True)
trades = kite.trades()
poly_trades = [t for t in trades if "POLYCAB" in t.get("tradingsymbol", "")]
for t in poly_trades:
    ts = t.get("fill_timestamp")
    sym = t.get("tradingsymbol")
    tx = t.get("transaction_type")
    qty = t.get("quantity")
    price = t.get("average_price")
    tid = t.get("trade_id")
    print(f"{ts} | {sym} | {tx} | Qty: {qty} | Price: {price} | TradeId: {tid}", flush=True)

print("\n=== KITE POSITIONS (POLYCAB) ===", flush=True)
positions = kite.positions()
net_pos = [p for p in positions.get("net", []) if "POLYCAB" in p.get("tradingsymbol", "")]
day_pos = [p for p in positions.get("day", []) if "POLYCAB" in p.get("tradingsymbol", "")]
print("NET:", net_pos, flush=True)
print("DAY:", day_pos, flush=True)

print("\n=== SQLITE TRADES DB (POLYCAB) ===", flush=True)
db_path = paths.TRADES_DB
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM trades WHERE symbol LIKE '%POLYCAB%' OR contract LIKE '%POLYCAB%'")
    rows = cur.fetchall()
    for r in rows:
        print(dict(r), flush=True)

print("\n=== JOURNAL FILE (POLYCAB) ===", flush=True)
jfile = os.path.join(PROJECT_ROOT, "output", "journal.json")
if os.path.exists(jfile):
    try:
        with open(jfile) as f:
            jdata = json.load(f)
        for item in jdata:
            if "POLYCAB" in str(item):
                print(item, flush=True)
    except Exception as e:
        print("Journal read err:", e, flush=True)
