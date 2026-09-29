import subprocess

SSH_KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

VMS = [
    {
        "name": "VM1 (Poovendan)",
        "ip": "140.245.197.71",
        "dir": "/home/opc/Price_Action_Strategy",
        "venv_py": "/home/opc/Price_Action_Strategy/venv/bin/python",
        "ak": "o8nnw6kxykvrsrhg"
    },
    {
        "name": "VM2 (Bhavani)",
        "ip": "129.225.69.131",
        "dir": "/home/trade/Trade_Kite/Price_Action_Strategy",
        "venv_py": "/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python",
        "ak": "jgdjmtymfyea4yn4"
    }
]

BASH_SCRIPT_TEMPLATE = r"""#!/usr/bin/env bash
cd __DIR__

__VENV_PY__ - << 'PYEOF'
import os, json
from kiteconnect import KiteConnect

ak = "__AK__"
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

print("=== 1. KITE NET POSITIONS ===")
positions = kite.positions().get("net", [])
open_cnt = 0
for p in positions:
    qty = p.get("quantity", 0)
    ts = p.get("tradingsymbol")
    prod = p.get("product")
    avg = p.get("average_price")
    pnl = p.get("pnl")
    if qty != 0:
        open_cnt += 1
        print(f"  [OPEN] {ts}: Qty={qty}, Prod={prod}, AvgPrice={avg}, PnL={pnl}")
    else:
        print(f"  [CLOSED] {ts}: Prod={prod}, AvgPrice={avg}, PnL={pnl}")
print(f"Total Open Net Positions: {open_cnt}")

print("\n=== 2. KITE ORDERS PLACED TODAY ===")
orders = kite.orders()
for o in orders:
    t = o.get("order_timestamp")
    ts = o.get("tradingsymbol")
    tx = o.get("transaction_type")
    st = o.get("status")
    fq = o.get("filled_quantity")
    q = o.get("quantity")
    pr = o.get("average_price")
    tag = o.get("tag")
    msg = o.get("status_message")
    print(f"  Time: {t} | {tx} {ts} | Status: {st} | Qty: {fq}/{q} @ {pr} | Tag: {tag} | Msg: {msg}")

PYEOF
"""

def main():
    for vm in VMS:
        print(f"\n{'='*60}\nInspecting {vm['name']} ({vm['ip']})...\n{'='*60}")
        script = (
            BASH_SCRIPT_TEMPLATE
            .replace("__DIR__", vm["dir"])
            .replace("__VENV_PY__", vm["venv_py"])
            .replace("__AK__", vm["ak"])
            .replace("\r\n", "\n")
            .replace("\r", "\n")
        ).encode("utf-8")
        
        p = subprocess.run(
            ["ssh", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no", f"opc@{vm['ip']}", "bash -s"],
            input=script,
            capture_output=True
        )
        print(p.stdout.decode("utf-8", errors="replace"))
        if p.stderr:
            print("STDERR:", p.stderr.decode("utf-8", errors="replace"))

if __name__ == "__main__":
    main()
