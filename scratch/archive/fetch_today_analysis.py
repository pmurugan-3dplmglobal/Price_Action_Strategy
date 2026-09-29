import subprocess
import json

KEY_PATH = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

REMOTE_SCRIPT = """
import sys, os
sys.path.insert(0, "/home/opc/Price_Action_Strategy/common")
import session
from kiteconnect import KiteConnect

api_key, access_token = session.load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
prof = kite.profile()
print(f"POOVENDAN ACCOUNT: {prof.get('user_id')} ({prof.get('user_name')})")

pos = kite.positions().get("day", [])
print(f"\\n--- DAY POSITIONS ({len(pos)}) ---")
tot_pnl = 0.0
for p in pos:
    pnl = float(p.get("pnl") or 0.0)
    tot_pnl += pnl
    sym = p.get('tradingsymbol')
    qty = p.get('quantity')
    bq = p.get('buy_quantity')
    bp = p.get('buy_price')
    sq = p.get('sell_quantity')
    sp = p.get('sell_price')
    print(f"  {sym:<25} | Net:{qty:<5} | Buy:{bq:<5} @ {bp:>7.2f} | Sell:{sq:<5} @ {sp:>7.2f} | PnL: Rs {pnl:>9.2f}")
print(f"TOTAL REALIZED/UNREALIZED DAY PnL: Rs {tot_pnl:,.2f}")

orders = [o for o in kite.orders() if "2026-09-08" in str(o.get("order_timestamp", ""))]
print(f"\\n--- ORDERS PLACED TODAY ({len(orders)}) ---")
orders.sort(key=lambda x: str(x.get("order_timestamp", "")))
for o in orders:
    ts = str(o.get("order_timestamp"))[:19]
    oid = o.get("order_id")
    sym = o.get("tradingsymbol")
    tt = o.get("transaction_type")
    q = o.get("quantity")
    fq = o.get("filled_quantity")
    ap = o.get("average_price")
    price = o.get("price")
    ot = o.get("order_type")
    st = o.get("status")
    msg = o.get("status_message") or ""
    print(f"  [{ts}] {oid} | {sym:<25} | {tt:<4} {ot:<6} | Qty:{fq:>4}/{q:<4} @ {ap:>6.2f} (req:{price}) | {st:<9} {msg[:40]}")
"""

p = subprocess.Popen(
    [
        "ssh",
        "-i", KEY_PATH,
        "-o", "StrictHostKeyChecking=no",
        "opc@140.245.197.71",
        "/home/opc/Price_Action_Strategy/venv/bin/python -"
    ],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True
)
stdout, stderr = p.communicate(input=REMOTE_SCRIPT)
print(stdout)
if stderr:
    print("ERR:", stderr)
