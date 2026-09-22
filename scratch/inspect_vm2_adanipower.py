import subprocess

SSH_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
VM2_IP = "129.225.69.131"
VM2_DIR = "/home/trade/Trade_Kite/Price_Action_Strategy"

BASH_SCRIPT = r'''#!/usr/bin/env bash
cd /home/trade/Trade_Kite/Price_Action_Strategy

echo "=== 1. ALL LOGS FOR ADANIPOWER TODAY (09:00 to 22:00) ==="
journalctl -u trading-options -u trading-stock --since "2026-09-16 09:00:00" | grep -i "ADANIPOWER" | head -n 40
echo "..."
journalctl -u trading-options -u trading-stock --since "2026-09-16 09:00:00" | grep -i "ADANIPOWER" | tail -n 20

echo "=== 2. CHECK ALL ORDERS PLACED ON KITE ON SEP 15 & SEP 16 ==="
venv/bin/python - << 'PYEOF'
import json, os
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
print(f"Total orders returned from Kite: {len(orders)}")
for o in orders:
    ts = o.get("tradingsymbol", "")
    if "ADANIPOWER" in ts:
        print(f"Time: {o.get('order_timestamp')} | {o.get('transaction_type')} {ts} | Status: {o.get('status')} | Qty: {o.get('filled_quantity')}/{o.get('quantity')} @ {o.get('average_price')} | Trigger: {o.get('trigger_price')} | Tag: {o.get('tag')} | Msg: {o.get('status_message')}")
PYEOF

echo "=== 3. LOOK AT POSITION MONITOR OR TRADE STATE ON VM2 ==="
venv/bin/python - << 'PYEOF'
import glob, json, os

for pat in ["output/*.json", "input/*.json", "output/trades.db"]:
    for p in glob.glob(pat):
        print(p, os.path.getmtime(p))
PYEOF

echo "=== 4. CHECK IF ADANIPOWER WAS IN ANY RECOVERY / MONITOR LIST ==="
journalctl -u trading-options -u trading-stock --since "2026-09-16 09:15:00" --until "2026-09-16 15:35:00" | grep -E "ADANIPOWER|Broker position recovery|Recovered" | head -n 30
'''

p = subprocess.run(
    ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", f"opc@{VM2_IP}", "bash -s"],
    input=BASH_SCRIPT.encode("utf-8"),
    capture_output=True
)
print(p.stdout.decode("utf-8", errors="replace"))
if p.stderr:
    print("STDERR:", p.stderr.decode("utf-8", errors="replace"))
