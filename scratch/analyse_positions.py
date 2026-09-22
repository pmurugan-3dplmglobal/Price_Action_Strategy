import os, sys, json
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

orders = kite.orders()
print("=== COMPLETED ORDERS TODAY ===")
for o in orders:
    if o.get("status") == "COMPLETE":
        ts = o.get("order_timestamp")
        sym = o.get("tradingsymbol")
        tx = o.get("transaction_type")
        qty = o.get("filled_quantity")
        p = o.get("average_price")
        print(f"{ts} | {sym:<25} | {tx:<4} | Qty: {qty:>5} | Price: {p:>8.2f}")

print("\n=== MARGINS ===")
margins = kite.margins("equity")
print(f"Net Available Margin: Rs. {margins.get('net', 0):,.2f}")
print(f"Utilised Margin    : Rs. {margins.get('utilised', {}).get('debits', 0):,.2f}")
