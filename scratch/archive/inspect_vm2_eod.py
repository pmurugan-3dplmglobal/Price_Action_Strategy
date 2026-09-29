import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
code = """
import sys, os, json
from datetime import datetime as dt
sys.path.insert(0, 'common')
from trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

orders = kite.orders()
today_str = dt.now().strftime("%Y-%m-%d")
print("=== VM2 COMPLETED ORDERS TODAY ===")
for o in orders:
    if str(o.get("order_timestamp", "")).startswith(today_str) and o.get("status") == "COMPLETE":
        print(f"Order #{o.get('order_id')} | {o.get('order_timestamp')} | {o.get('transaction_type')} {o.get('tradingsymbol')} Qty: {o.get('quantity')} @ {o.get('average_price')}")

pos = kite.positions()
print("\n=== VM2 NET POSITIONS ===")
for p in pos.get("net", []):
    ts = p.get("tradingsymbol")
    q = p.get("quantity", 0)
    pnl = p.get("pnl", 0)
    ltp = p.get("last_price", 0)
    if q != 0 or pnl != 0:
        print(f"{ts}: Qty={q}, LTP={ltp}, PnL={pnl}")
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@129.225.69.131", "cd /home/trade/Trade_Kite/Price_Action_Strategy && ./venv/bin/python -"]
res = subprocess.run(cmd, input=code, capture_output=True, text=True, encoding="utf-8", errors="replace")
print(res.stdout or res.stderr)
