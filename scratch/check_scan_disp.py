import json
import os
import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"

# Local
p_local = "output/monitor/scan_display.json"
if os.path.exists(p_local):
    d = json.load(open(p_local, encoding="utf-8"))
    staged = d.get("staged_trades", [])
    all_staged = d.get("all_staged_today", [])
    cf = d.get("carry_forward", [])
    act = d.get("active_live", [])
    # Unique by contract
    all_combined = staged + all_staged + cf + act
    unique_contracts = set()
    for t in all_combined:
        k = (t.get("contract") or t.get("symbol") or "").replace(" ", "").upper()
        if k:
            unique_contracts.add(k)
    print(f"LOCAL: staged={len(staged)}, all_staged={len(all_staged)}, unique={len(unique_contracts)}")

vms = [
    ("Bhavni", "129.225.69.131", "/home/trade/Trade_Kite/Price_Action_Strategy"),
    ("Poovendan", "140.245.197.71", "/home/opc/Price_Action_Strategy")
]

for name, ip, rdir in vms:
    py_cmd = f"import json, os; p='{rdir}/output/monitor/scan_display.json'; d=json.load(open(p)) if os.path.exists(p) else {{}}; s=d.get('staged_trades',[]); a=d.get('all_staged_today',[]); c=d.get('carry_forward',[]); act=d.get('active_live',[]); comb=s+a+c+act; u=set((t.get('contract') or t.get('symbol') or '').replace(' ','').upper() for t in comb if t); u.discard(''); print(f'staged={{len(s)}}, all_staged={{len(a)}}, unique={{len(u)}}')"
    cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{ip}", f"python3 -c \"{py_cmd}\""]
    res = subprocess.run(cmd, capture_output=True, text=True)
    print(f"{name} ({ip}): {res.stdout.strip() or res.stderr.strip()}")
