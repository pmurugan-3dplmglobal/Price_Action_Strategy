import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="ignore")

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
HOST = "opc@140.245.197.71"
REMOTE_DIR = "/home/opc/Price_Action_Strategy"

print("==================================================")
print(" DEEP AUDIT: LIVE POSITIONS ON 140.245.197.71:5050")
print("==================================================")

cmd = f"""{REMOTE_DIR}/venv/bin/python -c "
import sys, json, os
sys.path.insert(0, '{REMOTE_DIR}/common')
sys.path.insert(0, '{REMOTE_DIR}/Trade_Option')

# 1. Check Kite Session directly
from kiteconnect import KiteConnect
from session import load_kite_session, safe_kite_call

try:
    api_k, acc_t = load_kite_session('{REMOTE_DIR}/input/kite_access_token.txt')
    kite = KiteConnect(api_key=api_k)
    kite.set_access_token(acc_t)
    profile = kite.profile()
    print('Kite Account Profile:', profile.get('user_id'), profile.get('user_name'))
    
    pos_data = safe_kite_call(kite.positions) or {{}}
    net = pos_data.get('net', [])
    print(f'Live Kite Net Positions (Total: {{len(net)}}):')
    for p in net:
        if int(p.get('quantity', 0)) != 0:
            print(f'  [OPEN] {{p.get(\"tradingsymbol\")}} | Qty: {{p.get(\"quantity\")}} | BuyAvg: {{p.get(\"average_price\")}} | LTP: {{p.get(\"last_price\")}} | PnL: {{p.get(\"pnl\")}}')
        else:
            print(f'  [CLOSED] {{p.get(\"tradingsymbol\")}} | Qty: 0 | PnL: {{p.get(\"pnl\")}}')
except Exception as e:
    print('Kite Error:', e)

# 2. Check trades.sqlite3
import trade_db
active_db = trade_db.get_active_trades()
print(f'\nSQLite Active Trades (Total: {{len(active_db)}}):')
for t in active_db:
    print(f'  ID {{t.get(\"id\")}} | {{t.get(\"contract\", t.get(\"symbol\"))}} | SL: {{t.get(\"current_sl\")}} | T1: {{t.get(\"t1\")}} | Status: {{t.get(\"status\")}}')

# 3. Check active_positions_db.json
act_file = '{REMOTE_DIR}/output/monitor/active_positions_db.json'
if os.path.exists(act_file):
    with open(act_file) as f:
        act_data = json.load(f)
    print(f'\nactive_positions_db.json (Total: {{len(act_data.get(\"positions\", []))}}):')
    for p in act_data.get('positions', []):
        print(f'  {{p.get(\"contract\", p.get(\"symbol\"))}} | {{p.get(\"status\")}}')
" """

res = subprocess.run(["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", HOST, cmd], capture_output=True, text=True)
print(res.stdout)
print(res.stderr)
