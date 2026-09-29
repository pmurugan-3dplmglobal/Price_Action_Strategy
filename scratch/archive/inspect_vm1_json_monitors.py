import subprocess

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
IP = "140.245.197.71"
USER = "opc"
REPO = "/home/opc/Price_Action_Strategy"

cmd_scp = ["scp", "-i", KEY, "-o", "StrictHostKeyChecking=no", "scratch/remote_search_json.py", f"{USER}@{IP}:{REPO}/remote_search_json.py"]
subprocess.run(cmd_scp, capture_output=True, text=True, timeout=15)

cmd_run = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}", f"cd {REPO} && /home/opc/Price_Action_Strategy/venv/bin/python remote_search_json.py && rm -f remote_search_json.py"]
res = subprocess.run(cmd_run, capture_output=True, text=True, timeout=20)
print(res.stdout or res.stderr)
