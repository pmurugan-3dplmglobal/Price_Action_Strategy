import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@140.245.197.71"

cmd = """sudo grep -rn 'Price_Action_TradingView' /etc/systemd/system/ /var/spool/cron/ /home/opc/.config/ 2>/dev/null"""
res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True, text=True)
print("=== FILES MENTIONING Price_Action_TradingView ===")
print(res.stdout)
