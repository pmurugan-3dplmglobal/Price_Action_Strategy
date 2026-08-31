import subprocess
import os
import sys

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@129.225.69.131"
REMOTE_DIR = "/home/trade/Trade_Kite/Price_Action_Strategy"

print("==================================================")
print(" SYNCING TODAY'S KITE TOKEN & LATEST CODE TO VM")
print("==================================================")

# 1. Upload local token to VM
local_token_path = os.path.join("input", "kite_access_token.txt")
if os.path.exists(local_token_path):
    print(f"\n[1/3] Uploading today's access token to {HOST}:{REMOTE_DIR}/input/...")
    cmd_scp = ["scp", "-i", KEY, "-o", "StrictHostKeyChecking=no", local_token_path, f"{HOST}:{REMOTE_DIR}/input/kite_access_token.txt"]
    res = subprocess.run(cmd_scp, capture_output=True, text=True)
    if res.returncode == 0:
        print("  -> Token successfully uploaded to VM!")
    else:
        print(f"  -> SCP Error: {res.stderr}")

# 2. Pull latest code on VM
print("\n[2/3] Pulling latest git master branch on VM...")
cmd_pull = f"cd {REMOTE_DIR} && git pull origin master"
res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_pull], capture_output=True, text=True)
print(res.stdout or res.stderr)

# 3. Restart systemd services on VM
print("\n[3/3] Restarting services on VM...")
cmd_restart = f"sudo systemctl restart option_dashboard stock_dashboard || true"
res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_restart], capture_output=True, text=True)
print(res.stdout or res.stderr)

# 4. Verify token validity on VM
cmd_verify = f"cd {REMOTE_DIR} && python3 -c \"import sys; sys.path.insert(0, 'common'); from session import check_token_valid; print('VM Token Status:', check_token_valid())\""
res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_verify], capture_output=True, text=True)
print(res.stdout or res.stderr)

print("==================================================")
print(" VM SYNC COMPLETE! Check http://129.225.69.131:5050")
print("==================================================")
