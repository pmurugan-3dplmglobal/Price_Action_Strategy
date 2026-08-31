import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@129.225.69.131"
REMOTE_DIR = "/home/trade/Trade_Kite/Price_Action_Strategy"

cmd = f"""cd {REMOTE_DIR} && venv/bin/python -c "
import sys, os, json
sys.path.insert(0, 'common')
sys.path.insert(0, 'Trade_Option')
from app_option_Trade import check_token_valid
print('VM Token Validity Check:', json.dumps(check_token_valid(), indent=2))
" """

res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True)
print(res.stdout.decode("utf-8", errors="ignore"))
print(res.stderr.decode("utf-8", errors="ignore"))
