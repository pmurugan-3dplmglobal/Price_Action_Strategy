import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
snippet = """
import sys, os, json
sys.path.insert(0, os.path.abspath("common"))
from trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

orders = kite.orders()
for o in orders:
    if "POWERGRID" in o.get("tradingsymbol", "") and o.get("transaction_type") == "SELL":
        print(json.dumps(o, indent=2, default=str))
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71", "cd /home/opc/Price_Action_Strategy && ./venv/bin/python -"]
res = subprocess.run(cmd, input=snippet, capture_output=True, text=True)
print(res.stdout or res.stderr)
