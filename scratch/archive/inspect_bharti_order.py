import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

py_snippet = """
import json
from kiteconnect import KiteConnect

ak = "jgdjmtymfyea4yn4"
at_path = "input/kite_access_token.txt"
with open(at_path) as f:
    raw = f.read().strip()
    try:
        at_data = json.loads(raw)
        at = at_data.get("access_token", raw)
    except Exception:
        at = raw

kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

orders = kite.orders()
target_orders = [o for o in orders if 'BHARTIARTL' in str(o.get('tradingsymbol')) or str(o.get('order_id')) in ['260923170184513', '260923170184305']]

print(f"Total matching orders found: {len(target_orders)}")
for o in target_orders:
    print(f"Order ID: {o.get('order_id')} | Sym: {o.get('tradingsymbol')} | Type: {o.get('transaction_type')} | Status: {o.get('status')} | Price: {o.get('price')} | Qty: {o.get('quantity')} | Time: {o.get('order_timestamp')}")
    print(f"   Status Message: {o.get('status_message')}")
    print(f"   Status Message Raw: {o.get('status_message_raw')}")
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@129.225.69.131",
       "cd /home/trade/Trade_Kite/Price_Action_Strategy && /home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python -"]
res = subprocess.run(cmd, input=py_snippet, capture_output=True, text=True)
print("=== BHAVANI VM2 BHARTIARTL ORDER AUDIT ===")
print(res.stdout or res.stderr)
