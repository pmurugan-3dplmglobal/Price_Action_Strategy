import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
IP = "140.245.197.71"
USER = "opc"
REPO = "/home/opc/Price_Action_Strategy"

cmd = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}",
    f"grep -E 'SBILIFE|COLPAL' {REPO}/output/logs/stock_options_engine.log | tail -n 35"
]
res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
print("=== VM1 STOCK OPTIONS ENGINE LOG FOR SBILIFE & COLPAL ===")
print(res.stdout or res.stderr)
