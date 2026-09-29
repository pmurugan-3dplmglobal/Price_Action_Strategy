import os
import json
import sqlite3
import pandas as pd
from datetime import datetime as dt
import sys

sys.path.insert(0, ".")
from common.trading_core import load_kite_session
from kiteconnect import KiteConnect

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

print("================================================================================")
print("                       TODAY'S KITE BROKER TRADE AUDIT")
print("================================================================================")
orders = kite.orders()
today_str = dt.now().strftime("%Y-%m-%d")
today_orders = [o for o in orders if str(o.get("order_timestamp", "")).startswith(today_str)]

# Group executed orders by tradingsymbol
executed_orders = [o for o in today_orders if o.get("status") == "COMPLETE"]
print(f"Total Completed Orders on Kite Today: {len(executed_orders)}")

trades_by_symbol = {}
for o in executed_orders:
    ts = o.get("tradingsymbol")
    if ts not in trades_by_symbol:
        trades_by_symbol[ts] = []
    trades_by_symbol[ts].append({
        "order_id": o.get("order_id"),
        "time": str(o.get("order_timestamp", ""))[:19],
        "txn": o.get("transaction_type"),
        "qty": o.get("quantity"),
        "price": o.get("average_price"),
        "product": o.get("product")
    })

positions = kite.positions()
net_pos = positions.get("net", [])

print("\n--- POSITION PERFORMANCE SUMMARY ---")
summary_data = []
for p in net_pos:
    ts = p.get("tradingsymbol")
    qty = p.get("quantity", 0)
    buy_qty = p.get("buy_quantity", 0)
    sell_qty = p.get("sell_quantity", 0)
    buy_val = p.get("buy_value", 0.0)
    sell_val = p.get("sell_value", 0.0)
    buy_p = (buy_val / buy_qty) if buy_qty > 0 else 0.0
    sell_p = (sell_val / sell_qty) if sell_qty > 0 else 0.0
    ltp = p.get("last_price", 0.0)
    pnl = p.get("pnl", 0.0)
    m2m = p.get("m2m", 0.0)
    status = "OPEN" if qty != 0 else "CLOSED"
    summary_data.append({
        "symbol": ts,
        "status": status,
        "qty": qty,
        "buy_qty": buy_qty,
        "sell_qty": sell_qty,
        "avg_buy": buy_p,
        "avg_sell": sell_p,
        "ltp": ltp,
        "pnl": pnl
    })

df_summary = pd.DataFrame(summary_data)
if not df_summary.empty:
    print(df_summary.to_string(index=False))

print("\n================================================================================")
print("                       SCAN DISPLAY / RADAR ANALYSIS")
print("================================================================================")
scan_file = "output/monitor/scan_display.json"
if os.path.exists(scan_file):
    with open(scan_file, "r") as f:
        scan_data = json.load(f)
    print("Type of scan_data:", type(scan_data))
    if isinstance(scan_data, dict):
        print("Keys:", list(scan_data.keys()))
        for k, v in scan_data.items():
            if isinstance(v, list):
                print(f"Key '{k}': {len(v)} items")
                for item in v[:10]:
                    print(" ", item.get("symbol"), item.get("pattern"), item.get("side"), item.get("benchmark"), item.get("current_sl"), item.get("t1"))
            elif isinstance(v, dict):
                print(f"Key '{k}': sub-keys {list(v.keys())[:5]}")
                for sym, info in list(v.items())[:15]:
                    if isinstance(info, dict):
                        print(f"  {sym:12s} | Pattern: {info.get('pattern')} | Side: {info.get('side')} | BM: {info.get('benchmark')} | SL: {info.get('sl') or info.get('current_sl')} | T1: {info.get('t1')} | Tier: {info.get('tier_badge')}")

print("\n================================================================================")
print("                       TRADE JOURNAL LOGS (CSV)")
print("================================================================================")
journal_path = "output/trade_journal.csv"
if os.path.exists(journal_path):
    with open(journal_path, "r") as f:
        lines = [l.strip() for l in f if today_str in l or "Timestamp" in l or "Date" in l]
    print(f"Total journal entries today: {len(lines)}")
    for l in lines[-15:]:
        print(" ", l)

