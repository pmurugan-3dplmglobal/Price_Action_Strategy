import subprocess

SSH_KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'
ip = '129.225.69.131'
user = 'opc'
dir_ = '/home/trade/Trade_Kite/Price_Action_Strategy'
py = '/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python'

REMOTE_SCRIPT = """
import sys, os, sqlite3, json

# Check trade_db
db_path = 'output/monitor/trades.sqlite3'
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id, engine, symbol, status, created_at, updated_at, data_json FROM trades ORDER BY id DESC LIMIT 15")
    rows = cur.fetchall()
    print("=== RECENT TRADES IN DB ===")
    for r in rows:
        d = json.loads(r['data_json']) if r['data_json'] else {}
        print(f"ID:{r['id']} {r['engine']} {r['symbol']} ({d.get('contract')}) Stat:{r['status']} Exit:{d.get('exit_reason')} ExitP:{d.get('exit_price')} PnL%:{d.get('pnl_pct')} Upd:{r['updated_at']}")

# Check today's journal entries
j_path = 'output/monitor/trade_journal.csv'
if os.path.exists(j_path):
    print("\\n=== RECENT JOURNAL ENTRIES ===")
    with open(j_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        for l in lines[-25:]:
            print(l.strip())

# Check recent log entries around 09:16
print("\\n=== SYSTEM LOG TAIL ===")
os.system("sudo journalctl -u trading-options -u trading-stock --since '09:15:00' --no-pager | tail -n 50")
"""

ssh_cmd = [
    'ssh', '-i', SSH_KEY,
    '-o', 'StrictHostKeyChecking=no',
    f"{user}@{ip}",
    f"cd {dir_} && {py} -"
]
res = subprocess.run(ssh_cmd, input=REMOTE_SCRIPT, capture_output=True, text=True)
print(res.stdout)
if res.stderr and 'Permanently added' not in res.stderr:
    print("STDERR:", res.stderr)
