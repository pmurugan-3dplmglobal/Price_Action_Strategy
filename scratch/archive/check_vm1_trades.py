import subprocess
import json

ssh_key = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
remote_py = """
import sqlite3, json, os
os.chdir('/home/opc/Price_Action_Strategy')
conn = sqlite3.connect("output/monitor/trades.sqlite3")
c = conn.cursor()
c.execute("SELECT id, engine, symbol, contract, status, created_at, updated_at FROM trades ORDER BY id DESC LIMIT 15")
rows = c.fetchall()
print("TRADES_START")
print(json.dumps(rows, indent=2))
print("TRADES_END")
"""

ssh_cmd = [
    'ssh', '-i', ssh_key, '-o', 'StrictHostKeyChecking=no',
    'opc@140.245.197.71',
    'python3', '-'
]

res = subprocess.run(ssh_cmd, input=remote_py, capture_output=True, text=True)
print("STDOUT:")
print(res.stdout)
if res.stderr:
    print("STDERR:", res.stderr)
