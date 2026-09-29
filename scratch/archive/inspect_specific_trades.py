import subprocess, json

SSH_KEY = r'G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key'
ip = '129.225.69.131'
user = 'opc'
dir_ = '/home/trade/Trade_Kite/Price_Action_Strategy'
py = '/home/trade/Trade_Kite/Price_Action_Strategy/venv/bin/python'

REMOTE_SCRIPT = """
import sqlite3, json

conn = sqlite3.connect('output/monitor/trades.sqlite3')
conn.row_factory = sqlite3.Row
cur = conn.cursor()
cur.execute("SELECT id, engine, symbol, contract, status, created_at, updated_at, data_json FROM trades WHERE id IN (801, 802, 803, 805, 806, 807, 808)")
for r in cur.fetchall():
    d = json.loads(r['data_json']) if r['data_json'] else {}
    print(f"--- ID {r['id']} {r['symbol']} ({r['contract']}) ---")
    print(f"  Status: {r['status']}")
    print(f"  Created: {r['created_at']}, Updated: {r['updated_at']}")
    print(f"  Entry: {d.get('entry_spot') or d.get('entry_price')}, Benchmark: {d.get('benchmark')}")
    print(f"  SL: {d.get('current_sl')}, Initial SL: {d.get('sl')}")
    print(f"  Target 1: {d.get('t1')}, Target 2: {d.get('t2')}")
    print(f"  Exit Reason: {d.get('exit_reason')}, Exit Price: {d.get('exit_price')}")
    print(f"  Trailing Stage: {d.get('trailing_stage')}")
"""

ssh_cmd = [
    'ssh', '-i', SSH_KEY,
    '-o', 'StrictHostKeyChecking=no',
    f"{user}@{ip}",
    f"cd {dir_} && {py} -"
]
res = subprocess.run(ssh_cmd, input=REMOTE_SCRIPT, capture_output=True, text=True)
print(res.stdout)
