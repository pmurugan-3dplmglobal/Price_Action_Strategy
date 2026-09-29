import subprocess
import time

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
IP = "140.245.197.71"
USER = "opc"
REPO_DIR = "/home/opc/Price_Action_Strategy"
PY = f"{REPO_DIR}/venv/bin/python"

# Kill old index engine
cmd_kill = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}", "kill -9 159191 2>/dev/null || true"]
subprocess.run(cmd_kill, capture_output=True, text=True, timeout=10)

# Start new index engine with disown
cmd_start = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}",
    f"(cd {REPO_DIR} && nohup {PY} Trade_Option/index_options_trade_engine.py > output/logs/index_options_engine.log 2>&1 < /dev/null & disown)"
]
subprocess.run(cmd_start, capture_output=True, text=True, timeout=15)
time.sleep(2)

# Check processes
cmd_ps = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}", "ps aux | grep -E 'stock_options|index_options|app_option|app_Stock' | grep -v grep"]
res_ps = subprocess.run(cmd_ps, capture_output=True, text=True, timeout=15)
print("=== VERIFIED ACTIVE TRADING PROCESSES ON VM1 ===")
print(res_ps.stdout)
