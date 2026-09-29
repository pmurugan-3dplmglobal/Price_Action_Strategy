import subprocess
import json

KEY = r"G:\Poovendan\AI\Trading\Cloud\Oracle_Cloud\ssh-key-2026-08-05.key"
host = "opc@140.245.197.71"
cdir = "/home/opc/Price_Action_Strategy"

snippet = '''
import sqlite3, json

conn = sqlite3.connect("output/monitor/trades.sqlite3")
conn.row_factory = sqlite3.Row
rows = conn.execute("""
    SELECT id, engine, symbol, contract, status, created_at, updated_at, data_json 
    FROM trades 
    WHERE created_at LIKE '2026-09-28%' OR updated_at LIKE '2026-09-28%' OR status='ACTIVE'
""").fetchall()

trades = [dict(r) for r in rows]
print("---START_TRADES---")
print(json.dumps(trades, default=str))
print("---END_TRADES---")
'''

cmd = ["ssh", "-i", KEY, "-o", "StrictHostKeyChecking=no", host, f"cd {cdir} && ./venv/bin/python -"]
res = subprocess.run(cmd, input=snippet, capture_output=True, text=True)
if "---START_TRADES---" in res.stdout:
    json_str = res.stdout.split("---START_TRADES---")[1].split("---END_TRADES---")[0].strip()
    with open("scratch/today_vm1_trades_db.json", "w", encoding="utf-8") as f:
        f.write(json_str)
    print("Successfully saved scratch/today_vm1_trades_db.json")
else:
    print("ERROR:", res.stderr or res.stdout)
