import os, sys
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

import json
from datetime import datetime
from common.session import load_kite_session, safe_kite_call
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

orders = safe_kite_call(kite.orders)
positions = safe_kite_call(kite.positions)

today_str = datetime.now().strftime("%Y-%m-%d")
print(f"=== ALL ORDERS ON KITE ({today_str}) ===")
for o in orders:
    ts = str(o.get('order_timestamp', ''))
    # Filter for today if needed or display all
    print(f"ID: {o.get('order_id')} | Sym: {o.get('tradingsymbol')} | Side: {o.get('transaction_type')} | Qty: {o.get('quantity')} | Price: {o.get('price')} | Avg: {o.get('average_price')} | Status: {o.get('status')} | Tag: {o.get('tag')} | Time: {ts} | Msg: {o.get('status_message')}")

print("\n=== NET POSITIONS ===")
for p in positions.get('net', []):
    qty = p.get('quantity', 0)
    pnl = p.get('pnl', 0)
    m2m = p.get('m2m', 0)
    unrealised = p.get('unrealised', 0)
    realised = p.get('realised', 0)
    buy_p = p.get('buy_price', 0) or p.get('average_price', 0)
    ltp = p.get('last_price', 0)
    sym = p.get('tradingsymbol', '')
    day_buy_q = p.get('day_buy_quantity', 0)
    day_sell_q = p.get('day_sell_quantity', 0)
    print(f"Sym: {sym:25} | Net Qty: {qty:5} | DayBuy: {day_buy_q:5} | DaySell: {day_sell_q:5} | BuyPrice: {buy_p:7.2f} | LTP: {ltp:7.2f} | Realized: {realised:8.2f} | Unrealized: {unrealised:8.2f} | Total PnL: {pnl:8.2f}")

print("\n=== DAY POSITIONS ===")
for p in positions.get('day', []):
    qty = p.get('quantity', 0)
    pnl = p.get('pnl', 0)
    sym = p.get('tradingsymbol', '')
    print(f"Sym: {sym:25} | Qty: {qty:5} | PnL: {pnl:8.2f}")
