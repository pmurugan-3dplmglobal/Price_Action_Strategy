import json
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from common import session
from kiteconnect import KiteConnect

ak, at = session.load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

print("=" * 80)
print("FETCHING LIVE POSITIONS & DAY'S PNL DIRECTLY FROM ZERODHA KITE")
print("=" * 80)

positions = kite.positions()
net = positions.get("net", [])
day = positions.get("day", [])

total_pnl = 0.0
print("\n--- NET POSITIONS TODAY ---")
for p in net:
    qty = p.get("quantity", 0)
    buy_p = p.get("average_price", 0)
    ltp = p.get("last_price", 0)
    pnl = p.get("pnl", 0)
    total_pnl += pnl
    status = "OPEN" if qty != 0 else "CLOSED"
    print(f"[{status}] {p.get('tradingsymbol')} | Qty: {qty} | BuyAvg: {buy_p:.2f} | LTP: {ltp:.2f} | PnL: Rs. {pnl:+,.2f}")

print("-" * 80)
print(f"TOTAL REALIZED + UNREALIZED PnL: Rs. {total_pnl:+,.2f}")
print("=" * 80)
