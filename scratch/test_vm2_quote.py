import subprocess

SSH_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
VM2_IP = "129.225.69.131"

BASH_SCRIPT = r'''#!/usr/bin/env bash
cd /home/trade/Trade_Kite/Price_Action_Strategy

venv/bin/python - << 'PYEOF'
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

contract = "ADANIPOWER26SEP215CE"
exch = "NFO"
q_key = f"{exch}:{contract}"
print(f"Quoting {q_key}...")
try:
    q = kite.quote([q_key])
    print("Quote response:", q)
except Exception as e:
    print("Quote exception:", type(e), e)

from common.position_monitor import monitor_all_active_positions
print("Testing broker position recovery logic...")
net_pos = kite.positions().get("net", [])
for p in net_pos:
    if "ADANIPOWER" in p.get("tradingsymbol", ""):
        print("Found net pos for ADANIPOWER:", p.get("tradingsymbol"), p.get("quantity"), p.get("instrument_token"))
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
