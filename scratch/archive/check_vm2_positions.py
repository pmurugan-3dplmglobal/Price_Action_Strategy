import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

py_snippet = """
import json
from kiteconnect import KiteConnect

ak = "jgdjmtymfyea4yn4"
with open("input/kite_access_token.txt") as f:
    raw = f.read().strip()
    try:
        at = json.loads(raw).get("access_token", raw)
    except Exception:
        at = raw

kite = KiteConnect(api_key=ak)
kite.set_access_token(at)
pos = kite.positions()
net = pos.get("net", [])
print(f"Total Net Positions: {len(net)}")
for p in net:
    qty = p.get("quantity", 0)
    if qty != 0:
        tsym = p.get("tradingsymbol")
        bp = p.get("buy_price")
        ltp = p.get("last_price")
        pnl = p.get("pnl")
        print(f"  {tsym} | Qty: {qty} | BuyPrice: {bp} | LTP: {ltp} | PnL: {pnl}")
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@129.225.69.131",
       "cd /home/trade/Trade_Kite/Price_Action_Strategy && /home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python -"]
res = subprocess.run(cmd, input=py_snippet, capture_output=True, text=True)
print("=== BHAVANI KITE OPEN POSITIONS ===")
print(res.stdout or res.stderr)
