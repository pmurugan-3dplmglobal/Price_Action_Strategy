import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import sqlite3
from kiteconnect import KiteConnect
from common.session import load_kite_session, optimize_kite_session

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
optimize_kite_session(kite)

print("=== 1. KITE ORDERS TODAY ===")
orders = kite.orders()
today_orders = [o for o in orders if str(o.get("order_timestamp", "")).startswith("2026-09-22")]
print(f"Total orders today: {len(today_orders)}")
for o in today_orders:
    print(f"{o.get('order_timestamp')} | ID: {o.get('order_id')} | {o.get('tradingsymbol')} | {o.get('transaction_type')} | Qty: {o.get('filled_quantity')}/{o.get('quantity')} | Price: {o.get('price')} | AvgPrice: {o.get('average_price')} | Status: {o.get('status')} | Reason: {o.get('status_message')}")

print("\n=== 2. KITE POSITIONS TODAY ===")
pos_data = kite.positions()
net_pos = pos_data.get("net", [])
day_pos = pos_data.get("day", [])
print(f"Net positions: {len(net_pos)}, Day positions: {len(day_pos)}")
total_realized = 0.0
total_unrealized = 0.0

for p in net_pos:
    sym = p.get("tradingsymbol")
    qty = p.get("quantity")
    buy_qty = p.get("buy_quantity")
    sell_qty = p.get("sell_quantity")
    buy_val = p.get("buy_value")
    sell_val = p.get("sell_value")
    buy_p = p.get("buy_price")
    sell_p = p.get("sell_price")
    ltp = p.get("last_price")
    pnl = p.get("pnl")
    m2m = p.get("m2m")
    if buy_qty > 0 or sell_qty > 0 or qty != 0:
        total_unrealized += (pnl if qty != 0 else 0)
        realized_pnl = (sell_val - buy_val) if qty == 0 else 0
        total_realized += realized_pnl
        print(f"Symbol: {sym} | Qty: {qty} | BuyPrice: {buy_p:.2f} | SellPrice: {sell_p:.2f} | LTP: {ltp:.2f} | PnL: {pnl:.2f} | M2M: {m2m:.2f}")

print(f"\nSummary: Total Unrealized PnL: Rs {total_unrealized:.2f} | Total Realized PnL: Rs {total_realized:.2f} | Net Total: Rs {total_unrealized + total_realized:.2f}")

print("\n=== 3. TRADES DB TODAY ===")
conn = sqlite3.connect("output/monitor/trades.sqlite3")
trades_today = conn.execute("SELECT id, engine, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE created_at LIKE '2026-09-22%' OR updated_at LIKE '2026-09-22%' ORDER BY id ASC").fetchall()
print(f"Total trades in DB today: {len(trades_today)}")
for t in trades_today:
    tid, eng, sym, contract, status, c_at, u_at, d_json = t
    d = json.loads(d_json) if d_json else {}
    pattern = d.get("pattern")
    tier = d.get("tier_badge", "")
    entry = d.get("entry_spot") or d.get("benchmark")
    sl = d.get("current_sl") or d.get("stop_loss")
    t1 = d.get("t1")
    exit_p = d.get("exit_price")
    exit_r = d.get("exit_reason")
    def clean(s):
        return str(s).encode('ascii', errors='ignore').decode('ascii')
    print(f"ID {tid} | {eng} | {sym} ({contract}) | Status: {status} | Pattern: {clean(pattern)} ({clean(tier)}) | Entry: {entry} | SL: {sl} | T1: {t1} | ExitPrice: {exit_p} | ExitReason: {exit_r}")
