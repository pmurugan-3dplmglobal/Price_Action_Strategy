import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@129.225.69.131"
REMOTE_DIR = "/home/trade/Trade_Kite/Price_Action_Strategy"

cmd = f"""python3 -c "
import os, glob
paths = glob.glob('{REMOTE_DIR}/**/kite_access_token.txt', recursive=True)
for p in paths:
    with open(p) as f:
        content = f.read().strip()[:50]
    mtime = os.path.getmtime(p)
    print(f'Path: {{p}} | Size: {{os.path.getsize(p)}} | MTime: {{mtime}} | Start: {{content}}')
" """

res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True, text=True)
print("=== TOKEN FILES FOUND ON VM ===")
print(res.stdout)
print(res.stderr)
