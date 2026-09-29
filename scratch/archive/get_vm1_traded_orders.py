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
print(f"=== VM1 ALL ORDERS TODAY ({len(orders)}) ===")
for o in orders:
    tsym = o.get('tradingsymbol')
    if any(s in tsym for s in ['MIDCP', 'NAUKRI', 'ASIAN', 'DIXON', 'ULTRA', 'BHARTI', 'SENSEX', 'POWERGRID']):
        t = o.get('order_timestamp')
        tt = o.get('transaction_type')
        qty = o.get('quantity')
        ap = o.get('average_price')
        p = o.get('price')
        st = o.get('status')
        msg = o.get('status_message') or ''
        ot = o.get('order_type')
        print(f"[{t}] {tt} {tsym} {qty} qty @ avg={ap} req_p={p} ({ot}) -> {st} {msg}")
"""

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", "opc@140.245.197.71", "cd /home/opc/Price_Action_Strategy && ./venv/bin/python -"]
res = subprocess.run(cmd, input=snippet, capture_output=True, text=True)
print(res.stdout or res.stderr)
