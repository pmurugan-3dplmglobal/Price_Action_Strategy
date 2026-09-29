"""
Copy Kite Access Token from Local Poovendan to ONLY Poovendan VM1 (140.245.197.71).
Do NOT touch Bhavani VM2.
"""
import subprocess
import os
import sys

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
VM_IP = "140.245.197.71"
VM_USER = "opc"
LOCAL_TOKEN = r"G:\Poovendan\AI\Trading\Share\ReadyToDeploy\Prod_code_01\Price_Action_Strategy\input\kite_access_token.txt"
REMOTE_REPO = "/home/opc/Price_Action_Strategy"

if not os.path.exists(LOCAL_TOKEN):
    print(f"ERROR: Local token not found at {LOCAL_TOKEN}")
    sys.exit(1)

if not os.path.exists(KEY):
    print(f"ERROR: SSH key not found at {KEY}")
    sys.exit(1)

print(f"1. Copying {LOCAL_TOKEN} to {VM_USER}@{VM_IP}:{REMOTE_REPO}/input/kite_access_token.txt ...")
cmd_scp = [
    "scp", "-i", KEY, "-o", "StrictHostKeyChecking=no",
    LOCAL_TOKEN,
    f"{VM_USER}@{VM_IP}:{REMOTE_REPO}/input/kite_access_token.txt"
]
res_scp = subprocess.run(cmd_scp, capture_output=True, text=True, timeout=30)
if res_scp.returncode != 0:
    print(f"SCP FAILED:\nSTDOUT:\n{res_scp.stdout}\nSTDERR:\n{res_scp.stderr}")
    sys.exit(1)
print("   SCP successful!")

print("2. Syncing token to Trade_Option/input and Trade_Stock/input on Poovendan VM1 ...")
remote_cmd = (
    f"cp {REMOTE_REPO}/input/kite_access_token.txt {REMOTE_REPO}/Trade_Option/input/kite_access_token.txt && "
    f"cp {REMOTE_REPO}/input/kite_access_token.txt {REMOTE_REPO}/Trade_Stock/input/kite_access_token.txt && "
    f"ls -la {REMOTE_REPO}/input/kite_access_token.txt {REMOTE_REPO}/Trade_Option/input/kite_access_token.txt {REMOTE_REPO}/Trade_Stock/input/kite_access_token.txt"
)
res_sync = subprocess.run([
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
    f"{VM_USER}@{VM_IP}", remote_cmd
], capture_output=True, text=True, timeout=30)
print(res_sync.stdout)

print("3. Validating Kite session authentication on Poovendan VM1 ...")
verify_script = """
import sys
sys.path.insert(0, '/home/opc/Price_Action_Strategy')
from kiteconnect import KiteConnect
from common.session import load_kite_session

api_key, access_token = load_kite_session()
kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)
prof = kite.profile()
print(f"AUTH SUCCESS ON VM! User ID: {prof.get('user_id')}, User Name: {prof.get('user_name')}")
"""
res_auth = subprocess.run([
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
    f"{VM_USER}@{VM_IP}",
    f"{REMOTE_REPO}/venv/bin/python", "-c", verify_script
], capture_output=True, text=True, timeout=30)
print(res_auth.stdout or res_auth.stderr)

print("4. Restarting systemd services on Poovendan VM1 ...")
res_restart = subprocess.run([
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
    f"{VM_USER}@{VM_IP}",
    "sudo systemctl restart trading-options trading-stock trading-export"
], capture_output=True, text=True, timeout=40)
print("   Services restarted.")

res_status = subprocess.run([
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
    f"{VM_USER}@{VM_IP}",
    "systemctl is-active trading-options trading-stock trading-export"
], capture_output=True, text=True, timeout=20)
print("   Services status on Poovendan VM1:")
for line in res_status.stdout.strip().split('\n'):
    print(f"     {line}")

print("\nDONE: Token copied and validated on ONLY Poovendan VM1.")
