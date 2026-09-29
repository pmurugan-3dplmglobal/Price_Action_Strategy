import subprocess
import time

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
IP = "140.245.197.71"
USER = "opc"
REPO_DIR = "/home/opc/Price_Action_Strategy"
PY = f"{REPO_DIR}/venv/bin/python"

# 1. Inspect existing engine processes
cmd_ps = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}", "ps -ef | grep python"]
res_ps = subprocess.run(cmd_ps, capture_output=True, text=True)
print("=== CURRENT PROCESSES ON VM1 ===")
print(res_ps.stdout)

# 2. Check if there are separate systemd services or nohup/cron for trade engines
# If stock_options_trade_engine and index_options_trade_engine are running as background nohup scripts,
# kill them and restart them so they load the new code (with ISSUE-111 fixes)!
kill_cmd = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}",
    "pkill -f stock_options_trade_engine.py || true; pkill -f index_options_trade_engine.py || true"
]
subprocess.run(kill_cmd, capture_output=True, text=True)
print("Killed old trade engines.")
time.sleep(2)

# Restart them in background with nohup and closed stdin
start_cmd = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}",
    f"cd {REPO_DIR} && "
    f"nohup {PY} Trade_Option/stock_options_trade_engine.py > output/logs/stock_options_engine.log 2>&1 </dev/null & "
    f"nohup {PY} Trade_Option/index_options_trade_engine.py > output/logs/index_options_engine.log 2>&1 </dev/null & "
]
subprocess.run(start_cmd, capture_output=True, text=True, timeout=15)
print("Started fresh trade engines with new code.")
time.sleep(3)

# 3. Verify running
cmd_verify = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}", "ps -ef | grep python"]
res_verify = subprocess.run(cmd_verify, capture_output=True, text=True)
print("=== VERIFIED RUNNING PROCESSES ON VM1 ===")
print(res_verify.stdout)
