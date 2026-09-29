import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
IP = "140.245.197.71"
USER = "opc"

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}", "ps aux | grep -E 'stock_options|index_options|app_option|app_Stock' | grep -v grep"]
res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
print("=== ACTIVE TRADING PROCESSES ON VM1 ===")
print(res.stdout)
