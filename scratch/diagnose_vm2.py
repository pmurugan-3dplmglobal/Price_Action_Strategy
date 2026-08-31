import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@140.245.197.71"

print("==================================================")
print(" DIAGNOSING VM 140.245.197.71")
print("==================================================")

# 1. Check running directory and processes
cmd_ps = "ps aux | grep python"
res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_ps], capture_output=True, text=True)
print("\n[Running Processes]:")
print(res.stdout)

# 2. Find Price Action directory
cmd_find = "find / -name 'Price_Action_Strategy' 2>/dev/null | head -n 5"
res_find = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_find], capture_output=True, text=True)
print("\n[Price Action Directory]:")
print(res_find.stdout)
