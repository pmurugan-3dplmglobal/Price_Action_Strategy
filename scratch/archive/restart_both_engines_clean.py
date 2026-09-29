import subprocess
import time

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
IP = "140.245.197.71"
USER = "opc"
REPO_DIR = "/home/opc/Price_Action_Strategy"
PY = f"{REPO_DIR}/venv/bin/python"

# Kill old engines
cmd_kill = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}",
    "kill -9 168706 168821 2>/dev/null || true; pkill -9 -f stock_options_trade_engine.py || true; pkill -9 -f index_options_trade_engine.py || true"
]
subprocess.run(cmd_kill, capture_output=True, text=True, timeout=10)
time.sleep(1)

# Start fresh engines
cmd_start = [
    "ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}",
    f"(cd {REPO_DIR} && nohup {PY} Trade_Option/stock_options_trade_engine.py > output/logs/stock_options_engine.log 2>&1 < /dev/null & disown); "
    f"(cd {REPO_DIR} && nohup {PY} Trade_Option/index_options_trade_engine.py > output/logs/index_options_engine.log 2>&1 < /dev/null & disown)"
]
subprocess.run(cmd_start, capture_output=True, text=True, timeout=15)
time.sleep(2)

cmd_ps = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", f"{USER}@{IP}", "ps aux | grep -E 'stock_options|index_options' | grep -v grep"]
res_ps = subprocess.run(cmd_ps, capture_output=True, text=True, timeout=10)
print(res_ps.stdout)
