import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
VM_IP = "140.245.197.71"
VM_USER = "opc"
PYTHON_BIN = "/home/opc/Price_Action_Strategy/venv/bin/python"

script = """
import sys
sys.path.insert(0, '/home/opc/Price_Action_Strategy')
from kiteconnect import KiteConnect
from common.session import load_kite_session

k, tok = load_kite_session()
kite = KiteConnect(api_key=k)
kite.set_access_token(tok)
prof = kite.profile()
print(f"POOVENDAN VM AUTH VERIFIED! User: {prof.get('user_id')} - {prof.get('user_name')}")
"""

res = subprocess.run([
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no",
    f"{VM_USER}@{VM_IP}",
    PYTHON_BIN
], input=script, capture_output=True, text=True, timeout=30)

print(res.stdout)
if res.stderr:
    print("STDERR:", res.stderr)
