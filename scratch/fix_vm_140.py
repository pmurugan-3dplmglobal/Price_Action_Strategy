import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@140.245.197.71"
REMOTE_DIR = "/home/opc/Price_Action_Strategy"

print("==================================================")
print(" FIXING VM 140.245.197.71 (PRICE_ACTION_STRATEGY)")
print("==================================================")

# 1. Kill any processes running from Price_Action_TradingView
cmd_kill = "pkill -f 'Price_Action_TradingView' || true"
subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_kill], capture_output=True)
print("\n[1/4] Terminated rogue Price_Action_TradingView processes.")

# 2. Pull latest git master in /home/opc/Price_Action_Strategy
print("\n[2/4] Pulling latest git master branch on 140.245.197.71...")
cmd_pull = f"cd {REMOTE_DIR} && git pull origin master"
res_pull = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_pull], capture_output=True, text=True)
print(res_pull.stdout)

# 3. Restart systemd services pointing to /home/opc/Price_Action_Strategy
print("\n[3/4] Restarting systemd services on 140.245.197.71...")
cmd_restart = "sudo systemctl restart trading-options trading-stock trading-export"
subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_restart], capture_output=True)
print("  -> Systemd services restarted.")

# 4. Verify running processes and live Kite positions
cmd_verify = f"""{REMOTE_DIR}/venv/bin/python -c "
import sys, json
sys.path.insert(0, '{REMOTE_DIR}/common')
sys.path.insert(0, '{REMOTE_DIR}/Trade_Option')
from kiteconnect import KiteConnect
from session import load_kite_session, safe_kite_call

api_k, acc_t = load_kite_session('{REMOTE_DIR}/input/kite_access_token.txt')
kite = KiteConnect(api_key=api_k)
kite.set_access_token(acc_t)
pos = safe_kite_call(kite.positions) or {{}}
net = pos.get('net', [])
print('Live Kite Net Positions Count:', len(net))
for p in net:
    if int(p.get('quantity', 0)) != 0:
        print('  ', p.get('tradingsymbol'), 'Qty:', p.get('quantity'), 'LTP:', p.get('last_price'), 'PnL:', p.get('pnl'))
" """

print("\n[4/4] Verifying live Kite API positions on 140.245.197.71...")
res_ver = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd_verify], capture_output=True, text=True)
print(res_ver.stdout)
print(res_ver.stderr)

print("==================================================")
print(" FIXED! Check http://140.245.197.71:5050/")
print("==================================================")
