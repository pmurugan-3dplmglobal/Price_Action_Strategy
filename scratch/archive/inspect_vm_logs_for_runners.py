import subprocess
import os

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
vm_ip = "140.245.197.71"

symbols = ["LTM", "TMPV", "SWIGGY", "WAAREEENER", "VOLTAS", "HCLTECH", "KPITTECH"]

for sym in symbols:
    cmd = [
        "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"opc@{vm_ip}",
        f"journalctl -u trading-options --no-pager -S today | grep -i '{sym}' | tail -n 15"
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    out = res.stdout.strip()
    print(f"=== {sym} on VM ===")
    if out:
        print(out)
    else:
        print("No log lines found.")
