import subprocess
import os

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@129.225.69.131"
REMOTE_DIR = "/home/trade/Trade_Kite/Price_Action_Strategy"

cmd = "sudo systemctl restart trading-options trading-stock trading-export"
subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True)

# Check status
cmd_status = "sudo systemctl status trading-options --no-pager"
res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_status], capture_output=True)
print("=== TRADING-OPTIONS STATUS ON VM ===")
print(res.stdout.decode("ascii", errors="replace")[:600])

# Check token validity via local endpoint on VM
cmd_token = "curl -s http://127.0.0.1:5050/api/token/check"
res_token = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_token], capture_output=True)
print("\n=== VM API TOKEN CHECK ===")
print(res_token.stdout.decode("ascii", errors="replace"))
