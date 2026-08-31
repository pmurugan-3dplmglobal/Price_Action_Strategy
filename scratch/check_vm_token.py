import subprocess
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@129.225.69.131"

cmd = "curl -s http://127.0.0.1:5050/api/token/check"
res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True)
print("VM API Token Check Output:")
print(res.stdout.decode("utf-8", errors="ignore"))
