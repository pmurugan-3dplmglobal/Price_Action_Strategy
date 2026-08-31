import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@129.225.69.131"
REMOTE_DIR = "/home/trade/Trade_Kite/Price_Action_Strategy"

cmd = f"""python3 -c "
import shutil, os

src = '{REMOTE_DIR}/input/kite_access_token.txt'
dst_opt = '{REMOTE_DIR}/Trade_Option/input/kite_access_token.txt'
dst_stk = '{REMOTE_DIR}/Trade_Stock/input/kite_access_token.txt'

for d in [dst_opt, dst_stk]:
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copyfile(src, d)
    print(f'Copied token to {{d}}')
" """

res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True, text=True)
print("=== COPIED TOKEN TO ALL VM LOCATIONS ===")
print(res.stdout)
print(res.stderr)

# Restart services
cmd_restart = "sudo systemctl restart trading-options trading-stock trading-export"
subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_restart], capture_output=True)
print("=== RESTARTED SYSTEMD SERVICES ON VM ===")
