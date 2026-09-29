import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
VMS = [
    ("VM1 (Poovendan)", "opc@140.245.197.71", "/home/opc/Price_Action_Strategy"),
    ("VM2 (Bhavani)", "opc@129.225.69.131", "/home/trade/Trade_Kite/Price_Action_Strategy")
]

snippet = """
import sys, os, json
sys.path.insert(0, os.path.abspath("common"))
from trading_core import load_kite_session
from kiteconnect import KiteConnect

ak, at = load_kite_session()
kite = KiteConnect(api_key=ak)
kite.set_access_token(at)

try:
    orders = kite.orders()
    print(f"=== TOTAL ORDERS TODAY: {len(orders)} ===")
    for o in orders:
        status = o.get('status')
        tsym = o.get('tradingsymbol')
        tt = o.get('transaction_type')
        qty = o.get('quantity')
        p = o.get('price')
        ap = o.get('average_price')
        ot = o.get('order_type')
        t = o.get('order_timestamp')
        s_msg = o.get('status_message')
        print(f"[{t}] {tt} {tsym} {qty} qty @ {ap or p} ({ot}) -> {status} | Msg: {s_msg or ''}")
except Exception as e:
    print(f"Error getting orders: {e}")
"""

for name, host, cdir in VMS:
    print(f"\n============================== {name} ==============================")
    cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", host, f"cd {cdir} && ./venv/bin/python -"]
    res = subprocess.run(cmd, input=snippet, capture_output=True, text=True)
    print(res.stdout or res.stderr)
