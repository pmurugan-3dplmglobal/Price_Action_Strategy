import subprocess

SSH_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
VM2_IP = "129.225.69.131"

BASH_SCRIPT = r'''#!/usr/bin/env bash
cd /home/trade/Trade_Kite/Price_Action_Strategy

venv/bin/python - << 'PYEOF'
import sys
sys.path.insert(0, ".")
import common.trade_db as trade_db
import common.paths as paths
print("TRADES_DB path:", paths.TRADES_DB)

print("Active trades in DB:", trade_db.get_active_trades())
print("Completed trades in DB:", trade_db.get_completed_trades())

# Check what monitor_all_active_positions does right now step by step
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

pos_data = kite.positions()
net_pos = [p for p in pos_data.get("net", []) if p.get("tradingsymbol") and int(p.get("quantity", 0)) != 0]
for p in net_pos:
    print("Net position on Kite:", p.get("tradingsymbol"), "qty:", p.get("quantity"), "avg:", p.get("average_price"), "token:", p.get("instrument_token"))

from common.position_monitor import monitor_all_active_positions
print("\nRunning single iteration of monitor_all_active_positions with logging to stdout:")
import logging
logging.basicConfig(level=logging.DEBUG)
res = monitor_all_active_positions(kite, live=True)
print("Result of monitor_all_active_positions:", res)

PYEOF
'''

p = subprocess.run(
    ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", f"opc@{VM2_IP}", "bash -s"],
    input=BASH_SCRIPT.encode("utf-8"),
    capture_output=True
)
print(p.stdout.decode("utf-8", errors="replace"))
if p.stderr:
    print("STDERR:", p.stderr.decode("utf-8", errors="replace"))
