import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@129.225.69.131"
REMOTE_DIR = "/home/trade/Trade_Kite/Price_Action_Strategy"

cmd = f"""python3 -c "
import json
p = '{REMOTE_DIR}/input/program_config.json'
with open(p) as f:
    d = json.load(f)
print('VM api_key in program_config.json:', d.get('api_key'))
print('VM api_secret length:', len(d.get('api_secret', '')))
" """

res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True, text=True)
print(res.stdout)
